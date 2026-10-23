# SHA2 registered admission, CV and completion metadata (G, 2026-10-22)

Recipe SHA256: `261d8873671a651d8864568998991cdb1982e90a0c17a92f821b66321ad442ec`.

The component fixture holds primitive `774433bd...` fixed and compares the prior F1 recipe (`06abf13c...`) to G. It does not substitute for the separately frozen G primitive / whole-core integration.

`format_cv` is read and registered in DESCRIBE. The SHA256 input receives this 256-bit register instead of a tag-selected CV bank. PREPARE sets per-slot final_compression from the already registered format_length/format_block; phase/shape/arity decoding no longer sits behind the final_compression write path.

A one-entry packed admission record registers left/right values and all context metadata. Admission reserves busy_slot immediately and clears old complete/need_block on that edge. External ready is low while the record is pending. The following edge allocates all context banks from the record. Input selection uses job mode independently of the busy/ready reduction. Allocation occurs before last-priority reservation so retirement/refill remains valid, and no response can publish a partially allocated slot. This adds one clock per ordinary scalar request, not per hash, chain step or block. Requests are admitted at most every second clock.

F1's separate initial_capture_pending/tag are removed. Initial capture compares only registered admission controls and writes captured simultaneously with zero-step complete/scalar_result. Captured zero-step batch latency remains two clocks; disabled capture changes one to two. Invalid scalar recipes are rejected after admission without any compression. Existing scheduler/descriptor/192-bit beat staging and the original four128-bit block words remain; no extra512-bit block buffer or hash lane is added, and no P/U specialization is introduced.

690 scalar recipe vectors passed (P1U1 normal, P4U2 SYNTHESIS). Every case has identical output/capture bytes and Hash/compression counts, with exactly+1 acceptance-to-response clock. Aggregate component latencies are111021->111366 and63213->63558. The test includes fixed/binary, all supported recipe shapes, HMAC/MGF, LMS34-block lists, padding/address boundaries, output stalls, invalid recipes and reset replay.

P8U1 four-live-tag batching passed12 groups/96requests. P12/P24 all-context tests passed in both normal and SYNTHESIS views:12groups/432requests, all tags occupied and all results retained, capture hold checks, out-of-order completion, request poisoning and same-edge tag reuse. Counts and normal/SYNTHESIS coverage/cycles match. These are stress-bench cycles; full Sign cycles remain the integration measurement.

A new dedicated reset test observes a pending admitted request with busy_slot reserved, ready deasserted and no response, asserts reset before allocation, and confirms no stale response/hash. It then replays15 zero-step cases (all families; starts0/7/15; equal/mismatched/disabled capture) with held outputs. Both normal and SYNTHESIS passed,30zero-step cases plus2pending-reset cases; all return in2clocks with0Hash/0compressions.

Only production sha2-recipe.sv and this tmp evidence were edited by this task. No hardware task was started. Area, actual frequency and ATP are not inferred from component results.
