# Controlled-comparison figure QA

All10 measurements are retained: SLotH, i-generic, i-opt, c and t for SHAKE and SHA2. This is a deterministic33-byte KAT comparison, not an average or sampled subset; no uncertainty intervals are inferred. Numeric units are millions of cycles, with exact integer data and percentage denominators in the companion report.

i-generic versus i-opt changes only the software chain compiler strategy, not RTL, Hash work, input or signature. It adds no wait/NOP. The original generic loop is a declared controlled baseline rather than a claim about best software performance. SHA2 generic Remaining is higher than SLotH; this does not overwrite the optimized result or inherit its earlier dual-backend Remaining claim.

The Python plot structure is adapted from the preceding measured comparison; category order explicitly expands to five bars per backend. Both panels have the same zero baseline, linear0–10million scale, colors and dimensions. Thin t Remaining segments carry callout labels, while small nonzero Transfer segments remain at their true height. Exact Transfer values are in the table.

| Panel | Role | Statistics | Alignment | Collision and text | Visual inspection |
|---|---|---|---|---|---|
| a / SHAKE | Separate software loop strategy from existing control-granularity performance | One matched KAT; no averaging or uncertainty estimate | PASS, equal plot dimensions/shared row | PASS, no collisions/clipping; labels at least6.8pt | PASS: all5 bars and small segments visible, generic/opt labels distinct |
| b / SHA2 | Test the same controlled contrast with compression-dominated runtime | Same policy as a | PASS, same scale and order | PASS, no collisions/clipping | PASS: generic slightly exceeds SLotH total; optimized result is retained visibly |

Source preflight has0FAIL and one reviewed TIFF warning: this chart is delivered in editable PDF/SVG with a600dpi PNG preview, not as a journal raster submission. Rendered collision audit has0FAIL/0WARN;18 fully contained text/fill overlays are the intentional stack labels. PDF minimum text is6.8pt. Final PNG and both panels were inspected after the final export. Panel alignment passed without exemptions.

Hash accounting remains explicit. SLotH includes some setup/chain-control clocks in Hash; the project's Hash is actual rounds plus SHA2 feed-forward. Transfer is hash-exclusive MMIO occupancy, not all internal movement. Source/fixture/work/signature identities are independently recorded in DATA_AUDIT.json. No production source or historical plot was changed.
