#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
if [[ ${HASH_BACKEND:-shake} != shake ]]; then echo 'This source branch supports SHAKE only.' >&2;exit 2;fi
profile=${1:-slh_128f};operation=${2:-sign};k=${3:-1};u=${4:-1}
if [[ $k != 1 || $u != 1 ]];then echo 'This source architecture is fixed K1U1.' >&2;exit 2;fi
shift "$(( $# >= 4 ? 4 : $# ))"
exec python3 - "$profile" "$operation" "$@" <<'PY'
import os,sys
from pathlib import Path
from scripts import run_hash_backends as flow
name,label,*options=sys.argv[1:]
if label not in flow.OPERATIONS:raise SystemExit('operation must be keygen, sign or verify')
folder=flow.ROOT/'build/hashflow/image_chain'
vector=Path(os.environ.get('VECTORS_DIR',str(folder/'vectors'))).resolve()
image=Path(os.environ.get('IMAGES_DIR',str(flow.ROOT/'tb/vectors'))).resolve()
if not (vector/name/label/'result.json').exists():raise SystemExit('Generate fixtures first: python3 scripts/run_hash_backends.py models --tag image_chain')
binary=flow.build_binary(folder,stats=os.environ.get('PROFILE_ENABLE','1')!='0',synthesis=os.environ.get('SIM_SYNTHESIS','0')=='1')
print(flow.simulate(folder,name,label,binary,options=tuple(options),image_folder=image,vector_folder=vector))
PY
