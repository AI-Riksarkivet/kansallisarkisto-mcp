---
icon: lucide/clipboard-check
---

# Code Audit

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

> **`build_fts_index`** — the Swedish full-text index, with stemming, stop-word removal,
> accent folding and a raised token-length limit …

Stop-word removal is **off**, and turning it off is one of the better-argued decisions in the
codebase: Swedish stop words are Latin content words here, and removing them cost `de` 1,735
documents, `den` 846 and `om` 1,133. `search-tips.md` states the opposite, correctly ("Stop
words are **kept**, unlike a normal Swedish index"). `remove_stop_words=False` is indeed
*passed explicitly*, which is presumably what the list meant, but it reads as a feature list.

### 9. README duplicates its architecture bullets

Lines 89–92 and 96–99 are the same two bullets, once under the diagram and once under "A uv
workspace of two packages", with only a trailing clause differing.

### 10. The repo-layout block omits the largest script

`docs/development/index.md` annotates `scripts/` as "ingest_df.py, mcp_smoke.py". It also
contains `harvest.py` — 410 lines, the single biggest file in the repository and the entry
point for the entire data pipeline. The Makefile table on the same page likewise omits the
`harvest` and `verify-data` targets.

### 11. Smaller things

- **No `LICENSE` file**, though both `pyproject.toml`s declare `license = "Apache-2.0"` and
  the README says the code is Apache-2.0.
- **`build_fts_index(column: str = "searchable_text")`** hardcodes the literal rather than
  defaulting to `FTS_COLUMN`, which is defined seventy lines above and used everywhere else —
  two sources of truth for one column name.
- **`HOST`, `PORT` and `LOG_LEVEL` are unprefixed** (`env_prefix=""`), unlike the `KA_`-prefixed
  pair. An unrelated `PORT` in the environment silently retargets the server.
- **`test_fuzzy_is_opt_in_so_stemming_keeps_working(search)`** takes the `search` fixture and
  never uses it, paying for a full fixture ingest to assert a module constant.
- **Version validation covers one package.** Both `publish.yml` and Dagger's `validateVersion`
  checked only `packages/kansallisarkisto-mcp/pyproject.toml`; the lib version could drift
  unnoticed. **Resolved** — `publish.yml` now validates both manifests against the tag.
- **`or` is cited as 51 charters** in `search-tips.md` and 50 in `test_retrieval_quality.py`.
  Trivial in isolation, but this repository argues from exact counts, so an unreconciled pair
  costs more here than it would elsewhere.
- **Two publish paths.** CI published via `docker/build-push-action` while Dagger's
  `PublishDocker` was never called and pushed no attestations. **Resolved** — `PublishDocker`
  is deleted; there is one publish path.

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
