#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
p=${1:-12}; u=${2:-1}
if [[ ! $p =~ ^[0-9]+$ || ! $u =~ ^[0-9]+$ ]]; then echo 'P/U must be integers.' >&2; exit 2; fi
p=$((10#$p)); u=$((10#$u))
destination=${3:-build/benchmarks/P${p}U${u}}
mkdir -p "$destination"
stats=${PROFILE_ENABLE:-1}; lut6=${KECCAK_LUT6:-0}
work="build/sim/P${p}U${u}_stats${stats}"
if [[ $lut6 == 1 ]]; then work+=_lut6; fi
for target in 'slh_128f sign' 'xmss_omega4 keygen' 'lms_omega4 keygen'; do
    read -r profile operation <<< "$target"
    bash scripts/simulate.sh "$profile" "$operation" "$p" "$u"
    cp "$work/${profile}_${operation}.log" "$destination/"
done
