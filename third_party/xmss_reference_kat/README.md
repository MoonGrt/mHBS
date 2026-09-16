# RFC 8391 XMSS reference cross-check

The committed XMSS KAT was generated with the reference implementation that
accompanies RFC 8391. The upstream source is not a build or run-time
dependency of μHBS; this directory only preserves the exact provenance and the
small deterministic driver used for the independent cross-check.

- Upstream: `https://github.com/XMSS/xmss-reference`
- Pinned commit: `171ccbd26f098542a67eb5d2b128281c80bd71a6`
- Upstream license: CC0 1.0 Universal
- Profile: `XMSS-SHAKE256_10_256`, OID `0x00000010`
- Deterministic seed: bytes `00, 01, ..., 5f`
- Signature index: `5`
- Message: ASCII `micro-hbs-xmss-kat-v1`

To reproduce manually, checkout the pinned upstream commit and compile
`kat_generator.c` together with its non-fast reference sources:

```bash
gcc -O3 -Wall -Wextra -I/path/to/xmss-reference \
  kat_generator.c \
  /path/to/xmss-reference/{params,hash,fips202,hash_address,randombytes,wots,xmss,xmss_core,xmss_commons,utils}.c \
  -lcrypto -o xmss-kat-generator
./xmss-kat-generator > xmss_shake256_10_256_idx5.json
```

The official implementation calls the Winternitz base `w=16`; the compared
Unified HBS paper labels the same setting `w=4`, meaning four bits per digit.
Both have `len=67` for `n=32`.
