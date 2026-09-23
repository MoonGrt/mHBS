# Unified HBS image ABI 4

The executable specification is `model/unified_hbs.py`. Seven static profiles
share the same five macro operations and core source. `model/profiles.py`
defines profile names and parameters. Job keys and messages are separate from
images; product wrappers supply fixed Job parameters and expose streaming I/O.

## Image encoding

Tokens and templates remain 128 bits. SINGLE/RUN/LOOP/HALT and the two-level
loop stack retain their existing encoding. Templates contain the exclusive
48-bit macro command `opcode:4 | descriptor:8 | route:8 | flags:4 | coordinate:24`.
Coordinates hold layer at 23:19 and group at 18:13.

Descriptors remain 64 bits, with kind at 63:60. Kinds are HASH=1, SEGMENT=2,
CHAIN=4, TREE=5, ROUTE=6, TRANSFORM=8, EMIT=9, IMAGE=10 and PROFILE=11.
The IMAGE header uses version **4** at 59:56, Keygen entry at 55:47, Sign entry
at 46:38, Keygen output bytes at 35:18 and Sign output bytes at 17:0.
ABI 3 images are rejected by the current core. Historical ABI 3 results are
replayed using the fixed Git revision recorded by the comparison verifier.

| Descriptor | Fields |
|---|---|
| PROFILE | stateful 59; family 58:56 (SLH=1, XMSS=2, LMS=3); n bytes 55:48; omega bits 47:44; subtree height 43:40; FORS a 39:36; message bound 31:24; FORS k 23:18; layers d 17:13; digest bytes m 12:7; total height h 6:0 |
| HASH | shape 59:56; domain 55:48; arity 47:40; output bytes 37:32; maximum rate blocks **29:24** |
| CHAIN | seed recipe 59:52; step recipe 51:44; reduction recipe 43:36; leaf recipe 35:28; chain count 27:20; steps 19:15; reduction mode 13:12 |
| TREE | chain 59:52; parent recipe 51:44; height 43:40; target source 37:36; indexing 33:32; cache build 31; lookup 30; software full cache 29 |
| ROUTE | slot 57:56; emit 55; digest parsing 54; group root store 53 |
| TRANSFORM | operation 59:56; value source 49:48; subtree index shift 43:40 |
| EMIT | segment base 59:52; count 51:48 |
| SEGMENT | source 59:56; byte count 55:48; constant 31:0 |

The interpreter decodes parameters from image words, independently of the
image filename. RTL wrappers supply matching static parameters so synthesis
can remove unused widths, recipes and stateful logic. Digest storage is
34/42/49 bytes for SLH and 32 bytes for XMSS/LMS. Chain endpoint addressing
supports 133 values. The node store is sized for each static profile.

CHAIN performs seed generation, bounded feedback, optional signature capture,
then list hashing or binary L-tree reduction with odd-node promotion. TREE
uses the same chain iterator and a stack. With two physical lanes, FORS generates adjacent leaves concurrently and pushes both through that same stack. Flags are capture=1, auth=2,
signature-only=4 and external-root=8. SLH ADDRESS_LIST domain 4 selects FORS
roots; WOTS public-key compression reads chain endpoints. Source selection
does not depend on coincidental equality of list lengths.

SHAKE256 keeps its 136-byte rate and domain/padding rules. The Keccak
permutation is shared by all node sizes. SLH chain feedback has statically
sized prefixes and captured values for n=16/24/32. n=24 list streaming tracks
its remainder with counters; power-of-two node sizes use constant bit slices.
The 13-bit input offset supports the 4,278-byte, 32-block LMS omega=2 list.

Result chunks transfer directly without a word-packing buffer. `out_keep` marks valid bytes, including short chunks before the final beat.

Byte zero occupies the least significant byte on RTL data paths. Serialized
integer fields remain big endian. omega means bits per Winternitz digit:
omega=2 uses base 4 and 133 chains; omega=4 uses base 16 and 67 chains for n=32.

## Stateful operation

Each production start builds the complete h=10 tree and retains only the
selected initial index's ten authentication nodes and root. One signature
uses that path. Another index requires rebuilding its path. The software
full-cache mode is for verification; production RTL rejects its descriptor bit.
The index guard requires commit acknowledgement before any signature output.
Committed indices remain consumed after an execution failure.

## Reproducible verification

`make compile-microcode` runs independent seven-profile software verification,
seals the input hashes in `manifests/experiments/unified_hbs_v4/software_gate.json`,
then exports ROMs, fixed jobs, expected outputs and boundary vectors. Stale
software gates are rejected before generation.

Use `make rtl-unit-test` for Icarus Verilog 12.0. Full algorithms use Verilator
5.008 with `--binary --timing`, for example:

```sh
make rtl-profile-test PROFILE=slh_192f
make rtl-profile-test PROFILE=xmss_omega2 Q=1023 BACKPRESSURE=1
make rtl-profile-test PROFILE=lms_omega2 LANES=2 SWAP=1 BACKPRESSURE=1
make rtl-all-profiles
```

Simulation records bind complete output comparisons and cycles to the RTL and
ROM hashes. Synthesis and route collection reject mismatched simulation inputs.

## Area and timing acceptance

Screen candidates with `make synth-profile PROFILE=...` at a common 100 MHz
normalization. Report synthesis timing separately. Route selected candidates
with `make route-profile PROFILE=...` on xc7a200tffg1156-3 using Vivado 2025.2.
The accepted frequency is measured on the routed netlist, rounded to 0.1 ns
with at least 0.1 ns setup margin and passing hold/pulse-width/coverage checks.
The timing scope is OOC internal register paths; external pin timing is not
part of the measurement.

Equivalent Slice = LUT/4 + FF/8 + (RAMB36 + RAMB18/2)*232.4 + DSP*102.4.
Final Sign ATP = equivalent Slice * Sign cycles * routed period(ns) / 1e6.
Profile thresholds are recorded in `model/profiles.py`. The three original
profiles additionally must not regress against their archived, unrounded ATP.
All comparisons retain the fixed-input, specialization and algorithm-version
limitations documented in the paper comparison report.
