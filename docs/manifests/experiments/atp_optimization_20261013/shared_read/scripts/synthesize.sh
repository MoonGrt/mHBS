#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
p=${1:-1}; u=${2:-2}
if [[ ! $p =~ ^[0-9]+$ || ! $u =~ ^[0-9]+$ ]]; then
    echo 'Usage: scripts/synthesize.sh [P] [U]' >&2; exit 2
fi
p=$((10#$p)); u=$((10#$u))
if ((p < 1 || p > 12 || u < 1 || p*u > 24 || 24%(p*u) != 0)); then
    echo 'Require 1<=P<=12, U>0 and P*U dividing 24.' >&2; exit 2
fi
vivado_bin=${VIVADO:-vivado}
command -v "$vivado_bin" >/dev/null || { echo 'Vivado is required.' >&2; exit 2; }
work="build/synth/P${p}U${u}"
lut6=${KECCAK_LUT6:-1}
if [[ ! $lut6 =~ ^[01]$ ]]; then echo 'KECCAK_LUT6 must be 0 or 1.' >&2; exit 2; fi
if [[ $lut6 == 0 ]]; then work+=_generic; fi
mkdir -p "$work"
echo "Synthesize common core P${p}U${u}; log: $work/vivado.log"
if ! "$vivado_bin" -mode batch -nolog -nojournal -source scripts/synth.tcl \
    -tclargs "$p" "$u" >"$work/vivado.log" 2>&1; then
    tail -n 40 "$work/vivado.log" >&2; exit 1
fi
grep 'MHBS_SYNTH_PASS' "$work/vivado.log"
echo "Reports: $work/core_utilization.rpt and $work/core_hierarchical.rpt"
