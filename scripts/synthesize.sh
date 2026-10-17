#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
if (($# >= 1)) && [[ $1 != 1 ]]; then echo 'This source architecture is fixed K1U1.' >&2;exit 2;fi
if (($# >= 2)) && [[ $2 != 1 ]]; then echo 'This source architecture is fixed K1U1.' >&2;exit 2;fi
exec python3 scripts/synthesize.py "${@:3}"
