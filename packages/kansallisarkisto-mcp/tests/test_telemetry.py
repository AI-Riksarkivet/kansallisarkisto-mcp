"""Telemetry: off by default, and when on, one trace across both layers.

The trace cascade is the invariant worth testing. FastMCP instruments the
`tools/call` boundary automatically and this project instruments the operations
and LanceDB layers by hand; if the two do not share a TracerProvider they
produce two disconnected traces and the whole thing is useless. That is checked
here against a real in-memory exporter rather than a mock.
"""

from __future__ import annotations

import logging

import pytest
from fastmcp import Client
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from ra_mcp_kansallisarkisto_lib.telemetry import get_meter, get_tracer, mark_span_error, record_span_exception
from ra_mcp_kansallisarkisto_mcp import telemetry, tools


@pytest.fixture(autouse=True)
def reset_search():
    yield
    tools._search = None


# --- off by default -----------------------------------------------------------


def test_telemetry_is_off_unless_explicitly_enabled(monkeypatch):
    """The default is no telemetry: a stdio client on a laptop should not try to
    reach a collector that is not there."""
    monkeypatch.delenv("KA_MCP_OTEL_ENABLED", raising=False)
    assert telemetry._is_enabled() is False


@pytest.mark.parametrize("value", ["true", "1", "yes", "TRUE"])
def test_enabling_accepts_the_usual_spellings(monkeypatch, value):
    monkeypatch.setenv("KA_MCP_OTEL_ENABLED", value)
    assert telemetry._is_enabled() is True


def test_init_is_a_no_op_when_disabled(monkeypatch):
    """It must not touch the SDK or install providers when switched off."""
    monkeypatch.delenv("KA_MCP_OTEL_ENABLED", raising=False)
    telemetry.init_telemetry()
    assert telemetry._initialized is False
    assert telemetry._providers == []


def test_shutdown_is_safe_when_never_initialised():
    """It is registered with atexit unconditionally, so it runs on every exit."""
    telemetry.shutdown_telemetry()


# --- the api-only helpers degrade to no-ops ----------------------------------


def test_helpers_work_with_no_sdk_configured():
    """The lib depends on opentelemetry-api only. With no SDK these must still
    return usable objects, or every instrumented call site would raise."""
    with get_tracer("test").start_as_current_span("span") as span:
        span.set_attribute("k", "v")
    get_meter("test").create_counter("test.counter").add(1)


def test_mark_span_error_without_a_recording_span():
    """Called from a tool handler that may run outside any span at all."""
    mark_span_error("something went wrong", "validation")


def test_record_span_exception_logs_once(caplog):
    """One failure unwinding through the spine and the tool layer must not log
    the same traceback twice and double the ERROR-log counter."""
    logger = logging.getLogger("test.telemetry")
    exc = RuntimeError("boom")
    with caplog.at_level(logging.ERROR):
        record_span_exception(logger, exc)
        record_span_exception(logger, exc)
    # Count records, not text: exc_info renders the message again in the traceback.
    assert len([r for r in caplog.records if r.levelno == logging.ERROR]) == 1


# --- the invariant: both layers land in one trace ----------------------------


_EXPORTER = InMemorySpanExporter()


@pytest.fixture(scope="module", autouse=True)
def _tracer_provider():
    """Install one real SDK TracerProvider for this module.

    Set once, not per test: opentelemetry's ProxyTracer caches the real tracer the
    first time it resolves one, so swapping providers per test would leave the
    module-level tracers in the lib still writing into the first test's exporter.
    The global is assigned directly because set_tracer_provider() is guarded by a
    run-once and would warn instead of taking effect.
    """
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(_EXPORTER))
    previous = trace._TRACER_PROVIDER
    trace._TRACER_PROVIDER = provider
    yield provider
    trace._TRACER_PROVIDER = previous


@pytest.fixture
def spans(_tracer_provider):
    """The recorded spans for one test, cleared so tests cannot see each other's."""
    _EXPORTER.clear()
    return _EXPORTER


async def test_manual_spans_nest_under_the_fastmcp_tool_span(spans, df_search):
    """The cascade: tools/call -> DfSearch.search -> search df, one trace id.

    If the layers were configured separately this would come back as two traces,
    and no backend could show the LanceDB latency underneath the tool call.
    """
    tools._search = df_search
    async with Client(tools.kansallisarkisto_mcp) as client:
        await client.call_tool("df_search", {"keyword": "konung"})

    recorded = spans.get_finished_spans()
    names = [s.name for s in recorded]
    assert "DfSearch.search" in names, names
    assert "search df" in names, names

    operations = next(s for s in recorded if s.name == "DfSearch.search")
    query = next(s for s in recorded if s.name == "search df")
    # The query span is a child of the operations span...
    assert query.parent is not None
    assert query.parent.span_id == operations.context.span_id
    # ...which is itself inside FastMCP's automatic tools/call span, in one trace.
    # Scoped to that trace deliberately: the client also issues tools/list on
    # connect, and that is a separate operation which *should* be its own trace.
    call_trace = query.context.trace_id
    in_call = {s.name for s in recorded if s.context.trace_id == call_trace}
    assert {"DfSearch.search", "search df"} <= in_call, in_call
    assert any(name.startswith("tools/call") for name in in_call), in_call
    assert operations.context.trace_id == call_trace


async def test_the_query_span_carries_what_was_asked_and_what_came_back(spans, df_search):
    tools._search = df_search
    async with Client(tools.kansallisarkisto_mcp) as client:
        await client.call_tool("df_search", {"keyword": "Åbo", "language": "latina", "limit": 1})

    query = next(s for s in spans.get_finished_spans() if s.name == "search df")
    assert query.attributes["db.system"] == "lancedb"
    assert query.attributes["db.collection.name"] == "df"
    assert query.attributes["db.query.text"] == "Åbo"
    assert "language = 'latina'" in query.attributes["db.query.filter"]
    # The total is the corpus's answer; returned_rows is the page. They differ.
    assert query.attributes["db.response.total_hits"] >= 1
    assert query.attributes["db.response.returned_rows"] == 1


async def test_a_tool_that_returns_an_error_string_still_flags_its_span(spans, df_search):
    """FastMCP reports OK whenever a handler returns normally, so without
    mark_span_error a server erroring on every call would show a zero failure
    rate. This is the test that pins that."""
    tools._search = df_search
    async with Client(tools.kansallisarkisto_mcp) as client:
        result = await client.call_tool("df_search", {"keyword": "   "})
    assert result.content[0].text.startswith("Error: keyword must not be empty")

    errored = [s for s in spans.get_finished_spans() if s.status.status_code is trace.StatusCode.ERROR]
    assert errored, [(s.name, s.status.status_code) for s in spans.get_finished_spans()]
    assert any(s.attributes.get("error.type") == "validation" for s in errored)


def test_shutdown_is_bounded_when_a_provider_hangs(monkeypatch, caplog):
    """A stuck exporter must not block interpreter exit.

    With the SDK enabled and no collector listening, an unbounded shutdown never
    returned: the OTLP gRPC exporter retries an unreachable endpoint with
    exponential backoff and `shutdown()` waits for it, which `force_flush`'s
    timeout does not bound. Since shutdown runs from atexit, that hung the
    process on every exit — for stdio, after every session.
    """
    import threading
    import time

    release = threading.Event()

    class Hanging:
        def force_flush(self, timeout_millis=None):
            release.wait(60)

        def shutdown(self):
            release.wait(60)

    monkeypatch.setattr(telemetry, "_providers", [Hanging()])
    monkeypatch.setattr(telemetry, "SHUTDOWN_TIMEOUT_SECONDS", 0.2)

    started = time.perf_counter()
    with caplog.at_level(logging.WARNING):
        telemetry.shutdown_telemetry()
    elapsed = time.perf_counter() - started
    release.set()  # let the daemon thread go

    assert elapsed < 5, f"shutdown blocked for {elapsed:.1f}s"
    assert "did not finish" in caplog.text
    assert telemetry._initialized is False
