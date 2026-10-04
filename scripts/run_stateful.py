#!/usr/bin/env python3
"""Runtime-vector stateful regression and common-core synthesis, no routing."""
from pathlib import Path
import sys,subprocess,json,re,hashlib,argparse
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from v42_common_partition import partition
from stateful_vectors import OUT
BUILD=ROOT/'build/stateful_20261008'
def build(k=2,p=1,u=1,profile=1,swap=0):
    point=f'K{k}P{p}U{u}_stats{profile}_swap{swap}';d=BUILD/point;d.mkdir(parents=True,exist_ok=True)
    common,_=partition((ROOT/'rtl/top/mhbs_top.sv').read_text());(d/'mhbs_common.sv').write_text(common)
    sources=[ROOT/f for f in (ROOT/'manifests/v42_sources.txt').read_text().splitlines() if f!='rtl/top/mhbs_top.sv']+[d/'mhbs_common.sv',ROOT/'tb/integration/tb_mhbs_stateful.sv']
    ident={str(f):hashlib.sha256(f.read_bytes()).hexdigest() for f in sources};binary=d/'obj/Vtb_mhbs_stateful'
    if not binary.exists() or not (d/'identity.json').exists() or json.loads((d/'identity.json').read_text())!=ident:
        cmd=['verilator','--binary','--timing','-O3','-j','8','-Wno-fatal','--top-module','tb_mhbs_stateful',f'-GLANES={k}',f'-GPIPELINE={p}',f'-GUNROLL={u}',f'-GPROFILE_ENABLE={profile}',f'-GSWAP={swap}','--Mdir',str(d/'obj'),*map(str,sources)]
        with (d/'compile.log').open('w') as f:subprocess.run(cmd,cwd=ROOT,stdout=f,stderr=subprocess.STDOUT,check=True)
        (d/'identity.json').write_text(json.dumps(ident,indent=2));print('BUILD_PASS',point,flush=True)
    return binary

def run(binary,vector,options=(),suffix=''):
    d=OUT/'logs';d.mkdir(exist_ok=True);name='_'.join(vector.relative_to(OUT/'vectors').parts)+'_'+binary.parents[1].name+suffix
    log=d/(name+'.log')
    with log.open('w') as f:subprocess.run([str(binary),f'+VECTOR={vector}',*options],cwd=ROOT,stdout=f,stderr=subprocess.STDOUT,check=True)
    t=log.read_text();m=re.search(r'STATEFUL_PASS (\w+) op=(\d+) cycles=(\d+) total=(\d+) hashes=(\d+) permutations=(\d+)',t)
    if m:
        result=dict(point=m[1],operation=int(m[2]),compute_cycles=int(m[3]),total_cycles=int(m[4]),hashes=int(m[5]),permutations=int(m[6]),log=str(log.relative_to(ROOT)))
        print('PASS',name,result['compute_cycles'],flush=True);return result
    assert 'INDEX_REJECT_PASS' in t or 'STATEFUL_FAULT_PASS' in t;print('PASS',name,flush=True);return dict(passed=True)
if __name__=='__main__':
    a=argparse.ArgumentParser();a.add_argument('--k',type=int,default=2);a.add_argument('--p',type=int,default=1);a.add_argument('--u',type=int,default=1);a.add_argument('--profile',type=int,default=1);a.add_argument('--swap',type=int,default=0);a.add_argument('--name');a.add_argument('--op',type=int);a.add_argument('--build-only',action='store_true');args=a.parse_args()
    b=build(args.k,args.p,args.u,args.profile,args.swap)
    if not args.build_only:
        rows=[]
        for v in sorted((OUT/'vectors').glob(f'{args.name or "*"}/q0_m1/{args.op if args.op is not None else "[012]"}')):
            rows.append(dict(profile=v.parents[1].name,**run(b,v)))
        (OUT/f'K{args.k}P{args.p}U{args.u}_simulation.json').write_text(json.dumps(rows,indent=2)+'\n')
