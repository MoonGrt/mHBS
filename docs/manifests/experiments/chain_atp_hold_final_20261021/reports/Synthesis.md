# Common-core synthesis and ATP

Fixed K1U1; xc7a200tffg1156-3; 100 MHz OOC synthesis, two threads, PROFILE_ENABLE=0. The core excludes program ROM and signature cache. No placement or routing was performed.

| Backend | LUT | FF | BRAM36 | DSP | Equivalent Slice | Status |
|---|---:|---:|---:|---:|---:|---|
| shake | 17,660 | 4,727 | 0 | 0 | 5,005.875 | measured |

SHAKE source-area comparison: LUT +43.1234%, FF +14.9283%. The source-import 1% gate does not apply after adding XMSS/LMS.

Run logs: `/tmp/mhbs-image-chain/build/synth/chain_atp_hold_final`. Frozen RTL and checksums accompany this report.
