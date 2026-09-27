#!/usr/bin/env python3
"""Export three independent v4.1 ROMs and frozen expected output streams."""
from pathlib import Path
from dataclasses import replace
import sys,json,hashlib
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from model.autonomous_hbs import pack
from model.profiles import PROFILES
from tests.test_unified_hbs import default_job
from verify_autonomous_models import require_gate
OUT=ROOT/'manifests/experiments/unified_hbs_v4.1'

def main():
    require_gate()
    baseline=json.loads((ROOT/'manifests/experiments/unified_hbs_v4/model_gate.json').read_text())['profiles']
    boundary=json.loads((ROOT/'manifests/experiments/unified_hbs_v4/boundary_counts.json').read_text())
    records={}
    for name,p in PROFILES.items():
        job,message=default_job(name)
        for q in ([5,0,1023] if p.stateful else [0]):
            suffix='' if q==(5 if p.stateful else 0) else f'_q{q}'
            image=pack(name,replace(job,q=q),message);directory=OUT/'images'/(name+suffix);image.write(directory)
            d=dict(baseline[name]);d['initial_q']=q;d['image_sha256']={f:hashlib.sha256((directory/f).read_bytes()).hexdigest() for f in ('program.mem','template.mem','descriptor.mem')}
            if suffix:
                d.update(boundary[name][str(q)])
            for kind in ('keygen','sign'):
                data=(ROOT/f'tb/vectors/mhbs_{name}_{kind}{suffix}.mem').read_bytes()
                (directory/(kind+'.mem')).write_bytes(data)
                digest=hashlib.sha256(bytes(int(x,16) for x in data.split())).hexdigest()
                if not suffix:assert digest==baseline[name][kind+'_sha256']
                d[kind+'_sha256']=digest
            meta=[d['keygen_bytes'],d['sign_bytes'],d['keygen_hashes'],d['keygen_permutations'],d['sign_hashes'],d['sign_permutations'],q,int(p.stateful),p.n,len(message)]
            (directory/'metadata.mem').write_text(''.join(f'{v:08x}\n' for v in meta))
            records[name+suffix]=d
    (OUT/'images.json').write_text(json.dumps(dict(version='v4.1',abi_version=4,profiles=records),indent=2)+'\n')
    print('V4.1_IMAGES_PASS',len(records))
if __name__=='__main__':main()
