# Common-core synthesis and ATP

Fixed K1U1; xc7a200tffg1156-3; 100 MHz OOC synthesis, two threads, PROFILE_ENABLE=0. The core excludes program ROM and signature cache. No placement or routing was performed.

| Backend | LUT | FF | BRAM36 | DSP | Equivalent Slice | Status |
|---|---:|---:|---:|---:|---:|---|
| shake | 21,508 | 4,460 | 0 | 0 | 5,934.500 | measured |

SHAKE source-area comparison: LUT +37.0111%, FF +6.0642%. The source-import 1% gate does not apply after adding XMSS/LMS.

Run logs: `/tmp/mhbs-image-chain-tree/build/synth/tree_opt_flat_no_endpoint`. Frozen RTL and checksums accompany this report.
