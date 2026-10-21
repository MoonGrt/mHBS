# CHAIN control RTL verification fixture correction

The original frozen fixture changed its mutable ROM immediately before releasing reset; its first header sample was zero. The corrected fixture holds reset for two additional clocks after changing the ROM. No production RTL changed. Every active production RTL file and `sources.txt` is SHA256-identical to the frozen candidate; `control_fixture_fix/SOURCE.json` records both identities. The original failed fixture remains part of the frozen experiment.

The corrected RTL control test passes all four backend / SYNTHESIS views. Each view executes 20 cases: two positive controls and 18 rejection cases. CALL/RET and RAM address 107 succeed. Invalid context writes, height/mode bounds, overflow, reserved RAM, input ownership, return/call misuse, PC overflow, TREE templates, legacy headers, backend mismatch and invalid encodings fail without granting Hash or output ownership; faults remain quiescent.

`CONTROL_RTL_VALIDATION.json` contains the source-bound summary. The existing `candidate_rtl.tar.gz` is the frozen hardware artifact; `control_fixture_fix/tests.tar.gz` contains the corrected fixtures. Detailed logs remain in `build/chain_controls`.

The top signature fixture also uses K1U1 and a 20-million-cycle bound instead of the restored main fixture's P4U1 / 2-million-cycle settings. All eight corrected signature/debug macro views pass: two backends × SYNTHESIS off/on × signature storage off/on. Each emits all 17,088 bytes. SHAKE executes 104,937 Hashes / 105,641 permutations; SHA2 executes 104,925 Hashes / 211,432 compression blocks. `TOP_SIGNATURE_RTL_VALIDATION.json` binds these results to the same frozen hardware.

The fast simulation wrapper also now forwards `SIM_HASH_TRACE` to the C++ `+HASH_TRACE` flag and prints the trace marker. The original full regression attempt that lacked this wrapper flag is retained; an absent trace marker does not count as trace verification. The corrected wrapper identity is in the supplementary ledger.
