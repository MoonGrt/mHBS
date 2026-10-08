#!/usr/bin/env python3
"""K2P2/P3 regression against the frozen starting source snapshot."""
from pathlib raise SystemExit("Removed pipeline configurations: use scripts/verify_lu_p1.py and frozen historical sources.")
import Path
import tarfile,subprocess,json,sys
from v42_external_flow import ROOT,BASE,simulate_case
OUT=ROOT/'manifests/experiments/stateful_20261008';BUILD=ROOT/'build/stateful_20261008'
ws=BUILD/'frozen_kp';ws.mkdir(exist_ok=True)
with tarfile.open(OUT/'baseline/source_snapshot.tar.gz') as t:t.extractall(ws,filter='data')
code='''import sys,json
from pathlib import Path
sys.path.insert(0,str(Path.cwd()/"scripts"))
from v42_external_flow import ROOT,BASE,simulate_case
f=ROOT/"results";f.mkdir(exist_ok=True)
r={}
for p in (2,3):
 label=f"K2P{p}U1"
 _,r[label]=simulate_case(f,label,BASE/"vectors/slh_128f/sign",lanes=2,pipeline=p,unroll=1)
(f/"results.json").write_text(json.dumps(r,indent=2)+"\\n")
'''
with (BUILD/'frozen_kp.log').open('w') as f:subprocess.run([sys.executable,'-c',code],cwd=ws,stdout=f,stderr=subprocess.STDOUT,check=True)
ref=json.loads((ws/'results/results.json').read_text());rows=json.loads((OUT/'slh_variants.json').read_text())
for p in (2,3):
 label=f'K2P{p}U1';_,r=simulate_case(BUILD/'slh_variants',label,BASE/'vectors/slh_128f/sign',lanes=2,pipeline=p,unroll=1)
 for k in ('sign_cycles','total_cycles','hashes','permutations','output_sha256'):assert r[k]==ref[label][k],(label,k)
 rows[label]=r
(OUT/'slh_variants.json').write_text(json.dumps(rows,indent=2)+'\n')
(OUT/'frozen_k2_middle.json').write_text(json.dumps(ref,indent=2)+'\n')
print('K2_MIDDLE_PASS',flush=True)
