#!/usr/bin/env bash
set -euo pipefail
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
usage() {
    echo 'Usage: scripts/ablation.sh {i|c|t} {simulate-fast|simulate|generate|recipes|controls|signature|synthesize} [arguments...]' >&2
}
if (($# < 2)); then usage; exit 2; fi
design=$1; action=$2; shift 2
case "$design" in i|c|t) ;; *) usage; exit 2;; esac
# Keep full high-tree operations opt-in, consistently across legacy scripts.
if [[ $action == simulate || $action == simulate-fast ]]; then
    profile=${1:-xmss_h10}; operation=${2:-verify}
    case "$profile/$operation" in
        xmss_h16/keygen|xmss_h16/sign|xmss_h20/keygen|xmss_h20/sign|lms_h15/keygen|lms_h15/sign|lms_h20/keygen|lms_h20/sign)
            if [[ ${ALLOW_FULL_STATEFUL_TREE:-0} != 1 ]]; then
                echo "High-tree Keygen/Sign remains disabled: $profile/$operation" >&2; exit 2
            fi ;;
    esac
fi
export MHBS_DESIGN="$design"
cd -- "$root"
case "$action" in
    simulate-fast) exec bash scripts/simulate_fast.sh "$@" ;;
    simulate) exec bash scripts/simulate.sh "$@" ;;
    generate) exec python3 -m model.vectors "$@" ;;
    recipes) exec python3 scripts/check_recipes.py "$@" ;;
    controls)
        if [[ $design == t ]]; then
            echo "Design $design has no software-control instruction interface." >&2; exit 2
        fi
        exec python3 scripts/check_chain_controls.py "$@" ;;
    signature) exec python3 scripts/check_top_signature.py "$@" ;;
    synthesize) exec bash scripts/synthesize.sh "$@" ;;
    *) usage; exit 2 ;;
esac
