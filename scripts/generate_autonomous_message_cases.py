#!/usr/bin/env python3
"""Message-tail/cross-block vectors using the independent SLH implementation."""
from pathlib import Path
import sys,json,hashlib
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from model.autonomous_hbs import pack,AutonomousMachine
from model.reference import slh_dsa
from model.profiles import PROFILES
from tests.test_unified_hbs import default_job
BASE=ROOT/'manifests/experiments/unified_hbs_v4.1'
records={}
for name,size in [('slh_128f',87),('slh_192f',17),('slh_256f',8)]:
    job,_=default_job(name);message=bytes(range(size));image=pack(name,job,message)
    machine=AutonomousMachine(image);kg,sg=machine.run()
    p=PROFILES[name];params=getattr(slh_dsa,f'SLH_DSA_SHAKE_{p.n*8}F')
    sk,pk=slh_dsa.keygen_internal(params,job.secret,job.prf,job.public)
    assert kg==sk+pk and sg==slh_dsa.sign_internal(params,message,sk)
    folder=BASE/'images'/f'{name}_m{size}';image.write(folder)
    for kind,value in [('keygen',kg),('sign',sg)]:
        (folder/(kind+'.mem')).write_text(''.join(f'{b:02x}\n' for b in value))
    metadata=[len(kg),len(sg),*machine.stats['keygen'],*machine.stats['sign'],0,0,p.n,size]
    (folder/'metadata.mem').write_text(''.join(f'{v:08x}\n' for v in metadata))
    records[folder.name]={f.name:hashlib.sha256(f.read_bytes()).hexdigest() for f in folder.glob('*.mem')}
    print('MESSAGE_MODEL_PASS',name,size,flush=True)
(BASE/'message_cases.json').write_text(json.dumps(records,indent=2)+'\n')
