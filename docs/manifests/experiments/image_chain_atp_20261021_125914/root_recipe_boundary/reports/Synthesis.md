# Common-core synthesis and ATP

Fixed K1U1; xc7a200tffg1156-3; 100 MHz OOC synthesis, two threads, PROFILE_ENABLE=0. The core excludes program ROM and signature cache. No placement or routing was performed.

| Backend | LUT | FF | BRAM36 | DSP | Equivalent Slice | Status |
|---|---:|---:|---:|---:|---:|---|
| shake | 17,871 | 4,803 | 0 | 0 | 5,068.125 | measured |

SHAKE source-area comparison: LUT +44.8335%, FF +16.7761%. The source-import 1% gate does not apply after adding XMSS/LMS.

Run logs: `/tmp/mhbs-hierarchy-recipe_only/build/synth/hierarchy`. Frozen RTL and checksums accompany this report.
