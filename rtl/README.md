# RTL source policy

The production source closure is `../manifests/unified_sources.txt`. Both the
Makefile and the synthesis script consume it. All three product wrappers
(`uhbs_slh_dsa_top`, `uhbs_xmss_top`, `uhbs_lms_top`) instantiate `uhbs_hbs`.
They select ABI 3 images and fixed Job parameters at elaboration and are
synthesized separately.

`LANES` selects one or two physical instances of `uhbs_recipe_lane`; `UNROLL`
selects Keccak rounds per cycle. Static recipe masks prune capabilities absent
from each image and from the second, chain-only logical lane. The physical
lane swap test exchanges placement without changing logical behavior.

See `../docs/Architecture.md` and `../docs/Job_Interface.md` for the current
interfaces. Historical cores and benches remain reference artifacts and are
excluded from the production source closure.
