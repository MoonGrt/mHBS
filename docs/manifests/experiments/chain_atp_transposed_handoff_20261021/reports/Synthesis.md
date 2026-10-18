# Common-core synthesis and ATP

Fixed K1U1; xc7a200tffg1156-3; 100 MHz OOC synthesis, two threads, PROFILE_ENABLE=0. The core excludes program ROM and signature cache. No placement or routing was performed.

| Backend | LUT | FF | BRAM36 | DSP | Equivalent Slice | Status |
|---|---:|---:|---:|---:|---:|---|
| shake | 17,577 | 4,734 | 0 | 0 | 4,986.000 | measured |

SHAKE source-area comparison: LUT +42.4508%, FF +15.0985%. The source-import 1% gate does not apply after adding XMSS/LMS.

Run logs: `/tmp/mhbs-image-chain/build/synth/chain_atp_transposed_handoff`. Frozen RTL and checksums accompany this report.
