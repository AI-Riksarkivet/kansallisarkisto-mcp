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

## What the Security tab shows, and why it is not an emergency

`security.yml` uploads the **full** Trivy report to GitHub's code-scanning dashboard — every
severity, not just the gate's CRITICAL/HIGH — so the alert count there is larger than the six
above and will stay that way. All of it is the base image; **zero are Python packages**.

So the dashboard is a **report**, not a queue. The thing that gates a release is `scan-ci`,
which runs with `--ignore-unfixed` and therefore fails only on findings a rebuild or a
dependency bump can actually clear. An alert with a fixed version available is the signal
worth acting on. The standing remainder is not, and no amount of triage closes it until
Debian ships patches — which is exactly why the packages that could be removed were removed
instead.

The full unfiltered view, without the dashboard:

```bash
dagger call scan --ignore-unfixed=false
```

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

The security consequence used to be 54 CRITICAL/HIGH findings, every one unfixed upstream —
`perl-base`, `util-linux` and its libraries, `ncurses`, `gzip`, `libsqlite3-0`, `libsystemd0`.
That is the price of the wheels, and it is what a Debian base costs.

**Most of it was avoidable without changing base image.** The container runs one Python
entrypoint as a non-root user; it never executes perl, the util-linux tools, or systemd's
client libraries. Purging them in the final stage takes the image from **54 findings to 6,
and from three CRITICALs to none** — measured, with the full MCP smoke test passing
afterwards. See the Dockerfile for what is removed and why, and for the two packages
deliberately kept.

The six that remain are `ncurses` and `libsqlite3-0`, still unfixed and still unreachable.
They stay because CPython links them: removing them does reach zero, and it breaks
`import sqlite3`, `curses` and `readline`. Nothing here imports those today, but a future
dependency that did would fail at runtime rather than at build time — a bad trade for six
findings in libraries this server never calls.

Zero Python-package findings throughout; `pip-audit` gates that separately.

### Wolfi, evaluated and deferred

Alpine is impossible, but it is not the only small base, and the findings were never a fact
of life — the purge above already removed 48 of the original 54. This section is what was
measured before that, and is kept because it still decides the base image. A multi-stage [Wolfi](https://github.com/wolfi-dev) build — `cgr.dev/chainguard/python:latest-dev`
to build, `cgr.dev/chainguard/python:latest` to run — was built and measured against the
current image:

| | `python:3.14-slim` | Wolfi, multi-stage |
|---|---|---|
| Trivy CRITICAL/HIGH | 54 (3 CRITICAL), unpurged | **0** |
| Image size | 879 MB | **704 MB** |
| Python | 3.14.6 | 3.14.7 |
| libc | glibc (Debian 13.6) | glibc 2.44 |
| `lancedb` + FTS search | works | works |
| `/health` | 200 | 200 |
| `USER 1000` | yes | yes |

It works. Wolfi is glibc, so the manylinux wheels install exactly as they do on Debian; the
image was run and answered `/health`, and `lancedb` built an FTS index and returned hits from
it. Wolfi simply does not ship `perl` or `util-linux` in a Python runtime, which is where 48 of
the original 54 findings lived — the same packages the purge now removes from the Debian
image. The runtime stage carries no shell or package manager, so it is also 175 MB
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

Three other bases were measured:

| base | CRITICAL/HIGH | fixable | Python | digest-stable | verdict |
|---|---:|---:|---|---|---|
| `python:3.14-slim`, purged (current) | **6** | 0 | 3.14.6 | yes | in use |
| `python:3.14-slim`, unpurged | 54 | 0 | 3.14.6 | yes | what the purge replaced |
| Wolfi, multi-stage | **0** | 0 | 3.14.7 | **no** | deferred, see above |
| `gcr.io/distroless/python3-debian13` | 22 | 0 | **3.13.5** | yes | needs reverting the 3.14 bump |
| `gcr.io/distroless/python3-debian12` | 48 | 19 | 3.11 | yes | worse, and older |

`python3-debian13` was the interesting near-miss before the purge. It is now behind the
current image on findings (22 against 6) as well as on interpreter version, so the case for
it has gone. Wolfi still reaches 0 and is 175 MB smaller, and still costs digest pinning —
the purge closes most of that gap without paying for it.

`python:3.14-alpine` is not a trade-off, it is impossible. `lancedb` publishes exactly four
files — macOS arm64, manylinux aarch64, manylinux x86_64, Windows — with **no musllinux wheel
and no sdist**, so on musl `uv` can neither install it nor fall back to building it. Only a
musllinux wheel or an sdist from upstream changes that; `pyarrow`, by contrast, ships six.

### These findings are noise, not exposure

Worth stating plainly before anyone spends a week on the remaining six: they are unfixed, and
none is reachable. `ncurses` and `libsqlite3-0` are linked by CPython and never called by
this server, which runs one Python entrypoint as `USER 1000`. The release path gates on
*fixable* findings only.

So the case for going further — Wolfi's 0 — is signal-to-noise and attack surface, not
exploitable risk. That is a real benefit, and a different one from what the raw number
suggests. Removing the 48 that could be removed was worth doing because it was free; trading
digest-pinned reproducibility for the last six is not obviously so.

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
