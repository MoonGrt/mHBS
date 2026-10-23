# E1 SHA2 all-context scheduling validation

SHA2 P12U1 and P24U1, normal and SYNTHESIS, each pass all three chain families at q=1024. All 12 groups passed, with 432 requests and 432 returns. No RTL, frozen input, or existing test file was modified.

The new standalone bench uses TAG_BITS=clog2(P), P live tags, and 2P independently serialized hashlib requests. It accepts the entire first wave with response_ready=0, asserts all P busy bits, waits for all P complete bits, and checks every retained digest/capture bank eight times before consuming any result. It then exercises same-edge retirement/refill, out-of-order completions, invalid request-field poisoning, and held-response stability. All coverage gates are actual observations. A 1,000,000-clock timeout is present; no group exceeded it.

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

Exact frozen-core file SHA, source manifest SHA, new harness SHA, tool SHA, and actual active tag lists are recorded in SUMMARY.json and SOURCE_BINDING.json. The complete source manifest was rechecked after testing. Detailed compilation and vector logs remain under runs/.

The core is frozen E1 source from build/p1sha_atp_e/candidate_20261021_221627/source. This extends the prior four-live-tag test for large P; it does not reuse its full_context_occupancy claim. This is scheduler/recipe validation, not a complete Sign or physical timing result.
