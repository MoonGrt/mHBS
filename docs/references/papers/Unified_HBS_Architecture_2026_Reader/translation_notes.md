# Translation and extraction notes

- Source format: selectable-text PDF; all 22 pages were processed.
- Integrity: SHA-256 matches `references/SHA256SUMS`.
- Poppler reports a malformed trailer/xref warning, but page count, rendering, and text extraction complete successfully.
- Chinese body text is an offline Argos/CTranslate2 first-pass translation. Core terminology was normalized, but dense formula-bearing prose and bibliography were not line-edited; use the English block and PDF as authority.
- Equations E001–E006 were reconstructed from the rendered pages and marked medium confidence. Mathematical symbols are not translated.
- Figure/table crops are approximate semantic crops at 120 dpi. Captions remain separate in Markdown.
- Bibliographic entries retain original wording; the Chinese side states that metadata is unchanged.
- Known source inconsistencies (standard citation, units/notation, cross-references, comparison fairness) are not silently corrected in the bilingual body; they are audited in the companion analysis report.

## Audited supplement — 2026-09-24

- Added `Extracted_Data_and_Analysis.md`, raw Table 1/2/5/6/7 CSV/JSON, separate recomputed values, and native text for PDF pages 9, 16–19.
- Table 7 includes all 29 rows as reported by this paper; cited works were not independently revalidated. Missing values remain null; merged cells and the h=10 default are explicitly expanded.
- Recropped Table 1, Table 2 and Table 5 from the original PDF at 120 dpi; missing labels/bottom rows are now visible. Existing T001/T002/T005 anchors are retained. Updated build crop coordinates preserve these repairs.
- Table 2 h denotes subtree height; h*d is derived total height. Table 1 n is bytes; Table 2 n is bits. Neither units nor cycle/time/ATP inconsistencies are silently corrected in raw data.
- Added `UHBS_Comparison_2026-09-24.md` and current-result evidence snapshots. These are external analysis, not paper-authored text or measurements; all comparisons retain NON_STRICT limitations.
- Converted three inherited parenthesized pseudo-math spans to inline math without changing their values or the original source-map text.
- `apply_supplement.py` restores navigation, source-map supplement metadata and these notes after reader regeneration. It does not regenerate or replace bilingual paragraphs.
- Table 3/4 were not newly transcribed; the pre-existing full reader and assets remain available. Other existing translation uncertainties are unchanged.
