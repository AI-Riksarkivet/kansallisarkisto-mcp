---
icon: lucide/shield-check
---

# Security

## Image scanning

`dagger call scan` builds the image from `.docker/kansallisarkisto-mcp.dockerfile` and runs
[Trivy](https://trivy.dev/) (`aquasec/trivy:latest`) against it, defaulting to
`--severity CRITICAL,HIGH --format table --exit-code 1 --ignore-unfixed` (`.dagger/scan.go`).

**`--ignore-unfixed` is on by default here, and that is a deliberate choice with a cost.**
The Debian base carries a standing set of unfixed OS-package CVEs (see
[Base image](#base-image-digest-pinned) for the measured list). Gating on those makes the
gate fail on every run forever, and a gate that always fails is one nobody reads. Gating on
*fixable* findings means a red scan is always something this repo can act on — and it turns
red the moment Debian ships a fix that a rebuild has not picked up, which is the signal worth
having. The cost is that an unfixed critical does not fail the gate, so the unfiltered view
is not optional: `dagger call scan --ignore-unfixed=false` (or `--format json --exit-code 0`
for a report that never fails). Two related functions, both rebuilding the image fresh so
results always reflect the current Dockerfile and lockfile:

- **`scan-ci`** — the CRITICAL/HIGH gate phrased for a pipeline: non-zero exit and a wrapped
  error message on failure. `.github/workflows/publish.yml` runs this **before** the push, so
  a release that would ship a fixable CRITICAL or HIGH never reaches the registry, and
  `security.yml` runs it weekly.
- **`scan-sarif`** — SARIF output to a file (`trivy-results.sarif` by default), the format
  GitHub's Security tab ingests. `security.yml` uploads it as a workflow artifact and, once
  Code Security is enabled on the repository, to the Security tab itself.

## SBOM generation

- **`generate-sbom-spdx`** — builds the image and runs Trivy again to emit an SPDX-JSON SBOM.
- **`generate-sbom-cyclone-dx`** — the same, in CycloneDX format.

Both run weekly in `security.yml`, are attached to every tagged release beside the
provenance, and are what `make sbom` writes locally. Append `export --path ./sbom.json` to
either to write the file rather than return a handle.

## Supply-chain attestations at publish time

`.github/workflows/publish.yml` (the release workflow — see [Deployment](deployment.md)) asks
`docker/build-push-action` to attach both an SBOM and SLSA provenance directly to the pushed
manifest: `sbom: true`, `provenance: mode=max`. After the push, it calls the Dagger
`extract-provenance-attestation` function
(`--image-ref riksarkivet/kansallisarkisto-mcp:<tag> export --path ./provenance.intoto.jsonl`), which uses
`crane` to pull the real provenance blob back out of the pushed image's attestation manifest
— not a separately regenerated one — and uploads it as a release asset, so the provenance a
consumer can inspect is provably the one BuildKit actually attached to what was pushed.

The image is then signed **keylessly** with [cosign](https://docs.sigstore.dev/cosign/overview/)
(installed via `sigstore/cosign-installer`, then `cosign sign --yes riksarkivet/kansallisarkisto-mcp@<digest>`).
No signing key is configured anywhere in the workflow: cosign uses GitHub Actions' own OIDC
token to obtain a short-lived certificate from Sigstore's Fulcio CA and records the signature
in the public Rekor transparency log — verifiable later against the GitHub Actions identity
that produced it, with no long-lived secret to leak or rotate.

## SLSA Build Level 3 provenance

The BuildKit provenance above is attached by the same job that builds — useful, but a
compromised workflow could forge it. On tag releases a second job therefore hands the pushed
digest to the SLSA project's trusted builder
([`slsa-github-generator`](https://github.com/slsa-framework/slsa-github-generator)'s
`generator_container_slsa3.yml` reusable workflow, referenced by release tag as its verifier
requires): an **isolated job with its own OIDC identity** regenerates the provenance, signs it
keylessly through Sigstore, and attaches the signed attestation to the image in Docker Hub.
That isolation is what makes it SLSA **Build L3** — the publish job cannot tamper with the
attestation that vouches for it. Consumers verify with:

```bash
slsa-verifier verify-image docker.io/riksarkivet/kansallisarkisto-mcp@<digest> \
  --source-uri github.com/AI-Riksarkivet/kansallisarkisto-mcp
```

## Base image, digest-pinned

`.docker/kansallisarkisto-mcp.dockerfile` builds on `python:3.14-slim` (Debian, glibc).

**This is forced, not chosen.** The obvious posture for a small scan surface is Alpine.
It is not available here: `lancedb` is a Rust extension published as
manylinux wheels only — no musllinux wheel and, because it also publishes no sdist, no
source fallback either. On a musl base `uv sync` fails outright, which is exactly how this
was found (`dagger call test-mcp` could not build the image). `pyarrow` does ship musl
wheels; `lancedb` alone settles it.

The security consequence is real, measured, and worth stating plainly rather than glossing.
Trivy on this image reports **54 CRITICAL/HIGH findings — 3 CRITICAL and 51 HIGH — and every
single one is unfixed upstream**: `perl-base`, `util-linux` and its libraries (`libblkid1`,
`libmount1`, `libuuid1`, `libsmartcols1`, `login`, `mount`), `ncurses`, `gzip`, `libsqlite3-0`,
`libsystemd0`. All of them are OS packages; **zero** are Python packages, so the dependency
surface the application actually controls is clean (and `pip-audit` gates that separately).

None of it is actionable *within Debian* — there is no patched version to move to. That is
precisely the package set an Alpine base avoids, and it is the price of the wheels. The image
is also ~880 MB rather than a few hundred. A different glibc base does clear them; see
[Wolfi, evaluated and deferred](#wolfi-evaluated-and-deferred) below.

What is gained in exchange: `python:3.14-slim` is the same base the CI test container and
the Dagger dev container use, so the published image runs on the same libc the tests ran
on — the alternative would have been testing on glibc and shipping on musl.

Both bases are pinned by digest, not just tag:

```dockerfile
FROM python:3.14-slim@sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6

COPY --from=ghcr.io/astral-sh/uv:0.12.5@sha256:db2d5999728c5837e1bf9ba278ee6b05cef1e95e82a20e27b0c915cb4478b9d7 /uv /uvx /bin/
```

so a `vX.Y.Z` image tag stays reproducible: rebuilding it later cannot silently pick up a
different base or `uv` build than the one that was actually scanned and signed at release
time.

### Wolfi, evaluated and deferred

Alpine is impossible, but it is not the only small base, and the 54 findings are not a fact
of life. A multi-stage [Wolfi](https://github.com/wolfi-dev) build — `cgr.dev/chainguard/python:latest-dev`
to build, `cgr.dev/chainguard/python:latest` to run — was built and measured against the
current image:

| | `python:3.14-slim` | Wolfi, multi-stage |
|---|---|---|
| Trivy CRITICAL/HIGH | 54 (3 CRITICAL) | **0** |
| Image size | 879 MB | **704 MB** |
| Python | 3.14.6 | 3.14.7 |
| libc | glibc (Debian 13.6) | glibc 2.44 |
| `lancedb` + FTS search | works | works |
| `/health` | 200 | 200 |
| `USER 1000` | yes | yes |

It works. Wolfi is glibc, so the manylinux wheels install exactly as they do on Debian; the
image was run and answered `/health`, and `lancedb` built an FTS index and returned hits from
it. Wolfi simply does not ship `perl` or `util-linux` in a Python runtime, which is where all
54 findings live. The runtime stage carries no shell or package manager, so it is also 175 MB
smaller than the Debian image despite the base being half the size of `python:3.14-slim`
(98.9 MB against 191 MB).

**It is deferred because it costs the digest pinning described just above.** Chainguard's
free tier publishes only `:latest`; versioned tags are a paid subscription. A digest can be
resolved and pinned, but old digests are garbage-collected, so a pinned digest goes
unpullable after some weeks and rebuilding an old `vX.Y.Z` tag fails. That trades away
exactly the reproducibility this section exists to guarantee, and `:latest` would float the
Python version too.

The trade is worth revisiting if the reproducibility guarantee is relaxed, if a paid
Chainguard tier becomes available, or if another digest-stable minimal glibc base appears.
Two other options were measured and rejected outright: `gcr.io/distroless/python3-debian12`
is *worse* (48 findings, 19 of them fixable — an older Debian 12), and `python:3.14-alpine`
scores 9 but cannot run `lancedb` at all.

## Non-root runtime

The final container runs as `USER 1000`, not root — declared in the Dockerfile, so the same
non-root posture applies under a plain `docker run` or `compose` as under a host that would
force it anyway (Hugging Face Spaces does).

This has a consequence worth knowing before it costs an afternoon: lance writes mode-`0600`
files, so a table copied into an image without `--chown=1000:1000` is unreadable by the
runtime user — and lance reports that permission error as `Not found`. See
[Deployment](deployment.md#the-table-has-to-be-readable-by-uid-1000); the server now catches
it at boot.

The data mount is read-only in `docker-compose.yml` (`../data:/data:ro`). The server never
writes: indexes are baked in at ingest time, and the ingest is a separate, offline step.

## Dependency audit

`dagger call checks` ends with `uv export --no-emit-workspace --format requirements-txt`
followed by `uv run --with pip-audit pip-audit --strict --desc -r <that file>`, run only after
`ruff format --check`, `ruff check`, and `ty check` all pass (`.dagger/checks.go`, `Checks`).
Exporting first (rather than auditing the live environment or shelling out via `uvx`, which
audits pip-audit's own ephemeral, unrelated venv) audits the project's real ~81 resolved
third-party dependencies while excluding the two local workspace packages
(`ra-mcp-kansallisarkisto-lib`, `ra-mcp-kansallisarkisto-mcp`) — they're never published to PyPI and always installed
editable, so pip-audit can't look them up and `--strict` would otherwise hard-fail on them
every run. A known-vulnerable dependency fails `make check`/`make ci` the same way a lint
error would — before an image is even built, let alone published.
