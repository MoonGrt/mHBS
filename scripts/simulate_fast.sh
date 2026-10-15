#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
hash_backend=${HASH_BACKEND:-shake}
case "$hash_backend" in shake|sha2) ;; *) echo "HASH_BACKEND must be shake or sha2." >&2; exit 2;; esac
export HASH_BACKEND="$hash_backend"
default_vectors=tb/vectors
if [[ $hash_backend == sha2 ]]; then default_vectors+=/sha2; fi
if [[ ${PROFILE_ENABLE+x} ]]; then echo "PROFILE_ENABLE removed; use SIM_SYNTHESIS=1 for the SYNTHESIS macro view." >&2; exit 2; fi
slow_opt=${SIM_FAST_OPT_SLOW--O3}
case "$slow_opt" in
    -O0|-O1|-O2|-O3|-Os) ;;
    *) echo 'SIM_FAST_OPT_SLOW must be -O0, -O1, -O2, -O3 or -Os.' >&2; exit 2 ;;
esac
profile=$(python3 -c 'from model.profiles import get_profile; import sys; print(get_profile(sys.argv[1], hash_backend=sys.argv[2]).name)' "${1:-xmss_h10}" "$hash_backend")
operation=${2:-verify}
p=${3:-4}; u=${4:-1}
if [[ ! $p =~ ^[0-9]+$ || ! $u =~ ^[0-9]+$ ]]; then echo 'P/U must be integers.' >&2; exit 2; fi
p=$((10#$p)); u=$((10#$u))
if ((p < 1 || p > 24 || u < 1 || p*u > 24 || 24%(p*u) != 0)); then
    echo 'Require 1<=P<=24, U>0 and P*U dividing 24.' >&2; exit 2
fi
vector="${VECTORS_DIR:-$default_vectors}/$profile/$operation"
synthesis=${SIM_SYNTHESIS:-0}
[[ $synthesis =~ ^[01]$ ]] || { echo "SIM_SYNTHESIS must be 0 or 1" >&2; exit 2; }
defines=()
if [[ $hash_backend == sha2 ]]; then defines+=(-DMHBS_SHA2); fi
if [[ $synthesis == 1 ]]; then defines+=(-DSYNTHESIS); fi
work=build/sim/P${p}U${u}_fast_o3_synthesis${synthesis}
if [[ $slow_opt != -O3 ]]; then work+=_slow_${slow_opt#-}; fi
if [[ $hash_backend == sha2 ]]; then work+=_sha2; fi
mkdir -p "$work"
mapfile -t sources < sources.txt
verilator_bin=${VERILATOR:-verilator}
identity=$( { sha256sum "${sources[@]}" tb/tb_fast.sv tb/fast_main.cpp; printf "%s\n" OPT_FAST=-O3 "OPT_SLOW=$slow_opt" "SYNTHESIS=$synthesis" "HASH_BACKEND=$hash_backend"; "$verilator_bin" --version; } | sha256sum | cut -d' ' -f1)
if [[ ! -x "$work/obj/Vtb_fast" || ! -f "$work/source.sha256" || $(cat "$work/source.sha256") != "$identity" ]]; then
    exec 9>"$work/compile.lock"
    flock 9
    if [[ ! -x "$work/obj/Vtb_fast" || ! -f "$work/source.sha256" || $(cat "$work/source.sha256") != "$identity" ]]; then
        "$verilator_bin" --cc --exe --build -O3 -j 2 -Wno-fatal --top-module tb_fast \
            "-GPIPELINE=$p" "-GUNROLL=$u" "${defines[@]}" \
            --Mdir "$work/obj" -MAKEFLAGS "OPT_FAST=-O3 OPT_SLOW=$slow_opt" -CFLAGS '-O3 -march=native' "${sources[@]}" tb/tb_fast.sv \
            "$PWD/tb/fast_main.cpp" > "$work/compile.log" 2>&1
        printf '%s\n' "$identity" > "$work/source.sha256"
    fi
    flock -u 9
fi
if [[ ${SIM_COMPILE_ONLY:-0} == 1 ]]; then exit 0; fi
"$work/obj/Vtb_fast" "+VECTOR=$vector" > "$work/${profile}_${operation}.log" 2>&1
rg 'STATEFUL_PASS ' "$work/${profile}_${operation}.log"
