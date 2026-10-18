# Common-core synthesis and ATP

Fixed K1U1; xc7a200tffg1156-3; 100 MHz OOC synthesis, two threads, PROFILE_ENABLE=0. The core excludes program ROM and signature cache. No placement or routing was performed.

| Backend | LUT | FF | BRAM36 | DSP | Equivalent Slice | Status |
|---|---:|---:|---:|---:|---:|---|
| shake | 18,568 | 4,726 | 0 | 0 | 5,232.750 | measured |

SHAKE source-area comparison: LUT +50.4822%, FF +14.9040%. The source-import 1% gate does not apply after adding XMSS/LMS.

Run logs: `/tmp/mhbs-image-chain/build/synth/chain_atp_read_node_case`. Frozen RTL and checksums accompany this report.
