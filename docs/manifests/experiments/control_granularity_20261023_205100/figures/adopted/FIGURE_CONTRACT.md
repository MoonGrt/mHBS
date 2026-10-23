# Latest SLH-DSA-128f Sign cycle composition

- Question: How do the adopted i/c designs and unchanged t compare with SLotH in total signing clocks and their Hash, Transfer and Remaining components?
- Claim: The optimized software i reduces Remaining below SLotH for both backends while preserving explicit per-Hash execution; c/t expose the remaining control-granularity comparison.
- Evidence: Eight measured observations, ordered SLotH/i/c/t within SHAKE and SHA2; one matching 33-byte first KAT per backend, with full signature/cache and cryptographic-work checks. No aggregation, sampling, error bars, frequency conversion, or extrapolation.
- Layout: Two comparable panels with one shared zero-based linear cycle scale. Panel a shows SHAKE decomposition; panel b tests the same comparison under SHA2's greater compression work. Identical component colors, bar order, units and axis limits.
- Backend: Continue the existing Python/matplotlib plotting workflow. Adapt its structure and colors; preserve the historical outputs and data.
- Export: Editable PDF/SVG, 600 dpi PNG, exact integer Markdown/JSON source data, source checksums, and QA evidence in this directory. No report CSV.
- Definitions: Hash has priority over overlapping internal handoffs. Transfer is non-overlapped hash-MMIO occupancy, zero for i/c/t. Remaining is the complement, including internal data movement outside Hash. SLotH's reported Hash also contains some engine setup/chain-control clocks; preserve and disclose that boundary.
- Source selection: i_software is adopted, not i_timing_v3. c_control_pipeline is adopted; its 33-byte KAT must be measured again. Reuse t only after matching its frozen RTL to production. Do not substitute the 1-byte default-vector cycle counts.
- QA: Assert exact component sums, source/fixture/signature identities and work counts; measure rendered panel alignment; audit source, PDF text and collisions; inspect both panels and the whole figure. All eight observations and all three requested components remain represented.
