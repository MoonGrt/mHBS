# R5 executor routed path review

Baseline: `candidate_20261020_100441`. The following are routed STA observations, not frequency extrapolations.

| Job | Source → destination | Delay ns | Logic ns | Route ns | Levels | Slack ns |
|---|---|---:|---:|---:|---:|---:|
| P12U1_130MHz | `core/state_reg[5]/C` → `core/result_reg[152]/D` | 7.635 | 1.145 | 6.490 | 7 | +0.016 |
| P12U1_130MHz | `core/lane/scheduled_execution.fixed_context.held_tag_reg[3]/C` → `core/lane/scheduled_execution.fixed_context.held_capture_reg[102]/D` | 7.633 | 1.395 | 6.238 | 6 | +0.019 |
| P12U1_130MHz | `core/read_addresses.address_reg[5]/C` → `core/lane/scheduled_execution.fetched_source_reg[120]/D` | 7.649 | 1.509 | 6.140 | 10 | +0.042 |
| P12U1_130MHz | `core/target_reg[13]/C` → `core/endpoints/banks[0].regular.words_reg_0_63_153_155/RAM*/WADR2` | 7.561 | 1.819 | 5.742 | 10 | +0.048 |
| P12U1_130MHz | `core/target_reg[13]/C` → `core/endpoints/banks[0].regular.words_reg_0_63_153_155/RAM*/WADR2` | 7.561 | 1.819 | 5.742 | 10 | +0.048 |
| P12U1_130MHz | `core/target_reg[13]/C` → `core/endpoints/banks[0].regular.words_reg_0_63_153_155/RAM*/WADR2` | 7.561 | 1.819 | 5.742 | 10 | +0.048 |
| P12U1_130MHz | `core/target_reg[13]/C` → `core/endpoints/banks[0].regular.words_reg_0_63_153_155/RAM*/WADR2` | 7.561 | 1.819 | 5.742 | 10 | +0.048 |
| P12U1_130MHz | `core/target_reg[13]/C` → `core/endpoints/banks[0].regular.words_reg_0_63_204_206/RAM*/WADR2` | 7.553 | 1.819 | 5.734 | 10 | +0.055 |
| P12U1_130MHz | `core/target_reg[13]/C` → `core/endpoints/banks[0].regular.words_reg_0_63_204_206/RAM*/WADR2` | 7.553 | 1.819 | 5.734 | 10 | +0.055 |
| P12U1_150MHz | `core/read_addresses.address_reg[5]/C` → `core/lane/scheduled_execution.fetched_source_reg[89]/D` | 7.809 | 1.395 | 6.414 | 9 | -1.140 |
| P12U1_150MHz | `core/read_addresses.address_reg[5]/C` → `core/endpoints/banks[1].regular.words_reg_0_63_165_167/RAM*/I` | 7.466 | 1.020 | 6.446 | 7 | -1.116 |
| P12U1_150MHz | `core/read_addresses.address_reg[5]/C` → `core/endpoints/banks[0].regular.words_reg_0_63_54_56/RAM*/I` | 7.433 | 1.020 | 6.413 | 7 | -1.083 |
| P4U1_130MHz | `core/target_reg[11]/C` → `core/endpoints/banks[1].regular.words_reg_0_63_189_191/RAM*/I` | 7.306 | 1.974 | 5.332 | 11 | +0.065 |
| P4U1_130MHz | `core/read_addresses.address_reg[6]/C` → `core/lane/scheduled_execution.fetched_source_reg[18]/D` | 7.558 | 1.311 | 6.247 | 10 | +0.093 |
| P4U1_130MHz | `core/target_reg[11]/C` → `core/endpoints/banks[0].regular.words_reg_0_63_213_215/RAM*/I` | 7.250 | 1.974 | 5.276 | 11 | +0.130 |
| P4U1_130MHz | `core/target_reg[11]/C` → `core/endpoints/banks[0].regular.words_reg_0_63_189_191/RAM*/I` | 7.220 | 2.071 | 5.149 | 12 | +0.156 |
| P4U1_130MHz | `core/target_reg[11]/C` → `core/endpoints/banks[0].regular.words_reg_0_63_168_170/RAM*/I` | 7.219 | 1.974 | 5.245 | 11 | +0.160 |
| P4U1_130MHz | `core/target_reg[11]/C` → `core/endpoints/banks[1].regular.words_reg_0_63_153_155/RAM*/WADR0` | 7.525 | 1.974 | 5.551 | 11 | +0.163 |
| P4U1_130MHz | `core/target_reg[11]/C` → `core/endpoints/banks[1].regular.words_reg_0_63_153_155/RAM*/WADR0` | 7.525 | 1.974 | 5.551 | 11 | +0.163 |
| P4U1_130MHz | `core/target_reg[11]/C` → `core/endpoints/banks[1].regular.words_reg_0_63_153_155/RAM*/WADR0` | 7.525 | 1.974 | 5.551 | 11 | +0.163 |
| P4U1_130MHz | `core/target_reg[11]/C` → `core/endpoints/banks[1].regular.words_reg_0_63_153_155/RAM*/WADR0` | 7.525 | 1.974 | 5.551 | 11 | +0.163 |
| P4U1_130MHz | `core/target_reg[11]/C` → `core/endpoints/banks[1].regular.words_reg_0_63_222_224/RAM*/I` | 7.192 | 1.974 | 5.218 | 11 | +0.187 |
| P4U1_150MHz | `core/node_level_reg[3]/C` → `core/endpoints/banks[1].regular.words_reg_0_63_219_221/RAM*/I` | 7.012 | 1.977 | 5.035 | 12 | -0.658 |
| P4U1_150MHz | `core/node_level_reg[3]/C` → `core/endpoints/banks[1].regular.words_reg_0_63_132_134/RAM*/I` | 7.004 | 1.880 | 5.124 | 11 | -0.654 |
| P4U1_150MHz | `core/node_level_reg[3]/C` → `core/endpoints/banks[1].regular.words_reg_0_63_144_146/RAM*/WE` | 6.862 | 1.880 | 4.982 | 11 | -0.650 |
| P4U1_150MHz | `core/node_level_reg[3]/C` → `core/endpoints/banks[1].regular.words_reg_0_63_144_146/RAM*/WE` | 6.862 | 1.880 | 4.982 | 11 | -0.650 |
| P4U1_150MHz | `core/node_level_reg[3]/C` → `core/endpoints/banks[1].regular.words_reg_0_63_144_146/RAM*/WE` | 6.862 | 1.880 | 4.982 | 11 | -0.650 |
| P4U1_150MHz | `core/node_level_reg[3]/C` → `core/endpoints/banks[1].regular.words_reg_0_63_144_146/RAM*/WE` | 6.862 | 1.880 | 4.982 | 11 | -0.650 |
| P4U1_150MHz | `core/node_level_reg[3]/C` → `core/endpoints/banks[1].regular.words_reg_0_63_210_212/RAM*/I` | 6.986 | 1.977 | 5.009 | 12 | -0.636 |
| P4U1_150MHz | `core/lane/FSM_sequential_scheduled_execution.state_reg[2]/C` → `core/result_reg[198]/D` | 7.261 | 1.223 | 6.038 | 6 | -0.633 |
| P4U1_150MHz | `core/node_level_reg[3]/C` → `core/endpoints/banks[0].regular.words_reg_0_63_225_227/RAM*/I` | 6.965 | 1.977 | 4.988 | 12 | -0.618 |
| P4U1_150MHz | `core/node_level_reg[3]/C` → `core/endpoints/banks[0].regular.words_reg_0_63_219_221/RAM*/WE` | 6.821 | 1.880 | 4.941 | 11 | -0.609 |

Implemented generic cut: maintain `target_at_level == target >> node_level` during tree execution. All target setup, level-0 leaves, FORS level-2 roots, and parent advances have matching updates. The simulation-only invariant covers PUSH_NODE/PUSH_STACK/PARENT_SETUP/PARENT_DONE. This adds no state/cycle. Parent performs integrated S1 tests.

Next evidence-directed cuts:

1. Register adjacent workspace read address on the existing read-address update edge. Current `read1 = address+1` and last-address correction are after the main register and precede parity bank selection/RAM access. No node data register or read latency is required.
2. If auth write remains dominant, register `auth_node_match` on each node producer edge; this removes the 21-bit equality/carry from the RAM write mux path, with no extra FSM state.
3. The P12 130 MHz context-read tag path is still state decode → tag mux → high-fanout bank read → result. It needs a registered read-tag ownership/control stage, or a one-cycle deferred payload read stage. This is separate from direct response payload snapshots already in R5.
4. No reset path appears in the top 20 of these four routed reports; avoid adding more reset fanout as an unsupported target. Existing abort_execution is registered.
