# Common-core synthesis and ATP

Fixed K1U1; xc7a200tffg1156-3; 100 MHz OOC synthesis, two threads, PROFILE_ENABLE=0. The core excludes program ROM and signature cache. No placement or routing was performed.

| Backend | LUT | FF | BRAM36 | DSP | Equivalent Slice | Status |
|---|---:|---:|---:|---:|---:|---|
| shake | 17,924 | 4,802 | 0 | 0 | 5,081.250 | measured |

SHAKE source-area comparison: LUT +45.2630%, FF +16.7518%. The source-import 1% gate does not apply after adding XMSS/LMS.

Run logs: `/tmp/mhbs-hierarchy-recipe_sponge/build/synth/hierarchy`. Frozen RTL and checksums accompany this report.
