---
icon: lucide/hard-drive
---

# Local Install

## Requirements

- Python 3.14 and [uv](https://docs.astral.sh/uv/)
- A harvested Sisältöhaku export (see [The Corpora](../how-it-works/data-sources.md))

## Build the table

```bash
git clone https://github.com/AI-Riksarkivet/kansallisarkisto-mcp
cd kansallisarkisto-mcp
make install
make ingest-df
```

`make ingest-df` reads `.data/df/df.jsonl.gz` and writes the `df` table into `data/`,
building a Swedish full-text index over the searchable text and scalar indexes on the
filtered columns. It takes a couple of seconds for `df`.

Both directories are git-ignored: `.data/` is the 6.3 GB harvest, `data/` is derived from it.

Point the ingest elsewhere if your export lives somewhere else:

```bash
uv run python scripts/ingest_df.py --jsonl /path/to/df.jsonl.gz --output /path/to/lancedb
```

## Run

```bash
uv run kansallisarkisto-mcp                          # stdio
KA_MCP_TRANSPORT=http uv run kansallisarkisto-mcp    # streamable HTTP on :8000
```

## Container

The image carries no data — the corpora are gigabytes and are rebuilt, not shipped. Mount a
LanceDB directory at `/data`:

```bash
docker build -f .docker/kansallisarkisto-mcp.dockerfile -t kansallisarkisto-mcp .
docker run -p 8000:8000 -v "$PWD/data:/data:ro" kansallisarkisto-mcp
```

Or via compose, which builds the image and mounts `./data` read-only:

```bash
docker compose -f .docker/docker-compose.yml up --build
```

## Settings

| variable | default | meaning |
|---|---|---|
| `KA_LANCEDB_URI` | *(resolved)* | Where the LanceDB tables live. Unset resolves to `<project root>/data` in a clone and `/data` in the image. Any lancedb URI works, including `s3://` and `gs://`. |
| `KA_MCP_TRANSPORT` | `stdio` | `stdio` or `http`. An unknown value fails loudly rather than silently serving stdio. |
| `HOST` | `0.0.0.0` | HTTP bind address. |
| `PORT` | `8000` | HTTP port. |
| `LOG_LEVEL` | `INFO` | Root log level. Logs go to stderr, so stdio transport stays clean. |
| `KA_MCP_OTEL_ENABLED` | `false` | Master switch for OpenTelemetry. Unset, the SDK is never initialised and every instrumentation call resolves to a no-op — which is what a stdio client on a laptop should get. |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | `http://localhost:4317` | Collector endpoint. Only read when telemetry is enabled. |
| `OTEL_EXPORTER_OTLP_PROTOCOL` | `grpc` | `grpc` or `http/protobuf`. |
| `OTEL_SERVICE_NAME` | `kansallisarkisto-mcp` | Service name reported to the collector. |
| `KA_MCP_OTEL_LOG_BRIDGE` | `true` | Bridge Python logging into OpenTelemetry logs. |

Settings are read from the environment or a `.env` file in the working directory. The
`OTEL_*` names are the OpenTelemetry SDK's own, so anything else it recognises works too;
none of them is read at all unless `KA_MCP_OTEL_ENABLED` is set.
