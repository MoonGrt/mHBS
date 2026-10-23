# Latest SLH-DSA-128f Sign clocks

P1U1; one matched 33-byte KAT per backend. All counts are measured integer clocks.

| Backend | Design | Hash | Transfer | Remaining | Total |
|---|---|---:|---:|---:|---:|
| SHAKE | SLotH | 2,641,069 | 265,156 | 2,036,877 | 4,943,102 |
| SHAKE | i | 2,536,104 | 0 | 1,220,483 | 3,756,587 |
| SHAKE | c | 2,536,104 | 0 | 555,546 | 3,091,650 |
| SHAKE | t | 2,536,104 | 0 | 79,235 | 2,615,339 |
| SHA2 | SLotH | 7,134,844 | 244,167 | 1,784,934 | 9,163,945 |
| SHA2 | i | 6,923,410 | 0 | 1,640,672 | 8,564,082 |
| SHA2 | c | 6,923,410 | 0 | 598,967 | 7,522,377 |
| SHA2 | t | 6,923,410 | 0 | 122,659 | 7,046,069 |

i uses adopted i_software; c uses adopted c_control_pipeline; t is unchanged and source checked.

Transfer counts non-overlapped hash-MMIO clocks (zero for i/c/t). Internal movement outside Hash remains in Remaining.
SLotH reported Hash includes some engine setup/chain control; project Hash counts primitive rounds and SHA2 feed-forward.
The SHA2 Hash difference is accounting, with matching primitive work; no control clocks were relabelled as Hash.
