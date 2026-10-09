#!/usr/bin/env bash
# Extended regression for the unified P4U1 core. Logs are kept per case.
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
out=${1:-build/p4_validation}
mkdir -p "$out"
run_case() {
    local label=$1 profile=$2 operation=$3
    shift 3
    bash scripts/simulate.sh "$profile" "$operation" 4 1 "$@" > "$out/$label.log" 2>&1
    local stats=${PROFILE_ENABLE:-1}
    cp "build/sim/P4U1_stats${stats}/${profile}_${operation}.log" "$out/$label.log"
    rg 'PASS|P4_COVERAGE' "$out/$label.log"
}
bash scripts/simulate.sh --all 4 1 > "$out/all30.log" 2>&1
python3 scripts/check_recipes.py > "$out/recipes.log" 2>&1
python3 scripts/check_pipeline.py > "$out/pipeline.log" 2>&1
for profile in slh_128f xmss_omega4 lms_omega4; do
    run_case "${profile}_stalls" "$profile" sign +STALL=1 +REPLAYS=2 +INTERRUPT=1
    run_case "${profile}_cut" "$profile" verify +CUT=5 +STALL=1
    for tamper in 1 2 3 4 5; do
        run_case "${profile}_tamper${tamper}" "$profile" verify "+TAMPER=$tamper"
    done
    for fault in 1 2; do
        run_case "${profile}_fault${fault}" "$profile" sign "+FAULT=$fault"
    done
    PROFILE_ENABLE=0 run_case "${profile}_stats0" "$profile" sign
    if [[ $profile != slh_128f ]]; then
        run_case "${profile}_invalidq" "$profile" verify +Q=1024 +INVALID=1
    fi
done
for profile in xmss_omega2 lms_omega2; do run_case "${profile}_tail" "$profile" sign; done
for config in '1 2' '4 2' '12 1'; do
    read -r p u <<< "$config"
    bash scripts/simulate.sh --smoke "$p" "$u" > "$out/compat_P${p}U${u}.log" 2>&1
done
for item in 'xmss_omega4 1 1' 'lms_omega4 1 87' 'xmss_omega4 1023 3' 'lms_omega4 1023 3'; do
    read -r profile q length <<< "$item"
    vectors="$out/${profile}_q${q}"
    python3 -m model.vectors --profile "$profile" --q "$q" --message-length "$length" --output "$vectors" > "$out/${profile}_q${q}_generation.log" 2>&1
    for op in sign verify; do
        VECTORS_DIR="$vectors" run_case "${profile}_q${q}_${op}" "$profile" "$op" +STALL=1
    done
done
printf '%s\n' P4_VALIDATION_PASS
