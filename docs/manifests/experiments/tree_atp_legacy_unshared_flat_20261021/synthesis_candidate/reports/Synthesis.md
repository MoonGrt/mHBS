# Common-core synthesis and ATP

Fixed K1U1; xc7a200tffg1156-3; 100 MHz OOC synthesis, two threads, PROFILE_ENABLE=0. The core excludes program ROM and signature cache. No placement or routing was performed.

| Backend | LUT | FF | BRAM36 | DSP | Equivalent Slice | Status |
|---|---:|---:|---:|---:|---:|---|
| shake | 20,536 | 4,841 | 0 | 0 | 5,739.125 | measured |

SHAKE source-area comparison: LUT +30.8192%, FF +15.1249%. The source-import 1% gate does not apply after adding XMSS/LMS.

Run logs: `/tmp/mhbs-image-chain-tree/build/synth/tree_opt_legacy_unshared_flat`. Frozen RTL and checksums accompany this report.
