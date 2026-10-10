#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."

usage() {
    echo 'Usage: scripts/simulate.sh [profile] [keygen|sign|verify] [P] [U] [+OPTION=VALUE ...]'
    echo '       scripts/simulate.sh --smoke [P] [U]'
    echo '       scripts/simulate.sh --all [P] [U]'
    echo 'Defaults: slh_128f sign P1U2; SIM_SYNTHESIS=0; VECTORS_DIR=tb/vectors; compile threads=2.'
}
if [[ ${PROFILE_ENABLE+x} ]]; then echo "PROFILE_ENABLE removed; use SIM_SYNTHESIS=1 for the SYNTHESIS macro view." >&2; exit 2; fi
mode=single
case "${1:-}" in
    -h|--help) usage; exit 0 ;;
    --smoke|--all) mode=${1#--}; shift; profile=; operation=; p=${1:-1}; u=${2:-2}; shift "$(( $# >= 2 ? 2 : $# ))" ;;
    *) profile=${1:-slh_128f}; operation=${2:-sign}; p=${3:-1}; u=${4:-2}; shift "$(( $# >= 4 ? 4 : $# ))" ;;
esac
synthesis=${SIM_SYNTHESIS:-0}
lut6=${KECCAK_LUT6:-0}
vectors_root=${VECTORS_DIR:-tb/vectors}
if [[ ! $p =~ ^[0-9]+$ || ! $u =~ ^[0-9]+$ || ! $synthesis =~ ^[01]$ || ! $lut6 =~ ^[01]$ ]]; then
    echo 'P/U must be integers; SIM_SYNTHESIS and KECCAK_LUT6 must be 0 or 1.' >&2; exit 2
fi
p=$((10#$p)); u=$((10#$u))
if ((p < 1 || p > 24 || u < 1 || p*u > 24 || 24%(p*u) != 0)); then
    echo 'Require 1<=P<=24, U>0 and P*U dividing 24.' >&2; exit 2
fi
verilator_bin=${VERILATOR:-verilator}
command -v "$verilator_bin" >/dev/null || { echo 'Verilator is required.' >&2; exit 2; }
mapfile -t sources < sources.txt
work="build/sim/P${p}U${u}_synthesis${synthesis}"
defines=()
if [[ $synthesis == 1 ]]; then defines+=(-DSYNTHESIS); fi
if [[ $lut6 == 1 ]]; then defines+=(+define+MHBS_XILINX_LUT6); work+=_lut6; fi
mkdir -p "$work"
identity=$( { sha256sum "${sources[@]}" tb/tb.sv; printf '%s\n' "KECCAK_LUT6=$lut6" "SYNTHESIS=$synthesis"; "$verilator_bin" --version; } | sha256sum | cut -d' ' -f1)
exec 9>"$work/compile.lock"
flock 9
    if [[ ! -x "$work/obj/Vtb" || ! -f "$work/source.sha256" || $(cat "$work/source.sha256") != "$identity" ]]; then
    echo "Compile P${p}U${u} SYNTHESIS=$synthesis; log: $work/compile.log"
    if ! "$verilator_bin" --binary --timing -O3 -j 2 -Wno-fatal --top-module tb \
        "-GPIPELINE=$p" "-GUNROLL=$u" \
        --Mdir "$work/obj" "${defines[@]}" "${sources[@]}" tb/tb.sv >"$work/compile.log" 2>&1; then
        tail -n 40 "$work/compile.log" >&2; exit 1
    fi
    printf '%s\n' "$identity" > "$work/source.sha256"
fi
flock -u 9

run_case() {
    local name=$1 op=$2
    shift 2
    name=$(python3 -c 'from model.profiles import get_profile; import sys; print(get_profile(sys.argv[1]).name)' "$name")
    local vector="$vectors_root/$name/$op" canonical="$work/${name}_${op}.log"
    local log
    log=$(mktemp "$work/${name}_${op}.XXXXXX.log")
    [[ -d $vector ]] || { echo "Unknown vector: $name/$op" >&2; return 2; }
    if ! "$work/obj/Vtb" "+VECTOR=$vector" "$@" >"$log" 2>&1; then
        cp "$log" "$canonical"
        tail -n 30 "$log" >&2; return 1
    fi
    if ! grep -E 'STATEFUL_PASS |STATEFUL_FAULT_PASS|INDEX_REJECT_PASS' "$log"; then
        echo "Missing pass marker: $log" >&2; return 1
    fi
    cp "$log" "$canonical"
    rm "$log"
}
profiles=(slh_128f slh_192f slh_256f slh_128s slh_192s slh_256s xmss_h10 xmss_h16 xmss_h20 lms_h10 lms_h15 lms_h20)
if [[ $mode == smoke ]]; then
    for name in "${profiles[@]}"; do run_case "$name" verify "$@"; done
    run_case slh_128f keygen "$@"
    run_case slh_128f sign "$@"
elif [[ $mode == all ]]; then
    for name in "${profiles[@]}"; do
        for op in keygen sign verify; do run_case "$name" "$op" "$@"; done
    done
else
    case $operation in 0) operation=keygen;; 1) operation=sign;; 2) operation=verify;; esac
    run_case "$profile" "$operation" "$@"
fi
