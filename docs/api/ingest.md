---
icon: lucide/import
---

# Ingest

```python
ingest_df(db, jsonl_path, *, table_name="df", batch_size=5000) -> lancedb.table.Table
```

Reads the harvested Diplomatarium Fennicum export — `.jsonl` or `.jsonl.gz`, transparently —
and creates the LanceDB table with its indexes. Returns the table handle that carries them.

Raises `ValueError` if the export yields no valid records. Individual malformed lines are
logged and skipped: these are harvested exports, and losing one bad line beats losing the
run. The check for "no records at all" happens **before** the stream is handed to LanceDB, so
an empty export fails as a plain `ValueError` rather than as an Arrow C-interface error with
the real message buried in a traceback and a half-created table left behind.

## The declared schema

`DF_SCHEMA` is declared, not inferred, for two reasons.

Inference reads a sample. `lat` and `lng` are null for 2,734 of the 6,876 charters, so a
batch in which every charter is unlocated infers as a null-typed column and then fails to
merge with a later batch that has floats.

And the corpora disagree with each other: `file_id` is a zero-padded string in `voudintilit`
and an integer in `tuomiokirjat`. Pinning the schema per corpus is the only way both load
correctly.

| column | type | source |
|---|---|---|
| `object_id` | string | `objectID` |
| `df` | string | `df` |
| `df_number` | int32 | derived — `df` as an int, so `10` sorts after `2` |
| `transcript` | string | `transcript` |
| `indexterm` | string | `indexterm` |
| `issuingplace` | string | `issuingplace` |
| `issuingplacecountry` | string | `issuingplacecountry` |
| `language` | string | `language` |
| `dating_start_year` | int32, nullable | `dating_start_year`, with 0 → null |
| `dating_end_year` | int32, nullable | `dating_end_year`, with 0 → null |
| `year_from` | int32, nullable | derived — the dating interval, closed |
| `year_to` | int32, nullable | derived |
| `lat` | float64, nullable | `_geoloc.lat` |
| `lng` | float64, nullable | `_geoloc.lng` |
| `searchable_text` | string | derived — what the full-text index is built over |

## Streaming

The export is read as Arrow record batches of 5,000 rows and handed to LanceDB as a
`RecordBatchReader`, so peak memory is one batch. `df` does not need this; `tuomiokirjat`,
at ~20 GB uncompressed, does, and the same code path serves both.

## Indexes built

- **FTS** on `searchable_text`: `language="Swedish"`, with `stem`, `remove_stop_words` and
  `ascii_folding` all passed explicitly, and `max_token_length=64` so long Swedish compounds
  are not dropped.
- **BTree** on `df_number`, `year_from`, `year_to` — the ordered columns filters range over.
- **Bitmap** on `language`, `issuingplacecountry` — low-cardinality equality filters.

Substring-filtered columns (`issuingplace`) are deliberately left unindexed: a
leading-wildcard `LIKE` cannot use a BTree or Bitmap.

Building an index mutates the on-disk dataset, so it belongs in the ingest path — never
against already-published live data.
