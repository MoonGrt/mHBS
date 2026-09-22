# Unified HBS image ABI 3

The interpreter in `model/unified_hbs.py` is the executable specification.
Images contain only immutable scheduling and recipe data. Fixed demonstration
jobs are separate from microcode. ABI 1/2 images are not accepted by this core.

## Storage and execution

128-bit SINGLE/RUN/LOOP/HALT tokens retain the existing token encoding and
two-level affine loop stack. 128-bit templates contain one exclusive 48-bit
macro command and event-zero dependency fields. A macro command is
`opcode:4 | descriptor:8 | route:8 | flags:4 | coordinate:24`.
Coordinates retain layer at 23:19 and group at 18:13.

All descriptors are 64-bit with kind in 63:60. Kinds are HASH=1, SEGMENT=2,
CHAIN=4, TREE=5, ROUTE=6, TRANSFORM=8, EMIT=9, IMAGE=10, PROFILE=11.
Descriptor zero contains version 3 at 59:56, Keygen entry at 55:47, Sign entry
at 46:38, Keygen output bytes at 35:18, and Sign output bytes at 17:0.
Descriptor one contains stateful at bit 59, n at 55:48, tree height at 43:40,
and maximum message bytes at 31:24.

| Descriptor | Fields (most significant first) |
|---|---|
| HASH | shape 59:56, domain 55:48, arity 47:40, output bytes 37:32, max rate blocks 28:24 |
| CHAIN | seed recipe 59:52, step recipe 51:44, reduction recipe 43:36, leaf recipe 35:28, chain count 27:20, steps 19:15, reduction mode 13:12 |
| TREE | chain 59:52, parent recipe 51:44, height 43:40, target source 37:36, indexing 33:32, cache build 31, cache lookup 30, full cache 29 |
| ROUTE | value slot 57:56, emit 55, digest parsing 54, group-indexed root store 53 |
| TRANSFORM | operation 59:56, value source 49:48, index shift 43:40 |
| EMIT | first segment 59:52, segment count 51:48 |
| SEGMENT | source 59:56, byte count 55:48, constant 31:0 |

CHAIN performs seed, bounded feedback, optional capture, then optional list
or odd-promotion binary reduction and leaf hashing. TREE uses that same CHAIN
iterator to generate leaves, reduce levels, capture authentication nodes and
optionally retain the complete tree. Cache lookup uses the same TREE opcode
with a descriptor flag. Full-cache mode is a software verification option;
the current production RTL rejects TREE bit 29. Macro flags are capture=1, auth=2, signature-only=4,
external-root=8. No legacy TREE_PUSH meaning is retained under version 3.

The single-sign demonstration images retain only the authentication path for
the fixed initial q plus the root during Keygen. They still hash the complete
tree. This eliminates the full 2047-node cache; another q requires rebuilding
its path. The software full-cache option also checks q=0/1023 and consecutive
signatures. This storage difference from the paper is disclosed in ATP tables.

The fifteen recipe shapes specify input concatenation and compound masked
hashing, independently of algorithm names. Their enum and byte constructions
are defined in `Shape` and `Machine.hash_recipe`. Memory and stream byte zero
is the least significant byte; serialized integer fields are big endian.

## Verification and measurement

Before RTL changes, `python3 -m unittest tests.test_unified_hbs -v` executes
all three Keygen/Sign images, checks KAT bytes and permutation counts, varied
messages, q=0/1023/exhaustion, commit rejection and post-commit failure.
`scripts/compile_unified_hbs.py` exports images and vectors only after checking
their full results, and records the model digest and counts in its manifest.

Use Icarus Verilog for small units and Verilator 5.008 `--binary --timing`
for complete algorithms. Candidate area is first measured after synthesis.
The screening score is equivalent Slice multiplied by simulated Sign cycles
at a common 100 MHz normalization; synthesis timing is reported separately.
Only selected candidates proceed to route. Final ATP uses post-route area
and a clock frequency with nonnegative WNS and zero TNS.

Equivalent Slice = LUT/4 + FF/8 + (RAMB36 + RAMB18/2)*232.4 + DSP*102.4.
The numerical Sign ATP targets are 57360.476 (SLH), 1506.437 (XMSS), and
579.399 (LMS), in Slice.ms. These are rounded-paper-time targets and are
non-strict external comparisons, not same-workload superiority claims.
