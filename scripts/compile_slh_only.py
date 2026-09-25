#!/usr/bin/env python3
"""Build the three production SLH images; preserve archived seven-point images."""
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from model.autonomous_hbs import pack
from model.slh_only import SLH_PROFILES,admit
from tests.test_unified_hbs import default_job

ARCHIVE=ROOT/'manifests/experiments/unified_hbs_v4.1/images'
OUT=ROOT/'manifests/experiments/unified_hbs_v4.1/slh_only/images'

def main():
    gate=json.loads((OUT.parent/'software_gate.json').read_text())
    assert gate['passed'] and set(gate['profiles'])==set(SLH_PROFILES)
    records={}
    for name in SLH_PROFILES:
        job,message=default_job(name)
        image=pack(name,job,message)
        admit(image)
        target=OUT/name
        image.write(target)
        for kind in ('keygen','sign','metadata'):
            (target/(kind+'.mem')).write_bytes((ARCHIVE/name/(kind+'.mem')).read_bytes())
        digests={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in target.glob('*.mem')}
        assert digests==gate['profiles'][name]['image_sha256']
        records[name]=digests
    (OUT.parent/'images.json').write_text(json.dumps({'version':'v4.1','abi_version':4,
        'profile_set':'slh_only','profiles':records},indent=2)+'\n')
    print('SLH_ONLY_IMAGES_PASS',len(records))

if __name__=='__main__':main()
