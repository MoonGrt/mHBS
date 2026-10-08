#!/usr/bin/env python3
"""K1P1-4U1 ATP candidate: simulate, synthesize, validate a winning candidate."""

if __name__ == "__main__":
    raise SystemExit("Pipeline support removed. Use scripts/run_lu_p1.py; historical experiments require their frozen source snapshots.")
import argparse,csv,json,shutil,subprocess,tarfile
from pathlib import Path
from v42_external_flow import ROOT,BASE,simulate_case,build_binary,run,write,sha
from run_lup_sign_atp import snapshot,synth,check_same

def main():
 ap=argparse.ArgumentParser();ap.add_argument('--candidate',required=True);ap.add_argument('--best',type=float,default=40892.87622);ap.add_argument('--experiment',default='kpu_atp_unified_20261007');ap.add_argument('--mandatory',action='store_true');ap.add_argument('--cycle-reference');a=ap.parse_args()
 assert all(x and all(c.isalnum() or c in '_-' for c in x) for x in (a.experiment,a.candidate))
 out=ROOT/'manifests/experiments'/a.experiment/a.candidate;build=ROOT/'build'/a.experiment/a.candidate
 out.mkdir(parents=True,exist_ok=True);build.mkdir(parents=True,exist_ok=True)
 identity=snapshot(out)
 (out/'implementation.patch').write_bytes(subprocess.check_output(['git','diff','HEAD'],cwd=ROOT))
 write(out/'config.json',dict(K=1,U=1,P=[1,2,3,4],scope='128f sign common core',assumed_mhz=150,clock_ns=6.666667,previous_best=a.best))
 ref=json.loads((ROOT/'manifests/experiments/l1up_128f_20261007_v1/simulation.json').read_text())['points']['1'];vector=BASE/'vectors/slh_128f/sign'
 def sim(name,p,**kw):return simulate_case(build,name,vector,unroll=kw.pop('unroll',1),pipeline=p,lanes=kw.pop('lanes',1),**kw)[1]
 points={}
 for p in (1,2,3,4):
  r=sim(f'K1P{p}U1',p);check_same(r,ref,cycles=False);points[p]=r

 if a.cycle_reference:
  cycle_ref=json.loads((ROOT/a.cycle_reference).read_text())
  for p in (1,2,3,4):check_same(points[p],cycle_ref[str(p)])
 elif a.mandatory:
  for p,c in enumerate((2619719,1410128,985022,770546),1):assert points[p]['sign_cycles']==c,(p,points[p]['sign_cycles'],c)
 write(out/'simulation.json',points);shutil.copytree(build/'logs',out/'simulation',dirs_exist_ok=True)
 ws=build/'source';ws.mkdir(exist_ok=True)
 with tarfile.open(out/'source_snapshot.tar.gz') as t:t.extractall(ws,filter='data')
 for path,h in identity.items():assert sha(ws/path)==h,path
 rows=[]
 for p in (1,2,3,4):
  point=f'K1P{p}U1';d=out/point
  if (d/'synthesis.json').exists():area=json.loads((d/'synthesis.json').read_text())['area']
  else:area=synth(out,p,ws,lanes=1,point=point)
  r=points[p];ms=r['sign_cycles']/150000
  rows.append(dict(point=point,**area,compute_cycles=r['sign_cycles'],total_cycles=r['total_cycles'],hashes=r['hashes'],permutations=r['permutations'],time_ms=ms,atp_slice_ms=area['equivalent_slice']*ms,keccak_utilization=r['permutations']*24/(p*r['sign_cycles'])))
 write(out/'results.json',rows)
 with (out/'results.csv').open('w') as f:w=csv.DictWriter(f,fieldnames=rows[0]);w.writeheader();w.writerows(rows)
 best=min(rows,key=lambda r:r['atp_slice_ms']);gain=best['atp_slice_ms']<a.best;checks={}
 if gain or a.mandatory:
  for p in (1,2,3,4):
   checks[f'P{p}_off']=sim(f'K1P{p}U1_stats_off',p,profile_enable=False);check_same(checks[f'P{p}_off'],points[p])
   checks[f'P{p}_replay']=sim(f'K1P{p}U1_replay',p,options=('+REPLAYS=2','+STALL=1','+INTERRUPT=1','+TAIL_NOISE=1'))
   assert (checks[f'P{p}_replay']['hashes'],checks[f'P{p}_replay']['permutations'])==(104937,105641)
  checks['partition']=sim('K1P4U1_partition',4,partitioned=True);check_same(checks['partition'],points[4])
  checks['default']=sim('K2P1U2_default',1,lanes=2,unroll=2);assert checks['default']['sign_cycles']==729983;check_same(checks['default'],ref,cycles=False)
  checks['K2P4U1']=sim('K2P4U1_regression',4,lanes=2);assert checks['K2P4U1']['sign_cycles']==486328;check_same(checks['K2P4U1'],ref,cycles=False)
  binary=build_binary(build,json.loads((vector/'job.json').read_text()),unroll=1,pipeline=4,lanes=1)
  for mode in (1,2):
   log=build/'logs'/f'fault_{mode}.log';run([str(binary),f'+IMAGE={BASE/"images/slh_128f"}',f'+VECTOR={vector}',f'+FAULT={mode}'],log);assert 'V42_FAULT_PASS' in log.read_text();checks[f'fault_{mode}']={'passed':True,'log_sha256':sha(log)}
  run(['python3','scripts/verify_lup_pipeline.py'],out/'unit.log')
  shutil.copytree(ROOT/'build/lup_shared_units',out/'unit_evidence',ignore=shutil.ignore_patterns('*.vvp'),dirs_exist_ok=True)
 write(out/'validation.json',checks);shutil.copytree(build/'logs',out/'simulation',dirs_exist_ok=True)
 write(out/'decision.json',dict(accepted=gain or a.mandatory,mandatory=a.mandatory,best=best,previous_best=a.best,validated=gain or a.mandatory))
 write(out/'evidence_sha256.json',{str(p.relative_to(out)):sha(p) for p in out.rglob('*') if p.is_file() and p.name!='evidence_sha256.json' and p.suffix!='.dcp'})
 print('CANDIDATE_COMPLETE',a.candidate,'ACCEPT' if gain or a.mandatory else 'REJECT',best['point'],best['atp_slice_ms'],flush=True)
if __name__=='__main__':main()
