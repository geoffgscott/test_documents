# Wrong-mapping corpus — provenance & licensing

Synthesized fixtures for xberg issue #1696: a PDF text layer that decodes cleanly via
`/ToUnicode` but to the *wrong* letters. `xberg-native-pdf`'s `best_mapping_provenance` treats any
non-empty `/ToUnicode` CMap as an authoritative mapping tier, and no renderer reads `/ToUnicode` --
so rewriting the CMap changes the decoded text while the rendered page stays byte-identical to the
source. Every file here is built from a clean, redistributable source by
`scripts/build_wrong_mapping_pdfs.py`, which is the record of exactly what was changed.

Only `/ToUnicode` CMap streams are touched. `/Encoding /Differences` is never modified, because
that changes what an embedded font actually draws on the page and would break the "renders
identically" property the fixture depends on.

## Files

| output filename | source path | source id (readoc) | source license | transform | sha256 |
|---|---|---|---|---|---|
| `wrong_mapping_177210299.pdf` | `pdf/177210299.pdf` | `177210299` | MIT | ToUnicode ROT-3 letter substitution via `scripts/build_wrong_mapping_pdfs.py`, applied to all fonts on all pages; rendering unchanged | `1d7c523d19265af6db4b5a18a94223684ebf18f9876bbb24fc8c9b530e1f70b3` |
| `wrong_mapping_276728418.pdf` | `pdf/276728418.pdf` | `276728418` | MIT | ToUnicode ROT-3 letter substitution via `scripts/build_wrong_mapping_pdfs.py`, applied to all fonts on all pages; rendering unchanged | `da63167a6764ceaebc2f95e256ec82b57983046b76b3c5dd25ee23892cea5dd2` |
| `wrong_mapping_290573779.pdf` | `pdf/290573779.pdf` | `290573779` | MIT | ToUnicode ROT-3 letter substitution via `scripts/build_wrong_mapping_pdfs.py`, applied to all fonts on all pages; rendering unchanged | `8ee228ea9a5f8f43204f5c28ad6dcb9f3ad99f375b341e58b62deda8ae0e3370` |

All three sources are readoc-github README PDFs (`source_dataset: "readoc"`, `redistribute:
"vendor"` in `ground_truth/corpus_manifest.json`), MIT-licensed, already committed at `pdf/<id>.pdf`.
Each output's ground truth is a copy of the source's own ground truth
(`ground_truth/pdf/wrong_mapping/wrong_mapping_<id>.{txt,md}`) -- that is what correct extraction
(e.g. OCR-based, ignoring the wrong ToUnicode) should recover, not what naive ToUnicode-based text
extraction of the synthesized file produces.

## Why three readoc PDFs and not the FinTabNet / arXiv candidates

The build brief called for a pure-Latin-prose source, a FinTabNet table page, and an arXiv/formula
page. Both of the latter two turned out to be unsuitable for this fixture shape, checked directly
with `qpdf --qdf --stream-data=uncompress` before being ruled out:

- **FinTabNet.** Every FinTabNet PDF present under `pdf/` (`ft_ACN_2009_page_102_t0`,
  `ft_BAX_2012_page_100_t1`, `ft_BEN_2010_page_100_t0`, `ft_BKNG_2012_page_109_t0`,
  `ft_CAT_2017_page_101_t1`, `ft_CB_2008_page_102_t0` -- the only six with `redistribute: "vendor"`
  that are actually committed) uses a plain `/Type1 /BaseFont /Helvetica` font with no
  `/ToUnicode` entry at all. Text is decoded via the font's built-in encoding, so there is no CMap
  to rewrite; step 4 of the build recipe (abort if any font lacks `/ToUnicode`) rules every one of
  them out.
- **arXiv / formula-heavy.** `MATH_PROVENANCE.md`'s math corpus has no PDF entries at all -- its
  CC-BY arXiv sources are HTML, EPUB, Jupyter, LaTeX, JATS, etc, never PDF -- and no other CC-BY
  arXiv PDF with `redistribute: "vendor"` was found among the committed `pdf/` files. So this
  category has no candidate to synthesize from.

Three readoc README PDFs (MIT, all with every font ToUnicode-covered) were used instead, which
still exercises the fixture across the recipe's core mechanism -- CIDFontType0/Identity-H fonts
with Adobe-Identity-UCS ToUnicode CMaps holding a mix of `bfchar` and `bfrange` entries, including
multi-code-point ligature destinations.
