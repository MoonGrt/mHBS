# Common-core synthesis and ATP

Fixed K1U1; xc7a200tffg1156-3; 100 MHz OOC synthesis, two threads, PROFILE_ENABLE=0. The core excludes program ROM and signature cache. No placement or routing was performed.

| Backend | LUT | FF | BRAM36 | DSP | Equivalent Slice | Status |
|---|---:|---:|---:|---:|---:|---|
| shake | 18,258 | 4,765 | 0 | 0 | 5,160.125 | measured |

SHAKE source-area comparison: LUT +47.9699%, FF +15.8522%. The source-import 1% gate does not apply after adding XMSS/LMS.

Run logs: `/tmp/mhbs-sponge-explore/build/synth/input_or_v2`. Frozen RTL and checksums accompany this report.
