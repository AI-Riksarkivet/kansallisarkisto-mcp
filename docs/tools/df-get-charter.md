---
icon: lucide/file-text
---

# `df_get_charter`

One Diplomatarium Fennicum charter by its DF number, with the **full** transcript rather than
a snippet.

## Parameters

| parameter | type | notes |
|---|---|---|
| `df_number` | int ≥ 1 | The DF number, e.g. `1451` for "DF 1451". This snapshot runs from 1 to 6888, with gaps. |

The DF number is the citable identifier a researcher quotes, and the one carried on every
`df_search` hit — so this is the natural follow-up to a search. It is backed by a BTree
index, making the lookup a page read rather than a scan.

## Example

```
df_get_charter(df_number=1451)
```

```
**DF 1451** — 1415 — Viborg, Suomi

Language: ruotsi
Index term: Yksityiset, Tili- ja pöytäkirjamerkinnät

Transcript:
…
```

Coordinates are shown when the charter has them (60% do). They locate the **place of issue**,
not the events the charter describes, and the corpus asserts nothing about their precision.

An unknown number returns a message, not an error:

```
No charter DF 99999 in the Diplomatarium Fennicum corpus. Valid DF numbers in this
snapshot run from 1 to 6888 (with gaps).
```

For a charter with no transcript — 36% of the corpus — the catalogue record is still
returned, followed by a line saying the charter is catalogued but not transcribed.
