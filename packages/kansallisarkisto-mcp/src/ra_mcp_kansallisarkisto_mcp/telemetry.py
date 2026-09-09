"""OpenTelemetry SDK initialisation — the one place the SDK is touched.

Configures TracerProvider, MeterProvider and (optionally) LoggerProvider with
OTLP exporters. Gated on ``KA_MCP_OTEL_ENABLED``: with it unset this does
nothing at all, which is the default and what a stdio client on a laptop gets.

Everything else in the workspace depends on ``opentelemetry-api`` only and goes
through :mod:`ra_mcp_kansallisarkisto_lib.telemetry`, so with the SDK
uninitialised the instrumentation resolves to no-ops.

Environment variables:
    KA_MCP_OTEL_ENABLED: Master switch (default: false)
    OTEL_EXPORTER_OTLP_ENDPOINT: Collector endpoint (default: http://localhost:4317)
    OTEL_EXPORTER_OTLP_PROTOCOL: grpc or http/protobuf (default: grpc)
    OTEL_SERVICE_NAME: Service name (default: kansallisarkisto-mcp)
    KA_MCP_OTEL_LOG_BRIDGE: Bridge Python logging to OTel (default: true)

Ported from ra-mcp's ``ra_mcp_server.telemetry``.
"""

from __future__ import annotations

import contextlib
import logging
import os
import threading
from typing import Any

logger = logging.getLogger(__name__)

SERVICE_NAME = "kansallisarkisto-mcp"

_initialized = False
_providers: list[Any] = []


def _flag(name: str, default: str) -> bool:
    return os.getenv(name, default).lower() in ("true", "1", "yes")


def _is_enabled() -> bool:
    return _flag("KA_MCP_OTEL_ENABLED", "false")


def init_telemetry() -> None:
    """Initialise the OpenTelemetry SDK when ``KA_MCP_OTEL_ENABLED`` is set.

    Safe to call more than once — it initialises only the first time. The SDK
    imports live inside the function so that a server running without telemetry
    never pays for importing them.
    """
    global _initialized
    if _initialized or not _is_enabled():
        return

    from importlib.metadata import PackageNotFoundError, version

    from opentelemetry import metrics, trace
    from opentelemetry.sdk.metrics import MeterProvider
    from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    try:
        service_version = version("ra-mcp-kansallisarkisto-mcp")
    except PackageNotFoundError:  # pragma: no cover - only when running from a tree without metadata
        service_version = "unknown"

    service_name = os.getenv("OTEL_SERVICE_NAME", SERVICE_NAME)
    resource = Resource.create({"service.name": service_name, "service.version": service_version})

    protocol = os.getenv("OTEL_EXPORTER_OTLP_PROTOCOL", "grpc")
    if protocol == "http/protobuf":
        from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    else:
        from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

    tracer_provider = TracerProvider(resource=resource)
    tracer_provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    trace.set_tracer_provider(tracer_provider)
    _providers.append(tracer_provider)

    meter_provider = MeterProvider(resource=resource, metric_readers=[PeriodicExportingMetricReader(OTLPMetricExporter())])
    metrics.set_meter_provider(meter_provider)
    _providers.append(meter_provider)

    # Build-info gauge (the Prometheus _info pattern: value 1, version as a label).
    meter = metrics.get_meter("kansallisarkisto_mcp")
    meter.create_gauge("kansallisarkisto_mcp.build_info", description="Build information for the kansallisarkisto-mcp server").set(1, {"version": service_version})

    # Log volume by severity, so an error-rate panel does not require sampling traces.
    log_counter = meter.create_counter("kansallisarkisto_mcp.log.messages", description="Log messages emitted, by severity level")
    _setup_log_metrics(log_counter)

    if _flag("KA_MCP_OTEL_LOG_BRIDGE", "true"):
        _setup_log_bridge(resource)

    _initialized = True
    logger.info("OpenTelemetry initialised (service=%s, version=%s, protocol=%s)", service_name, service_version, protocol)


class _MetricsLoggingHandler(logging.Handler):
    """Logging handler that increments an OTel counter per log record level."""

    def __init__(self, counter: Any) -> None:
        super().__init__()
        self._counter = counter

    def emit(self, record: logging.LogRecord) -> None:
        self._counter.add(1, {"log.level": record.levelname})


def _setup_log_metrics(counter: Any) -> None:
    handler = _MetricsLoggingHandler(counter)
    handler.setLevel(logging.WARNING)
    logging.getLogger().addHandler(handler)


def _setup_log_bridge(resource: Any) -> None:
    """Attach the OTel LoggingHandler to the root logger.

    Best-effort: the log bridge is the least stable part of the SDK, and failing
    to export logs must not stop a server that is otherwise fine from starting.
    """
    try:
        from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
        from opentelemetry.sdk._logs.export import BatchLogRecordProcessor

        if os.getenv("OTEL_EXPORTER_OTLP_PROTOCOL", "grpc") == "http/protobuf":
            from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
        else:
            from opentelemetry.exporter.otlp.proto.grpc._log_exporter import OTLPLogExporter

        log_provider = LoggerProvider(resource=resource)
        log_provider.add_log_record_processor(BatchLogRecordProcessor(OTLPLogExporter()))
        _providers.append(log_provider)
        logging.getLogger().addHandler(LoggingHandler(level=logging.NOTSET, logger_provider=log_provider))
    except Exception:
        logger.debug("OTel log bridge setup failed — continuing without log export", exc_info=True)


# How long the whole flush-and-shutdown may take before the process gives up on
# it. Measured, not guessed: with the SDK enabled and no collector listening,
# an unbounded shutdown never returned at all — the OTLP gRPC exporter retries
# an unreachable endpoint with exponential backoff and `shutdown()` waits for
# that retry loop, and `force_flush(timeout_millis=...)` does not bound it.
# Since this runs from atexit, that hung the process on every exit — and for
# stdio, exit is after every session. A misconfigured collector must cost a few
# seconds of dropped telemetry, never a hang.
SHUTDOWN_TIMEOUT_SECONDS = 5.0


def shutdown_telemetry() -> None:
    """Flush and shut down every provider, within a bounded time.

    Registered with ``atexit`` by the entry point: without the flush, the last
    batch of spans and metrics is lost every time the process exits, which for a
    stdio server is after every session.

    The work runs on a daemon thread that is joined with a timeout, so an
    unreachable collector cannot block interpreter exit — a daemon thread does
    not keep the process alive. Telemetry is best-effort by nature; a clean exit
    is not.
    """
    global _initialized
    providers, _providers[:] = list(_providers), []
    _initialized = False
    if not providers:
        return

    def _drain() -> None:
        for provider in providers:
            # Suppressed deliberately: at exit the collector may be gone and the
            # interpreter tearing down. Failing to flush telemetry must not turn a
            # clean shutdown into a traceback.
            with contextlib.suppress(Exception):
                if hasattr(provider, "force_flush"):
                    provider.force_flush(timeout_millis=int(SHUTDOWN_TIMEOUT_SECONDS * 1000))
                provider.shutdown()

    worker = threading.Thread(target=_drain, name="otel-shutdown", daemon=True)
    worker.start()
    worker.join(SHUTDOWN_TIMEOUT_SECONDS)
    if worker.is_alive():
        logger.warning(
            "OpenTelemetry shutdown did not finish within %.0fs — exiting anyway; some spans or metrics were dropped. The usual cause is an unreachable OTLP endpoint (%s).",
            SHUTDOWN_TIMEOUT_SECONDS,
            os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4317"),
        )
