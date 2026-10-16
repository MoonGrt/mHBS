# S4 SHAKE recipe timing review

S4 is the source frozen under `candidate_20261020_110957`; production RTL has not been edited by this review.

| Routed evidence | Critical recipe path | Delay | Logic levels | Route proportion |
|---|---|---:|---:|---:|
| P4U1 150 MHz | penultimate `stage_tag` to `return_address` | 6.652 ns | 1 | 92.633% |
| P4U1 140 MHz | penultimate `stage_tag` to `return_digest` | 7.008 ns | 1 | 93.750% |
| P12U1 140 MHz | penultimate `stage_tag` to `return_key` | 7.046 ns | 1 | 93.046% |
| P12U1 140 MHz | `awaiting_response` to `held_capture` | 7.031 ns | 4 | 87.357% |

The 150 MHz P12 worst paths instead cross the recipe/executor ready/response-control boundary, reaching FORS and executor state clock enables in 8–9 logic levels. Keccak round arithmetic does not appear in these top 20 paths.

`local_read.patch` adds a context-local read-address register one pipeline stage ahead of the existing operand-prefetch registers, without changing functional latency. For P>=3 its source is stage P-3. For P2 it samples the stage-0 input metadata. A last-traversal fixed-request enable differs functionally from the generic stage-tag enable, allowing the local address to remain a distinct register without preservation attributes. It also reuses `return_key` and `return_digest` in context-bank writeback instead of reading the same banks again using the final tag.

Isolated validation passed 1836 scalar/stream recipe cases at P2U12, P3U2, P4U1, P12U1; P4U1/P12U1 batch validation passed 24 groups / 192 requests, including unordered completions, same-cycle refill, retained captures and poison controls. P12 batch tests exercise four live tags, not all twelve. No synthesis or routing has been launched for this isolated patch, so no timing or area improvement is claimed.

A subsequent optional cut can split response publication into an elastic selected-tag stage and the existing held-payload stage. That removes priority encoding from the RAM-read cycle and preserves one-response-per-cycle throughput, at the cost of one final-response cycle and an expanded ownership invariant. It is not included in this patch.
