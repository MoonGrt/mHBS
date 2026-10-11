#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
formatter=${VERIBLE_FORMAT_BIN:-verible-verilog-format}
command -v "$formatter" >/dev/null || {
    echo 'Install Verible or set VERIBLE_FORMAT_BIN to its formatter executable.' >&2
    exit 2
}
mapfile -t sources < sources.txt
"$formatter" --failsafe_success=false --indentation_spaces=4 --column_limit=100 \
    --try_wrap_long_lines=true --port_declarations_alignment=flush-left \
    --module_net_variable_alignment=flush-left --inplace "${sources[@]}"
