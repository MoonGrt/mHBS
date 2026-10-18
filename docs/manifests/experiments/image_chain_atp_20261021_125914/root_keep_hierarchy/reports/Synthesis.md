# Common-core synthesis and ATP

Fixed K1U1; xc7a200tffg1156-3; 100 MHz OOC synthesis, two threads, PROFILE_ENABLE=0. The core excludes program ROM and signature cache. No placement or routing was performed.

| Backend | LUT | FF | BRAM36 | DSP | Equivalent Slice | Status |
|---|---:|---:|---:|---:|---:|---|
| shake | 17,871 | 4,735 | 0 | 0 | 5,059.625 | measured |

SHAKE source-area comparison: LUT +44.8335%, FF +15.1228%. The source-import 1% gate does not apply after adding XMSS/LMS.

Run logs: `/tmp/mhbs-sponge-hierarchy/build/synth/hierarchy`. Frozen RTL and checksums accompany this report.
