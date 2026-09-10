---
icon: lucide/hard-drive
---

# Local Install

## Requirements

- Python 3.14 and [uv](https://docs.astral.sh/uv/)
- A harvested Sisältöhaku export (see [The Corpora](../how-it-works/data-sources.md))

## Build the tables

```bash
git clone https://github.com/AI-Riksarkivet/kansallisarkisto-mcp
cd kansallisarkisto-mcp
make install
make harvest                                          # df: ~3 s
make ingest-df
uv run python scripts/harvest.py --index voudintilit  # ~1 min
make fetch-astia                                      # ~35 min, resumable
make ingest-voudintilit
```

`make ingest-df` reads `.data/df/df.jsonl.gz` and writes the `df` table into `data/`,
building a Swedish full-text index over the searchable text and scalar indexes on the
filtered columns. It takes a couple of seconds for `df`.

`make ingest-voudintilit` does the same for `.data/voudintilit/voudintilit.jsonl.gz`, joined
with the Astia snapshot `make fetch-astia` writes beside it — each volume's archival reference
and each page's image link, which the export itself lacks. Without the snapshot the pages
are still ingested, but carry neither.

Both directories are git-ignored: `.data/` is the 6.3 GB harvest, `data/` is derived from it.

Point an ingest elsewhere if your export lives somewhere else:

```bash
uv run python scripts/ingest_df.py --jsonl /path/to/df.jsonl.gz --output /path/to/lancedb
uv run python scripts/ingest_voudintilit.py --jsonl /path/to/voudintilit.jsonl.gz --astia /path/to/astia.jsonl --output /path/to/lancedb
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
| `KA_MCP_STAGE_DATASETS` | `false` | Copy the tables onto local disk at boot and serve the copy — for a Hugging Face Space, whose bucket mount lance cannot query under load. See [Deployment](../development/deployment.md#hugging-face-space). |
| `KA_MCP_STAGE_DIR` | `/data-local` | Where that copy goes. Must be writable by the runtime user. |
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
