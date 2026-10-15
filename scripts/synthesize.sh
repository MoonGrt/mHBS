#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
hash_backend=${HASH_BACKEND:-shake}
case "$hash_backend" in shake|sha2) ;; *) echo "HASH_BACKEND must be shake or sha2." >&2; exit 2;; esac
export HASH_BACKEND="$hash_backend"
default_vectors=tb/vectors
if [[ $hash_backend == sha2 ]]; then default_vectors+=/sha2; fi
p=${1:-1}; u=${2:-2}
if [[ ! $p =~ ^[0-9]+$ || ! $u =~ ^[0-9]+$ ]]; then
    echo 'Usage: scripts/synthesize.sh [P] [U]' >&2; exit 2
fi
p=$((10#$p)); u=$((10#$u))
if ((p < 1 || p > 24 || u < 1 || p*u > 24 || 24%(p*u) != 0)); then
    echo 'Require 1<=P<=24, U>0 and P*U dividing 24.' >&2; exit 2
fi
vivado_bin=${VIVADO:-vivado}
command -v "$vivado_bin" >/dev/null || { echo 'Vivado is required.' >&2; exit 2; }
work="build/synth/P${p}U${u}"
lut6=${KECCAK_LUT6:-0}
if [[ ! $lut6 =~ ^[01]$ ]]; then echo 'KECCAK_LUT6 must be 0 or 1.' >&2; exit 2; fi
if [[ $lut6 == 0 ]]; then work+=_generic; fi
if [[ $hash_backend == sha2 ]]; then work+=_sha2; fi
mkdir -p "$work"
echo "Synthesize common core P${p}U${u}; log: $work/vivado.log"
defer_seconds=${SYNTH_DEFER_SECONDS:-${SYNTH_SKIP_SECONDS:-600}}
[[ $defer_seconds =~ ^[1-9][0-9]*$ ]] || { echo 'SYNTH_DEFER_SECONDS must be positive.' >&2; exit 2; }
status=0
setsid "$vivado_bin" -mode batch -nolog -nojournal -source scripts/synth.tcl \
    -tclargs "$p" "$u" </dev/null >"$work/vivado.log" 2>&1 &
synthesis_pid=$!
printf '%s\n' "$synthesis_pid" > "$work/synthesis.pid"
started=$SECONDS
while kill -0 "$synthesis_pid" 2>/dev/null; do
    if ((SECONDS-started >= defer_seconds)); then
        echo "MHBS_SYNTH_DEFERRED P${p}U${u}: PID=$synthesis_pid continues in background; analyze other configurations."
        printf '%s\n' "analysis deferred; synthesis continues; PID=$synthesis_pid" > "$work/DEFERRED.txt"
        exit 0
    fi
    sleep 5
done
wait "$synthesis_pid" || status=$?
if [[ $status != 0 ]]; then
    tail -n 40 "$work/vivado.log" >&2; exit 1
fi
grep 'MHBS_SYNTH_PASS' "$work/vivado.log"
echo "Reports: $work/core_utilization.rpt and $work/core_hierarchical.rpt"
