# Latest SLotH and i/c/t clock composition

Outputs: `clock_breakdown.png`, `clock_breakdown.pdf`, `clock_breakdown.svg`.

Exact integer values are in `cycle_breakdown_data.json` and `cycle_breakdown_table.md`. Both panels compare SLH-DSA-128f Sign using one matched 33-byte KAT per backend; the three project designs use P1U1. These are cycle counts, with no conversion to frequency or time.

The source selection is the adopted i_software and c_control_pipeline, with unchanged t. The old figure directory is preserved. c was profiled again because its new control stages change Remaining. i's adopted measurements and t's existing measurements were source-checked before reuse. `DATA_AUDIT.json` records independent checks, and `profile/c` contains the new real simulation and its frozen source.

Reproduce from the project root after retaining the referenced measured evidence:

```sh
python3 tmp/sloth_ict_cycle_comparison_latest/assemble_data.py
python3 tmp/sloth_ict_cycle_comparison_latest/plot_cycle_breakdown.py
```

The figure explicitly preserves the original Hash accounting caveat: SLotH includes engine setup/chain control in Hash; project Hash counts primitive rounds plus SHA2 feed-forward. Hash-exclusive MMIO Transfer is zero for i/c/t, while internal data movement outside Hash remains in Remaining.

See `qa/QA_NOTES.md` and the source, alignment, PDF text and collision audit JSON files for rendering checks. Detailed simulation logs remain under `profile/c`; no synthesis or routing was started for this figure update.
