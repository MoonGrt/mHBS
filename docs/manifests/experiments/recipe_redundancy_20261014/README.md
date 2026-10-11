# Recipe redundancy optimization evidence

Baseline: `20261014_113650`; selected candidate: `20261014_122421`.

Areas are complete common OOC cores, generic Keccak, 6.666667 ns synthesis constraints, two Vivado threads. ATP uses assumed 150 MHz; no new routed STA is claimed.

`evidence.tar.gz` contains baseline/selected source and vectors, every candidate RTL, measured synthesis/simulation reports, exact selected-source validation and mask failure/pass evidence. The rejected candidates are retained. DCP files remain in build with paths and SHA256 in CHECKPOINTS.json.

XMSS/LMS h20 Keygen and Sign stayed stopped. Historical reports are unchanged.

Unfinished rejected-candidate syntheses are delivery-time snapshots and continue in the background. The live report may backfill their measurements; this evidence archive remains the delivery snapshot.
