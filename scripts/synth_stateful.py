#!/usr/bin/env python3
"""Freeze and synthesize the all-algorithm K1/K2P1U1 common cores."""
import json,tarfile,subprocess
from pathlib import Path
from run_lup_sign_atp import snapshot,synth,ROOT,sha
OUT=ROOT/'manifests/experiments/stateful_20261008/implementation'
def main():
 OUT.mkdir(parents=True,exist_ok=True);identity=snapshot(OUT)
 meta=json.loads((OUT/'inputs.json').read_text());meta.update(scope='all-algorithm common core',operation='Keygen/Sign/Verify',profiles=['slh_128f','slh_192f','slh_256f','slh_128s','slh_192s','slh_256s','xmss_omega2','xmss_omega4','lms_omega2','lms_omega4'])
 (OUT/'inputs.json').write_text(json.dumps(meta,indent=2)+'\n')
 (OUT/'changes.patch').write_bytes(subprocess.check_output(['git','diff','--binary'],cwd=ROOT))
 ws=ROOT/'build/stateful_20261008/synth_source';ws.mkdir(parents=True,exist_ok=True)
 with tarfile.open(OUT/'source_snapshot.tar.gz') as t:t.extractall(ws,filter='data')
 assert all(sha(ws/f)==h for f,h in identity.items())
 rows={}
 for k in (1,2):rows[f'K{k}P1U1']=synth(OUT,1,ws,lanes=k,point=f'K{k}P1U1')
 (OUT/'area.json').write_text(json.dumps(rows,indent=2)+'\n')
if __name__=='__main__':main()
