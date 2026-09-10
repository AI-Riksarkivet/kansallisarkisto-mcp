---
icon: lucide/file-text
---

# `tuomiokirjat_get_page`

One court-record page by its page id, with the **full** text rather than a snippet — plus its
citation, its Astia link, and the pages either side of it in the same volume.

## Parameters

| parameter | type | notes |
|---|---|---|
| `page_id` | string | The id shown on every `tuomiokirjat_search` hit — e.g. `Y4Q4IZcBCao99UPKS6L8`. |

The page id is Sisältöhaku's own document id, because `<volume>_<page>` is not unique in this
corpus: 60,000 images were indexed twice or three times under distinct ids, and the ingest keeps
one of each. The lookup rides the `page_id` index; the neighbours the `volume_id` one.

## Example

```
tuomiokirjat_get_page(page_id="Y4Q4IZcBCao99UPKS6L8")
```

```
**Helsingin raastuvanoikeuden tuomiokirjat g:87 1792, p. 45**

Archive: Raastuvanoikeuksien renovoidut tuomiokirjat
Series: Helsingin raastuvanoikeuden tuomiokirjat
Record type: Tuomiokirjat
Signum: g:87
Page id: Y4Q4IZcBCao99UPKS6L8
Page image in Astia: https://astia.narc.fi/uusiastia/viewer/?fileId=5930213631&aineistoId=2320246345
Previous page: kIQ4IZcBCao99UPKTaIn
Next page: I4Q4IZcBCao99UPKSqJT

Text:
76. 1792 then 3. Maji Ehronen i Kraft af sin fod sel, i grund af Nikets antagne och
faststälde Sacresium ord¬ ning …
```

Cases run across pages, so follow `Previous page` and `Next page` to read on. They name the
nearest page that exists in the corpus, so at a gap the neighbour of page N is not N ± 1; at
either end of a volume the line says `none`.

An unknown or malformed id returns a message, not an error:

```
No page nonsense in tuomiokirjat. A page id is the one shown on every tuomiokirjat_search hit
— e.g. 'Y4Q4IZcBCao99UPKS6L8'.
```

The text is machine-recognised handwriting over three centuries — this very page reads
`Nikets antagne` for what is surely *Rikets antagne* — so check any quotation against the
image.
