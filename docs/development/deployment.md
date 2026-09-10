---
icon: lucide/rocket
---

# Deployment

## The image

`.docker/kansallisarkisto-mcp.dockerfile` builds a digest-pinned `python:3.14-slim` image
that serves streamable HTTP on `:8000` as `USER 1000`.

It carries **no data**. The corpora are gigabytes, they are derived by a documented ingest,
and they change independently of the code — so they are mounted, not baked:

```bash
docker run -p 8000:8000 -v "$PWD/data:/data:ro" riksarkivet/kansallisarkisto-mcp:latest
```

`KA_LANCEDB_URI` defaults to `/data` in the image. Point it at object storage
(`s3://…`, `gs://…`) instead if that suits the deployment better — lancedb reads either.

Without a table the server still boots, logs which tables it did find, and answers every tool
call with a clear missing-table message. That is deliberate: a container that crash-loops on a
missing mount is harder to diagnose than one that says what it is missing.

### Liveness and readiness are different questions

`/health` answers "the process is up" and stays 200 even with no table mounted — restarting
would not conjure one. `/ready` answers "a search would actually succeed", and returns **503**
with a reason when it would not:

```json
{"status": "not ready", "table": "df", "reason": "The df table is not available on this server. …"}
```

It runs the same one-row probe as the boot check, because listing table names only reads the
manifest — which stays readable in exactly the case that bites hardest, a table whose data
files the runtime user cannot read (below). Point an orchestrator's readiness probe at
`/ready` and its liveness probe at `/health`; using `/health` for both routes traffic to a
server whose every tool call is an error message.

### The table has to be readable by uid 1000

**lance writes its data and index files mode `0600`** — owner-only. The container runs as
`USER 1000`, so a table that arrives owned by anyone else is unreadable, and the failure is
genuinely misleading: lance reports the resulting `EACCES` as

```
RuntimeError: lance error: Not found: /data/df.lance/_indices/<uuid>/tokens.lance
```

for a file that is sitting right there. Listing the table names still works, because the
manifest is read separately — so the table looks present and every search fails.

A bind mount from a uid-1000-owned directory is fine, which is why `docker run -v` and the
compose service work. Copying the table in is what breaks:

```dockerfile
COPY --chown=1000:1000 data /data    # not plain COPY
```

and in Dagger, `WithDirectory("/data", data, dagger.ContainerWithDirectoryOpts{Owner: "1000:1000"})`.

The server diagnoses this at boot rather than leaving it to the first query: after listing the
tables it runs one real search, and an unreadable table produces a startup error naming the
ownership cause. Non-fatal — a table mounted late should still start working.

## Hugging Face Space

The server is hosted at <https://huggingface.co/spaces/Riksarkivet/kansallisarkisto-mcp>; MCP
clients connect to `https://riksarkivet-kansallisarkisto-mcp.hf.space/mcp`. The Space runs the
published image: its Dockerfile is [`.docker/hf.dockerfile`](https://github.com/AI-Riksarkivet/kansallisarkisto-mcp/blob/main/.docker/hf.dockerfile),
which is `FROM` a release tag plus two settings.

The tables live in the private `Riksarkivet/kansallisarkisto` storage bucket, mounted
read-only at `/data`. That mount is a Xet-backed FUSE layer, and lance's concurrent random
reads fail on it under load with `os error 5` (EIO) — ra-mcp found this first. So the Space
sets `KA_MCP_STAGE_DATASETS=1`: at boot the server copies the tables from `/data` onto the
Space's ordinary disk (`KA_MCP_STAGE_DIR`, `/data-local`) and serves the copy. One sequential
read of the mount at boot is fine; it is the random reads at query time that fail. A copy
that fails is deleted rather than served, and the server falls back to the mount.

The bucket holds all three tables — `df.lance` (69 MB), `voudintilit.lance` (296 MB) and
`tuomiokirjat.lance` (22 GB: 11 GB of pages, 11 GB of full-text index). The boot-time copy
runs at about 100 MB/s off the mount — measured on the v0.3.0 deploy: all 22 GB staged in
220 s — so a cold start takes about four minutes before the court records serve, well inside
the Space's 30-minute startup limit. (A small copy looks far slower, 370 MB in 14 s, because
the mount's per-file cost dominates it.) The size is still the reason the tuomiokirjat table
carries no duplicate search column. Once warm, the server sits at about
7.5 GB resident with the full index in use, against the free tier's 16 GB; the first query
after a start pays a few seconds of index warm-up.

To publish new data, mirror `data/` into the bucket (this needs a recent `hf` CLI), then
restart the Space so it copies the new tables. **Mirror before deploying a release that adds
a table**: `/ready` requires every served table, so an image that knows `tuomiokirjat` and a
bucket that lacks it is 503 until the table arrives, while the other tools work.

```bash
hf buckets sync --delete data hf://buckets/Riksarkivet/kansallisarkisto
```

To deploy a release, bump the tag in `.docker/hf.dockerfile` and upload it as the Space's
Dockerfile:

```bash
hf upload Riksarkivet/kansallisarkisto-mcp .docker/hf.dockerfile Dockerfile --repo-type space
```

## Building the data

The tables are built by `make ingest-df` and `make ingest-voudintilit` (or the scripts they
call, with `--output <path>`) from a harvest of the Sisältöhaku export endpoint. `voudintilit`
also joins the Astia snapshot, `make fetch-astia`, for its references and page links — see
[The Corpora](../how-it-works/data-sources.md#voudintilit-bailiff-accounts). Building an index mutates the on-disk dataset, so
indexes are baked in at ingest time and the served copy is read-only.

## Release

1. Bump `version` in both package `pyproject.toml`s and run `uv lock`.
2. Tag `vX.Y.Z` and push the tag.

`.github/workflows/publish.yml` then validates that the tag matches
`packages/kansallisarkisto-mcp/pyproject.toml`, runs the Dagger test suite, gates on
`dagger call scan-ci` (Trivy CRITICAL/HIGH, fixable only) **before** anything is pushed,
builds and pushes `riksarkivet/kansallisarkisto-mcp:vX.Y.Z` and `:latest` with an SBOM and
`provenance=mode=max` attached, extracts the provenance back out of the pushed image as a release asset, signs the
image keylessly with cosign, and hands the digest to the SLSA trusted builder for Build L3
provenance. See [Security](security.md).

### What a manual run publishes

`publish.yml` also accepts a `workflow_dispatch`, and a dispatch is **not** a release:

- It still builds, scans, pushes, signs and generates **SLSA L3 provenance** — every image
  this workflow pushes is attested, on either trigger. That is the point of the job carrying
  no tag gate.
- It pushes only `:vX.Y.Z`, taken from `packages/kansallisarkisto-mcp/pyproject.toml`. It does
  **not** move `:latest`, because the tag/version validation cannot run without a tag ref, and
  an unvalidated build must not be able to replace the image everyone pulls by default.
- It skips the two release-asset steps (extracting the provenance blob and uploading it), which
  attach to a GitHub release a dispatch run does not have.

After the push the workflow pulls the image back from the registry and checks it serves
(`test-published`) — everything before that point exercises a locally built image, not the
artefact consumers receive.

There is deliberately only one publish path. A second, Dagger-native one existed and was
removed: it pushed under the same tags without SBOM, provenance or signature, and nothing
ever ran it — the same condition that had left `scan-sarif` broken since it was written.

## Documentation

`.github/workflows/docs.yml` builds this site with `zensical build --clean` and deploys it to
GitHub Pages on every push to `main`, and on demand via `workflow_dispatch`.

The repository is public, so the site is too: <https://ai-riksarkivet.github.io/kansallisarkisto-mcp/>.
