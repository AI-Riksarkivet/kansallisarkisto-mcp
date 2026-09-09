---
icon: lucide/clipboard-check
---

# Code Audit

Two full reads of the codebase, newest first. Each read every source file, test, script,
Dagger function, workflow and doc page, and checked the behavioural claims by running them.

---

## Second audit — commit `8c61270`

Baseline: **194 tests passing, 7 skipped** (the corpus-only ones) in 10 s on Python 3.14.7;
`ruff check`, `ruff format --check` and `ty check` clean; `uv lock --check` clean;
`pip-audit --strict` over the exported third-party set reports no known vulnerabilities. On
GitHub, the Tests, CodeQL and Security workflows are green on `main`, and there are no open
pull requests or issues.

Every finding from the first audit that was marked resolved was re-checked. All of them
hold, with one exception recorded as finding 9 below.

### What holds up

**The substring filters cannot break out of their predicate either.** The first audit
tested injection through `language`, which is an `equals`. This one ran ten payloads through
`issuingplace` and `country`, which go through `text_contains` and LIKE — `' OR 1=1 --`,
`Åbo') OR (1=1`, `x' OR lower(issuingplace) LIKE '%`, and the wildcard cases `%`, `_`, `\`,
`\%`, `%'%`. Every one returned 0 hits against a 7-hit unfiltered baseline, i.e. it was
matched as a literal string. The `ESCAPE '\'` clause is honoured by the engine: a bare `%`
matches nothing rather than everything.

**Model-shaped input does not raise.** `""`, `"`, `" "`, a 5,000-character keyword, a phrase
mixed with a loose term, a keyword with a newline — all answered, none escaped. Together
with the `_answer` wrapper this means nothing reaches the client as a protocol error.

**The lock, the audit and the pins.** The lockfile is current, no locked dependency has a
known advisory today, every action is SHA-pinned, the base image and the uv binary are
digest-pinned, and the auto-merge job is scoped to the two permissions it needs.

**The first-audit fixes are real.** Out-of-range DF numbers return `None`, fuzzy on a quoted
phrase is refused with a sentence, a lancedb `ValueError` is folded into the generic reply,
the FTS configuration is asserted against the index actually built, and the bounded
telemetry shutdown is pinned.

### Findings

#### 1. `/ready` reports ready forever after its first success, and does not run the probe the docs describe

Verified on the fixture: ingest a table, call `readiness()` → `(True, 'df')`. Delete the
table directory. `readiness()` → still `(True, 'df')`, while a search now raises
`Table 'df' was not found`. Only resetting the cached facade makes the probe notice.

`readiness()` goes through `get_search()`, whose whole job is to build the `DfSearch` facade
once and cache it. That is right for the tools and wrong for a probe, because a probe is
asked *repeatedly* precisely so that it can change its answer. And `get_search()` never runs
a query — it lists table names, which the first audit's finding 4 and `probe_table_readable`
both explain is the one check that stays green in the case that bites hardest: lance's
mode-0600 files owned by the wrong uid, where the manifest reads fine and every search fails.

The documentation says otherwise. `deployment.md`: "It runs the same one-row probe as the
boot check, because listing table names only reads the manifest". The resolved-box under
finding 4 below: "running the same one-row probe as the boot check rather than trusting a
table listing". `observability.md` describes the code as it is ("goes through the same
`get_search()`") — so the three pages disagree, and the two that promise the probe are the
ones an operator would read when wiring a readiness check.

The fix is small: have `readiness()` run the one-row `PROBE_KEYWORD` search on every call
(it is a few milliseconds on a mounted table), and drop the cached facade when it fails so a
late-arriving mount is picked up. Then the prose is true.

#### 2. `/ready` returns exception text to an unauthenticated caller

With `KA_LANCEDB_URI` pointed at a regular file:

```
GET /ready -> 503 {"status": "not ready", "reason": "FileExistsError: [Errno 17] File exists: '/tmp/…/nope.txt'"}
```

`readiness()` formats the fallback branch as `f"{type(exc).__name__}: {exc}"`. The tools
deliberately keep only the type (`format_error`, and the first audit's finding 12 is about
exactly this class of leak); the probe is a plain HTTP route on the same listener and gets no
such treatment. The message should go to the log and the type to the response.

#### 3. CI cannot fail on formatting or fixable lint

`.dagger/checks.go`, `Checks`: step 1 runs `ruff format .`, step 2 runs `ruff check --fix .`,
and only then step 3 runs `ruff format --check` and `ruff check`. Inside the container the
files have just been formatted and fixed, so the two checks can only pass. A push with
unformatted code, or with a lint error ruff can auto-fix, goes green — and the fix stays in
the container, so `main` carries the drift. Only `ty` and unfixable lint errors gate.
`make check` has the same shape locally, which is fine for a developer target and is presumably
where the CI version was copied from.

Both tools also run as `uvx ruff` / `uvx ty`, i.e. whatever is latest on the day. A ruff
release that changes a formatting rule changes what CI "verifies" without a commit, and the
`ruff` in `uv.lock` (which `make format` uses) may disagree with it. Verify-only in CI, and
run the locked ruff, and this is closed.

#### 4. A `workflow_dispatch` can overwrite a released image tag

`publish.yml` on dispatch computes `TAG=v$(version from pyproject)` and pushes
`riksarkivet/kansallisarkisto-mcp:${TAG}`. After `v0.1.0` has been released, any dispatch
from a commit whose `pyproject.toml` still reads `0.1.0` — every commit until the next bump —
re-pushes `:v0.1.0` with different content, signs it, and hands the new digest to the SLSA
job, which attests it. The first audit's 5b closed the `:latest` half of this and left the
version tag open. The Dockerfile's own comment says digest-pinned bases exist "so versioned
image tags (vX.Y.Z) cannot drift on rebuild"; this path drifts them from the other side.

A dispatch should push a tag that cannot collide with a release — `sha-<short>` or
`v0.1.0-dev.<run_number>` — or the workflow should refuse to push a version tag that already
exists in the registry.

#### 5. Dependabot auto-merge will rarely fire for Python

`dependabot.yml` groups every pip update into `python-packages`. A grouped pull request is
titled "Bump the python-packages group … with N updates", which has no `from X to Y`, so the
auto-merge script's parser finds nothing and leaves it for review — as its own comment says
it will. Only a group that happens to contain a single package keeps the parseable title.
The docker, github-actions and gomod ecosystems are ungrouped and do merge. `SECURITY.md`
("patch and minor bumps merge automatically once tests pass") and the workflow header
promise more than this delivers for the ecosystem with the most updates.

Two options: drop the group so each Python bump is its own PR, or read the bump range from
the PR body (Dependabot lists each package there) instead of the title.

Related, and worth knowing rather than fixing: the merge gate is the Tests workflow alone.
The Security workflow's Trivy gate runs *after* merge, on push to `main`, and only when the
lockfile or image changed — so a bump that introduces a fixable CVE is merged first and
flagged second.

#### 6. One out-of-range DF number aborts the whole ingest

A line with `"df": "99999999999"` — numeric, so `from_json` sets `df_number` — raises
`ArrowInvalid: Value 99999999999 too large to fit in C integer type` from
`RecordBatch.from_pylist`, which is outside the per-line guard, and the run stops with a
half-built table. The per-line skip that `_df_batches` promises covers parse errors only.
The corpus has no such value today, but the whole point of that guard is that the harvest is
re-runnable and the sibling corpora differ. `get_charter` already range-checks against
`int32`; `from_json` should do the same and store `None`.

A smaller cousin: `df.isdigit()` is true for `"²"`, and `int("²")` then raises, so a charter
whose `df` field carried a superscript would be *skipped entirely* over a cosmetic field
rather than kept with `df_number=None`. `isdecimal()` is the test that matches `int()`.

#### 7. The CI and release tooling runs on floating image tags

The production image is digest-pinned; the containers that test and release it are not:

| where | image |
|---|---|
| `main.go` `withUv`, `test.go` | `ghcr.io/astral-sh/uv:latest` |
| `main.go` `buildWithUv`, `test.go` | `python:3.14-slim` (no digest) |
| `scan.go` | `aquasec/trivy:latest` |
| `serve.go` | `curlimages/curl:latest` |
| `scan.go` `ExtractProvenanceAttestation` | `alpine:latest` + `apk add jq`, `crane:latest` |
| every workflow | `dagger-for-github` with `version: "latest"` |

Two consequences. The test suite runs on whichever `python:3.14-slim` is current, which is
not necessarily the digest the image ships — the README's "runs on the same libc the tests
ran on" is true of the distribution, not the build. And the release path itself
(`extract-provenance-attestation`) pulls two unpinned images and installs a package from
Alpine's repository at release time. Scorecard does not see any of it — it does not parse a
Go Dagger module — so its Pinned-Dependencies score of 9/10 on the latest green run counts
"1 out of 1 container image pinned" and overstates the position. Digest-pin the ones in the
release path first; the rest can follow via Dependabot only if they move into a Dockerfile
it parses, so they need a note in `docs/development/security.md` either way.

#### 8. `dataset.py` says it has no telemetry

The module docstring: "Ported from ra-mcp's `ra_mcp_dataset_lib`, with its OpenTelemetry
layer left out: this server, like ape-mcp, has no telemetry stack." Forty lines later the
module creates a tracer, a meter, three counters and two histograms. In a codebase where the
prose is load-bearing this is the sentence a reader meets first.

#### 9. Documentation drift, second round

- **`docs/development/index.md`** — the Makefile table does not list `harvest`,
  `verify-data`, `scan` or `sbom`. The first audit's finding 10 is marked resolved with
  "the Makefile table covers `harvest` and `verify-data`"; it does not. The repo-layout
  block does list `harvest.py`, which is the half that was done.
- **`docs/development/index.md`** — "`make ci` runs exactly what `.github/workflows/ci.yml`
  runs". `ci.yml` also runs `test-server`; the `ci` Make target does not.
- **`docs/development/deployment.md`** — the not-ready example shows a `"table": "df"` key
  the response does not carry.
- **`docs/api/index.md`** — lists three URI-resolution steps; the code and the `config`
  docstring have four (the last falls back to `<root>/data` even when it does not exist).
- **27 vs 28** compound-language charters: `search-tips.md` says 27, the `df_search` field
  description says 28.
- **`SECURITY.md`** — "Trivy scans the published image weekly". It scans a fresh build of
  the current Dockerfile; the published image is checked only by `test-published`, and only
  for `/health`.
- **Finding 11 below** still lists `HOST`, `PORT` and `LOG_LEVEL` as unprefixed, and they
  still are. Carried, not re-argued.

#### 10. The Python pin resolved to a release candidate

`.python-version` says `3.14`. On a machine whose `uv` predates the 3.14.0 final release,
that resolves to `3.14.0rc2`, and there `import lancedb` fails at collection time inside
pydantic: `_eval_type() got an unexpected keyword argument 'prefer_fwd_module'`. That is
what this audit hit first; the 194-passing baseline above is on 3.14.7 after installing a
current uv. Not a code defect, but `3.14.7` in `.python-version` (or a note in the setup
page) spares the next person the detour. The Dagger containers are not affected — they pull
`python:3.14-slim`, which is a final release — so CI never saw it.

#### 11. Smaller things

- **`get_charter` truncates floats and accepts booleans.** `int(1.5)` is 1 and `int(True)`
  is 1, so both return DF 1. Unreachable through the MCP tool, which types the argument as
  `int`; reachable through the library, which the docs say is usable on its own.
- **`keyword="df"` matches every charter**, because the citation `df <number>` is in every
  record's search text. By design, and harmless with `match_all=True`, but a model that
  includes the word `DF` in a `match_all=False` search gets the whole corpus.
- **`harvest.py` writes `checkpoint.json` non-atomically**, so a crash mid-write leaves a
  file the next `--resume` cannot parse. Write to a sibling and rename.
- **`scripts/ingest_df.py` does `Path(resolve_lancedb_uri()).mkdir()`**, so an `s3://`
  override creates a local directory named `s3:` before lancedb sees the URI.
- **`publish.yml` runs `test` and `scan-ci` but not `checks`**, so pip-audit does not gate a
  release. Trivy does scan the Python packages in the image, which is why this is minor.
- **`trufflehog.yml` triggers on both `push` and `pull_request`**, so a same-repo PR is
  scanned twice per push.
- **The latest Scorecard run on `main` failed** with a GitHub-side GraphQL error
  (`ListCommits … Something went wrong while executing your query`). The run before it
  passed and published a score of **6.3**; nothing in the repository caused the failure.
- **`main` has no branch protection**, and Scorecard scores Branch-Protection and
  Code-Review at 0 for it (0 of the last 30 changesets reviewed). The auto-merge workflow's
  header already says so, and it is why that workflow gates on a completed run rather than
  on required checks. Everything above about what CI does or does not catch is bounded by
  this: nothing stops a direct push to `main` that skips CI altogether.
- **HTTP transport has no authentication and no host validation.** FastMCP's
  `http_host_origin_protection` defaults to off, the server trusts every proxy header
  (`forwarded_allow_ips="*"`), each search materialises up to 10,000 rows, and keyword length
  is unbounded. All of it is acceptable for stdio and for a container behind a proxy, which
  is the documented deployment; it is the list of things to settle before a hosted endpoint
  exists.

### Behaviour confirmed as correct

| checked | result |
|---|---|
| Wildcards and quotes through `issuingplace` / `country` | `%`, `_`, `\`, `\%`, `%'%` and five injection strings all match as literals: 0 hits each |
| Degenerate keywords | `""`, `"`, `" "`, 5,000 × `a`, `konung\nÅbo` — answered, no exception |
| Phrase mixed with a loose term | `'"Åbo" konung'` routes to the parser and returns 7 |
| `get_charter(" 1031 ")`, `("1_031")` | both 1031 — `int()` semantics, as documented |
| `get_charter("1031.0")`, `("0x40f")` | `None`, as documented |
| A `²` in the `df` field | logged and skipped as a bad line, ingest completes with 18 rows |
| `pip-audit --strict` on the exported lock | no known vulnerabilities |
| `uv lock --check` | current |

### Suggested order of work

1. **Finding 1** — a real probe in `readiness()`, then the three pages agree.
2. **Finding 4** — a non-colliding tag for dispatch runs; one line in `publish.yml`.
3. **Finding 3** — verify-only in the CI `Checks`, on the locked ruff.
4. **Finding 2** — type-only in the `/ready` fallback.
5. **Findings 8, 9, 10** — text, and the `.python-version` pin.
6. **Finding 6** — the int32 guard in `from_json`, with a test line in `test_ingest.py`.
7. **Findings 5, 7** — process; decide, then either fix or document the limit.

---

## First audit — commit `c81ffa4`

A full read of the codebase at commit `c81ffa4` — every source file, test, script, Dagger
function, workflow and doc page — with the behavioural claims checked by running them rather
than by reading them.

Baseline at the time of the audit: **130 tests passing** in 3.3 s, `ruff check`, `ruff format
--check` and `ty check` all clean, 46 files formatted. The findings below are what survives
that clean baseline.

## What holds up

Worth stating first, because it shapes how the findings should be read.

**Filter values cannot break out of their SQL predicate.** Three injection payloads were run
through the `language` filter against the fixture — `latina' OR '1'='1`, `latina'; DROP TABLE
df; --`, and `x' OR df_number > 0 OR 'x'='x`. All three returned 0 hits, i.e. they were
matched as literal strings, against a 7-hit unfiltered baseline. `_sql_str` doubles single
quotes and `text_contains` escapes LIKE wildcards in the correct order (backslash first, then
`%` and `_`), so a literal `%` in a filter matches a literal `%`.

**Errors do not leak internals.** `format_error` keeps the exception type — which is what
lets a caller tell a transient failure from a permanent one — and drops the message, which
for lance errors quotes the on-disk dataset path. Pinned by a test.

**The retrieval-quality suite is the most valuable thing in the repository.** It asks whether
the design is *adequate*, not merely whether the code matches it, and it caught three ways
documents were silently unfindable: words fused to footnote superscripts, words split by
editorial brackets, and Swedish stop-word removal deleting Latin content words. Each fix is
now pinned against the fixture. Most codebases have nothing in this category.

**The boot probe earns its place.** Running one real query at startup catches the case where
lance reports an `EACCES` on its mode-0600 files as `Not found` — a failure that otherwise
sends an operator hunting for a file that is sitting right there.

**Supply chain is genuinely tight**: digest-pinned base image, SHA-pinned actions, keyless
cosign signing, and SLSA Build L3 provenance from an isolated trusted builder.

The code is also unusually well commented, and the comments explain *why*, with measured
numbers attached. That is precisely why the documentation-drift findings below are real
defects rather than nitpicks: in this repository the prose is load-bearing, and a reader has
been trained to trust it.

---

## Findings

### 1. `get_charter` raises instead of returning `None` above 2³¹

!!! success "Resolved"

    The `int()` guard now range-checks against the int32 column, so an out-of-range number
    returns `None` as documented rather than surfacing as an internal error.

!!! success "Resolved"

    `get_charter` now range-checks against `int32` and returns `None`; verified for
    `2**31`, `2**63` and `10**20`.

`df_number` is an `int32` column. Any number at or above `2**31` fails predicate resolution:

```
get_charter(2147483647)  -> None      (fine)
get_charter(2147483648)  -> ValueError: Invalid input, Error resolving filter
                            expression df_number = 2147483648
```

Both the docstring ("or ``None`` if there is no such charter") and `docs/api/search.md`
("Returns the charter row, or `None` for an unknown or non-numeric number") promise otherwise.
The MCP tool declares `df_number` as `int` with `ge=1` and no upper bound, so a model passing
a large number gets `Error: the search failed with an internal ValueError` — the generic
server-fault reply — for what is an ordinary out-of-range lookup.

The non-numeric case is already handled by the `int()` guard. Extending that guard to a range
check, or adding `le=2**31 - 1` to the field, restores the documented contract.

### 2. `fuzzy` is silently ignored for a quoted keyword

!!! success "Resolved"

    The combination now raises with a sentence saying what to do instead, and the MCP layer
    returns caller-fixable `ValueError`s verbatim rather than folding them into the generic
    internal-error reply. The field description says it too.

!!! success "Resolved"

    The combination is now rejected with an actionable sentence rather than silently
    dropped — see finding 12 for the disclosure bug that fix briefly introduced.

`lancedb_fts_search` routes any keyword containing `"` to the raw query parser, which takes no
fuzziness argument — so `fuzzy` is dropped with no signal:

```
search('"de ecclesia"', fuzzy=0)  -> 1 hit
search('"de ecclesia"', fuzzy=2)  -> 1 hit
```

The tool advertises `fuzzy` as 0–2 unconditionally. This is the same shape of problem the
recent `fix(mcp): stop telling the model to use operators that do not exist` commit addressed:
a parameter the description offers and the engine quietly discards. Either say so in the field
description, or reject the combination with an actionable sentence — the pattern the inverted
year range already uses.

### 3. Two docstrings state the wrong default for `fuzzy`

!!! success "Resolved"

    Both corrected, and `test_search_invariants.py` now asserts the docstring against the
    constant — the point being that nothing tested prose.

!!! success "Resolved"

    Both now say 0, matching `DEFAULT_FUZZINESS` and the reasoning around it.

```
dataset.py:236           "see DEFAULT_FUZZINESS for why it defaults to 1 rather than 0"
search_operations.py:63  "fuzzy: Edit distance allowed per term (default 1)."
```

`DEFAULT_FUZZINESS = 0`, and the surrounding prose argues at length *for* zero — fuzzy
matching and stemming are mutually exclusive in the engine, so `konungen` collapses from 279
hits to 6. The two docstrings contradict the constant sitting beside them and the reasoning
around them. Confirmed on the fixture: `konungen` gives 3 hits at `fuzzy=0` and 0 at
`fuzzy=1`.

Nothing tests a docstring, and `docs/api/` is written by hand from these, so this propagates.

### 4. `/health` reports OK while every tool call fails

!!! success "Resolved"

    Split into `/health` (liveness, always 200) and `/ready` (readiness, 503 when
    the table cannot be searched), the same shape as ra-mcp — alongside a full
    OpenTelemetry layer. See [Observability](observability.md).

!!! success "Resolved"

    `/ready` added, returning 503 with a reason when a search would fail, and running the
    same one-row probe as the boot check rather than trusting a table listing. `/health` is
    unchanged and remains liveness — restarting the process would not conjure a table.

Verified: with the LanceDB URI pointed at an empty directory, `GET /health` returns `200
{"status": "ok"}` while `df_search` returns `The df table is not available on this server`.

Booting without data is a deliberate and well-argued choice, and the boot log says what is
missing. But the HTTP probe does not, so an orchestrator will route traffic to a server whose
every tool call is an error message. The distinction needed is liveness versus readiness —
either have `/health` report table status, or add a separate readiness route that the boot
probe's result feeds.

### 5. The end-to-end test that CI needs most is the one CI never runs

!!! success "Resolved"

    `test-mcp` now runs in `.github/workflows/ci.yml` and `scan-ci` gates
    `publish.yml` before the push; `make ci` runs all three calls so it still matches CI.
    Both were verified green locally before wiring — `scan-ci` reports 0 findings across
    every target, and `test-mcp` passes all 6 checks. The remaining unwired functions below
    are still unwired.

`.github/workflows/ci.yml` ran `dagger call checks` and `dagger call test`. That was all.

`docs/development/index.md` describes `test-mcp` as "the only place the **index configuration**
is verified end to end — Swedish stemming and accent folding are index-time settings, so a
wrong FTS config is invisible to anything that searches only exact forms." It is correct, and
that check ran only when someone typed `make test-mcp` locally.

`publish.yml` ran `test`, but not `checks` and not `scan` — so a release image was built and
pushed without the Trivy gate that `docs/development/security.md` describes in detail.

!!! success "Resolved"

    Every remaining function is now either executed or gone.

    A new `security.yml` runs `scan-ci` as a gate, then `scan-sarif`, on pushes that touch
    the image or its dependencies and weekly on a schedule — CVE surface moves when
    advisories are published, not when this repository is edited. It uploads the SARIF as a
    workflow artifact and, best-effort, to the Security tab: code scanning needs GitHub Code
    Security, which is off for this private repository and answers 403, so that step is
    `continue-on-error` and starts working the moment it is enabled. A second job produces
    both SBOM formats.

    `publish.yml` gained the SBOMs as release assets beside the provenance, and a
    `test-published` step that pulls the pushed image back and checks it serves — everything
    earlier in the job exercises a locally built image, not the artefact consumers receive.

    `make scan` and `make sbom` make the developer-facing variants reachable, and
    `test-server` joined `ci.yml`: it is the only check of the documented no-data path, where
    the image ships empty and the server must still boot and answer `/health` rather than
    crash-loop — `test-mcp` always mounts a table.

    `scan-json` and `export-sbom` were deleted rather than wired. Both were thin wrappers
    over `scan` and `generate-sbom`, which already take the format and exit-code parameters;
    two names for one behaviour is how `scan-sarif` stayed broken unnoticed.

    **`scan-sarif` was broken**, which is what being never-executed buys you: it wrote to
    `/output/` without creating it, so every run would have ended in "failed to create output
    file". The SBOM functions had the `mkdir -p` line and it did not. Fixed and verified —
    it now emits valid SARIF 2.1.0 with 173 results.

    **`publish-docker` was deleted** rather than wired. It pushed under the same tags as the
    release workflow but without SBOM, provenance or signature, and nothing ran it — the same
    condition that had left `scan-sarif` broken. An untested path that writes to a public
    registry is worse than no path. `getVersion` and `validateVersion` went with it; the
    workflow validates the tag in bash, and now checks **both** package versions rather than
    only the one the image is named after.

Ten Dagger functions remained wired into no workflow and no Make target. None was a gate, so
none was urgent, but each was code that was maintained and never executed:

```
scan          scan-json     scan-sarif
generate-sbom-spdx    generate-sbom-cyclone-dx    export-sbom
test-server   test-published    serve-published    publish-docker
```

`scan-sarif` was the notable one: it existed to feed GitHub's Security tab, and nothing
uploaded its output.

### 5b. `workflow_dispatch` published without provenance

!!! success "Resolved"

    The `provenance` job's `if: startsWith(github.ref, 'refs/tags/v')` gate is removed, so
    every image the workflow pushes is attested. A dispatch no longer moves `:latest`.

Found while wiring the above. `publish.yml` fires on tag pushes **and** `workflow_dispatch`,
and the publish job pushed `:latest` on both — but the SLSA L3 `provenance` job, the
provenance extraction and the release upload were all gated on a tag ref. A manual run
therefore replaced the image everyone pulls by default with one carrying no SLSA attestation,
having also skipped the tag/version validation, which cannot run without a tag.

The provenance job is now ungated: it attaches the attestation to a registry **digest**, which
exists on either trigger. The two release-asset steps stay tag-gated, since they attach to a
GitHub release that a dispatch run does not have.

### 6. The fixture holds 18 charters, and seven places say 16

!!! success "Resolved"

    All seven now say 18, derived from `wc -l` on the fixture rather than retyped.

`df_sample.jsonl` has 18 lines. `test_ingest.py` asserts `DF_FIXTURE_ROWS = 18` and passes.
The prose says 16 in:

```
README.md:140                                   .dagger/serve.go:18
docs/development/index.md:56                    .dagger/testmcp.go:10
packages/kansallisarkisto-lib/tests/conftest.py:12
packages/kansallisarkisto-mcp/tests/conftest.py:11
scripts/mcp_smoke.py:3
```

The tests are right; the descriptions are stale. Two charters were added without the count
following.

### 7. `docs/api/search.md` is the one page that never learned about `fuzzy`

!!! success "Resolved"

    Both signatures now carry `fuzzy=0`, with the stemming trade-off and the quoted-phrase
    rejection written out, plus the `SearchInputError` contract from 12 below.

It reproduces both signatures exactly — and both omit the parameter:

```python
search(keyword, *, limit=25, offset=0, language=None, issuingplace=None,
       country=None, year_min=None, year_max=None, match_all=True) -> SearchResult

lancedb_fts_search(db, table_name, keyword, *, limit, offset=0,
                   where=None, columns=None, match_all=True) -> SearchResult
```

`docs/tools/df-search.md`, `search-tips.md` and `data-sources.md` all document `fuzzy`. The
API reference — the page whose whole job is the signature — is the one that missed it.

### 8. `docs/how-it-works/index.md` credits the index with stop-word removal

!!! success "Resolved"

    The bullet now says stop-word removal is deliberately **off**, and why.

> **`build_fts_index`** — the Swedish full-text index, with stemming, stop-word removal,
> accent folding and a raised token-length limit …

Stop-word removal is **off**, and turning it off is one of the better-argued decisions in the
codebase: Swedish stop words are Latin content words here, and removing them cost `de` 1,735
documents, `den` 846 and `om` 1,133. `search-tips.md` states the opposite, correctly ("Stop
words are **kept**, unlike a normal Swedish index"). `remove_stop_words=False` is indeed
*passed explicitly*, which is presumably what the list meant, but it reads as a feature list.

### 9. README duplicates its architecture bullets

!!! success "Resolved"

    The duplicate pair is gone; the workspace bullets appear once.

Lines 89–92 and 96–99 are the same two bullets, once under the diagram and once under "A uv
workspace of two packages", with only a trailing clause differing.

### 10. The repo-layout block omits the largest script

!!! success "Resolved"

    `harvest.py` is listed, and the Makefile table covers `harvest` and `verify-data`.

`docs/development/index.md` annotates `scripts/` as "ingest_df.py, mcp_smoke.py". It also
contains `harvest.py` — 410 lines, the single biggest file in the repository and the entry
point for the entire data pipeline. The Makefile table on the same page likewise omits the
`harvest` and `verify-data` targets.

### 11. Smaller things

- ~~**No `LICENSE` file**~~ — added.
- ~~**Version validation covers one package**~~ — `publish.yml` now checks both.
- ~~**Two publish paths**~~ — the unattested Dagger `PublishDocker` path was deleted.
- ~~**`build_fts_index` hardcodes the column literal**~~ — it defaults to `FTS_COLUMN`.
- ~~**The fuzzy-default test takes an unused fixture**~~ — dropped, saving an ingest per run.
- ~~**`or` cited as 51 and 50**~~ — 51 is right; confirmed by ingesting the full 6,876-charter
  corpus and running the query. The test docstring was the wrong one.
- **`HOST`, `PORT` and `LOG_LEVEL` are unprefixed** (`env_prefix=""`), unlike the `KA_`-prefixed
  pair. An unrelated `PORT` in the environment silently retargets the server.
- **Version validation covers one package.** Both `publish.yml` and Dagger's `validateVersion`
  checked only `packages/kansallisarkisto-mcp/pyproject.toml`; the lib version could drift
  unnoticed. **Resolved** — `publish.yml` now validates both manifests against the tag.
- **Two publish paths.** CI published via `docker/build-push-action` while Dagger's
  `PublishDocker` was never called and pushed no attestations. **Resolved** — `PublishDocker`
  is deleted; there is one publish path.

### 12. A lancedb `ValueError` reached the client verbatim

!!! success "Resolved"

    `SearchInputError` now separates this library's own validation messages from
    everything else, and two tests pin both halves.

Found while continuing the CI work, and introduced by the fix for finding 2. Rejecting
`fuzzy` on a quoted phrase needed the tools to return that message, which was done with a
broad `except ValueError` in `df_tool.py`. But lancedb raises `ValueError` too, so an
out-of-`int32` bound leaked its internals straight to the client:

```
df_search(keyword="Åbo", year_min=10**20)
-> Error: Invalid input, Error resolving filter expression year_to >= 100000000000000000000:
   Invalid user input: Received literal Float64(...) and could not convert to literal
```

The logged form went further and quoted a Rust source path inside the lance crate. That is
exactly what `format_error` exists to prevent — see **What holds up** above, which had
recorded the property as sound one commit earlier.

The guards now raise `SearchInputError`, a `ValueError` subclass, and `df_tool.py` catches
that instead of the base class. Caller-correctable messages still come through; anything
else goes back to the generic internal-error reply with the traceback server-side.

The general lesson is narrow: a bare `except ValueError` around a third-party call is a
disclosure decision, not just a control-flow one.

### 13. OTel shutdown hung the process when no collector was reachable

!!! success "Resolved"

    Bounded by a daemon thread joined with a timeout, and pinned by a test.

Found by running the telemetry layer rather than reading it. With
`KA_MCP_OTEL_ENABLED=true` and nothing listening on the OTLP endpoint,
`shutdown_telemetry()` never returned — killed at 120s, having reported `init`
and the search itself as instant:

```
init done
ingest done
search: 3 hits in 0.0s
shutdown: (never returned)
```

The OTLP gRPC exporter retries an unreachable endpoint with exponential backoff
and `shutdown()` waits for that loop; `force_flush(timeout_millis=5000)` does not
bound it. Because the function is registered with `atexit`, this hung the process
on **every exit** — and for stdio, exit is after every session. So the failure mode
was: misconfigure the collector, and the server stops exiting.

The flush now runs on a daemon thread joined with `SHUTDOWN_TIMEOUT_SECONDS`;
a daemon thread cannot keep the interpreter alive, so a dead collector costs five
seconds and a warning. Verified: the same script now finishes in 5.0s and exits 0.

This is inherited from the reference implementation's shape, so ra-mcp and the
sibling Kansallisarkisto server likely have it too — worth a look there.

---

## Behaviour confirmed as correct

Checked because it looked risky, and found sound — recorded so it need not be re-checked:

| checked | result |
|---|---|
| Paging past the end | `offset=999999` → 0 records, `total_hits` still true, formatter says "No more results … Total found: 7" |
| `limit` far above the corpus | `limit=10_000_000` accepted and harmless; the ranked set is already bounded by `MAX_TOTAL_COUNT` |
| `get_charter(-1)`, `get_charter(0)` | `None`, as documented |
| `match_all` switch | AND gives 7 hits, OR gives 9 on the fixture — both routed through `MatchQuery` since `bd84d64` |
| Quoted phrase vs loose terms | phrase strictly narrower, and identical under both `match_all` settings |
| Awkward model input | unclosed quotes, stray brackets, `*`, `^2` — none reach the caller as an exception |

## Suggested order of work

1. **Findings 3, 6, 7, 8** — pure text, no behaviour risk, and they are what a reader trusts.
2. **Finding 1** — a range guard in `get_charter`, restoring a documented contract.
3. **Finding 2** — one sentence in the field description, or an explicit rejection.
4. ~~**Finding 5**~~ — done, along with **5b**, which the wiring turned up.
5. **Finding 4** — readiness versus liveness, once the deployment target is settled.
6. **Finding 11** — `LICENSE` first; the rest as they are passed.
