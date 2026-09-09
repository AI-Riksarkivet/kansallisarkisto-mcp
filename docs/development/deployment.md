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

## Building the data

The tables are built by `make ingest-df` (or `scripts/ingest_df.py --output <path>`) from a
harvest of the Sisältöhaku export endpoint. Building an index mutates the on-disk dataset, so
indexes are baked in at ingest time and the served copy is read-only.

## Release

1. Bump `version` in both package `pyproject.toml`s and run `uv lock`.
2. Tag `vX.Y.Z` and push the tag.

`.github/workflows/publish.yml` then validates that the tag matches
`packages/kansallisarkisto-mcp/pyproject.toml`, runs the Dagger test suite, builds and pushes
`riksarkivet/kansallisarkisto-mcp:vX.Y.Z` and `:latest` with an SBOM and `provenance=mode=max`
attached, extracts the provenance back out of the pushed image as a release asset, signs the
image keylessly with cosign, and hands the digest to the SLSA trusted builder for Build L3
provenance. See [Security](security.md).

The Dagger module can also publish directly:

```bash
dagger call publish-docker \
  --docker-username env:DOCKERHUB_USERNAME \
  --docker-password env:DOCKERHUB_SECRET
```

which runs the tests and the build first, and refuses a tag that does not match the packaged
version unless `--skip-validation` is passed.

## Documentation

`.github/workflows/docs.yml` builds this site with `zensical build --clean` and deploys it to
GitHub Pages. It is **manual-only** (`workflow_dispatch`) while the repository is private,
since Pages is not available for private repositories on the free plan; restore the push
trigger when the repository goes public.
