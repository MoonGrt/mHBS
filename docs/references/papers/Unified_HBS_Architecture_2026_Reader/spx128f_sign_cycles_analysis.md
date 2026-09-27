## SPHINCS+-SHAKE-128f Task and Cycle Analysis

This analysis uses a signing flow equivalent to FIPS 205: FORS tree construction and signature output share the selected secret values, avoiding duplicate PRF calls. To simplify control and facilitate shared task control and hash datapaths across LMS, XMSS, and SPHINCS+, all 22 HT layers use a uniform full-XMSS-tree schedule. All WOTS chains execute 15 F steps, with signature elements saved at the required positions in the selected WOTS chains, avoiding special top-layer early-termination control. The workload and cycle model uses a 16-byte internal signing message and the task numbering in Table 4 of the paper.

At 108 MHz, the breakdown is as follows. The total cycles are measured; Keccak and HIL components are modeled, with the remainder attributed to control, scheduling, and boundary overhead.

```text
Keccak computation                  636,060 cycles = 5.88944 ms
HIL input                            80,225 cycles = 0.74282 ms
Control, scheduling, and boundaries 99,421 cycles = 0.92056 ms
────────────────────────────────────────────────────────────
Total                               815,706 cycles = 7.55283 ms
```

The following sections derive the task workload, Keccak cycles, HIL cycles, and control latency, then reconcile the total.

---

## 1. Task Workload Counts

```text
SPHINCS+-SHAKE-128f target schedule: 105,196 SHAKE invocations
├─ Message processing: 2
│  ├─ PRF_msg [TASK 0]: 1
│  └─ H_msg   [TASK 1]: 1
├─ FORS: 6,304
│  ├─ PRF [TASK 2]: 2,112
│  ├─ F   [TASK 2]: 2,112
│  ├─ H   [TASK 4]: 2,079
│  └─ T_l [TASK 5]: 1
└─ HT: 98,890
   └─ 22 XMSS layers: 4,495 per layer
      ├─ PRF [TASK 6]: 280/layer
      ├─ F   [TASK 7]: 4,200/layer
      ├─ H   [TASK 10]: 7/layer
      └─ T_l [TASK 8]: 8/layer
```

Each `T_l` in Tasks 5 and 8 requires 5 Keccak permutations.

```text
Task 5 input length
  = PK.seed + ADRS + 33 FORS roots
  = 16 + 32 + 33×16
  = 576 bytes
  = 4×136 + 32
  → 5 permutations

Task 8 input length
  = PK.seed + ADRS + 35 WOTS chain values
  = 16 + 32 + 35×16
  = 608 bytes
  = 4×136 + 64
  → 5 permutations
```

For the 16-byte internal signing message, Tasks 0/1 have inputs of 48 and 64 bytes, respectively, each requiring 1 Keccak permutation.

Each of the 33 FORS trees reuses 1 selected secret value, saving 33 PRF calls relative to a reference flow that regenerates it. All HT layers execute complete chains: signature coefficients determine where to capture signature elements, not the F count. A coefficient of 0 captures the chain starting value directly.

```text
Task 7 F count = 22 × 8 × 35 × 15 = 92,400
SHAKE invocations = 2 + 6,304 + 22×4,495 = 105,196
T_l invocations = 1 + 22×8 = 177
For m≤87 bytes: Keccak permutations = 105,196 + 177×(5−1) = 105,904
```

Here, m is the internal signing message length in bytes.

---

## 2. Pure Keccak Computation Cost Under the Selected Schedule

A “batch” comprises up to two Keccak permutations that can run in parallel on the two cores. Permutations constrained by sponge-state, hash-chain, or tree-level dependencies require separate batches.

Each core processes one Keccak state at a time, without interleaving independent states. The 12-cycle cost covers round computation only; input and control overhead are accounted for separately.

For independent operations requiring one permutation each:

```text
Batch count = ceil(permutations / 2)
Keccak cycles = Batch count × 12
```

The per-task batch counts are:

```text
Task 0  = 1
Task 1  = 1
Task 2  = 4,224 / 2                         = 2,112
Task 4  = 2,046/2 + 33                      = 1,056
Task 5  = 1 T_l × 5 sequential permutations = 5
Task 6  = 6,160 / 2                         = 3,080
Task 7 = 22 × (8 × 35 / 2) × 15             = 46,200
Task 8  = 22×(8/2)×5                       = 440
Task 10 = 22×5                            = 110
```

| Task | Batch count | Pure Keccak cycles |
|---:|---:|---:|
| 0 | 1 | 12 |
| 1 | 1 | 12 |
| 2 | 2,112 | 25,344 |
| 4 | 1,056 | 12,672 |
| 5 | 5 | 60 |
| 6 | 3,080 | 36,960 |
| 7 | 46,200 | 554,400 |
| 8 | 440 | 5,280 |
| 10 | 110 | 1,320 |
| **Total** | **53,005** | **636,060 cycles** |

**PT/DDT notes:**

- Task 4 pairs lower-level nodes within each FORS tree across the two cores and processes the final root separately.
- Task 5 compresses a single FORS public key. Its 5 permutations share the sponge state and are DDT.
- Task 7 is PT across WOTS chains and DDT within each chain. Each core completes a whole chain before processing the next; every chain executes 15 F steps in every layer.
- Task 8 is PT across WOTS public keys; the 5 permutations within each T_l are DDT. Each layer has two subtrees with 4 leaves each, requiring 2 dual-core compression groups per subtree and 4 groups in total.
- Task 10 processes subtrees sequentially. Each layer computes two height-2 subtrees and the final root in `2×(2/2+1)+1=5` batches; all 22 layers require `22×5=110` batches.

Under this ideal parallel model:

```text
Keccak computational budget = 636,060 cycles
Latency at 108 MHz = 5.88944 ms
```

---

## 3. Theoretical HIL Analysis

The paper defines two HIL input paths.

### 3.1 Dedicated OTS High-Speed Path

Task 7 (WOTS chain F) uses this path. With 1 extra input cycle per batch, Task 7 has 46,200 ideal batches:

```text
C_HIL,Task7 = 46,200 × 1
            = 46,200 cycles
```

### 3.2 Flexible Resource-Efficient Path for Other Tasks

Other tasks use the flexible path. The model overlaps 17-cycle assembly of a 1088-bit rate block with 12-cycle Keccak computation, giving a steady-state difference of:

```text
17 - 12 = 5 cycles/batch
```

Of the 53,005 total batches, Task 7 accounts for 46,200. Excluding Task 7, the flexible-path batches are:

```text
53,005 - 46,200 = 6,805
```

Their HIL cost is:

```text
C_HIL,flex = 6,805 × 5
           = 34,025 cycles
```

Total theoretical HIL cycles:

```text
C_HIL = 46,200 + 34,025
      = 80,225 cycles
```

The model assumes dual-port RAM accesses overlap with hashing, so no separate RAM cycles are added. Including pure Keccak cycles:

```text
C_Keccak = 636,060 cycles
C_HIL    =  80,225 cycles
────────────────────────
C_theory = 716,285 cycles
```

At 108 MHz:

```text
t_theory = 716,285 / 108,000
         ≈ 6.63227 ms
```

This optimistic steady-state budget excludes control and boundary costs that cannot be overlapped.

---

## 4. Measured Total Cycles and Control and Scheduling Overhead

The existing dual-core result is 815,706 cycles:

```text
C_run = 815,706 cycles
      = 7.55283 ms @ 108 MHz
```

The FORS-reuse and full-HT-tree model uses 53,005 batches, 636,060 Keccak cycles, and 80,225 HIL cycles. The residual is:

```text
C_external
  = C_run - C_Keccak - C_HIL
  = 815,706 - 636,060 - 80,225
  = 99,421 cycles
```

With 53,005 batches, the average control, scheduling, and boundary residual per batch is:

```text
C_external,avg
  = 99,421 / 53,005
  ≈ 1.875691 cycles/batch
  ≈ 1.88 cycles/batch
```

The average residual of 1.88 cycles/batch represents the estimated control, scheduling, and boundary overhead inferred from the measured total after subtracting the Keccak and HIL model costs.

At 108 MHz:

```text
Average control, scheduling, and boundary residual per batch ≈ 1.875691 × 9.25926 ns
                                  ≈ 17.37 ns

Total control, scheduling, and boundary residual = 99,421 / 108,000
                               ≈ 0.92056 ms
```

The total cycle breakdown is:

```text
Keccak computation                  636,060 cycles = 5.88944 ms
HIL input                            80,225 cycles = 0.74282 ms
Control, scheduling, and boundaries 99,421 cycles = 0.92056 ms
────────────────────────────────────────────────────────────
Total                               815,706 cycles = 7.55283 ms
```
