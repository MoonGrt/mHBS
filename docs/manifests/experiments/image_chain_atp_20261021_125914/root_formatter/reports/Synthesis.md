# Common-core synthesis and ATP

Fixed K1U1; xc7a200tffg1156-3; 100 MHz OOC synthesis, two threads, PROFILE_ENABLE=0. The core excludes program ROM and signature cache. No placement or routing was performed.

| Backend | LUT | FF | BRAM36 | DSP | Equivalent Slice | Status |
|---|---:|---:|---:|---:|---:|---|
| shake | 18,399 | 4,743 | 0 | 0 | 5,192.625 | measured |

SHAKE source-area comparison: LUT +49.1126%, FF +15.3173%. The source-import 1% gate does not apply after adding XMSS/LMS.

Run logs: `/tmp/mhbs-fixed-frame-explore/build/synth/fixed_frame`. Frozen RTL and checksums accompany this report.
