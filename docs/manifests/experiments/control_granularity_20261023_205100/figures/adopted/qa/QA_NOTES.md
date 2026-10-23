# Figure QA

The updated figure shows all eight requested observations and all three components. The two panels use the same zero-based linear scale (0–10 million clocks), order, colors and units. Deterministic single-KAT observations have no sampling, averaging or uncertainty intervals. No categories or observations were excluded.

i uses the adopted i_software candidate, not i_timing_v3. c uses newly executed c_control_pipeline profiling. The unchanged t measurements were reused only after independent RTL, ROM, input and binary-output checks. All six project observations match the 33-byte KAT and the complete signature/cache; primitive work is unchanged. DATA_AUDIT.json passed.

The prior Python plot was structurally adapted without changing its original files. Hash, Transfer and Remaining map directly to their integer data fields; dividing by one million only sets the display units. Totals and sufficiently large segments carry three-decimal labels. Thin t Remaining segments have external labels rather than being omitted. Small SLotH Transfer labels are omitted for space, but the orange segment is drawn at its exact height and the integer count remains in the table/JSON.

| Panel | Role | Summary and uncertainty | Alignment | Rendered labels and geometry | Result |
|---|---|---|---|---|---|
| a / SHAKE | Compare the latest control implementations and baseline | Actual clocks, one matched deterministic KAT; no error bars | PASS, common row and scale | Four bars, Remaining labels, thin Transfer and t Remaining retained; no clipping | PASS |
| b / SHA2 | Compare the same designs under greater primitive work | Actual clocks, same KAT policy | PASS, common row and scale | All totals and segment labels readable, thin t Remaining labelled; no clipping | PASS |

Final dimensions are 183 × 125 mm. PNG is 600 dpi; PDF and SVG contain editable text. Final rendered PDF text minimum is 6.8 pt. Source preflight has zero FAIL and one reviewed WARN: TIFF is absent because this delivery uses vector PDF/SVG and a PNG preview. This is not a journal raster submission.

Rendered collision audit: PASS, zero FAIL and zero WARN. The 14 contained fill overlays are intentional in-bar numeric labels. Alignment: PASS, no exemptions. Both panels and the assembled PNG were visually inspected after the final render; zero baselines, colors, totals, callouts, shared legend and methodological footnotes are clear.

Hash/Transfer/Remaining boundaries remain unchanged: Transfer is hash-exclusive MMIO occupancy and is zero for the project variants; internal movement is not asserted to be zero. SLotH's reported Hash includes some setup/chain control. For SHA2, the 211,434-clock Hash difference is setup accounting rather than different round/feed-forward work. No project control clocks were moved into Hash.

PDF geometry QA uses an isolated PyMuPDF dependency directory; drawing and exports use the existing Python/matplotlib workflow exclusively. No production RTL, ROM, historical figure or experiment evidence was modified by the plotting task.
