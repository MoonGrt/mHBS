# Scalar endpoint stream mux optimization

Baseline SHAKE recipe SHA: `f0a5ded9340a87452e52fd2a7b35c373b563be5451cc22cb13b0653552827081`; candidate1 SHA: `c34a7b19ad1b72d16e66dd1329f6715c02d37cd50a8be75a533a4b39c8355972`.

C3 P1U1 routed actual path starts `read_addresses.address_reg[2]`, crosses endpoint distributed RAM and source/window/payload selectors, and ends `scalar_execution.staged_data_reg[121]`. The report gives 9 logic levels, 6.640 ns data delay, 5.426 ns route delay (81.716%), WNS -0.010 ns at 6.667 ns.

The endpoint's generic random word source is not observable in scalar streams. ADDRESS_LIST body beats use the dedicated list window. PREFIX_LIST needs only the first node's sixteen low bits in the 22-byte prefix beat at position 16; later beats also use the list window. PREFIX_MESSAGE uses randomizer/message data and never an endpoint node. Replacing these impossible generic source paths with explicit direct endpoint paths removes endpoint fanout into all seed/message/address source muxes.

The final payload source mode is registered beside the existing lookahead source controls. No data buffer or protocol stage is added. Stream position, list cursor, acceptance, output consumption, hash starts and chain steps are untouched. Three mode FFs replace repeated source/position decisions in the wide data path. Normal simulation reconstructs the original source_word/payload logic and checks the complete payload and mode every live STREAM cycle, including stalls. All scheduled_execution code is byte-identical.

Validation1 records 1836 normal/SYNTHESIS P1U1/U2 recipe KAT cases, 918 P4U1/P12U1 compatibility recipe cases, and 432 independent compact-chain cases, all passing. Chain test cycle totals remain 39094/20518 for P1U1/U2, matching the prior baseline bench; this is not a complete Sign cycle measurement. Full-core/area/target-frequency results remain the parent experiment's responsibility.
