# SHAKE P1 scalar candidate

Only `scalar_execution` changes; the complete `scheduled_execution` suffix is byte-identical to the frozen baseline. No interface, handshake, pipeline count, permutation count, chain step or stream schedule changes.

- Compact SLH feedback replaces the final-round digest-to-frame-to-layout path with direct writes into the node-length-dependent fixed sponge word positions. This preserves same-cycle next-chain launch. Header/address/control fields still use the existing formatter. The simulation oracle compares every written word against the original formatted block.
- Stream padding uses sixteen registered per-byte live/padding controls, prepared beside the existing source selectors in START or on accepted current beat. Endpoint data sees a mask after source selection, rather than length arithmetic and priority muxes. A simulation assertion checks controls against the current position, including backpressure. No full-node data register is added.

Normal and SYNTHESIS P1U1/P1U2 recipe tests each pass all 459 independent hashlib cases, including 135/136/137-byte boundaries, variable node length, long lists, response/producer stalls and alternating reset replay. Independent scalar-chain tests each pass 216 cases covering n=16/24/32, 0/1/2/7/15 steps, seed/intermediate/final capture, preserve-counter domain=3 and normal-counter domain=0x83, q=0/1024/1048575. Full-core Sign is deliberately left to the frozen parent experiment; recipe tests alone do not establish system ATP or target timing.
