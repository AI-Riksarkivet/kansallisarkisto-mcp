---
icon: lucide/activity
---

# Observability

Two probes and an OpenTelemetry layer, in the same shape as ra-mcp.

## Liveness and readiness are different questions

The server boots without a table **on purpose** — the image ships empty, the
table is mounted or ingested separately, and a missing mount should be a readable
message rather than a crash loop. That design has a consequence: "the process is
up" and "the process can answer a search" are genuinely different states, and a
single always-200 probe reported only the first.

| route | question | when the table is missing |
|---|---|---|
| `/health` | Liveness — is it serving HTTP? Restart it if not. | `200 {"status": "ok"}` |
| `/ready` | Readiness — can it actually search? Hold traffic back if not. | `503 {"status": "not ready", "reason": "…"}` |

`/health` deliberately does not touch LanceDB: a liveness probe that failed on
missing data would restart a process behaving exactly as designed. `/ready` goes
through the same `get_search()` the tools use, so readiness and the tools agree by
construction — if `/ready` says ready, a tool call will not come back with the
missing-table error. It never raises: a probe that 500s tells an orchestrator less
than one that answers "not ready" and why.

In Kubernetes, wire `livenessProbe` to `/health` and `readinessProbe` to `/ready`.

## Telemetry is off by default

Nothing is exported unless `KA_MCP_OTEL_ENABLED` is set. With it unset the
instrumentation resolves to no-op tracers and meters, which is what a stdio client
on a laptop should get — no collector to reach, and no cost for having the code
there.

| variable | default | meaning |
|---|---|---|
| `KA_MCP_OTEL_ENABLED` | `false` | Master switch. |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | `http://localhost:4317` | Collector endpoint. |
| `OTEL_EXPORTER_OTLP_PROTOCOL` | `grpc` | `grpc` or `http/protobuf`. |
| `OTEL_SERVICE_NAME` | `kansallisarkisto-mcp` | Service name on the resource. |
| `KA_MCP_OTEL_LOG_BRIDGE` | `true` | Bridge Python logging to OTel logs. |

## Two layers, one trace

FastMCP instruments the MCP boundary automatically. This project instruments the
layers beneath it by hand. Both share the global `TracerProvider`, so they nest:

```
tools/call df_search              ← FastMCP, automatic
└── DfSearch.search               ← manual: what was asked, in the caller's terms
    └── search df                 ← manual: what was run against LanceDB
```

The split is deliberate. The operations span knows the *question* — which filters
the caller set, in their own vocabulary — while the query span knows the
*execution*: the SQL predicate, the row counts, the latency. Rolling them into one
span would lose whichever half you did not name it after.

**Never add a manual span inside an `@mcp.tool()` handler.** FastMCP already
covers that boundary, and a second span there only nests a duplicate.

### Where the SDK lives

`kansallisarkisto-lib` depends on `opentelemetry-api` **only** — never the SDK.
The SDK and the OTLP exporters are dependencies of `kansallisarkisto-mcp`, and
`init_telemetry()` in its `telemetry` module is the single place they are touched.
That is what makes the lib usable on its own without dragging in an exporter, and
what makes "telemetry off" genuinely free.

### What is recorded

| span | attributes |
|---|---|
| `DfSearch.search` | `df.keyword`, `df.limit`, `df.offset`, `df.match_all`, `df.fuzzy`, plus `df.language` / `df.issuingplace` / `df.country` / `df.year_min` / `df.year_max` **only when set** |
| `search df` | `db.system`, `db.collection.name`, `db.query.text`, `db.query.filter`, `db.response.total_hits`, `db.response.returned_rows`, `db.response.total_is_capped` |
| `DfSearch.get_charter` | `df.number`, `df.found` |

Metrics, on the LanceDB layer where every search passes:
`kansallisarkisto.lancedb.queries`, `.errors`, `.query.duration`, and `.results`.

`.results` is a behavioural signal rather than a health one — its **zero bucket is
searches that matched nothing**, which is what people looked for that this corpus
cannot answer. The query terms stay on the span, not on the metric, where they
would explode cardinality.

### Errors have to be marked explicitly

Every tool here returns *text* rather than raising — an exception reaches the
model as a protocol error it cannot act on. But FastMCP's `tools/call` span
reports OK whenever a handler returns normally, so without help, a server whose
every call answered "the df table is not available" would show a tool failure rate
of exactly zero. `mark_span_error()` is called on each error-string path to flag
the span, with `error.type` grouping the class (`validation`, `missing_table`, or
the exception name).

## Shutdown is bounded on purpose

`shutdown_telemetry()` is registered with `atexit`, because without a final flush
the last batch of spans is lost every time the process exits — and for stdio that
is after every session.

It runs the flush on a **daemon thread joined with a timeout**, and that is not
belt-and-braces. Measured with the SDK enabled and no collector listening, an
unbounded shutdown *never returned*: the OTLP gRPC exporter retries an unreachable
endpoint with exponential backoff, `shutdown()` waits for that retry loop, and
`force_flush(timeout_millis=…)` does not bound it. Since this runs at exit, that
hung the process on every exit precisely when telemetry was misconfigured. A dead
collector now costs `SHUTDOWN_TIMEOUT_SECONDS` and a warning, never a hang.

## Verifying the cascade

The trace tree is the invariant: if the two layers do not share a provider they
produce two disconnected traces and no backend can show LanceDB latency under a
tool call. `packages/kansallisarkisto-mcp/tests/test_telemetry.py` asserts it
against a real in-memory span exporter — that the query span's parent is the
operations span, and that both sit in the same trace as FastMCP's `tools/call`.
