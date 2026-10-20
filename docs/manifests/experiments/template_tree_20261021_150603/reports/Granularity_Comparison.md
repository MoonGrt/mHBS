# Template macro architecture comparison

K1U1, SHAKE / SHA2. Area is common only, excluding program/template/descriptor ROMs and signature cache. ATP uses an assumed 100 MHz; synthesis timing is diagnostic and does not establish a routed frequency.

The frozen main job inputs are used for all three architectures. Main stateful Sign may repeat target-chain prefix work; report actual Hash counts rather than assuming identical primitive workloads.

| Architecture | Program capacity | Template capacity | Descriptor capacity |
|---|---:|---:|---:|
| image | 512 | 0 | 32 |
| image-chain | 128 | 32 | 32 |
| image-chain-tree | 16 | 16 | 32 |

Static usage covers the shared image for all three operations. Descriptor usage includes meaningful zero-valued identity records. Macro counts below count program words, not repetitions or TREE-internal CHAIN execution.

| Profile | Backend | Architecture | Program used | Template used | Descriptor valid / reachable | Static CHAIN / TREE | Valid record bytes |
|---|---|---|---:|---:|---|---|---:|
| slh_128f | shake | image | 413 | 0 | 15 / — | 0 / 0 | 3424 |
| slh_128f | shake | image-chain | 124 | 12 | 30 / 26 | 4 / 0 | 1328 |
| slh_128f | shake | image-chain-tree | 14 | 11 | 30 / 30 | 0 / 4 | 440 |
| slh_128f | sha2 | image | 434 | 0 | 18 / — | 0 / 0 | 3616 |
| slh_128f | sha2 | image-chain | 124 | 12 | 30 / 26 | 4 / 0 | 1328 |
| slh_128f | sha2 | image-chain-tree | 14 | 11 | 30 / 30 | 0 / 4 | 440 |
| xmss_h10 | shake | image | 331 | 0 | 15 / — | 0 / 0 | 2768 |
| xmss_h10 | shake | image-chain | 80 | 8 | 22 / 19 | 2 / 0 | 880 |
| xmss_h10 | shake | image-chain-tree | 10 | 8 | 22 / 22 | 1 / 2 | 320 |
| xmss_h10 | sha2 | image | 331 | 0 | 15 / — | 0 / 0 | 2768 |
| xmss_h10 | sha2 | image-chain | 80 | 8 | 22 / 19 | 2 / 0 | 880 |
| xmss_h10 | sha2 | image-chain-tree | 10 | 8 | 22 / 22 | 1 / 2 | 320 |
| lms_h10 | shake | image | 193 | 0 | 15 / — | 0 / 0 | 1664 |
| lms_h10 | shake | image-chain | 81 | 8 | 25 / 22 | 2 / 0 | 912 |
| lms_h10 | shake | image-chain-tree | 10 | 8 | 25 / 25 | 1 / 2 | 344 |
| lms_h10 | sha2 | image | 193 | 0 | 15 / — | 0 / 0 | 1664 |
| lms_h10 | sha2 | image-chain | 81 | 8 | 25 / 22 | 2 / 0 | 912 |
| lms_h10 | sha2 | image-chain-tree | 10 | 8 | 25 / 25 | 1 / 2 | 344 |

| Architecture | Backend | LUT | FF | BRAM36 | Equivalent Slice | Status | RTL bound |
|---|---|---:|---:|---:|---:|---|---|
| image | shake | 16,221 | 4,701 | 0 | 4,642.875 | passed | True |
| image | sha2 | 13,748 | 4,810 | 0 | 4,038.25 | measured | True |
| image-chain | shake | 20,511 | 6,400 | 0 | 5,927.75 | passed | True |
| image-chain | sha2 | 17,905 | 7,362 | 0 | 5,396.5 | passed | True |
| image-chain-tree | shake | 18,081 | 6,214 | 0 | 5,297 | passed | True |
| image-chain-tree | sha2 | 15,435 | 7,210 | 0 | 4,760 | passed | True |

## slh_128f Sign

| Architecture | Backend | Cycles | Hashes | Blocks | Time ms | ATP Slice·ms | Rank within backend | Standard signature equal |
|---|---|---:|---:|---:|---:|---:|---:|---|
| image | shake | 2800644 | 104937 | 105641 | 28.006440 | 130,030.400115 | 1 | True |
| image | sha2 | 16001154 | 104925 | 211432 | 160.011540 | 646,166.601405 | 1 | True |
| image-chain | shake | 3165156 | 104937 | 105641 | 31.651560 | 187,622.534790 | 3 | True |
| image-chain | sha2 | 15616296 | 104925 | 211432 | 156.162960 | 842,733.413640 | 3 | True |
| image-chain-tree | shake | 2619846 | 104937 | 105641 | 26.198460 | 138,773.242620 | 2 | True |
| image-chain-tree | sha2 | 15071002 | 104925 | 211432 | 150.710020 | 717,379.695200 | 2 | True |

## xmss_h10 Sign

| Architecture | Backend | Cycles | Hashes | Blocks | Time ms | ATP Slice·ms | Rank within backend | Standard signature equal |
|---|---|---:|---:|---:|---:|---:|---:|---|
| image | shake | 94629367 | 3430398 | 3430398 | 946.293670 | 4,393,523.223101 | 1 | True |
| image | sha2 | 533583084 | 3430398 | 6998012 | 5,335.830840 | 21,547,418.889630 | 1 | True |
| image-chain | shake | 86744390 | 3431815 | 3431815 | 867.443900 | 5,141,990.578225 | 3 | True |
| image-chain | sha2 | 498032990 | 3431950 | 7001183 | 4,980.329900 | 26,876,350.305350 | 3 | True |
| image-chain-tree | shake | 86567075 | 3431815 | 3431815 | 865.670750 | 4,585,457.962750 | 2 | True |
| image-chain-tree | sha2 | 497855675 | 3431950 | 7001183 | 4,978.556750 | 23,697,930.130000 | 2 | True |

## lms_h10 Sign

| Architecture | Backend | Cycles | Hashes | Blocks | Time ms | ATP Slice·ms | Rank within backend | Standard signature equal |
|---|---|---:|---:|---:|---:|---:|---:|---|
| image | shake | 29501936 | 1100800 | 1116160 | 295.019360 | 1,369,738.011060 | 1 | True |
| image | sha2 | 87571861 | 1100800 | 1135615 | 875.718610 | 3,536,370.676832 | 1 | True |
| image-chain | shake | 28707044 | 1101392 | 1116752 | 287.070440 | 1,701,681.800710 | 3 | True |
| image-chain | sha2 | 81206896 | 1101347 | 1136162 | 812.068960 | 4,382,330.142640 | 3 | True |
| image-chain-tree | shake | 28524614 | 1101392 | 1116752 | 285.246140 | 1,510,948.803580 | 2 | True |
| image-chain-tree | sha2 | 81024466 | 1101347 | 1136162 | 810.244660 | 3,856,764.581600 | 2 | True |

## Dynamic Sign macro execution

Direct CHAIN commands and TREE-child CHAIN executions are separate counts. A CHAIN invocation executes a whole configured chain group, including leaf construction.

| Architecture | Backend | Profile | HASH | Direct CHAIN | TREE | TREE-child CHAIN | TRANSFORM | Controls |
|---|---|---|---:|---:|---:|---:|---:|---:|
| image-chain | shake | slh_128f | 2233 | 2288 | 0 | 0 | 43 | 103213 |
| image-chain | shake | xmss_h10 | 1025 | 1025 | 0 | 0 | 1 | 32800 |
| image-chain | shake | lms_h10 | 1024 | 1025 | 0 | 0 | 1 | 33823 |
| image-chain | sha2 | slh_128f | 2233 | 2288 | 0 | 0 | 43 | 103213 |
| image-chain | sha2 | xmss_h10 | 1025 | 1025 | 0 | 0 | 1 | 32800 |
| image-chain | sha2 | lms_h10 | 1024 | 1025 | 0 | 0 | 1 | 33823 |
| image-chain-tree | shake | slh_128f | 3 | 0 | 55 | 2288 | 43 | 0 |
| image-chain-tree | shake | xmss_h10 | 2 | 1 | 1 | 1024 | 1 | 0 |
| image-chain-tree | shake | lms_h10 | 1 | 1 | 1 | 1024 | 1 | 0 |
| image-chain-tree | sha2 | slh_128f | 3 | 0 | 55 | 2288 | 43 | 0 |
| image-chain-tree | sha2 | xmss_h10 | 2 | 1 | 1 | 1024 | 1 | 0 |
| image-chain-tree | sha2 | lms_h10 | 1 | 1 | 1 | 1024 | 1 | 0 |

## Measured result

The requested control boundaries and standard outputs are reproduced. The measured ATP ordering must be read from the tables: the hoped-for image > image-chain > image-chain-tree ordering is not an acceptance assumption.

For SHAKE, the CHAIN executor controller uses 7,536 LUT and its sequencer uses 977 LUT; the TREE executor uses 5,508 LUT and a 182-LUT sequencer. Both have one 2,157-LUT Keccak round and the same 954-LUT workspace. The explicit control decode/selection and instruction handshake are remaining area/cycle costs; static image compression does not imply a smaller common core. Hierarchical synthesis reports provide this breakdown.

Pending results are blank. h16/h15 full Keygen/Sign are not run; h20 full trees remain stopped.

All focus measurements available: True. Focus signatures agree: True. This measurement status does not replace the required full regression summaries.
