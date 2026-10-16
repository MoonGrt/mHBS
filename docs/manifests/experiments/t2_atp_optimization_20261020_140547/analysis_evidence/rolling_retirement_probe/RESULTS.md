# U4 registered rolling retirement probe / U5 source binding

6/6 full Sign pass. Output/cache and Hash/permutation checks pass; frozen probe source unchanged. No Vivado.

| P/U | Profile | U4 cycles | Probe cycles | Delta | Delta % |
|---|---|---:|---:|---:|---:|
| P4U1 | slh_128f | 763717 | 764949 | 1232 | 0.161316 |
| P4U1 | xmss_h10 | 22429934 | 22446318 | 16384 | 0.073045 |
| P4U1 | lms_h10 | 7673376 | 7689760 | 16384 | 0.213517 |
| P12U1 | slh_128f | 300561 | 300869 | 308 | 0.102475 |
| P12U1 | xmss_h10 | 8360666 | 8365786 | 5120 | 0.061239 |
| P12U1 | lms_h10 | 3134331 | 3139451 | 5120 | 0.163352 |

Only RTL change from U4: roll_free = ~pipe_active. A returning slot becomes eligible after registered retirement on the next edge; previously idle slots remain eligible immediately. This removes response-valid/tag from the free-slot priority encoder and downstream request-tag/context-ready feedback. No extra Hash work, lane, or P/U specialization. P1 does not use rolling batch scheduling.

Maximum measured cycle cost: 0.213518%. Area/frequency benefit still requires synthesis/physical measurement; no frequency claim follows from these simulations.

Nine RTL files byte-identical; executor differs only in two comment lines describing the identical roll_free expression. Exact diff retained, with all10 comment/whitespace-normalized code digests equal. Probe frozen source was never modified to imitate U5 byte identity. SHA256 identities and raw-log references are retained in RESULTS.json. Detailed simulation logs remain only in the build run directory.

U4 source manifest SHA256: 79fe6191a2d489447308fbb968ab8d81a2ea4d8a00831b5fb42d13d6ff5ca018
Probe source manifest SHA256: f5ef7e68a78c1f66ff56828758907ec2d4aec033f65612debb554a56e6875fb3
U5 source manifest SHA256: 40f3a70f7a61255747d3acc4ff0b8d836290e2fd04245a2eb58c7caa3cc06df5
