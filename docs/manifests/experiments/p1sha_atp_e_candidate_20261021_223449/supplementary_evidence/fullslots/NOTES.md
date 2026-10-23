# Final E2 SHA2 all-context scheduling validation

Final E2 freeze candidate_20261021_223449: SHA2 P12U1 and P24U1, normal and SYNTHESIS, each pass all three chain families at q=1024. All 12 groups passed, with 432 requests and 432 returns. The E1 standalone harness and tool are unchanged; E2 is independently compiled and validated against its own frozen source.

The bench uses TAG_BITS=clog2(P), P live tags, and 2P independent hashlib requests. It accepts the entire first wave with response_ready=0, asserts all P busy bits, waits for all P complete bits, and checks every retained digest/capture bank eight times before consuming any result. It then exercises same-edge retirement/refill, out-of-order completions, request-field poisoning, and held-response stability. All occupancy gates are observed from functional state. A 1,000,000-clock timeout is present; no group exceeded it.

| Config | Family | Requests | Max live | Full cycles | All-complete hold cycles | Capture checks | Same-edge | Unordered | Test cycles |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| P12U1 | 0 | 24 | 12 | 2559 | 20 | 96 | 12 | 20 | 5027 |
| P12U1 | 1 | 24 | 12 | 7271 | 20 | 96 | 12 | 21 | 14453 |
| P12U1 | 2 | 24 | 12 | 1354 | 20 | 96 | 12 | 20 | 2617 |
| P12U1_synthesis | 0 | 24 | 12 | 2559 | 20 | 96 | 12 | 20 | 5027 |
| P12U1_synthesis | 1 | 24 | 12 | 7271 | 20 | 96 | 12 | 21 | 14453 |
| P12U1_synthesis | 2 | 24 | 12 | 1354 | 20 | 96 | 12 | 20 | 2617 |
| P24U1 | 0 | 48 | 24 | 2632 | 33 | 192 | 24 | 46 | 5124 |
| P24U1 | 1 | 48 | 24 | 7363 | 33 | 192 | 24 | 46 | 14574 |
| P24U1 | 2 | 48 | 24 | 1431 | 33 | 192 | 24 | 46 | 2729 |
| P24U1_synthesis | 0 | 48 | 24 | 2632 | 33 | 192 | 24 | 46 | 5124 |
| P24U1_synthesis | 1 | 48 | 24 | 7363 | 33 | 192 | 24 | 46 | 14574 |
| P24U1_synthesis | 2 | 48 | 24 | 1431 | 33 | 192 | 24 | 46 | 2729 |

All observed scheduler metrics, including complete test-cycle totals, match the separately validated E1 run per configuration/family. Outputs and Hash/compression counts are independently checked against the generated vectors in this E2 run. This comparison does not substitute E1 evidence for E2.

Exact frozen-core file SHA, source manifest SHA, harness SHA, tool SHA, and actual active tag lists are recorded in SUMMARY.json and SOURCE_BINDING.json. The complete final E2 source manifest was rechecked after testing. The withdrawn 223105 candidate was never read or tested. Detailed compilation and vector logs remain under runs/.

This is scheduler/recipe validation rather than complete Sign or physical timing evidence. All source files and old tests remain unmodified.
