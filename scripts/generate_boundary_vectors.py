#!/usr/bin/env python3
"""Index-boundary vectors from the already independently verified interpreter."""
from pathlib import Path
import json,sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from model.profiles import PROFILES
from model.unified_hbs import Machine,compile_image
from tests.test_unified_hbs import default_job
from verify_seven_models import require_gate
require_gate()
counts={}
for name,p in PROFILES.items():
    if not p.stateful:continue
    job,msg=default_job(name)
    machine=Machine(compile_image(name,full_cache=True),job)
    kg=machine.run(False)
    counts[name]={}
    for q in (0,1023):
        machine.q=q
        sg=machine.run(True,msg)
        for kind,data in (("keygen",q.to_bytes(4,'big')+kg[4:]),("sign",sg)):
            (ROOT/f'tb/vectors/uhbs_{name}_{kind}_q{q}.mem').write_text(''.join(f'{b:02x}\n' for b in data))
        counts[name][str(q)]=dict(sign_hashes=machine.hashes,sign_permutations=machine.permutations)
(ROOT/'manifests/experiments/unified_hbs_v4/boundary_counts.json').write_text(json.dumps(counts,indent=2)+'\n')
