# I combined component validation (2026-10-22)

RecipeSHA924a8a28b23a1515c7b2fc522af354abc958980acbb78bfd4aaae7e531d07e61; SHA256core140c3a7d13addd05aa60f4972164facc5c463df348f2a8d779999c907e1c3d11. Frozen input manifest candidate/SOURCE.json SHA635f494b81729bedcb42b9fecac0a746beaead36b71393a4f9a5f7aa4edf39c4. Composition rootG4b+G5+H2 and independent review are archived alongside.

G4b supplies constant-slot context writers, a local onehot admission/allocation register and onehot scalar byte-mask publication. G5 registers address ingredients in DESCRIBE and finishes packed_address in PREPARE. H2 balances the shared T1 addition tree. Interfaces, contexts, hash-lane count, algorithms and FSM/primitive cycle boundaries are preserved. Normal assertions cover allocation onehot/equivalence, scalar publication onehot, address formula equivalence and completion metadata.

The existing actualvalue.sv/parity-bank/registeredadjacent-address recipe harness was reused unchanged.690 independent scalar vectors passed: P1U1normal345, P4U2SYNTH345. Every output/capture byte, Hash/compression and per-vector cycle record equalsG2, sums111366/63558. Coverage includes fixed/unary/binary XMSS key/mask/right-node lifetime, HMAC/MGF, LMS34blocklists, SLHprefixlists, message/address/padding boundaries, output stalls, invalid recipes and reset replay.

P12/P24all-context tests passed both normal/SYNTHESIS:12groups/432requests. Every tagbusy/allcomplete, retainedcapture, out-of-order return, request poisoning, same-edge reuse, allHash/compression/cycle/coverage metrics equalG2. Per-family totals remain P12 5213/14946/2736 andP24 5523/15460/3038. Both views match exactly.

Dedicated normal/SYNTHESIS tests passed30zero-step cases plus2pending-admission reset/replay cases. Starts0/7/15, matching/mismatched/disabled capture, output retention, reservedbusy/blockedready and zero stale work after reset were checked; latency remains2 and nohash/compression is issued. Both genericMGF scenarios passed in each view: scalar49-byte output checks MGF1high17preserveslow32; subsequent batchtag3 16-byte output checks non-scalar MGF0 still clears sharedscalar_result and overwrites itslow16. Independent hashlib constants and5Hash/10compressions perview checked.

All14 frozen input checksums remain unchanged. No combined RTL or production file was edited during this task and no hardware job was launched/stopped. This is combined component validation, not a claim that all14 P/U meet physical frequency or ATP. Whole-core Sign/diagnostic/route measurements belong to the subsequent frozen experiment.
