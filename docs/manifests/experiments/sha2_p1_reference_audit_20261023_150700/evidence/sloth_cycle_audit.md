# SHA2 P1U1 versus SLOTH cycle audit

Read-only audit, 2026-10-23. No RTL changes and no synthesis/routing started.

## Frozen identities

- SLOTH commit: **unknown**. The source directory has no local `.git` metadata; `git -C` searches parent directories and returned the enclosing project HEAD, which is not a valid SLOTH version identifier. File identities are frozen in `SLOTH_SOURCE.json` (manifest SHA256 `1f9718dd8ba5b6eda9d0907725c068e8c9f689af9e7f7005363b6a25df948675`).
- Current `rtl/hash/sha2-recipe.sv`: `2472a6b077740d69d37b59bb25ecf793cadb2b2f78d81c1d15a951d28f217f29`.
- Current `rtl/hash/sha256.sv`: `e7affefe71404930b739dd8d8ccab23a118628be75e8455a9cc4e932dd185e4f`.

## Observed workload

Latest full matrix SHA2 P1U1 SLH128f Sign log reports 15,192,941 cycles, 104,925 full SHA256 calls and 211,432 compression blocks.
Python model observation of exactly the existing input reproduces those hash/block totals. It is used here only to identify input histograms, not as independent RTL correctness evidence.

- PRF_msg: two calls (HMAC inner/outer).
- H_msg: three calls (inner hash plus two MGF1 hashes).
- ADDRESS_SEED: 8,272 calls.
- ADDRESS_VALUE: 96,472 calls.
- ADDRESS_LIST: 176 calls.
- All 104,920 address calls start with identical 64-byte `PK.seed || 48 zero bytes`.

Input lengths: 81 (1), 96 (1), 49 (1), 68 (2), 102 (102,514), 118 (2,230), 614 (1), 646 (175). Raw machine-readable values are in `counts.json`.

## SLOTH difference grounded in sources

1. `../../source/sloth/drv/sloth_sha2.c:591-608` explicitly eliminates the first compression: compute the chaining state for PK.seed padded with zero bytes once, then write that state into S256_SEED. This is a compression midstate, not the finalized SHA256 digest.
2. `../../source/sloth/rtl/sha256_sloth.v:208-229` starts F and PRF from `seed_m` and formats only the ADRSc-plus-value suffix. `:243-260` performs one round per cycle plus separate feed-forward.
3. The same RTL has autonomous chain re-entry at `:262-267`; drivers at `drv/sloth_sha2.c:693-703` and `:734-744` invoke combined PRF+Chain. This is why treating SLOTH as a CPU doing every hash call through full software/MMIO is incorrect.
4. Current `rtl/hash/sha2-recipe.sv:550` formats the full identical prefix for every address call. Both initial allocation (`:781-786`) and hash restart (`:758-760`) set CV=IV and block index=0. No public-prefix midstate cache exists.
5. Current `rtl/hash/sha256.sv:174-175,270-278` executes U rounds per physical stage. P1U1 genuinely spends 64 round cycles per compression; feed-forward is a separate registered stage at `:284-296`.

## Quantified cause

- Current SHA256 round work: `211432 * 64 = 13,531,648` cycles, already above the user-supplied SLOTH total 9,127,150. Control/formatting/handshake accounts for the remaining 1,661,293 cycles.
- Compute the public prefix once per Job: remove 104,919 repeated compressions, leaving 106,513 compression calls and 6,816,832 SHA256 round cycles. Full Hash calls remain 104,925.
- Holding all other overhead fixed gives the structural estimate `15192941 - 104919*64 = 8,478,125` cycles (7.11% below supplied SLOTH total). This is not a measured RTL result or an exact prediction. Formatting and context transitions would also change.
- Prefix compression accounts for 49.62% of current compression calls.
- Cached SHA256 logical length must still include the skipped 64-byte block. The correct cached state is 256-bit raw chaining state; it must be invalidated/refreshed on public seed change.

SHAKE P1U1 has 2,619,846 cycles and 105,641 permutations, versus the 24-round lower bound of 2,535,384 cycles. Only 84,462 cycles are outside those rounds. SHA2 has materially more assembly/control overhead, while SLOTH already contains SHA2-specific prefix reuse and hardware chaining. Therefore the exact speedup relative to SLOTH need not match the SHAKE speedup.

## Correctness boundary

These observations establish avoidable repeated computation, not an incorrect signature. Existing model-vector equality does not replace an independent byte-for-byte slhdsa-c signature comparison; that check is being handled separately.
