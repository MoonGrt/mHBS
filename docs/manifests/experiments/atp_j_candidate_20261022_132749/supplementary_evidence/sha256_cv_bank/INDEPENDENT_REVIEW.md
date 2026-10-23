# SHA256 CV bank independent review — 2026-10-22

Reviewed production SHA256 `e7affefe71404930b739dd8d8ccab23a118628be75e8455a9cc4e932dd185e4f` without editing RTL. No allocation or lifetime defect was found.

The CV pointer advances only for a new input handshake. Its value is carried with the token; the external tag never addresses the bank and can have arbitrary or duplicate values. Each accepted compression has exactly `P × ceil(64/(P×U))` unstalled edges to feed-forward. Every token takes the same number of ring traversals; the final partial traversal changes arithmetic enables, not latency. Therefore tokens finish in admission order and at most P CV lifetimes overlap. A round-robin slot cannot wrap onto an older live token before that token finishes.

Finishing an old token and admitting its successor on the same edge is safe, including P=1: feed-forward observes the pre-edge bank value and the new CV write takes effect after that edge. Once feed-forward completes, the old CV is no longer needed because `output_cv` owns the response. Global output stalls prevent new admission and freeze data, slot IDs and traversal metadata together. Reset clears validity, return control, response validity and the write pointer; stale unreset bank bytes cannot reach a valid response. Explicit wrapping handles non-power-of-two P without invalid addresses.

The main physical risk is the new `cv_slot[last] → distributed CV read → feed-forward carry chain → output_cv` path. The initial implementation had the CV beside the arithmetic state. Setup and hold—including same-address read/write minimum-delay behavior—must pass on the actual routed netlist before this candidate is called a timing or ATP improvement. LUTRAM inference and write-data fanout can also change placement and area.

The integrated descriptor overlap appears consistent: `block_tag` holds the queued block identity while the next context is reserved, and DESCRIBE cannot overwrite its CV/metadata before acceptance. Last-beat commits precede compression sampling. List PREPARE primes the current endpoint pair; retained current words and following-word prefetch use separate validity/control positions. Every block restarts list validity and its first-index prefetch. No new functional issue was found in this read-only review.

The root's existing 30 legal P/U × normal/SYNTHESIS × 181-vector tests remain the empirical primitive evidence. This review adds lifetime reasoning and identifies the new timing path; it does not replace target-frequency physical acceptance.
