# Kansallisarkisto MCP server — streamable-HTTP transport over LanceDB tables
# built from the Sisältöhaku corpora.
#
# Debian slim, not Alpine — and that is forced, not a preference. lancedb is a
# Rust extension published as manylinux wheels only: no musllinux wheel and no
# sdist at all, so on a musl base uv can neither install it nor fall back to
# compiling it. (pyarrow does ship musl wheels; lancedb alone settles it.)
# slim is glibc, so both install as wheels and the image still needs no compiler.
# It is also the base the CI test and dev containers use, so the published image
# runs on the same libc the tests ran on.
# Base images digest-pinned so versioned image tags (vX.Y.Z) cannot drift on rebuild.
FROM python:3.14-slim@sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6

# uv from the official distroless image.
COPY --from=ghcr.io/astral-sh/uv:0.12.5@sha256:db2d5999728c5837e1bf9ba278ee6b05cef1e95e82a20e27b0c915cb4478b9d7 /uv /uvx /bin/

WORKDIR /app

# Keep uv's wheel cache out of the image layers; a managed-python download would
# silently swap the interpreter the image was scanned with — hard-fail instead.
ENV UV_NO_CACHE=1 \
    UV_PYTHON_DOWNLOADS=never

# Manifests first: the third-party dependency layer survives source-only edits.
COPY pyproject.toml uv.lock ./
COPY packages/kansallisarkisto-lib/pyproject.toml packages/kansallisarkisto-lib/
COPY packages/kansallisarkisto-mcp/pyproject.toml packages/kansallisarkisto-mcp/
RUN uv sync --all-packages --no-dev --frozen --no-install-workspace

# Then the sources; only the fast workspace-package install reruns on code changes.
COPY packages/ ./packages/
RUN uv sync --all-packages --no-dev --frozen

# pip is unused at runtime (uv-managed venv, entrypoint invoked directly) and its
# vendored msgpack/setuptools trip the image scan (GHSA-6v7p-g79w-8964,
# CVE-2025-47273). Remove it rather than upgrade it: nothing here needs it.
RUN rm -rf /usr/local/lib/python3.13/site-packages/pip* /usr/local/bin/pip*

# The image carries no data: the corpora are gigabytes and are rebuilt, not
# shipped. Mount a LanceDB directory at /data (the default the server resolves to
# when there is no project root), or point KA_LANCEDB_URI at object storage.
# Without either the server still boots and every tool call says the table is missing.
ENV KA_MCP_TRANSPORT=http \
    KA_LANCEDB_URI=/data \
    HOST=0.0.0.0 \
    PORT=8000
EXPOSE 8000
# No VOLUME declaration: it would make every `docker run` without -v create an
# anonymous volume to accumulate, and the bind mount works without it.

# HF Spaces forces uid 1000 anyway; declare non-root for every other runtime too.
USER 1000

# Invoking the venv script directly means nothing needs write access at startup
# (uv run would write cache/lock state).
ENTRYPOINT ["/app/.venv/bin/kansallisarkisto-mcp"]
