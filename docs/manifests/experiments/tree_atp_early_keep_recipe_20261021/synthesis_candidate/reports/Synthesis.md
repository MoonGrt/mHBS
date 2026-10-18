# Common-core synthesis and ATP

Fixed K1U1; xc7a200tffg1156-3; 100 MHz OOC synthesis, two threads, PROFILE_ENABLE=0. The core excludes program ROM and signature cache. No placement or routing was performed.

| Backend | LUT | FF | BRAM36 | DSP | Equivalent Slice | Status |
|---|---:|---:|---:|---:|---:|---|
| shake | 20,336 | 4,975 | 0 | 0 | 5,705.875 | measured |

SHAKE source-area comparison: LUT +29.5452%, FF +18.3115%. The source-import 1% gate does not apply after adding XMSS/LMS.

Run logs: `/tmp/mhbs-image-chain-tree/build/synth/tree_opt_early_keep_recipe`. Frozen RTL and checksums accompany this report.
