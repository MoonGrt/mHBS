# Software CHAIN image layout 5

This experimental branch starts from the verified C1 image-chain implementation.
It preserves the compound Hash recipes and moves all CHAIN control into the
program. One K1U1 Hash lane executes one request at a time. SHAKE is the default;
`MHBS_SHA2` selects SHA256 recipes. Layout 5 is independent of HashFlow ABI5.

## ROM and task templates

ROM capacities are 256×64 program, 32×64 template and 32×64 descriptor. Program
PC is eight bits and template address is five bits. Both backends retain main's
recipe, profile and output-size fields. Descriptor 1 bit 5 is the backend marker.
Descriptor 0 contains:

| Bits | Field |
|---|---|
| 17:0 | Sign output byte count |
| 35:18 | Keygen output byte count |
| 42:36 | Keygen entry PC |
| 49:43 | Sign entry PC |
| 56:50 | Verify entry PC |
| 63:57 | Required layout marker `0x54` |

The three seven-bit entry fields point to fixed trampolines at PCs 0, 1 and 2.
Each trampoline jumps to an eight-bit actual entry. Sign and Verify may share
actual code; operation is a read-only context source.
The template low 17 bits preserve main's encoding: op [2:0], recipe/macro
descriptor [7:3], route [12:8], CAPTURE [13], AUTH [14], EXTERNAL_ROOT [15],
SIGN_ONLY [16]. HASH=1, TRANSFORM=4, EMIT=5. CHAIN=2 and TREE=3 are rejected.
Old layout markers are rejected at Job startup.

A macro token retains main's fields: kind [63:62], template low four bits
[61:58], coordinate [57:47], repeat [46:41], stride [40:30]. Template bit 4
uses token bit 29. Bit 28 KEEP_COORD means use the software LAYER/GROUP
contexts. Bits 27:0 are reserved zero. The compiler emits SINGLE macro tokens. RUN repeats and the original two-level
counted LOOP remain supported; software tree loops use explicit BR instructions. A task cannot retire before its single macro
completes.

The compiler emits shared software routines for chains and reduction. A HASH
issues one existing recipe and never advances A (chain index), B (step), or the
next chain automatically. Digit-zero capture and digit-fifteen zero-step Verify
are explicit branches. XMSS L-tree handles odd tails with LOAD/STORE and no Hash;
LMS issues its list and leaf recipes explicitly. Stateful Sign retains the C1
standalone signature chains followed by cold full-tree recomputation.

## Explicit control words

Control tokens have kind [63:62]=3 and the following fields:

| Bits | Field |
|---|---|
| 61:57 | Control opcode |
| 56:52 | dst |
| 51:47 | src |
| 46:42 | aux |
| 41:21 | unsigned immediate |
| 20:13 | absolute branch/call target PC |
| 12:9 | condition |
| 8:0 | reserved zero |

| Opcode | Instruction | One retirement performs |
|---:|---|---|
| 0 | HALT | Complete the Job; all remaining fields must be zero |
| 1 | SET | narrow[dst] = immediate |
| 2 | MOV | narrow[dst] = narrow[src] |
| 3 | INC | narrow[dst] += 1 |
| 4 | SHR | narrow[dst] >>= immediate; shift 1..20 |
| 5 | XOR1 | narrow[dst] ^= 1 |
| 6 | ADD | narrow[dst] = narrow[src] + narrow[aux] |
| 7 | BR | Branch to target if condition succeeds |
| 8 | CALL | Save PC+1 and jump; a third outstanding CALL faults |
| 9 | RET | Pop one of two saved PCs; an empty return stack faults |
| 10 | LOAD | wide[dst] = RAM[narrow[src]+immediate] |
| 11 | STORE | RAM[narrow[dst]+immediate] = wide[src] |
| 12 | INPUT | Accept one Verify node into wide[dst] |
| 13 | OUTPUT | Emit one n-byte node from wide[src] |
| 14 | WMOV | wide[dst] = wide[src] |
| 15 | SHL | narrow[dst] <<= immediate; shift 1..20 |

No control instruction issues a hash, iterates a chain, walks a tree or captures
an authentication path automatically. HASH, TRANSFORM and EMIT are the only task templates.

BR conditions are ALWAYS=0, EQ=1, NE=2, LT=3, GE=4, ODD=5, ZERO=6,
BITSET=7, SIBLING=8, SAME_PARENT=9. With aux=0, compare narrow[dst] and
narrow[src]; aux=1 selects the immediate as the right operand. BITSET tests
`narrow[dst] & immediate`; SIBLING means `dst == (src ^ 1)` and SAME_PARENT
means `(dst >> 1) == (src >> 1)`. The latter two require register operands.

## Contexts and storage

| ID | Context | Width |
|---:|---|---:|
| 0 | LEAF / formatter leaf | 20 |
| 1 | A / formatter chain or height | 8 |
| 2 | B / formatter step or node address | 21 |
| 3 | CURSOR | 21 |
| 4 | INDEX | 21 |
| 5 | LEVEL | 5 |
| 6 | TARGET | 21 |
| 7 | PATH | 21 |
| 8 | BASE | 21 |
| 9 | HEIGHT | 5 |
| 10 | LIMIT | 21 |
| 11 | LAYER | 5 |
| 12 | GROUP | 6 |
| 13 | AUTH_LEVEL | 5 |
| 14 | FLAGS | 4 |
| 15 | MODE: ordinary=0, FORS=1, LMS heap=2 | 2 |
| 16 | Job q (read only) | 20 |
| 17 | parsed scalar leaf (read only) | 20 |
| 18 | current GROUP's FORS target (read only) | 14 maximum |
| 19 | profile height (read only) | 5 |
| 20 / 21 | ZERO / ONE (read only) | 1 |
| 22 | operation 0/1/2 (read only) | 2 |
| 23 / 24 | XMSS / STATEFUL (read only) | 1 |
| 25 | current A-indexed DIGIT (read only) | 4 |
| 26 | LT_COUNT | 8 |
| 27 | LT_CURSOR | 8 |
| 28 | LT_LEVEL | 4 |

Arithmetic overflow and writes to read-only selectors fault. HEIGHT, LEVEL and
AUTH_LEVEL are limited to 20; MODE is limited to 2. The contexts reuse narrow
main datapath registers, rather than a general-purpose CPU register file.

Wide selectors are NODE=0, LEFT=1, V0/V1/V2/V3=2/3/4/5, EMIT=6,
ZERO=7 (read only). HASH reads LEFT and NODE as binary operands, leaves its
result in LEFT and applies its main route. Software explicitly copies the
parent result into NODE. Only the H_msg recipe owns the full digest tail;
ordinary node writes do not overwrite it.

The shared workspace retains 128 physical 256-bit entries. Explicit control
access is restricted to addresses 0..107: LIST 0..67, STACK 68..87, AUTH
88..107. Addresses 108..127 remain reserved. A RAM instruction performs exactly
one access through the existing port; bounds are checked before a write.

The compiler's shared tree subroutine explicitly generates each leaf, compares
node coordinates, saves authentication nodes, pushes/loads the stack, issues
one parent HASH, updates height/index/path/base and branches. It emits saved
authentication nodes in order. There is no TREE template or TREE_STEP command.

## Generated images and verification

`compile_image(...).usage` reports allocated and effective program, template and
descriptor records. Capacities are checked before padding; overflow raises an
error. Descriptor usage includes meaningful zero-valued identity records.
CHAIN and TREE template counts must both be zero for every generated image.

`ControlMachine` executes the physical program, including software chain loops,
captures and reduction. It uses the existing compound Hash recipes, and does
not invoke the legacy CHAIN or TREE interpreter. Ordinary list HASH obtains its
node count from descriptor arity. Output, signature cache, Hash/block counts
and primitive preimage/result fingerprints are compared with frozen C1 inputs.
High stateful trees only execute real-height Verify; full h15/h16/h20 Keygen and
Sign are excluded from this experiment. Cycle and area measurements are bound
to frozen source identities in the experiment archive.
