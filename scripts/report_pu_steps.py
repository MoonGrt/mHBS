#!/usr/bin/env python3
"""Archive isolated P4 step evidence alongside the measured common matrix."""
import argparse,hashlib,json,re,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scripts.run_pu_sign_matrix import utilization
p=argparse.ArgumentParser(description=__doc__);p.add_argument('--run',type=Path,required=True);p.add_argument('--matrix',type=Path,required=True);a=p.parse_args();run=a.run.resolve();matrix=json.loads((a.matrix/'status.json').read_text());baseline=json.loads(Path('docs/manifests/experiments/pu_sign_matrix_20261013_183754/reports/PU_Sign_Matrix_20261013_183754_ATP.json').read_text())
profiles=('slh_128f','xmss_h10','lms_h10');steps=[]
def record(name,area,rows,source,synthesis_seconds=None):
 steps.append(dict(stage=name,configuration='P4U1',area=area,cycles={r['profile']:r['cycles'] for r in rows},source_manifest=str(source),synthesis_seconds=synthesis_seconds))
old=[r for r in baseline['results'] if r['configuration']=='P4U1'];r=old[0];record('baseline',{k:r['common_'+k] for k in ('lut','ff','bram36','dsp','equivalent_slice')},old,Path('build/pu_sign_matrix/20261013_183754/SOURCE.json').resolve())
for name in ('macro','generic'):
 stage=run/name;rows=[]
 matches=re.findall(r'STATEFUL_PASS P4U1 op=1 cycles=(\d+).*?hashes=(\d+) permutations=(\d+)',(stage/'sign_probe.log').read_text())
 if len(matches)!=3:raise ValueError(f'Incomplete isolated probes: {name}')
 for profile,values in zip(profiles,matches):
  expected=next(r for r in old if r['profile']==profile)
  if tuple(map(int,values[1:]))!=(expected['hashes'],expected['permutations']):raise ValueError('Workload changed')
  rows.append(dict(profile=profile,cycles=int(values[0])))
 log=(stage/'synth/P4U1/vivado.log').read_text();m=re.search(r'synth_design: Time \(s\): cpu = .*?; elapsed = (\d+):(\d+):(\d+)',log)
 seconds=sum(int(v)*s for v,s in zip(m.groups(),(3600,60,1))) if m else None
 record(name,utilization(stage/'synth/P4U1/utilization.rpt'),rows,stage/'SOURCE.json',seconds)
new=[r for r in matrix['results'] if r['configuration']=='P4U1'];r=new[0];record('shared_workspace',{k:r['common_'+k] for k in ('lut','ff','bram36','dsp','equivalent_slice')},new,a.matrix/'SOURCE.json',matrix['tasks']['synth/P4U1/common']['seconds'])
data=dict(schema='mhbs.pu_generic.steps.v1',steps=steps,scope='P4U1 isolated steps; all final matrix configurations share one RTL',profile=str(run/'profile/profile.json'))
(run/'steps.json').write_text(json.dumps(data,indent=2)+'\n')
manifest={}
for f in run.rglob('*'):
 if f.is_file() and f.suffix in ('.json','.log','.rpt','.tcl') and '/source/build/' not in str(f) and 'obj/' not in str(f):manifest[str(f.relative_to(run))]=hashlib.sha256(f.read_bytes()).hexdigest()
(run/'EVIDENCE.json').write_text(json.dumps({'sha256':manifest,'supplemental_validation_inputs':str((a.matrix/'source/VALIDATION_INPUTS.json').resolve())},indent=2)+'\n')
print(json.dumps(steps,indent=2))
