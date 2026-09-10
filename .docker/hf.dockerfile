# Hugging Face Spaces image — the Dockerfile of
# https://huggingface.co/spaces/Riksarkivet/kansallisarkisto-mcp.
#
# The Riksarkivet/kansallisarkisto storage bucket is mounted read-only at /data through
# a Xet FUSE layer. Serving lance queries straight off that mount fails under load —
# os error 5 (EIO) on concurrent random reads; ra-mcp hit this first. So the server
# copies the tables onto the Space's writable ephemeral disk once at boot and reads them
# there. The bucket stays the source of truth; no HF token or download is involved.
#
# KA_MCP_STAGE_DATASETS=1        copy the tables to local disk at boot
# KA_MCP_STAGE_DIR=/data-local   writable target on the ephemeral disk
#
# Deploy: bump the tag, then
#   hf upload Riksarkivet/kansallisarkisto-mcp .docker/hf.dockerfile Dockerfile --repo-type space
FROM riksarkivet/kansallisarkisto-mcp:v0.2.1

USER root
RUN mkdir -p /data-local && chown 1000:1000 /data-local
USER 1000

ENV KA_MCP_STAGE_DATASETS="1" \
    KA_MCP_STAGE_DIR="/data-local"
