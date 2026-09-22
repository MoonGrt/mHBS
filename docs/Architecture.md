# μHBS ABI 3 architecture

The three production wrappers `uhbs_slh_dsa_top`, `uhbs_xmss_top`, and
`uhbs_lms_top` all instantiate `uhbs_hbs`. The authoritative production source
closure is `manifests/unified_sources.txt`, consumed by Make and Vivado. Each product selects an immutable ABI 3
image and is synthesized separately; it is not a runtime three-algorithm
bitstream.

The shared core contains one token sequencer, one five-macro dispatcher, one or two
recipe/SHAKE lanes from common source (static `LANES`), a common chain iterator, stack-based tree
reduction, value stores, and a 64-bit output packer. n=16/n=32 is an elaboration
width. Recipes, tree addressing, chain reductions, output layouts, and entry
points come from image data. There is no algorithm selector in the core.
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
- Set `UNROLL=2` or `4`, and `LANES=1` or `2`, for synthesis and simulation.
  Make defaults to two lanes for SLH-DSA and one for XMSS/LMS; an explicit
  `LANES` overrides all three. Direct RTL wrapper defaults remain two lanes.
- Add `SWAP=1 BACKPRESSURE=1` to exercise physical-lane exchange, stream stalls,
  and delayed state persistence.
- `make synth-slh-dsa synth-xmss synth-lms`: post-synthesis candidate screening.
- Route only retained candidates with `experiments/route_unified_hbs.tcl`.

See `Unified_HBS_ABI.md` for the executable image contract and ATP formula.
The old `uhbs_stateless_hbs`/`uhbs_stateful_hbs` implementations and their
standalone benches were removed from the working tree. Git history preserves
them; `manifests/unified_sources.txt` is the current synthesis source list.
