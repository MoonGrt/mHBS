# HBS typed instructions, CHAIN and TREE ABI 4 (`hbs_micro64`)

ABI 4 encodes bounded HBS operations, a single-chain CHAIN and a complete
single-tree TREE on named, independently implemented state.
There are no scalar register numbers, arbitrary field copies, integer ALU,
indirect branches, byte RAM, runtime calls or interrupts. The default image organizes FORS GROUPs, hypertree LAYERs, digest preparation
and final verification. TREE owns one tree, including leaf/chain traversal,
merges and signature node streams. CHAIN remains a single-chain primitive.
The production core is fixed at K1U1: one physical Hash lane and one Keccak
round per cycle. L0/L1 remain logical context/result slots, not physical lanes.
Every HASH must select exactly one logical slot (effective mask 1 or 2) and
authorizes exactly one complete Hash. CHAIN selects one logical slot and
authorizes the bounded sequence below. Mask 0 or 3 faults before any request
is committed; the hardware never serializes a two-slot request automatically.

## Image format

`program.mem` has 512 unsigned 64-bit words, with one-cycle synchronous read;
`descriptor.mem` has 32 words and asynchronous read. Both use 16 hexadecimal
digits per line. Padding words are zero and illegal to execute. There is no
template. The descriptor layout is unchanged except for ABI=4:

| Word | Contents |
|---|---|
| 0 | magic `0x48425350` [63:32], ABI=4 [31:27], Keygen [26:18], Sign [17:9], Verify [8:0] |
| 1 | profile code 0/1/2/4/5/6 |
| 2…11 | recipe shape[59:56], domain[55:48], arity[47:40], output bytes[37:32], rate-block bound[29:24]; other bits zero |
| 12 | actual instruction count, 1…512 |
| 13 | Keygen bytes[31:0], Sign bytes[63:32] |
| 14 | bytes from low to high: n, hp, d, k, a, m, h, WOTS chains |
| 15…31 | zero |

Instructions use `opcode[63:56], d[55:48], a[47:40], b[39:32], imm[31:0]`.
Each opcode assigns private meanings to these fields. Unused fields must be
zero. Enum values below are decimal; branch targets are absolute 9-bit PCs.
The authoritative permission table is `model/microcode.py`; its generated
`rtl/executor/instructions.svh` is checked against the Python source.

## Named state

| Field | Bits | Allowed updates |
|---|---:|---|
| LAYER | 5 | first/top initialization and increment to d terminator |
| TREE | 64 | H_msg parse; profile-hp leaf extraction and right shift |
| LEAF | 10 | H_msg parse or TREE_NEXT |
| GROUP | 6 | zero and increment to k terminator |
| TARGET | 14 | FORS digest selection or current LEAF |
| CURSOR | 15 | zero, +1/+2 through `2^HEIGHT` terminator |
| CHAIN | 7 | zero, +1/+2; last pair may terminate at chains+1 |
| STEP[2], DIGIT[2] | 4 each | lane-selected initialization, increment or digit load |
| HEIGHT, LEVEL | 4 each | profile/literal height; level zero/increment |
| INDEX, PATH | 14 each | bounded node initialization and one-parent shift |
| FORS_BASE | 20 | GROUP-derived base and one-parent shift |
| MASK | 2 | fixed lanes, valid pair, unfinished suffix or prefix |
| REDUCE_INDEX, REDUCE_SPAN | 7 each | bounded LIST reduction index and span |
| ADRS leaf/a/b, per lane | 10/7/32 | fixed address constructors |
| ROOT_EQUAL | 1 | current root/public root comparison only |

All updates check range before commit. No arithmetic wraps silently. Metadata
state resets to zero; a separate validity flag protects loaded digits and
Verify root comparisons. Writing either compared root invalidates the latter.
TREE remains 64 bits throughout serialization and extraction.

## Instruction table

`lane` is CURRENT=0 (retained MASK), L0=1 (MASK intersect lane0), or L1=2
(MASK intersect lane1). A selector does not itself change MASK. `node` and
`space` are fixed objects described below.

| Op | Name | Private operands and effect |
|---:|---|---|
| 0 | INVALID | fault; also program padding |
| 1 | LAYER_INIT | d=FIRST(0)/TOP(1); LAYER=0/d−1 |
| 2 | LAYER_NEXT | increment LAYER once, including d terminator |
| 3 | TREE_NEXT | LEAF=TREE low hp bits; TREE=TREE>>hp |
| 4 | GROUP_INIT | GROUP=0 |
| 5 | GROUP_NEXT | increment GROUP once, including k terminator |
| 6 | CURSOR_INIT | CURSOR=0 |
| 7 | CURSOR_NEXT | imm=1/2; increment within height bound |
| 8 | CHAIN_INIT | CHAIN=0; invalidate lane digits |
| 9 | CHAIN_NEXT | imm=1/2; advance chain/pair, invalidate lane digits |
| 10 | HEIGHT | d=HT(0)/FORS(1)/LITERAL(2); HEIGHT=hp/a/imm; literal 1…4 |
| 11 | TARGET | d=FORS(0)/LEAF(1); read GROUP's digest target/current leaf |
| 12 | DIGITS | compute base16 digits and checksum from V2 |
| 13 | DIGIT_LOAD | d=lane; load digit[CHAIN+lane] into selected DIGIT fields |
| 14 | STEP_INIT | d=lane, a=ZERO(0)/DIGIT(1); initialize selected STEP |
| 15 | STEP_NEXT | d=lane; increment selected STEP once; 15 cannot increment |
| 16 | MASK | d=FIXED(0)/PAIR(1)/SUFFIX(2)/PREFIX(3); fixed imm=0…3, other imm=0 |
| 17 | NODE_BEGIN | d=CURSOR(0)/TARGET(1)/LEAF(2)/IMMEDIATE(3), a=HT(0)/FORS(1); LEVEL=0, INDEX=source, PATH=TARGET, FORS_BASE=0/GROUP<<a_profile; immediate 0…16383 |
| 18 | NODE_PARENT | LEVEL++; INDEX>>=1, PATH>>=1, FORS_BASE>>=1; no node access |
| 19 | LEVEL_INIT | LEVEL=0 |
| 20 | LEVEL_NEXT | increment LEVEL once through HEIGHT terminator |
| 21 | ADRS | d=address constructor, a=variant where allowed; no Hash |
| 22 | REDUCE_INIT | d=HT(0)/FORS(1); SPAN=2^HEIGHT≤68, INDEX=0, LEVEL=0, base=0/GROUP<<a_profile |
| 23 | REDUCE_NEXT | d=INDEX(0): index++; LEVEL(1): span>>=1, index=0, LEVEL++, base>>=1 |
| 24 | PARSE | extract TREE/LEAF from persistent H_msg |
| 25 | NMOV | node[d]=node[a] |
| 26 | LOAD | node[d]=space[a][typed_index(b,imm)] |
| 27 | STORE | space[d][typed_index(b,imm)]=node[a] |
| 28 | HASH | recipe descriptor[d], a=lane; effective mask must be 1 or 2 |
| 29 | WAIT | wait for all active results and atomically publish L0/L1 |
| 30 | INPUT | d=writable node; consume one Verify node |
| 31 | EMIT | a=node; emit low n bytes for Keygen/Sign |
| 32 | ROOT_COMPARE | compare current root V2 with public root V3; Verify only |
| 33 | END | finish; Verify returns valid ROOT_EQUAL |
| 34 | JMP | imm=absolute PC |
| 35 | BR | d=condition, a=lane 0/1 only for lane conditions, b=invert 0/1, imm=absolute PC; branch when predicate != invert |
| 36 | CHAIN | d=mode 0…3, a=lane selector, b=CURSOR(0)/LEAF(1), imm=0; blocking single WOTS chain |
| 37 | TREE | d=HT(0)/FORS(1), a=ROOT(0)/SIGN(1)/VERIFY(2), b=flags 0/1, imm=0; complete blocking tree |

PAIR includes only chains below the profile's chain count. SUFFIX additionally
requires STEP<15; PREFIX requires STEP<DIGIT. A completed Verify lane retains
STEP=15 and its node while the other lane continues. The ordinary metadata
operations contain no implicit loop, Hash launch, leaf traversal or tree merge.

## Blocking single-chain macro

CHAIN keeps the current instruction pending until one WOTS chain completes.
It cannot execute while a HASH is pending and does not require a following
WAIT. The image still advances CHAIN, stores endpoints, emits signatures,
traverses leaves, selects authentication nodes and merges trees.

| d | Mode | Hashes | Capture/result |
|---|---|---|---|
| 0 | FULL | PRF then F steps 0…14 | L result is the endpoint; CAP unchanged |
| 1 | CAP_FULL | PRF then F steps 0…14 | Capture digit position and return endpoint |
| 2 | CAP_PREFIX | PRF then F steps 0…digit−1 | Capture and return the digit node |
| 3 | SUFFIX | Existing L node, F steps digit…14 | Return endpoint; no PRF or capture |

Lane selection uses the same CURRENT/L0/L1 selectors as HASH and must yield
exactly one active logical slot. Its chain number is CHAIN+slot, checked before
narrowing. CURSOR must be below 1024 when used as the leaf. FULL needs no digit;
the other modes snapshot the selected chain's valid DIGIT. CAP0 belongs to L0,
CAP1 to L1. INPUT remains an image instruction before SUFFIX.

Recipes 7 and 8 are the fixed WOTS PRF/F pair: ADDRESS_SEED/domain5/arity1/out=n
and ADDRESS_VALUE/domain0/arity1/out=n. Both are validated and latched before
the first Hash. Layer, full TREE, leaf, chain, mode and digit are also captured.
Internal requests advance only the private Hash-step address. Architectural
ADRS, CHAIN and tree state are unchanged.

Digit zero captures the PRF output; CAP_PREFIX with digit zero still hashes
once. SUFFIX with digit15 performs no Hash and preserves L/CAP. On success the
selected STEP becomes digit for CAP_PREFIX, otherwise15. Only the selected L,
optional corresponding CAP and STEP are committed; inactive slots retain data.

The image is blocked during the macro. Intermediate captures use private RAM
word123 and an independent valid bit, outside the ISA-visible spaces. Feedback
reuses the retained sponge digest; its F input frame selects exactly n bytes. At successful completion
L and CAP commit over the existing single write port, then the instruction
retires. Commit launches no Hash and performs no fallible checks. A failed macro
leaves architectural nodes/STEP unchanged; physical Hash/Keccak counters may
include work already executed. Reset cancels the macro and invalidates shadow
data. Every internal Hash remains visible in the trace with macro ownership.

## Address constructors

ADRS changes the per-lane leaf/a/b fields; domain still comes from the recipe.
Layer and full TREE are captured separately by HASH.

| d | Constructor | Address values |
|---:|---|---|
| 0 | WOTS_CURSOR | leaf=CURSOR, a=CHAIN+lane, b=STEP[lane] |
| 1 | WOTS_LEAF | leaf=LEAF, a=CHAIN+lane, b=STEP[lane] |
| 2 | FORS_CURSOR | leaf=LEAF, a=0, b=(GROUP<<a_profile)+CURSOR+lane |
| 3 | FORS_TARGET | leaf=LEAF, a=0, b=(GROUP<<a_profile)+TARGET |
| 4 | FORS_NODE | leaf=LEAF, a=LEVEL, b=FORS_BASE+INDEX |
| 5 | HT_NODE | leaf=0, a=LEVEL, b=INDEX |
| 6 | WOTS_LIST | a variant CURSOR(0)/LEAF(1); address leaf from variant; address a/b=0 |
| 7 | FORS_LIST | leaf=LEAF, address a/b=0 |
| 8 | REDUCE_NODE | a variant HT(0)/FORS(1); leaf=0/LEAF, address a=LEVEL, b=REDUCE_INDEX+(0/FORS_BASE) |

Except WOTS_CURSOR and FORS_CURSOR, both lane address values are identical
unless a constructor explicitly uses lane. Inactive lane address fields may
refer to the unused member of an odd chain pair; only active requests execute.

## Branch conditions

| d | Condition | Predicate |
|---:|---|---|
| 0 | CURSOR_MORE | CURSOR < 2^HEIGHT |
| 1 | CHAIN_MORE | CHAIN < profile chains |
| 2 | GROUP_MORE | GROUP < k |
| 3 | LAYER_MORE | LAYER < d_profile |
| 4 | FINAL_LAYER | LAYER+1 == d_profile |
| 5 | LEVEL_MORE | LEVEL < HEIGHT |
| 6 | TARGET_LEAF | CURSOR == TARGET |
| 7 | INDEX_ODD | INDEX bit0 |
| 8 | AUTH_MATCH | INDEX == (PATH xor 1) |
| 9 | SAME_PARENT | INDEX>>1 == PATH>>1 |
| 10 | STEP_EQ_DIGIT | selected lane STEP == valid DIGIT |
| 11 | STEP_MORE | selected lane STEP < 15 |
| 12 | LANE_ENABLED | MASK[selected lane] |
| 13 | MASK_ZERO | MASK == 0 |
| 14 | FORS_PAIR_TARGET | CURSOR == (TARGET with bit0 cleared) |
| 15 | REDUCE_MORE | REDUCE_INDEX < REDUCE_SPAN |
| 16 | REDUCE_AGAIN | REDUCE_SPAN > 1 |
| 17 | ROOT_EQUAL | valid comparison result |

## Fixed node objects and storage

Node IDs are V0=0 (R), V1=1, V2=2 (current message/root), V3=3 (public
root), L0=4, L1=5, RIGHT=6, CAP0=7, CAP1=8, NODE=9, TMPNODE=10,
SECRET=11, PRF=12, PUBLIC=13, RANDOM=14, ZERO=15. Nodes11…15 are
read-only Job/constant sources; V3 initially contains the supplied public
root. Other writable nodes reset to zero. Nodes are 256 bits, low n bytes
valid, with high input bytes ignored/zeroed.

Spaces are LIST=0 (68 nodes), STACK=1 (16), AUTH=2 (16). The private index
selector b is LEVEL=0, CHAIN0=1, CHAIN1=2, GROUP=3, CURSOR=4,
REDUCE_LEFT=5, REDUCE_RIGHT=6, REDUCE_OUT=7, IMMEDIATE=8. The reduce selectors
mean 2×index, 2×index+1 and index. LIST accepts selectors1…8; STACK and AUTH
accept only LEVEL. imm must be zero except IMMEDIATE, whose permitted LIST
range is 0…67. Dynamic addresses are checked before reads or writes.

## Hash groups, stability and failures

HASH snapshots recipe, the one-hot mask, LAYER, TREE and the selected slot ADRS. Its node sources
are L0/L1 and RIGHT (lane0 only). List compression reads LIST on lane0.
Logical lane1 supports ADDRESS_SEED and single-node ADDRESS_VALUE only.
The single physical lane completes one full Hash, including multi-block absorption,
padding and Keccak. MESSAGE_DIGEST saves its full result in a separate persistent
49-byte H_msg register at WAIT; other hashes leave that register unchanged.
Inactive lane results stay unchanged.

Exactly one group may be outstanding. Between HASH and WAIT the allowed
operations are LAYER/GROUP/CURSOR/CHAIN updates, HEIGHT, STEP updates, MASK,
NODE_BEGIN/PARENT, LEVEL updates, ADRS, REDUCE updates and direct branches.
TARGET, PARSE, DIGITS, DIGIT_LOAD, node/storage access, I/O, ROOT_COMPARE,
END, CHAIN, TREE and another HASH require WAIT first. The compiler's access sets drive
bounded metadata overlap scheduling without numeric opcode-range assumptions.
WAIT without HASH faults. The physical lane retains its response until WAIT
publishes it to the selected logical result slot. The other slot is unchanged.

GROUP_INIT and GROUP_NEXT also maintain a private 9-bit FORS digest offset
equal to GROUP times the profile a. Its terminal value may be 320; an update
above 320 faults atomically. This redundant context removes multiplication
from TARGET without adding an instruction, loop, node access or Hash launch.

Instruction permissions are checked before execution. An invalid encoding,
reserved bit, forbidden space/index combination, stale digit/root comparison,
range violation or pending-group hazard cancels the operation without committing
that instruction's context/node/I/O updates. Reset clears the halted condition.
Header ABI1/2 is rejected by the wrapper; the new core has no legacy execution
mode. Program capacity and static branch/HASH-WAIT control flow are validated
offline; the RTL checks each executing instruction rather than scanning ROM.

WOTS digits use each message byte's high nibble then low nibble, followed by
three checksum nibbles, most significant first. PARSE uses the FIPS205 FORS,
tree and leaf byte splits with big-endian tree/leaf masks. TARGET selects
MSB-first FORS digest slices of profile width a. These transforms do not hash.

Message and node stream protocols are unchanged. Sign/Verify buffer 1…87
message bytes before entry execution; Keygen takes no message. Truncated Verify
input waits for a node or reset. Synchronous branches flush the single prefetch
and obsolete ROM responses; reset and END also discard fetch state.

## Blocking complete-tree macro

`TREE(kind, mode, flags=0)` uses the fields in opcode37 above. FORS/ROOT is
reserved. Mode must equal the Job operation. Only bit0 TOP_SHORTCUT is defined;
it is legal only for HT/SIGN at the final layer. Other bits and imm are zero.
TREE cannot overlap an outstanding HASH or another top-level macro. It freezes
the current instruction, waits internally, and retires exactly once; no WAIT follows.

| kind/mode | Work and node stream |
|---|---|
| HT/ROOT | Generate WOTS leaves in leaf/chain order and return the root; no output |
| HT/SIGN | Generate the tree; emit selected WOTS nodes in chain order, then AUTH from height0 upwards |
| HT/VERIFY | Read chains WOTS nodes followed by hp siblings; restore the actual root |
| FORS/SIGN | Generate the current GROUP tree; emit secret then a siblings |
| FORS/VERIFY | Read one secret then a siblings; restore the current GROUP root |

The image prepares TARGET and, for HT SIGN/VERIFY, immutable DIGITS. Height,
profile, target and full address context are snapshotted. Before Hash or I/O,
all required recipes are validated: HT7…10, FORS SIGN4…6, FORS VERIFY5/6.
Shape/domain/arity/output/reserved bits must match and block capacity must cover
the corresponding fixed or list frame. Child chains reuse the validated snapshot.

HT uses LIST endpoints and stack reduction; FORS keeps the paired PRF0, PRF1,
F0, F1 and first-parent schedule. It preserves LIST so outer FORS roots survive.
The fixed TREE-to-CHAIN return has no runtime call stack or programmable target.
A child-chain completion neither retires an instruction nor advances the PC.

Normal success returns the computed root in L0. TOP_SHORTCUT preserves signature
bytes and skips the selected leaf compression and ancestors; it returns V3 as
an external root and never claims to have computed that root. VERIFY forbids it.

LAYER/TREE64/LEAF/GROUP/TARGET, V0…V3, H_msg and global DIGITS remain unchanged.
Work metadata and ADRS clear to zero; MASK becomes1. L1/RIGHT/CAP0/CAP1/NODE/
TMPNODE become invalid and read zero. STACK/AUTH are scratch; HT may overwrite
LIST. A later explicit operation must initialize any required work context.

Input ready is asserted only for a needed node; stalls wait without accepting
extra nodes or generating faults. Outputs use the existing non-backpressured
node stream. Preflight failure causes no workspace/Hash/I/O effects. A later
failure aborts the whole Job: workspace and partial I/O may already have changed,
but no further work or completion is allowed, and the signature cache is invalid.
The consumer discards partial output and resets before replay. A cryptographic
root mismatch is reported by the image's final ROOT_COMPARE, not a TREE fault.

Trace ownership is HASH, standalone CHAIN or TREE. TREE records include instance,
leaf, chain, phase, step and level. TREE busy cycles include its children and must
not be added to child busy cycles; standalone CHAIN counters exclude TREE children.

## XMSS／LMS 加法扩展（ABI号不变）

opcode38 `XMSS_MASK d=0/1`：将NODE/TMPNODE与RIGHT中的MASK摘要异或，结果写入L0，仅XMSS且结果有效时允许，其他字段零；不发Hash、不推进链步。CHAIN36四种模式沿用，按family选择SLH、XMSS或LMS标准前像；TREE37仅在ABI4分支存在，stateful仅HT且不得TOP_SHORTCUT。

XMSS专用ADRS9/10选择L-tree cursor/leaf；cond18/19处理归约跨度/奇数尾项；REDUCE_INIT/NEXT选择器2执行L-tree的ceil(span/2)层推进。stateful允许20位叶/target/index/path、21位cursor、5位height/level及32位ADRS B。SLH与LMS不得借这些选择器访问XMSS权限，原SLH逻辑STACK/AUTH限制仍为16/16。
