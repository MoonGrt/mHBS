#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
profile=$(python3 -c 'from model.profiles import get_profile; import sys; print(get_profile(sys.argv[1]).name)' "${1:-xmss_h10}")
operation=${2:-verify}
vector="${VECTORS_DIR:-tb/vectors}/$profile/$operation"
work=build/sim/P4U1_fast_o3
mkdir -p "$work"
mapfile -t sources < sources.txt
verilator_bin=${VERILATOR:-verilator}
identity=$( { sha256sum "${sources[@]}" tb/tb_fast.sv tb/fast_main.cpp; printf "%s\n" OPT_FAST=-O3 OPT_SLOW=-O3; "$verilator_bin" --version; } | sha256sum | cut -d' ' -f1)
if [[ ! -x "$work/obj/Vtb_fast" || ! -f "$work/source.sha256" || $(cat "$work/source.sha256") != "$identity" ]]; then
    exec 9>"$work/compile.lock"
    flock 9
    if [[ ! -x "$work/obj/Vtb_fast" || ! -f "$work/source.sha256" || $(cat "$work/source.sha256") != "$identity" ]]; then
        "$verilator_bin" --cc --exe --build -O3 -j 2 -Wno-fatal --top-module tb_fast \
            --Mdir "$work/obj" -MAKEFLAGS "OPT_FAST=-O3 OPT_SLOW=-O3" -CFLAGS '-O3 -march=native' "${sources[@]}" tb/tb_fast.sv \
            "$PWD/tb/fast_main.cpp" > "$work/compile.log" 2>&1
        printf '%s\n' "$identity" > "$work/source.sha256"
    fi
    flock -u 9
fi
"$work/obj/Vtb_fast" "+VECTOR=$vector" > "$work/${profile}_${operation}.log" 2>&1
rg 'STATEFUL_PASS ' "$work/${profile}_${operation}.log"
