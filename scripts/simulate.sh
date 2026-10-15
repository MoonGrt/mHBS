#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
hash_backend=${HASH_BACKEND:-shake}
case "$hash_backend" in shake|sha2) ;; *) echo "HASH_BACKEND must be shake or sha2." >&2; exit 2;; esac
export HASH_BACKEND="$hash_backend"
default_vectors=tb/vectors
if [[ $hash_backend == sha2 ]]; then default_vectors+=/sha2; fi

usage() {
    echo 'Usage: scripts/simulate.sh [profile] [keygen|sign|verify] [P] [U] [+OPTION=VALUE ...]'
    echo '       scripts/simulate.sh --smoke [P] [U]'
    echo '       scripts/simulate.sh --all [P] [U]'
    echo 'Defaults: slh_128f sign P1U2; SIM_SYNTHESIS=0; SIM_VCD=0; HASH_BACKEND=shake|sha2; vectors default to tb/vectors[/sha2]; compile threads=2.'
    echo 'VCD: SIM_VCD=1 scripts/simulate.sh slh_128f keygen 4 1 [+VCD=/absolute/path.vcd]'
}
if [[ ${PROFILE_ENABLE+x} ]]; then echo "PROFILE_ENABLE removed; use SIM_SYNTHESIS=1 for the SYNTHESIS macro view." >&2; exit 2; fi
mode=single
case "${1:-}" in
    -h|--help) usage; exit 0 ;;
    --smoke|--all) mode=${1#--}; shift; profile=; operation=; p=${1:-1}; u=${2:-2}; shift "$(( $# >= 2 ? 2 : $# ))" ;;
    *) profile=${1:-slh_128f}; operation=${2:-sign}; p=${3:-1}; u=${4:-2}; shift "$(( $# >= 4 ? 4 : $# ))" ;;
esac
synthesis=${SIM_SYNTHESIS:-0}
trace_vcd=${SIM_VCD:-0}
lut6=${KECCAK_LUT6:-0}
vectors_root=${VECTORS_DIR:-$default_vectors}
if [[ ! $p =~ ^[0-9]+$ || ! $u =~ ^[0-9]+$ || ! $synthesis =~ ^[01]$ || ! $lut6 =~ ^[01]$ || ! $trace_vcd =~ ^[01]$ ]]; then
    echo 'P/U must be integers; SIM_SYNTHESIS, SIM_VCD and KECCAK_LUT6 must be 0 or 1.' >&2; exit 2
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
if [[ $hash_backend == sha2 ]]; then defines+=(-DMHBS_SHA2); fi
trace_options=()
if [[ $synthesis == 1 ]]; then defines+=(-DSYNTHESIS); fi
if [[ $lut6 == 1 ]]; then defines+=(+define+MHBS_XILINX_LUT6); work+=_lut6; fi
if [[ $trace_vcd == 1 ]]; then
    defines+=(-DMHBS_TRACE_VCD)
    trace_options+=(--trace --trace-max-array 136)
    work+=_vcd
fi
if [[ $hash_backend == sha2 ]]; then work+=_sha2; fi
mkdir -p "$work"
identity=$( { sha256sum "${sources[@]}" tb/tb.sv; printf '%s\n' "KECCAK_LUT6=$lut6" "SYNTHESIS=$synthesis" "HASH_BACKEND=$hash_backend" "SIM_VCD=$trace_vcd"; "$verilator_bin" --version; } | sha256sum | cut -d' ' -f1)
exec 9>"$work/compile.lock"
flock 9
    if [[ ! -x "$work/obj/Vtb" || ! -f "$work/source.sha256" || $(cat "$work/source.sha256") != "$identity" ]]; then
    echo "Compile P${p}U${u} SYNTHESIS=$synthesis; log: $work/compile.log"
    if ! "$verilator_bin" --binary --timing -O3 -j 2 -Wno-fatal --top-module tb \
        "-GPIPELINE=$p" "-GUNROLL=$u" \
        --Mdir "$work/obj" "${trace_options[@]}" "${defines[@]}" "${sources[@]}" tb/tb.sv >"$work/compile.log" 2>&1; then
        tail -n 40 "$work/compile.log" >&2; exit 1
    fi
    printf '%s\n' "$identity" > "$work/source.sha256"
fi
flock -u 9

run_case() {
    local name=$1 op=$2
    shift 2
    name=$(python3 -c 'from model.profiles import get_profile; import sys; print(get_profile(sys.argv[1], hash_backend=sys.argv[2]).name)' "$name" "$hash_backend")
    local vector="$vectors_root/$name/$op" canonical="$work/${name}_${op}.log"
    local log
    local trace_arguments=()
    if [[ $trace_vcd == 1 ]]; then
        local explicit_vcd=0
        for option in "$@"; do [[ $option != +VCD=* ]] || explicit_vcd=1; done
        if [[ $explicit_vcd == 0 ]]; then
            trace_arguments+=("+VCD=$PWD/$work/${name}_${op}.vcd")
        fi
    fi
    log=$(mktemp "$work/${name}_${op}.XXXXXX.log")
    [[ -d $vector ]] || { echo "Unknown vector: $name/$op" >&2; return 2; }
    if ! "$work/obj/Vtb" "+VECTOR=$vector" "${trace_arguments[@]}" "$@" >"$log" 2>&1; then
        cp "$log" "$canonical"
        tail -n 30 "$log" >&2; return 1
    fi
    if ! grep -E 'STATEFUL_PASS |STATEFUL_FAULT_PASS|INDEX_REJECT_PASS' "$log"; then
        echo "Missing pass marker: $log" >&2; return 1
    fi
    cp "$log" "$canonical"
    rm "$log"
}
profiles=(slh_128f slh_192f slh_256f slh_128s slh_192s slh_256s xmss_h10 xmss_h16 lms_h10 lms_h15)
if [[ $hash_backend == sha2 ]]; then profiles=(slh_128f slh_128s xmss_h10 xmss_h16 lms_h10 lms_h15); fi
if [[ $mode == smoke ]]; then
    for name in "${profiles[@]}"; do run_case "$name" verify "$@"; done
    run_case slh_128f keygen "$@"
    run_case slh_128f sign "$@"
elif [[ $mode == all ]]; then
    for name in "${profiles[@]}"; do
        for op in keygen sign verify; do
            if [[ $name == *_h20 && $op != verify ]]; then continue; fi
            run_case "$name" "$op" "$@"
        done
    done
else
    case $operation in 0) operation=keygen;; 1) operation=sign;; 2) operation=verify;; esac
    run_case "$profile" "$operation" "$@"
fi
