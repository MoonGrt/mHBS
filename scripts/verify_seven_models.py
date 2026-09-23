#!/usr/bin/env python3
"""Run independent model tests and seal the inputs before RTL generation."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
GATE = ROOT / 'manifests/experiments/unified_hbs_v4/software_gate.json'


def source_hashes():
    paths = list((ROOT/'model').rglob('*.py')) + list((ROOT/'tests/kat').glob('*'))
    paths += [ROOT/'tests/test_unified_hbs.py',ROOT/'tests/test_seven_profiles.py',Path(__file__).resolve()]
    return {str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(paths) if p.is_file()}


def require_gate():
    if not GATE.exists(): raise RuntimeError('run scripts/verify_seven_models.py before RTL generation')
    gate = json.loads(GATE.read_text())
    if not gate['pass'] or gate['sources'] != source_hashes():
        raise RuntimeError('software gate is stale: rerun independent model verification')
    return gate


def main():
    GATE.parent.mkdir(parents=True,exist_ok=True)
    sources=source_hashes()
    proc=subprocess.run([sys.executable,'-m','unittest','tests.test_unified_hbs','tests.test_seven_profiles','-v'],cwd=ROOT,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
    (GATE.parent/'software_gate.log').write_text(proc.stdout)
    print(proc.stdout,end='')
    ok=proc.returncode==0 and sources==source_hashes()
    GATE.write_text(json.dumps(dict(schema='uhbs.software_gate.v4',pass_=ok,sources=sources),indent=2).replace('"pass_":','"pass":')+'\n')
    if not ok: raise SystemExit(1)


if __name__=='__main__':main()
