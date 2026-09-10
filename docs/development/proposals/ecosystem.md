---
icon: lucide/file-search
---

# Ecosystem and federation across the Nordic archive MCP family

Every proposal from this lens in full, followed by the three skeptics' verdicts on it.
Effort and impact are the lens's own estimates; the verdict tally is the skeptics'.

## `ecosystem-1` — archive-mcp-core: one framework that Kansallisarkisto, Riksarkivet and the next archive instantiate from a declarative CorpusSpec

**pending (0/3 verdicts in) · effort XL · impact 5/5**

**What the code does today.** The spine announces itself as a copy: dataset.py:8 'Ported from ra-mcp's ra_mcp_dataset_lib'; lib telemetry.py:13-14 'Ported from ra-mcp's ra_mcp_common.telemetry, which the sibling Kansallisarkisto server also carries'; mcp telemetry.py:18 'Ported from ra-mcp's ra_mcp_server.telemetry'; routes.py:17 and observability.md:7 'same shape as ra-mcp'. The two workspace packages are 'never published to PyPI' (security.md:216), so nothing can be shared except by copy. The per-corpus tool is 218 lines (df_tool.py) of which the mechanism — _answer (df_tool.py:31), require_keyword/require_ordered_range (dataset.py:422,433), combine/equals/text_contains predicates, format_results (dataset.py:446) — is generic and only the prose, the renderer (_render_charter, formatter.py:66) and the filter->column map (search_operations.py:97-103) are df-specific. The result envelope is already identical across the family: ra-mcp's diplomatics_search_sdhk answered this session with "SDHK results for 'X': showing 10 of 194 (offset 0) ... More results available. Use offset=10 to see the next page." — the same strings as dataset.py:446-477. Spike (scratchpad/spikes/spec_parity.py): a df_search generated from a 12-line CorpusSpec via inspect.Signature + Tool.from_function produced a byte-identical inputSchema property list and byte-identical replies to the hand-written tool on 10/10 cases including the error paths (blank keyword, inverted range, fuzzy+phrase, out-of-int32 year).

**The gap.** Every fix is made three times (the comment 'ra-mcp and the sibling likely have it too' is the symptom), voudintilit and tuomiokirjat each need a fresh copy of df_tool.py, and there is no way to say 'this server conforms to the family contract' because there is no artefact that is the contract.

**The proposal.** Create a published package `archive-mcp-core` (PyPI, semver, owned jointly by AI-Riksarkivet) with: `core.spine` (dataset.py as is, renamed attributes per ecosystem-5), `core.spec` — `CorpusSpec(prefix, table, label, archive, id: IdSpec(column, citation_prefix='DF', url_template='https://df.kansallisarkisto.fi/document/{id}'), fts: FtsSpec(language='Swedish', stem=True, remove_stop_words=False, with_position=True, ascii_folding=True, max_token_length=64), filters: list[FilterSpec(name, column, kind: equals|contains|overlap_min|overlap_max, description)], keyword_description, search_description, instructions, render_record, snippet_chars=400)`; `core.tools.register_corpus(mcp, spec, get_db)` generating `<prefix>_search` and `<prefix>_get` exactly as the spike does; `core.ingest.build_table(db, spec, batches, provenance)` applying FtsSpec + scalar indexes derived from FilterSpec kinds (equals->Bitmap, overlap->BTree, contains->none, as build_scalar_indexes documents); `core.readiness`, `core.errors` (ecosystem-8), `core.testkit` (ecosystem-7). What stays local per archive: the record model and its corpus-specific cleaning (models.py strip_editorial_apparatus, UNKNOWN_YEAR), the harvester, the fixture, and all measured prose — the spec is where the numbers live, not a generic template. In this repo `packages/kansallisarkisto-lib` becomes `df.py` (~120 lines: DfRecord + df_spec + _render_charter) plus voudintilit.py and tuomiokirjat.py when ingested; `packages/kansallisarkisto-mcp` becomes tools.py = three register_corpus calls plus instructions. Rule enforced by the testkit: every FilterSpec.description and search_description must contain at least one digit — a description without a measured number is rejected, so 'declarative' cannot decay into 'generic'.

**Why it is once-in-a-lifetime.** It is the difference between 'a good archival MCP server' and 'the way archival MCP servers are built': the next corpus (voudintilit, 98,945 rows, already harvested) becomes a spec file and a renderer, and ra-mcp's 40+ dataset tools get the same spine, the same error semantics and the same tests without a port. The brief's own bar — 'the next corpus is a week's work' — becomes a day.

**How we would know.** (1) voudintilit served with a spec + renderer of ≤120 lines and zero edits to core; (2) the existing 201 tests pass unchanged against the generated df tools (they are the parity oracle — the spike already shows byte-identity on 10 cases); (3) ra-mcp's diplomatics module re-hosted on core passes the core testkit; (4) both repos pin the same core version and `pip-audit`/Trivy find it once, not twice.

**Risks.** Argues against the project's stated philosophy that every description is hand-written next to the code with measured numbers: the mitigation is that the spec holds the prose as data and the testkit refuses digit-free descriptions. Three repos and one core create version skew — the server card (ecosystem-4) must report core_version so a router can refuse mismatched servers. ra-mcp's non-search tools (viewer, IIIF, PDF) must not be forced into the spec; core covers the search/get pair and the conventions only. Dynamic signatures (inspect.Signature + __annotations__) are a FastMCP/pydantic implementation detail that could break on upgrade — pin fastmcp as the repo already does (==3.4.4) and keep the parity test.

**First step.** Inside this repo, no new package yet: create `ra_mcp_kansallisarkisto_lib/spec.py` with CorpusSpec/FilterSpec and `ra_mcp_kansallisarkisto_mcp/corpus_tools.py` with register_corpus (port the spike), define `df_spec` carrying the current df_tool.py prose verbatim, register df from it, delete the hand-written df_search/df_get_charter, and let the existing test suite (test_tools.py, test_telemetry.py, mcp_smoke.py) prove parity. One PR, ~300 lines net negative.

**Spike.** scratchpad/spikes/spec_parity.py (already run): builds df_search from a CorpusSpec over the 18-row fixture and diffs schema and replies against tools.kansallisarkisto_mcp — 10/10 byte-identical. Extend it by writing a voudintilit spec against a 20-line synthetic JSONL to show the second corpus needs no new code path.

---

## `ecosystem-2` — nordic-archives router: one MCP endpoint that searches Diplomatarium Fennicum and SDHK together with provenance-tagged, partial-failure-tolerant merging

**pending (0/3 verdicts in) · effort L · impact 5/5**

**What the code does today.** This server exposes df_search/df_get_charter (df_tool.py:61,199); ra-mcp exposes diplomatics_search_sdhk with (keyword, place, language, author, limit, offset, research_context). A Baltic historian today opens two servers with two vocabularies: `issuingplace` here vs `place` there, exact-label `language` here (df_tool.py:107) vs substring there, `year_min/year_max` here and no year filter on SDHK. The same charters sit in both: DF 1086 = SDHK 15325 (identical incipit 'Jak Abram Brodherson, riddare, høwitzman pa Abo'), DF 526 = SDHK 5478 (Kung Magnus, Åbo, 1347, bishop Hemming, Kumo), and the README's own example DF 2457 = SDHK 24100 (Karl Knutsson, Raumo, 1442) — verified by calling ra-mcp in this session. FastMCP 3.4.4 composes servers in-process: `FastMCP.mount(server, namespace=...)` (spike scratchpad/spikes/mount.py) produced tools fi_df_search, fi_df_get_charter, se_diplomatics_search_sdhk and routed calls correctly. The spine's design already makes fan-out safe: handlers are sync and threadpooled (df_tool.py module docstring), and tools never raise (_answer, df_tool.py:31).

**The gap.** No federated search exists at the MCP level; a model must know both servers, translate vocabularies itself, and has no way to learn that two hits are the same charter or that one archive was down.

**The proposal.** A third package `nordic-archives-mcp` (FastMCP name 'nordic-archives'): mounts kansallisarkisto-mcp in-process (namespace 'fi') and ra-mcp via `FastMCP.as_proxy(url)` (namespace 'se'), discovered from each server's card (ecosystem-4). One composite tool `charters_search(keyword, year_min=None, year_max=None, place=None, archives=('fi','se'), limit=10, fuzzy=0)` that: parses keyword once with the family grammar (ecosystem-3) and serialises per backend; fans out with asyncio.gather and a 10 s per-archive timeout; never merges BM25 scores (incommensurable engines — and SDHK's 194 hits for a three-word query show it is not even AND); instead reports per-archive totals, then interleaves hits by year (both carry one), each line prefixed with a provenance tag `[FI DF 1086]` / `[SE SDHK 15325]` followed by the id URL from the card; applies the year filter client-side to SDHK rows (it has none server-side) and says so; collapses known twins from the concordance (ecosystem-6) into one block with both citations and both datings; renders a failed archive as one line 'SE: unavailable (TimeoutError) — results are Finland only' rather than failing the call. Exposes ≤6 tools (charters_search, fi_df_search, fi_df_get_charter, se_diplomatics_search_sdhk, se_search_transcribed, se_browse_document) via mount tool_names; its instructions carry the cross-archive vocabulary (Åbo/Turku, DF text is source language while SDHK 'Summary' is modern Swedish regest).

**Why it is once-in-a-lifetime.** The Swedish realm's medieval record is split by a modern border; nobody has put the two national editions behind one query with honest provenance. The hard part — two servers that share an envelope and never raise — is already built; the router is the payoff of that discipline.

**How we would know.** A gold set of 20 queries built from the twins found today (start: 'Raumo 1442', 'Abram Brodherson', 'Hemming Kumo') returns both citations in one reply for ≥18; with the se proxy pointed at a dead port, fi results arrive in <10 s with the one-line notice; the router's tools/list is ≤6 tools; a test asserts every hit line begins with a `[FI …]` or `[SE …]` tag.

**Risks.** Depends on ra-mcp being reachable over streamable HTTP with a stable tool contract this repo does not control; SDHK has no year filter, so year bounds are post-filtered and totals for SE become approximate — must be labelled. Interleaving by year hides relevance; the alternative (two blocks) is safer and should be the default until the gold set says otherwise. Adds a third deployable and a network dependency to a family whose stated philosophy is 'stdio on a laptop costs nothing' — the router must also run stdio with fi in-process and se optional.

**First step.** Add `packages/nordic-router` with the mount of kansallisarkisto_mcp (namespace 'fi') and an `se` stub server carrying ra-mcp's exact diplomatics_search_sdhk signature; implement charters_search over the two with two-block output and the failure line; test in-memory with the 18-row fixture and a stub that raises/sleeps. No network needed.

**Spike.** scratchpad/spikes/mount.py (already run): FastMCP 3.4.4 mount(namespace=) of the real kansallisarkisto server plus an sdhk-shaped stub, calls routed through the router. Next: add charters_search with asyncio.gather + wait_for(10 s) and a stub that sleeps 30 s, and time the reply.

---

## `ecosystem-3` — One query grammar for the family: ra-mcp's inline syntax silently returns zero on this engine today

**pending (0/3 verdicts in) · effort M · impact 4/5**

**What the code does today.** ra-mcp's search_transcribed tells the model 'always use fuzzy search (~)', 'wildcards (troll*, st?ckholm)', 'Quoted phrases return 0 results — never quote'; df_search says the opposite: 'quote a phrase' (df_tool.py:84-86) and fuzziness is a parameter (df_tool.py:154). dataset.py:295 routes anything containing '"' to the parser and everything else to MatchQuery (dataset.py:305), whose tokenizer splits `Åbo~1` into a required token '1'. Measured on the fixture (scratchpad/spikes/syntax.py): `Åbo` 7 hits, `Åbo` fuzzy=1 8 hits, `Åbo~1` 0, `konung~1` 0, `Åb*` 0, `Åb?` 0, `ecclesi*` 3 (only because stemming happens to cover it), `Åbo 1` 0 — i.e. every ra-mcp-syntax query returns a clean 'No results' with no error, so a model that learned Riksarkivet's syntax concludes the Finnish archive has nothing. The reverse also holds: SDHK answered a 3-word keyword with 194 hits (OR-like) while df requires all words (dataset.py:305 FullTextOperator.AND). The project already refuses the analogous silent drop for fuzzy+phrase (dataset.py:295-300).

**The gap.** The family has two incompatible keyword dialects and no translation layer, so a federated query cannot send one string to both engines, and cross-training between servers actively harms recall.

**The proposal.** `archive_mcp_core.query`: `parse(keyword) -> ArchiveQuery(terms=[Term(text, fuzzy: int|None, prefix: bool)], phrases=[str], mode='all'|'any')` — one grammar: bare terms, `"phrase"`, `term~N` (N≤2), `term*`. Two serialisers: `to_lancedb(q)` (MatchQuery with fuzziness=max(term.fuzzy) or the phrase parser; prefix terms rejected) and `to_elastic(q)` for ra-mcp's engine (inline ~N and *, phrases dropped with a notice). On this server, `lancedb_fts_search` accepts `~N` inline as a synonym for fuzzy=N and answers `*`/`?` with SearchInputError: 'prefix wildcards are not supported on this archive; stemming already matches inflections (konung finds konungen), use fuzzy=1 for spelling variants'. Publish the grammar × engine conformance table as a pytest parametrisation both repos run.

**Why it is once-in-a-lifetime.** It turns 'four ways to get a silent zero' into a contract a model can learn once for every Nordic archive; without it, the router in ecosystem-2 cannot exist.

**How we would know.** Zero silent zeros: a fixture test asserts that every keyword containing `~`, `*` or `?` either returns ≥ the exact-match hit count (`Åbo~1` ≥ 7) or starts with 'Error:'; the conformance table has one row per grammar feature per engine and is green in both repos.

**Risks.** LanceDB's MatchQuery has one fuzziness for the whole query, not per term, so `bref~1 Åbo` widens Åbo too — document it or split into two MatchQueries and intersect ids in Python (bounded by MAX_TOTAL_COUNT, dataset.py:37). Accepting `~N` inline contradicts the current descriptions and must be added to them. ra-mcp's side of the conformance table cannot be run here.

**First step.** In lancedb_fts_search, detect `[~*?]` before routing: map `term~N` to fuzzy=N, raise SearchInputError for `*`/`?` with the sentence above; add the four measured cases to test_search_invariants.py. ~40 lines.

**Spike.** scratchpad/spikes/syntax.py (already run) — prints the hit counts above; re-run after the change to see `Åbo~1` become 8 and `Åb*` become an 'Error:' string.

---

## `ecosystem-4` — Stamp the snapshot's provenance into the table and publish a machine-readable server card at /.well-known/archive-mcp.json

**pending (0/3 verdicts in) · effort S · impact 4/5**

**What the code does today.** The harvester writes report.json with coverage_pct per corpus (harvest.py:13,329,334) and the docs insist 'A harvest is a snapshot, and the index moves — voudintilit went from 99,031 to 99,125' (data-sources.md), but nothing downstream carries that: DF_SCHEMA has no metadata (ingest.py:30), create_table drops it (ingest.py:144), /ready answers only {"status":"ready","table":"df"} (routes.py:55), the OTel resource carries service.version alone (telemetry.py:71), and format_results (dataset.py:446) has no snapshot line. A historian citing 'DF 1086 via kansallisarkisto-mcp' cannot say which harvest, and a router cannot discover what a server serves, which id scheme it uses, or which query grammar it speaks. Spike (scratchpad/spikes/metadata.py): nine `archive.*` keys set via DF_SCHEMA.with_metadata survive create_table, build_fts_index and a reopen from a fresh connection, with FTS intact.

**The gap.** Snapshot identity and family contract are documented in prose only; neither a person nor a program can read them from a running server.

**The proposal.** (1) `ingest_df(db, path, provenance=read_report('.data/df/report.json'))` writes `archive.archive=kansallisarkisto`, `archive.corpus=df`, `archive.source=<url>`, `archive.harvested_at`, `archive.documents`, `archive.coverage_pct`, `archive.report_sha256`, `archive.id_url_template`, `archive.core_version` as schema metadata; `dataset.table_provenance(db, table) -> Provenance`. (2) /ready becomes `{"status":"ready","corpora":{"df":{"documents":6876,"harvested_at":"2026-07-14","coverage_pct":100.0}}}`. (3) New route `GET /.well-known/archive-mcp.json` and an MCP resource `archive://card` with `{family:'archive-mcp', core_version, archive, corpora:[...provenance...], id_schemes:[{prefix:'DF', url_template}], query_grammar:'archive-query/1', tools:[...]}`. (4) One footer line in format_results: 'Snapshot harvested 2026-07-14 from Sisältöhaku (6,876 charters, 100% of the live index)'. (5) `archive.snapshot.harvested_at` on the OTel resource.

**Why it is once-in-a-lifetime.** It makes a citation reproducible ('DF 1086, kansallisarkisto-mcp snapshot 2026-07-14') and makes the family discoverable by machines — the router reads cards instead of a config file, and a mismatched core_version or grammar is refused rather than silently merged.

**How we would know.** test_ready_reports_snapshot passes; a server built from an ingest without report.json still boots and reports provenance 'unknown' rather than failing; the router (ecosystem-2) refuses a card whose query_grammar is absent; every search reply ends with the snapshot line.

**Risks.** Changing provenance requires re-ingest (it is table metadata) — acceptable, that is what a snapshot is. The footer adds ~90 characters per reply; keep it one line. `.well-known` is convention, not a standard for MCP; the MCP resource is the portable half.

**First step.** Add `provenance` to ingest_df and `table_provenance` to dataset.py, wire /ready to it, add the footer line; ~60 lines plus three tests.

**Spike.** scratchpad/spikes/metadata.py (already run): metadata keys survive reopen; extend by asserting `db.open_table('df').schema.metadata[b'archive.harvested_at']` from a second lancedb.connect.

---

## `ecosystem-5` — A family-wide telemetry attribute namespace and research_context parity with ra-mcp

**pending (0/3 verdicts in) · effort S · impact 3/5**

**What the code does today.** The operations span names its attributes after the corpus — 'df.keyword', 'df.limit', 'df.language' (search_operations.py:84-95), 'df.number'/'df.found' (search_operations.py:116) — and the metrics after the server: kansallisarkisto.lancedb.queries/errors/query.duration/results (dataset.py:81-87); the LanceDB span uses semconv db.* (dataset.py:320). voudintilit would presumably get 'voudintilit.keyword', and ra-mcp its own names, so one dashboard cannot union searches across corpora or archives. Every ra-mcp tool takes `research_context: 'Brief summary of the user's research goal. Used for telemetry only.'`; df_search has no such parameter, so the family cannot answer 'what are historians asking for' consistently — the thing the .results zero bucket (dataset.py:87) was designed to approximate.

**The gap.** Telemetry is per-server bespoke; the family has no shared vocabulary for spans, metrics or research intent.

**The proposal.** Freeze in core: ops-span attributes `archive.archive`, `archive.corpus`, `archive.query.text`, `archive.query.match_all`, `archive.query.fuzzy`, `archive.filter.<name>` (only when set, as today), `archive.result.total`, `archive.result.capped`, `archive.result.returned`, `archive.lookup.id`, `archive.lookup.found`, `archive.research_context`; metrics `archive.search.queries|errors|duration|results` with attribute set {archive.archive, archive.corpus, error.type} only; keep db.* on the engine span. Add `research_context: str | None = None` to df_search/df_get_charter with ra-mcp's exact description; record it on the ops span only, never on a metric, never in logs. Span names: `<Corpus>.search` and `search <table>` stay.

**Why it is once-in-a-lifetime.** One Grafana panel across Finland and Sweden: query volume, zero-result rate and p95 by corpus, plus a corpus of research intents — the first cross-archive signal of what historians actually ask and what the archives cannot answer.

**How we would know.** test_telemetry asserts every ops-span attribute key starts with `archive.`; metric names are byte-identical in both repos; a research_context passed by the client appears on the ops span and on no metric.

**Risks.** research_context is free text about a person's research and is PII-adjacent — document retention and keep it off logs; it slightly enlarges the tool schema the model reads. Renaming attributes breaks any existing dashboard (none exist yet — nothing has been released).

**First step.** Rename the attribute dict in DfSearch.search/get_charter and the four metric names; add research_context to both tools; update observability.md's table. ~40 lines, one PR.

**Spike.** Run test_telemetry.py's in-memory exporter and print the attribute keys of the DfSearch.search span before and after; assert the `archive.` prefix.

---

## `ecosystem-6` — A DF↔SDHK concordance: cross-archive identifiers for charters edited in both national editions

**pending (0/3 verdicts in) · effort L · impact 4/5**

**What the code does today.** The harvested df export has no cross-reference field (data-sources.md field table: objectID, df, transcript, indexterm, issuingplace, issuingplacecountry, language, dating, _geoloc), yet 1,207 charters are issued in Sweden (df_tool.py:132 'Ruotsi 1,207') and many Finland-issued royal acts are in SDHK too. Verified in this session by calling ra-mcp: DF 1086 = SDHK 15325 — same incipit, but DF dates it 1399 and SDHK 1400-01-10 'omdat. från 13990111'; DF 526 = SDHK 5478 — same charter, different edition text ('Vi Magnus, met Gudhz nampn' vs 'Wy. magnus med gudz nadhom'); DF 2457 = SDHK 24100. Fingerprint spike (scratchpad/spikes/concordance): after strip_editorial_apparatus + NFKD fold, DF 1086/SDHK 15325 have 12-token incipit Jaccard 1.00; DF 526/SDHK 5478 trigram Jaccard 0.24 vs 0.16 and 0.12 for two same-place controls — text alone separates same-edition twins perfectly and cross-edition twins weakly; all 15 transcribed fixture incipits are distinct.

**The gap.** Nothing links the two editions, so a historian gets two citations for one document, two datings that disagree, and no signal that they disagree.

**The proposal.** `scripts/concordance.py` producing a LanceDB table `concordance(df_number int32, sdhk_number int32, method str, confidence float, date_fi str, date_se str, place_fi str, place_se str)` next to `df`: block on (year ±1, folded place) and issuer token, then (a) exact folded 12-token incipit → confidence 1.0 'incipit'; (b) trigram ≥ 0.2 with issuer match → 0.6 'candidate'; (c) hand-curated overrides file. df_get_charter appends 'Also edited as SDHK 15325 (Riksarkivet), dated there 1400-01-10 — the editions disagree on the date'; df_search hits get a `= SDHK n` suffix when confidence 1.0. The router (ecosystem-2) collapses twins. Identifier convention for the family: `archive:fi:df:1086`, `archive:se:sdhk:15325`, declared in the server card (ecosystem-4).

**Why it is once-in-a-lifetime.** Cross-edition identity of medieval charters across the Finnish and Swedish national editions is scholarly infrastructure that does not exist in machine-readable form; producing it as a by-product of two MCP servers is what makes the family more than the sum of its servers.

**How we would know.** Coverage: fraction of the 1,207 Sweden-issued df charters with a confidence-1.0 twin (expect a majority); precision ≥ 0.95 on a 50-pair hand-checked sample for the 1.0 tier; the DF 1086 dating disagreement appears verbatim in one df_get_charter reply; the concordance table ships with its own provenance metadata.

**Risks.** Requires the SDHK data (ra-mcp's table) — a Riksarkivet decision, not a code change; unavailable in this environment beyond three verified pairs. Cross-edition twins are weakly separable by text (0.24 vs 0.16), so the candidate tier will need human review; presenting a twin as 'same document' when the editions differ is a scholarly claim — always say 'also edited as', never merge texts. Argues against 'holds no records' only mildly: the concordance is derived metadata, not records.

**First step.** Ship the fingerprint (fold + first-12-tokens + trigram set) as `models.incipit_fingerprint()` with the fixture tests above, and a `concordance_overrides.jsonl` seeded with the three verified pairs; render the 'Also edited as' line from it in format_charter. No SDHK data needed for the first PR.

**Spike.** scratchpad spike (already run): folds fixture incipits and scores the three verified pairs against controls; extend by exporting `data/concordance` from the three seed pairs and checking df_get_charter(1086) renders the SDHK line.

---

## `ecosystem-7` — A shared conformance test kit so every server in the family proves the same search invariants

**pending (0/3 verdicts in) · effort M · impact 4/5**

**What the code does today.** test_search_invariants.py holds engine-generic properties written against DfSearch and two literal terms (BASE_TERMS = ['Åbo','ecclesia'], line 29): AND ⊆ OR (line 92), fuzzy ⊇ exact on a base form, pages tile without gaps (line 133), stable order, case/accent invariance, page ≤ limit ≤ total, paging past the end keeps the total, phrase ⊆ words, fuzzy+phrase refused (line 184), blank keyword and impossible paging rejected — 11 of its ~20 tests mention nothing df-specific. The remainder pin df's index config (line 42) and filters (line 111). test_retrieval_quality.py guards against vacuous passes ('fixture no longer covers footnote markers'). The second audit ran ten injection payloads through the filters by hand. None of this can run against ra-mcp — and ra-mcp's SDHK visibly fails the first invariant today (194 hits for 'Magnus konunger Raumo' is not AND).

**The gap.** The most valuable tests in the family are trapped in one repo and coupled to one corpus's terms; conformance is asserted by copying prose ('same shape as ra-mcp'), not by running the same tests.

**The proposal.** `archive_mcp_core.testkit`: a `SearchContract` Protocol (`search(keyword, *, limit, offset, match_all, fuzzy) -> SearchResult`), a `Conformance(base_terms: list[str], filters: dict[str, tuple[value, row_predicate]], traps: TrapCoverage(untranscribed, unknown_year, apparatus, phrase, stop_words))` declared by each corpus, and `pytest_generate_tests` that instantiates the 11 invariants + the filter subset/honour tests + the audit's 10 injection payloads + `awkward_queries_do_not_raise` for every declared corpus. MCP-level kit: `assert_tools_never_raise(server, fuzz)`, `assert_error_strings_mark_span(server)`, `assert_descriptions_carry_numbers(server)` (every description contains a digit), `assert_landing_page_lists_tools`. Each corpus's TrapCoverage makes the fixture-coverage guards generic. Published inside core; both repos run `pytest -p archive_mcp_core.testkit`.

**Why it is once-in-a-lifetime.** Conformance becomes a fact a CI badge can state ('archive-mcp conformance 1.0') instead of a sentence in a docstring, and the ra-mcp run turns the family's divergences into a numbered backlog rather than folklore.

**How we would know.** kansallisarkisto passes 100% of the kit with zero df-specific code in the kit; the first ra-mcp/SDHK run reports a concrete failure count (expected ≥2: AND semantics, quote handling), each mapped to an ecosystem-3 grammar row; adding voudintilit requires only a Conformance declaration.

**Risks.** Some invariants are engine assumptions (BM25 tie stability, one ranked set sliced) that Elasticsearch-backed ra-mcp tools will legitimately fail — the kit needs tiers ('envelope', 'semantics', 'engine') so a failure is a classification, not a blocker. Extracting tests without the corpus prose risks losing the measured reasoning in their docstrings; keep the docstrings, they are the spec.

**First step.** Move the 11 generic invariants into `packages/kansallisarkisto-lib/src/ra_mcp_kansallisarkisto_lib/testkit.py` parametrised by a Conformance object, re-express test_search_invariants.py as `df_conformance = Conformance(base_terms=['Åbo','ecclesia'], filters={...})`, and keep the df-specific index-config tests where they are. Same test count, one PR.

**Spike.** Write the Conformance object for df and run the extracted invariants against DfSearch on the fixture (expect identical pass count to today); then run them against a 30-line stub SearchContract that implements OR semantics and confirm exactly 'requiring_all_terms_narrows' fails.

---

## `ecosystem-8` — A family error taxonomy, readiness contract and settings convention, extracted from _answer before it is copied a third time

**pending (0/3 verdicts in) · effort S · impact 3/5**

**What the code does today.** _answer (df_tool.py:31-56) is the family's de-facto error policy: MissingTableError → full message + error.type 'missing_table' (df_tool.py:42), SearchInputError → 'Error: ' + message + 'validation' (df_tool.py:49), anything else → type-only via format_error (formatter.py:113) + the exception class name as error.type. SearchInputError(ValueError) (dataset.py:63) is 'the only error type whose message is safe to show a caller'; MissingTableError(RuntimeError) lives in errors.py:15. The comment on _answer says it exists because 'the two tools had already drifted'. Readiness (tools.py:96) returns (bool, str) for one table; /ready (routes.py:51-55) can only say ready/not-ready for a server that will soon hold three corpora. Settings mix prefixes: ka_lancedb_uri/ka_mcp_transport (settings.py:21-22) with env_prefix='' (settings.py:12), KA_MCP_OTEL_ENABLED (telemetry.py:42), and the OTEL_* SDK variables; ra-mcp presumably uses RA_ — so an operator's runbook cannot be shared.

**The gap.** Error disclosure, span error classes, readiness shape and settings prefixes are conventions that live in one function and one tuple, are documented as 'same as ra-mcp' by assertion, and will drift on the next port.

**The proposal.** In core: `class ArchiveError(Exception): disclose: ClassVar[bool]`; `InputError(disclose=True)`, `NotReadyError(disclose=True)` (missing or unreadable table — the boot probe's EACCES-as-Not-found case, server.py:301), `UpstreamError(disclose=False)`; `answer(tool, produce)` moved to core with a closed `error.type ∈ {validation, not_ready, upstream, internal}` (today's 'missing_table' and raw exception names disappear — the class name stays in the message for 'internal'). Readiness contract: `readiness() -> Readiness(ok: bool, corpora: dict[str, CorpusStatus(ready|missing|unreadable, detail)])`, HTTP 503 only when no corpus is ready, the one-row probe run on every call (the audit's finding 1 is the bug; this is the contract), and the same object rendered in the server card. Settings: `ArchiveSettings(BaseSettings)` in core taking `env_prefix` from the archive code, so `KA_LANCEDB_URI` and `RA_LANCEDB_URI` are the same field, with HOST/PORT/LOG_LEVEL also prefixed and the OTEL_* names left to the SDK.

**Why it is once-in-a-lifetime.** Once error classes, readiness and settings are one contract, an operator who runs ra-mcp can run kansallisarkisto-mcp without reading source, and the router can treat 'not_ready' from any archive identically — which is what makes partial failure a message rather than an outage.

**How we would know.** _answer deleted from df_tool.py; test_telemetry asserts error.type takes only the four values; /ready on a server with df present and voudintilit absent returns 200 with `corpora.voudintilit='missing'`; the settings table in the README and ra-mcp's list the same variable names modulo prefix.

**Risks.** Changing error.type values and the /ready JSON is a (pre-release) contract change; nothing has been released, so now is the moment. Prefixing HOST/PORT breaks the compose file and the Dockerfile ENV — a one-line change each. This overlaps ecosystem-1's first step by design: it is the smallest extraction that establishes core's shape.

**First step.** Add `errors.py` to kansallisarkisto-lib with the three classes, make SearchInputError and MissingTableError subclasses, move _answer there as `answer()`, and switch the four error.type values; update the two tests that assert 'missing_table'. ~80 lines.

**Spike.** Run test_tools.py and test_telemetry.py after the change and print the set of error.type values seen across all spans — it must be a subset of the four.

---

