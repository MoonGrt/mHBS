# μHBS ABI 4 architecture

The seven `uhbs_<profile>_top` wrappers all instantiate `uhbs_hbs`.
Legacy `uhbs_slh_dsa_top`, `uhbs_xmss_top`, and `uhbs_lms_top` aliases
retain the 128f / omega4 configurations. The authoritative production source
closure is `manifests/unified_sources.txt`, consumed by Make and Vivado. Each product selects an immutable ABI 4
image and is synthesized separately; it is not a runtime multi-profile
bitstream.

The shared core contains one token sequencer, one five-macro dispatcher, one or two
recipe/SHAKE lanes from common source (static `LANES`), a common chain iterator, stack-based tree
reduction, value stores, and a direct 64-bit result stream with byte enables. n=16/24/32 is an
elaboration width; storage depths are specialized to each profile. Recipes, tree addressing, chain reductions, output layouts, and entry
points come from image data. Family and stateful identity are explicit ABI fields; n=32 does not imply stateful.
The second logical lane retains only the chain recipes present in the image;
physical lane exchange preserves these logical capabilities.

A wrapper accepts `start` only when `ready`. It supplies fixed Job parameters
internally, performs Keygen, asserts `keygen_done`, accepts one fixed-length
message, signs once, and asserts `done`. Result bytes share one output stream:
`result_kind=0` identifies SK||PK, `result_kind=1` identifies the signature.
Each result has its own `out_last`. The Keygen root is retained and used by Sign.
No product wrapper has Job data inputs or outputs.

XMSS/LMS cache only the authentication path for the selected q while computing
the entire Keygen tree. Sign requests durable persistence of q+1 through
`state_commit_valid/ready` and `state_next_q`; no signature output is released
before acknowledgment. A later start rebuilds the path at the live next q.
A reset invalidates cache and volatile state; the fixed-job wrappers are
measurement fixtures, not a persistent key-management service.

Keygen/Sign counters measure the rising-edge distance from acceptance of the
internal Job to the core's done pulse. They include serialization and external
waits. The main benchmark uses continuous message input, ready output, and
immediate state-commit acknowledgment. The wrapper lifecycle overhead between
operations is reported separately from these operation counters.

## Reproduction

- `make compile-microcode`: execute the software gate, export all images and
  vectors, and regenerate fixed-job wrappers.
- `make rtl-unit-test`: Icarus Verilog 12.0 (`iverilog -g2012` and `vvp`).
- `make rtl-slh-dsa-test rtl-xmss-test rtl-lms-test`: Verilator 5.008
  (`--binary --timing`), complete Keygen then Sign, every output byte checked.
- Set `UNROLL=1`, `2` or `4`, and `LANES=1` or `2`, for synthesis and simulation.
  Make defaults to two lanes for SLH-DSA and one for XMSS/LMS; an explicit
  `LANES` overrides all profiles. Direct RTL wrappers use their profile defaults.
- Add `SWAP=1 BACKPRESSURE=1` to exercise physical-lane exchange, stream stalls,
  and delayed state persistence.
- `make synth-slh-dsa synth-xmss synth-lms`: post-synthesis candidate screening.
- Route only retained candidates with `experiments/route_unified_hbs.tcl`.

See `Unified_HBS_ABI.md` for the executable image contract and ATP formula.
The old `uhbs_stateless_hbs`/`uhbs_stateful_hbs` implementations and their
standalone benches were removed from the working tree. Git history preserves
them; `manifests/unified_sources.txt` is the current synthesis source list.

## Seven-profile build and replay

`PROFILE` accepts `slh_128f`, `slh_192f`, `slh_256f`, `xmss_omega2`,
`xmss_omega4`, `lms_omega2`, and `lms_omega4`. Omega is bits per digit,
so omega2 means Winternitz base 4.

```bash
make rtl-profile-test PROFILE=slh_192f
make rtl-verification
make synth-profile PROFILE=slh_192f
make route-profile PROFILE=slh_192f
make archive-seven-profiles
make reproduce-paper-comparison
python3 scripts/replay_profile.py slh_192f --run rtl-profile-test
```

The seven-profile matrix checks normal flow, physical lane exchange, randomized
backpressure, both lane counts, and q=0/1023 for all stateful profiles.
`rtl-all-profiles`, `synth-all-profiles`, and `route-all-profiles` are batch entries.
A routed candidate must match its simulation's complete RTL/image hashes.
Historical ABI 3 reproduction uses the pinned c8dedf8 source, not the ABI 4 tree.

FORS leaf pairs execute concurrently on two lanes and use the same tree stack.
Absorption input is registered between the endpoint memory mux and SHAKE state.
SLH feedback is statically omitted from stateful lanes. The 24-byte stream
cursor advances with counters rather than runtime division. Synthesis disables
DSP inference for constant length arithmetic.
