# XMSS/LMS Stateful Microcode Extension

## Implemented products

The stateful extension supplies two separately synthesized product wrappers
over the same dual-lane execution core:

- `micro_hbs_horizontal_xmss_top`: RFC 8391
  `XMSS-SHAKE256_10_256` (`h=10`, `w=16`, `len=67`).
- `micro_hbs_horizontal_lms_top`: RFC 8554-shaped `h=10`, `w=4`,
  `len=67` research profile in which every SHA-256 invocation is replaced by
  SHAKE256/256.  This profile is deliberately not described as RFC 8554
  interoperable.  Its private LMS and LMOTS typecodes are `0x80000006` and
  `0x80000003`.

Each image has two immutable entry points read from the image header rather
than fixed in RTL.  Both use the public `HASH`, `CHAIN`, `TREE_PUSH`,
`TRANSFORM`, and
`EMIT` macro vocabulary and the common `SINGLE/RUN/LOOP/HALT` token
sequencer.  Algorithm and key material are not runtime-writable microcode.

The two physical Keccak lanes instantiate exactly the same
`micro_hbs_stateful_recipe_lane` module.  A build-time lane-swap parameter is
used only for verification.  The recipe lane supports 256-bit results, up to
16 SHAKE rate blocks, local chain feedback, and streamed 2166-byte endpoint
lists.  Fixed-format single-block recipes use a pre-padded fast-block path;
variable messages and long lists retain the 128-bit streaming composer.

The dispatcher owns every immutable job/descriptor field until a batch has
completed.  Recipe lanes therefore reference those stable registers directly
and only retain feedback, mask, key and compound-stage state locally.  This
removes two redundant copies of the message, seeds and lane descriptors while
preserving physical-lane equivalence.

## Stateful contract

Keygen builds a complete `2047 x 256-bit` height-10 tree cache and marks it
valid only after all nodes and the root have committed.  A new build or an
error invalidates the cache without resetting its BRAM contents.  Sign reads
ten cached authentication nodes and does not reconstruct the tree.

Before a Sign emits any byte, the core asserts `state_commit_valid` with
`state_next_q`.  Computation and output remain blocked until
`state_commit_ready` is accepted.  Acceptance consumes the leaf permanently
inside the live session; later failure never restores the old index.  The
external system must make this transition durable before acknowledging it.

Output is streamed in little-endian 64-bit beats.  `out_keep` identifies the
four valid bytes in the final partial beat for the 196-, 2500-, 140-, and
2508-byte products.

## Static image sizes

Both products use thirteen 128-bit tokens, nine 128-bit command templates and a
64-entry 64-bit descriptor image.  The images encode the following operation
programs:

```text
Keygen: TREE_PUSH(init)
        -> LOOP[1024](CHAIN(leaf endpoints) -> TREE_PUSH(node))
        -> EMIT(SK || PK) -> HALT
Sign:   HASH(message) -> TRANSFORM(base-w/checksum)
        -> CHAIN(67 endpoints) -> TREE_PUSH(read auth path)
        -> EMIT(signature) -> HALT
```

The two nested affine LOOP tokens expand Keygen to 2,051 macro operations.
Recipe roles, constant-table base, output layout, and operation entries come
from the static descriptor image.  The RTL has no XMSS/LMS profile parameter;
replacing the immutable image and re-synthesizing selects the product.
`TREE_PUSH` has two reducer contexts and implements odd-node promotion,
authentication capture, and optional cache writes without an algorithm-named
opcode.

## Frozen functional results

The test vectors are generated from independent Python models and stored as
byte memories.  The full RTL test performs Keygen followed by Sign at `q=5`
and a second Sign at `q=6`, compares every output byte, and checks the exact logical operation counts.

| Product | Operation | Hash contexts | Keccak permutations | RTL cycles |
|---|---:|---:|---:|---:|
| XMSS | Keygen | 3,430,396 | 3,430,396 | 25,475,275 |
| XMSS | Sign, q=5 | 1,554 | 1,555 | 17,177 |
| XMSS | Sign, q=6 | 1,689 | 1,690 | message-dependent |
| LMS-SHAKE research | Keygen | 1,100,799 | 1,116,159 | 8,202,421 |
| LMS-SHAKE research | Sign, q=5 | 548 | 548 | 7,906 |
| LMS-SHAKE research | Sign, q=6 | 548 | 548 | message-dependent |

These cycle figures use `UNROLL=2` and `out_ready=1`.  The article numbers
remain comparison targets, not correctness gates.  The retained SLH-DSA
product uses its independent core and therefore is not structurally changed
by this extension.

## Post-synthesis PPA

The retained candidate was synthesized out of context for
`xc7a200tffg1156-3` with `UNROLL=2` and profiling disabled.  Equivalent Slice
uses the project/article conversion
`LUT/4 + FF/8 + RAMB36-equivalent*232.4`; one RAMB18 counts as half a RAMB36.

| Static image | LUT | FF | LUTRAM | RAMB36 | RAMB18 | DSP | Equivalent Slice | post-synth WNS |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| XMSS | 37,915 | 14,471 | 950 | 14 | 1 | 0 | 14,657.43 | -7.266 ns |
| LMS-SHAKE | 33,733 | 13,975 | 950 | 14 | 1 | 0 | 13,549.93 | -7.266 ns |

Relative to the previous retained XMSS build
(`39,468 LUT / 19,234 FF`), stable request-field forwarding removes 1,553 LUT
and 4,763 FF without changing any operation count or cycle count.  For LMS the
corresponding reduction is 111 LUT and 2,993 FF.

The current candidates do **not** meet the requested `<24,184 LUT`,
`<11,587.98 Equivalent Slice`, XMSS Keygen `<=24M`, or 100 MHz timing gates.
Consequently no post-route run is claimed.  LMS remains just above both its
Keygen (`<=8M`) and Sign (`<=7k`) targets at 8,202,421 and 7,906 cycles.
XMSS Sign meets `<=18k`; XMSS Keygen remains 25,475,275 cycles.

Two post-synthesis ablations were rejected:

- Sharing the 1088-bit fixed-format block builder increased XMSS to
  `39,805 LUT / 19,367 FF` and added one arbitration cycle per paired task.
- Rewriting the sponge register to a single explicit next-state cone produced
  `39,500 LUT / 19,261 FF`, 32 LUT above the previous retained build.

An isolated U2 compact SHAKE lane is 7,670 LUT / 2,191 FF, while one bare
Keccak round is 2,123 LUT.  The remaining area gap is therefore primarily the
fixed-format recipe-to-sponge steering and the second U2 lane, not the token
sequencer (about 200 LUT) or TREE_PUSH reducer (about 0.6--1.0k LUT).

## Current unification boundary

The five macro opcodes and their descriptor-kind numbers are shared across
SLH-DSA, XMSS and LMS.  XMSS/LMS behavior is selected by immutable profile and
recipe descriptors; there is no compile-time `PROFILE==XMSS/LMS` branch and no
literal command-descriptor-ID branch.  The two stateful products also share
one RTL core and differ only in the `.mem` image selected by their wrappers.

The SLH-DSA product still instantiates the older n=16 generic core rather than
the n=32-capable stateful core.  Thus the repository now has a shared ISA and
descriptor ABI, but not yet one physical core implementation for all three
families.  The stateful materializer also still expands the common macros with
43 generic execution states; eliminating that last split requires replacing
the n-specific composer/store interfaces, not merely renaming FSM states.

## Reproduction

```bash
python3 -m unittest tests.test_lms_shake_oracle \
  tests.test_stateful_hbs_macrocode tests.test_xmss_oracle
make rtl-stateful-unit-test
make -j2 VERILATOR_JOBS=12 rtl-xmss-stateful-test rtl-lms-stateful-test
make -j2 VERILATOR_JOBS=12 rtl-xmss-stateful-robustness-test \
  rtl-lms-stateful-robustness-test
make JOBS=24 synth-stateful-xmss
make JOBS=24 synth-stateful-lms
```

The synthesis scripts target `xc7a200tffg1156-3`, cap Vivado at 24 host
threads, and record post-synthesis flat and hierarchical utilization.  Vivado
may internally cap synthesis at fewer workers.
