#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
design=$(python3 scripts/ablation_paths.py design)
export MHBS_DESIGN="$design"
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
if [[ $operation != verify && ( $profile == xmss_h16 || $profile == xmss_h20 || $profile == lms_h15 || $profile == lms_h20 ) && ${ALLOW_FULL_STATEFUL_TREE:-0} != 1 ]]; then
    echo "High-tree Keygen/Sign is disabled in this round: $profile/$operation" >&2; exit 2
fi
p=${3:-1}; u=${4:-1}
if [[ ! $p =~ ^[0-9]+$ || ! $u =~ ^[0-9]+$ ]]; then echo 'P/U must be integers.' >&2; exit 2; fi
p=$((10#$p)); u=$((10#$u))
if ((p != 1 || u != 1)); then
    echo 'This template architecture requires K1U1.' >&2; exit 2
fi
vector_args=("$profile" "$operation" --hash "$hash_backend")
if [[ -n ${VECTORS_DIR:-} ]]; then vector_args+=(--vectors-root "$VECTORS_DIR"); fi
vector=$(python3 scripts/ablation_paths.py vector "${vector_args[@]}")
synthesis=${SIM_SYNTHESIS:-0}
trace_hash=${SIM_HASH_TRACE:-0}
[[ $trace_hash =~ ^[01]$ ]] || { echo "SIM_HASH_TRACE must be 0 or 1" >&2; exit 2; }
[[ $synthesis =~ ^[01]$ ]] || { echo "SIM_SYNTHESIS must be 0 or 1" >&2; exit 2; }
defines=()
if [[ $hash_backend == sha2 ]]; then defines+=(-DMHBS_SHA2); fi
if [[ $synthesis == 1 ]]; then defines+=(-DSYNTHESIS); fi
work=build/ablation/${design}/sim/P${p}U${u}_fast_o3_synthesis${synthesis}
if [[ $slow_opt != -O3 ]]; then work+=_slow_${slow_opt#-}; fi
if [[ $hash_backend == sha2 ]]; then work+=_sha2; fi
mkdir -p "$work"
mapfile -t sources < <(python3 scripts/ablation_paths.py sources)
mapfile -t headers < <(python3 scripts/ablation_paths.py headers)
fast_tb=$(python3 scripts/ablation_paths.py bench tb_fast.sv)
fast_cpp=$(python3 scripts/ablation_paths.py bench fast_main.cpp)
verilator_bin=${VERILATOR:-verilator}
identity=$( { sha256sum "${sources[@]}" "${headers[@]}" "$fast_tb" "$fast_cpp"; printf "%s\n" OPT_FAST=-O3 "OPT_SLOW=$slow_opt" "SYNTHESIS=$synthesis" "HASH_BACKEND=$hash_backend"; "$verilator_bin" --version; } | sha256sum | cut -d' ' -f1)
if [[ ! -x "$work/obj/Vtb_fast" || ! -f "$work/source.sha256" || $(cat "$work/source.sha256") != "$identity" ]]; then
    exec 9>"$work/compile.lock"
    flock 9
    if [[ ! -x "$work/obj/Vtb_fast" || ! -f "$work/source.sha256" || $(cat "$work/source.sha256") != "$identity" ]]; then
        "$verilator_bin" --cc --exe --build -O3 -j 2 -Wno-fatal --top-module tb_fast \
            "-GPIPELINE=$p" "-GUNROLL=$u" "${defines[@]}" \
            --Mdir "$work/obj" -MAKEFLAGS "OPT_FAST=-O3 OPT_SLOW=$slow_opt" -CFLAGS '-O3 -march=native' -LDFLAGS '-lcrypto' "${sources[@]}" "$fast_tb" \
            "$PWD/$fast_cpp" > "$work/compile.log" 2>&1
        printf '%s\n' "$identity" > "$work/source.sha256"
    fi
    flock -u 9
fi
if [[ ${SIM_COMPILE_ONLY:-0} == 1 ]]; then exit 0; fi
"$work/obj/Vtb_fast" "+VECTOR=$vector" "+HASH_TRACE=$trace_hash" > "$work/${profile}_${operation}.log" 2>&1
rg 'STATEFUL_PASS |MACRO_METRICS |HASH_TRACE_METRICS ' "$work/${profile}_${operation}.log"
