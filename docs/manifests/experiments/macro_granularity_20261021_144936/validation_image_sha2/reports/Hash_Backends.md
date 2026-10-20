# HashFlow direct sha2 regression

Status: `passed`. Completed 3/3 required cases.

Full Keygen/Sign/Verify: SLH profiles and stateful h10. Higher stateful trees use real-height synthetic-path Verify only; these paths do not claim full-tree generation. h16/h15 Keygen/Sign are unvalidated this round; h20 full trees remain stopped.

| Case | Cycles | Hash calls | Compression/permutation blocks | Status |
|---|---:|---:|---:|---|
| slh_128f/sign | 16001154 | 104925 | 211432 | passed |
| lms_h10/sign | 87571861 | 1100800 | 1135615 | passed |
| xmss_h10/sign | 533583084 | 3430398 | 6998012 | passed |
