#!/usr/bin/env python3
"""Measure KxP1U1 128f sign with a frozen common-core synthesis source."""

if __name__ == "__main__":
    raise SystemExit("Pipeline support removed. Use scripts/run_lu_p1.py; historical experiments require their frozen source snapshots.")
import argparse,csv,json,subprocess,tarfile
from pathlib import Path
from v42_external_flow import ROOT,BASE,simulate_case,write,sha
from run_lup_sign_atp import snapshot,synth,check_same

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--tag',required=True)
    ap.add_argument('--lanes',type=int,nargs='+',choices=(1,2),default=[1,2])
    a=ap.parse_args()
    assert a.tag and all(c.isalnum() or c in '_-' for c in a.tag)
    out=ROOT/'manifests/experiments'/a.tag;build=ROOT/'build'/a.tag
    out.mkdir(parents=True,exist_ok=True);build.mkdir(parents=True,exist_ok=True)
    identity=snapshot(out)
    (out/'implementation.patch').write_bytes(subprocess.check_output(['git','diff','HEAD'],cwd=ROOT))
    write(out/'config.json',dict(lanes=a.lanes,pipeline=1,unroll=1,operation='128f sign',clock_ns=6.666667,assumed_mhz=150,routed=False))
    ref=json.loads((ROOT/'manifests/experiments/recipe_direct_keccak_20261008/direct/simulation.json').read_text())['1']
    points={}
    for k in a.lanes:
        name=f'K{k}P1U1'
        _,r=simulate_case(build,name,BASE/'vectors/slh_128f/sign',lanes=k,unroll=1,pipeline=1)
        check_same(r,ref,cycles=k==1);points[name]=r
    write(out/'simulation.json',points)
    ws=build/'source';ws.mkdir(exist_ok=True)
    with tarfile.open(out/'source_snapshot.tar.gz') as t:t.extractall(ws,filter='data')
    for path,h in identity.items():assert sha(ws/path)==h,path
    rows=[]
    for k in a.lanes:
        name=f'K{k}P1U1';r=points[name];area=synth(out,1,ws,lanes=k,point=name)
        ms=r['sign_cycles']/150000
        rows.append(dict(point=name,**area,compute_cycles=r['sign_cycles'],total_cycles=r['total_cycles'],hashes=r['hashes'],permutations=r['permutations'],time_ms=ms,atp_slice_ms=area['equivalent_slice']*ms,keccak_utilization=r['permutations']*24/(k*r['sign_cycles'])))
        write(out/'results.json',rows)
    with (out/'results.csv').open('w') as f:
        w=csv.DictWriter(f,fieldnames=rows[0]);w.writeheader();w.writerows(rows)
    import shutil
    shutil.copytree(build/'logs',out/'simulation',dirs_exist_ok=True)
    write(out/'evidence_sha256.json',{str(p.relative_to(out)):sha(p) for p in out.rglob('*') if p.is_file() and p.suffix!='.dcp' and p.name!='evidence_sha256.json'})
    print('LANE_SWEEP_PASS',a.tag,flush=True)
if __name__=='__main__':main()
