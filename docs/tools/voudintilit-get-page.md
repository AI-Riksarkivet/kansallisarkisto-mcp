---
icon: lucide/file-text
---

# `voudintilit_get_page`

One voudintilit page by its page id, with the **full** text rather than a snippet — plus its
citation, its Astia link, and the pages either side of it in the same volume.

## Parameters

| parameter | type | notes |
|---|---|---|
| `page_id` | string | `<volume>_<page>`, as shown on every `voudintilit_search` hit — e.g. `1578628789_0016`. |

The lookup is by volume and page number, both indexed, so it is a page read rather than a
scan.

## Example

```
voudintilit_get_page(page_id="1578628789_0016")
```

```
**2372 Ylä-Satakunnan tilikirja 1585, p. 16**

Collection: Satakunnan voutikuntien tilejä
Series: Asiakirjat
Page id: 1578628789_0016
Page image in Astia: https://astia.narc.fi/uusiastia/viewer/?fileId=8489049831&aineistoId=1578628789
Previous page: 1578628789_0015
Next page: 1578628789_0017

Text:
Bödich Fincke
Haffwer Konung Matt gunsteligen förlänth
Gödich fincke till sijn lyffztijdh uthi un¬
derhåld der opå konung Mattz breff
Datum then 12 Julij Annoh. 73
…
```

Accounts run across pages, so follow `Previous page` and `Next page` to read on. They name the
nearest page that exists in the corpus: 106 volumes have gaps, where Astia holds an image
Sisältöhaku has no text for, so the neighbour of page N is not always N ± 1. At either end of
a volume the line says `none`.

An unknown or malformed id returns a message, not an error:

```
No page 1578628789_9999 in voudintilit. A page id is '<volume>_<page>', as shown on every
voudintilit_search hit — e.g. '1578628789_0016'.
```

The text is machine-recognised handwriting — this very page reads `Ronung Matz breff` a few
lines further down — so check any quotation against the image.
