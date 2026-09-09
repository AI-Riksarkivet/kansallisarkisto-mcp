"""Telemetry helpers, using ``opentelemetry-api`` only.

This package deliberately depends on the API and never the SDK. With no SDK
configured, :func:`get_tracer` and :func:`get_meter` hand back no-op objects, so
the instrumentation below costs effectively nothing when telemetry is off —
which is the default, and what a stdio client on a laptop always gets.

The SDK is initialised in one place only, the server package's ``telemetry``
module, gated on ``KA_MCP_OTEL_ENABLED``. Both layers then share the global
providers, so FastMCP's automatic ``tools/call`` spans and the manual spans here
nest into a single trace.

Ported from ra-mcp's ``ra_mcp_common.telemetry``, which the sibling
Kansallisarkisto server also carries.
"""

from __future__ import annotations

import contextlib
import logging
import traceback

from opentelemetry import metrics, trace


def get_tracer(name: str) -> trace.Tracer:
    """Return a tracer, or a no-op one when no TracerProvider SDK is configured."""
    return trace.get_tracer(name)


def get_meter(name: str) -> metrics.Meter:
    """Return a meter, or a no-op one when no MeterProvider SDK is configured."""
    return metrics.get_meter(name)


_LOGGED_MARKER = "_ka_mcp_logged"


def record_span_exception(logger: logging.Logger, exc: BaseException) -> None:
    """Record an exception on the active span and in one correlated log record.

    The Span Event API (``span.record_exception``) is being deprecated, so rather
    than a span event this:

    1. sets the semantic-convention ``error.type`` on the active span, so a trace
       store can group and filter by error class — the caller still sets
       ``span.set_status(StatusCode.ERROR, ...)``; and
    2. emits a structured ERROR log **once per exception**. The class and message
       go in the log message itself, so it is readable through the plain stdlib
       formatter and not only via the OTLP bridge.

    ``error.type`` is set on every span the exception passes through — that is how
    the trace tree shows which spans failed — but the stacktrace is logged only the
    first time, so one failure unwinding through the search and spine layers does
    not emit the same traceback twice and double the ERROR-log count.
    """
    exc_type = type(exc).__name__
    trace.get_current_span().set_attribute("error.type", exc_type)

    if getattr(exc, _LOGGED_MARKER, False):
        return
    # Some builtin and C-level exceptions forbid attribute assignment — log anyway.
    with contextlib.suppress(AttributeError, TypeError):
        object.__setattr__(exc, _LOGGED_MARKER, True)

    logger.error(
        "%s: %s",
        exc_type,
        exc,
        exc_info=exc,
        extra={
            "exception.type": exc_type,
            "exception.message": str(exc),
            "exception.stacktrace": traceback.format_exc(),
        },
    )


def mark_span_error(message: str, error_type: str = "handled_error") -> None:
    """Mark the active span ERROR when a tool returns an error *string* rather than raising.

    This matters more here than in most servers. Every tool in this package
    deliberately returns text instead of raising — an exception reaches the model
    as a protocol error it cannot act on — but FastMCP's ``tools/call`` span
    reports OK whenever a handler returns normally. Without this, a server whose
    every call answered "the df table is not available" would show a tool failure
    rate of exactly zero.

    ``error_type`` groups the failure class: ``"validation"`` for arguments the
    caller can fix, the default ``"handled_error"`` for a caught exception. For a
    caught exception, also call :func:`record_span_exception` so the stacktrace is
    logged once.
    """
    span = trace.get_current_span()
    span.set_status(trace.StatusCode.ERROR, message)
    span.set_attribute("error.type", error_type)
