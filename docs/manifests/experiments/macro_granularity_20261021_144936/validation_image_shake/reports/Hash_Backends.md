# HashFlow direct shake regression

Status: `passed`. Completed 3/3 required cases.

Full Keygen/Sign/Verify: SLH profiles and stateful h10. Higher stateful trees use real-height synthetic-path Verify only; these paths do not claim full-tree generation. h16/h15 Keygen/Sign are unvalidated this round; h20 full trees remain stopped.

| Case | Cycles | Hash calls | Compression/permutation blocks | Status |
|---|---:|---:|---:|---|
| slh_128f/sign | 2800644 | 104937 | 105641 | passed |
| lms_h10/sign | 29501936 | 1100800 | 1116160 | passed |
| xmss_h10/sign | 94629367 | 3430398 | 3430398 | passed |
