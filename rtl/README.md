# RTL source policy

`top/micro_hbs_slh_dsa_top.sv` is the only complete synthesizable algorithm
top. Its exact production dependency list is `SLH_DSA_RTL` in the project
Makefile.

`top/micro_hbs_slh_dsa_job_stream_loader.sv` is a child of that top, not a
second algorithm implementation.

The RTL tree also retains small, independently verified LMS/XMSS foundations
(bounded SHA-256, state-index manager and standard parent hashes). They are not
complete LMS/XMSS tops.

Do not add capability or milestone `*_slice` modules under `rtl/`. Experimental
wrappers belong in a temporary branch; only modules used by the production top
or an explicitly retained cross-algorithm primitive belong here.
