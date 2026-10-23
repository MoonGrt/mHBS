# G2 private first-list index register (2026-10-22)

Private recipe SHA256: `286f869de240a4cea14d8bb249e25c28dd7f792aafafee4a45b37e650e9ccc0b`. Other RTL, including primitive `81a8e9a5...`, is copied unchanged from frozen G1 `build/sha2_timing_g/candidate_20261022_111728/source`.

This adds one INDEX_BITS-wide descriptor register. DESCRIBE computes first_list_address from the selected shape/block. PREPARE presents the registered index; ordinary BUILD lookahead remains byte-identical. No FSM state or clock is added. The executor registers the PREPARE index into its adjacent read-address pair on that edge. value.sv provides asynchronous reads from these address registers, so the first BUILD list-word fetch on the following edge sees the correct data. The earlier DESCRIBE prefetch was redundant because PREPARE already supplies a full clock for this address registration.

The original scalar recipe bench bypasses list_next_index0 and therefore cannot validate this boundary. Both private G1 reference and G2 benches were wired through the actual rtl/memory/value.sv parity-banked RAM and a registered read-address pair. The RAM is preloaded through its single write port with the original136 test nodes; guarded adjacency135->134 matches the executor. Only the hash-path address timing is reproduced here; whole-core arbitration remains separate integration validation.

1035 G2 scalar vectors passed through this real RAM: P1U1 normal, P4U2 SYNTHESIS, P12U1 normal,345 each. They include multi-block LMS34-block lists, all SLH list arities and first-block prefix bypass, message/address/padding boundaries, output and capture bytes, Hash/compression counts, stalls, invalid recipes and reset replay. G1 P1U1 real-RAM345 also passed. All345 P1 cycle/count records are exactly identical, aggregate111366clocks.

P12/P24 full-slot tests passed both views:12groups/432requests, every tag busy and complete, captured results retained, request poisoning and same-edge reuse. All coverage, output/count metrics and cycles equal the same frozen G1 integrated fixture. Per-family totals remain P12 5213/14946/2736 and P24 5523/15460/3038. These stress benches do not exercise long lists; the real-RAM scalar suite supplies that independent coverage.

After these private tests passed, root explicitly approved promotion. The tested recipe was copied byte-for-byte to production; all other RTL remained unchanged (PROMOTION.json). No hardware job was launched or stopped. Frequency/area/ATP remain separate frozen measurement results.
