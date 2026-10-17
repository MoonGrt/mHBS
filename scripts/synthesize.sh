#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
# Keep the old positional spellings only for the supported fixed K1U1 point.
if [[ ${1:-} =~ ^[0-9]+$ ]]; then
    if [[ $1 != 1 || ${2:-1} != 1 ]]; then echo 'This architecture supports K1U1 only.' >&2; exit 2; fi
    shift
    if [[ ${1:-} == 1 ]]; then shift; fi
fi
exec python3 scripts/synthesize.py "$@"
