# K/P/U 128f Sign cycle and synthesis matrix

Device: xc7a200tffg1156-3; Vivado 2025.2; 10 ns synthesis constraint; PROFILE_ENABLE=0.
Synthesis does not measure frequency. LUT includes LUTRAM. Common core excludes external ROM and signature cache.
K3/K4 are unsupported by the current controller and are listed in status.json.

| Point | Cycles | LUT | FF | LUTRAM | BRAM36 | DSP | Eq. Slice | Status |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| K1P1U1 | 2619719 | 19498.0 | 6819.0 | 1456.0 | 0.0 | 0.0 | 5726.875 | pass/pass |
| K2P1U1 | 1399919 | 26075.0 | 10073.0 | 1456.0 | 0.0 | 0.0 | 7777.875 | pass/pass |
| K1P2U1 | 1402428 | 26084.0 | 8444.0 | 2060.0 | 0.0 | 0.0 | 7576.5 | pass/pass |
| K2P2U1 | 770842 | 36475.0 | 16551.0 | 2320.0 | 0.0 | 0.0 | 11187.625 | pass/pass |
| K1P3U1 | 979434 | 27663.0 | 10083.0 | 2060.0 | 0.0 | 0.0 | 8176.125 | pass/pass |
| K2P3U1 | 559145 | 40928.0 | 19805.0 | 2320.0 | 0.0 | 0.0 | 12707.625 | pass/pass |
| K1P4U1 | 766014 | 30415.0 | 11694.0 | 2060.0 | 0.0 | 0.0 | 9065.5 | pass/pass |
| K2P4U1 | 486328 | 45695.0 | 23062.0 | 2320.0 | 0.0 | 0.0 | 14306.5 | pass/pass |
| K1P1U2 | 1352027 | 23265.0 | 6795.0 | 1456.0 | 0.0 | 0.0 | 6665.625 | pass/pass |
| K2P1U2 | 729983 | 33668.0 | 10056.0 | 1456.0 | 0.0 | 0.0 | 9674.0 | pass/pass |
| K1P2U2 | 757550 | 31357.0 | 10088.0 | 1888.0 | 0.0 | 0.0 | 9100.25 | pass/pass |
| K2P2U2 | 416998 | 45965.0 | 16583.0 | 2320.0 | 0.0 | 0.0 | 13564.125 | pass/pass |
| K1P3U2 | 544664 | 36678.0 | 11716.0 | 1888.0 | 0.0 | 0.0 | 10634.0 | pass/pass |
| K2P3U2 | 310457 | 58223.0 | 19806.0 | 2320.0 | 0.0 | 0.0 | 17031.5 | pass/pass |
| K1P4U2 | 437228 | 43988.0 | 13315.0 | 1888.0 | 0.0 | 0.0 | 12661.375 | pass/pass |
| K2P4U2 | 273772 | 62262.0 | 23020.0 | 2320.0 | 0.0 | 0.0 | 18443.0 | pass/pass |
