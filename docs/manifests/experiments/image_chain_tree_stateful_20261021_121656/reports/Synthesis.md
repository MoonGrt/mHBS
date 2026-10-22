# Common-core synthesis and ATP

Fixed K1U1; xc7a200tffg1156-3; 100 MHz OOC synthesis, two threads, PROFILE_ENABLE=0. The core excludes program ROM and signature cache. No placement or routing was performed.

| Backend | LUT | FF | BRAM36 | DSP | Equivalent Slice | Status |
|---|---:|---:|---:|---:|---:|---|
| shake | 24,065 | 4,914 | 0 | 0 | 6,630.500 | measured |

SHAKE source-area comparison: LUT +53.2998%, FF +16.8609%. The source-import 1% gate does not apply after adding XMSS/LMS.

Run logs: `/tmp/mhbs-image-chain-tree/build/synth/stateful_extension_release_20261021`. Frozen RTL and checksums accompany this report.
