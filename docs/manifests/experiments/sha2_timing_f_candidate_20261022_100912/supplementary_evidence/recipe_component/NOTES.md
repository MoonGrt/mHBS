# SHA2 formatter staging candidate (2026-10-22)

Recipe SHA256: `06abf13cf3466b37f231ff8e1180a95100da94a67be8b002e30c662b568aac6a`.

This component experiment holds the E2 compression primitive (`774433bd...`) fixed. Root's F1 integration experiment separately combines the new primitive; do not treat these standalone results as that combined source's validation.

The old need_block/cursor -> selection -> context read -> format/length decode -> byte masks/prefix write path is split into arbitration, descriptor and preparation cycles. The formatter registers the block index. Prefix writes use registered format_kind; source reads enter a 192-bit beat register before alignment/padding and the four existing 128-bit block words. Ordinary beats still issue consecutively; DRAIN commits the final staged beat before compression can accept the block. No full node bank or hash lane is added.

One pending capture flag/tag defers initial capture of a no-seed chain to the following edge. It compares registered capture_step/iteration and copies the allocated digest. Scalar response_valid and batch completion publication exclude this pending tag, so zero-step results cannot expose stale capture. Disabled capture is unchanged. Initial-pending processing occurs before last-priority allocation, keeping same-edge refill semantics.

690 scalar recipe vectors passed: P1U1 normal and P4U2 SYNTHESIS. The independent vectors cover fixed/unary/binary, all standard recipe shapes, LMS 34-block lists, HMAC and MGF, message/padding/address boundaries, output capture, stalls and replay. Full scalar latency delta is exactly 3*compression_blocks - fixed_prefix_blocks in all 690 comparisons; Hash/compression counts and output/capture bytes are unchanged. E.g. a two-block XMSS PRF is 138 ->143 clocks, three-block XMSS seed 209 ->217, LMS34 list2549 ->2651 (P1U1).

12 P8U1 batch groups (96 requests, four live tags) passed. P12U1/P24U1 normal and SYNTHESIS fully occupied all P contexts: 12 groups,432 requests, retained captures, all-complete hold, out-of-order completion, same-edge refill and request poisoning passed. Both views have identical coverage/counts/cycles. Aggregate full-slot cycles (SLH,XMSS,LMS) changed P12:5027/14453/2617 ->5211/14944/2734; P24:5124/14574/2729 ->5521/15458/3036. These are component stress-bench cycles, not complete Sign cycles.

Dedicated zero-step tests cover all families, nonzero starts7/15, equal/mismatched capture step, disabled capture and held outputs. Captured no-seed response visibility changes1 ->2 clocks; disabled capture stays1. No hashes/compressions occur.

Only the production sha2-recipe file was edited. No Vivado job was started by this component experiment. Area, frequency and full Sign ATP remain the separate frozen integration experiment's measurements. The formatter_only directory retains the pre-initial-capture intermediate simulation variant; it was not submitted for hardware measurement.
