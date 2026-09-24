#!/usr/bin/env python3
"""Seal software validation before v4.1 RTL modification/generation."""
import hashlib,json,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'manifests/experiments/unified_hbs_v4.1'
def sources():
    paths=list((ROOT/'model').rglob('*.py'))+list((ROOT/'tests/kat').glob('*'))
    paths += [ROOT/'tests'/n for n in ('test_unified_hbs.py','test_seven_profiles.py','test_autonomous_hbs.py')]+[Path(__file__)]
    return {str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(paths) if p.is_file()}
def require_gate():
    g=json.loads((OUT/'software_gate.json').read_text())
    if not g['pass'] or g['sources']!=sources():raise RuntimeError('v4.1 software gate missing/stale')
    return g
if __name__=='__main__':
    before=sources()
    p=subprocess.run([sys.executable,'-m','unittest','tests.test_unified_hbs','tests.test_seven_profiles','tests.test_autonomous_hbs','-v'],cwd=ROOT,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
    (OUT/'software_gate.log').write_text(p.stdout);print(p.stdout,end='')
    ok=p.returncode==0 and before==sources()
    (OUT/'software_gate.json').write_text(json.dumps({'version':'v4.1','abi_version':4,'pass':ok,'sources':before},indent=2)+'\n')
    sys.exit(0 if ok else 1)
