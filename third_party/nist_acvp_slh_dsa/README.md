# NIST ACVP SLH-DSA KAT provenance

The compact vector in
`tests/kat/slh_dsa_shake_128f_keygen_acvp_tc31.json` is copied from the
official NIST `usnistgov/ACVP-Server` sample vector set:

- repository: `https://github.com/usnistgov/ACVP-Server`;
- commit: `975de31eb83d87039ec88934fdc47d8c312b892d`;
- path: `gen-val/json-files/SLH-DSA-keyGen-FIPS205/internalProjection.json`;
- revision: `FIPS205`;
- parameter set: `SLH-DSA-SHAKE-128f`;
- test group/case: `4/31`.

The upstream repository is not vendored and is not a build/runtime dependency.
Normal tests consume only the compact immutable KAT. To audit it manually,
download the two JSON files at the pinned commit and compare group 4, case 31
between `prompt.json` and `expectedResults.json` or `internalProjection.json`.

The compact signature vector in
`tests/kat/slh_dsa_shake_128f_siggen_acvp_tc137.json` comes from the same
repository and commit, under `SLH-DSA-sigGen-FIPS205`, deterministic test
group/case `16/137`.  To avoid vendoring a 17,088-byte signature, the local
record pins its length, SHA-256 digest, randomizer and first/last 64 bytes.
The unit test regenerates the complete signature and checks all five values,
then verifies it and rejects a one-bit mutation.
