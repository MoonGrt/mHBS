#!/usr/bin/env python3
"""Real P4U1 full-tree regression; wait for independently generated large vectors."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import time
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from model.profiles import PROFILES, get_profile

ROOT=Path(__file__).resolve().parents[1]

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--hash',dest='hash_backend',choices=('shake','sha2'),default='shake')
    parser.add_argument('--include-h20-verify',action='store_true',help='Explicitly add h20 Verify; full h20 trees remain excluded')
    parser.add_argument('--skip-h20-full',action='store_true',help='Keep h20 Verify; do not run h20 Keygen or Sign')
    parser.add_argument('--workers',type=int,default=4)
    parser.add_argument('--output',type=Path,default=ROOT/'build/standard_migration/full36')
    parser.add_argument('--exclude-profile',action='append',default=[],choices=list(PROFILES))
    parser.add_argument('--resume',type=Path,help='Reuse passed cases with the same frozen RTL/test sources')
    args=parser.parse_args()
    if not 1<=args.workers<=8:parser.error('workers must be 1..8')
    out=args.output.resolve()
    if args.hash_backend=='sha2' and out==ROOT/'build/standard_migration/full36':out=ROOT/'build/standard_migration/sha2'
    out.mkdir(parents=True,exist_ok=True)
    env=dict(os.environ,HASH_BACKEND=args.hash_backend,SIM_SYNTHESIS="0",SIM_FAST_OPT_SLOW="-O3")
    vectors=ROOT/'tb/vectors'
    if args.hash_backend=='sha2':vectors=vectors/'sha2'
    subprocess.run(['bash','scripts/simulate_fast.sh','xmss_h10','verify'],cwd=ROOT,env=env,check=True)
    exe=ROOT/'build/sim'/('P4U1_fast_o3_synthesis0'+('_sha2' if args.hash_backend=='sha2' else ''))/'obj/Vtb_fast'
    files=(ROOT/'sources.txt').read_text().splitlines()+['sources.txt','tb/tb_fast.sv','tb/fast_main.cpp']
    identity={f:hashlib.sha256((ROOT/f).read_bytes()).hexdigest() for f in files}
    source_checksum=''.join(h+'  '+f+'\n' for f,h in identity.items())+'HASH_BACKEND='+args.hash_backend+'\n'
    if args.resume and (args.resume.parent/'source.sha256').read_text()!=source_checksum:
        parser.error('Resume RTL/test source checksums differ')
    (out/'source.sha256').write_text(source_checksum)
    profiles=[get_profile(p.name,hash_backend=args.hash_backend) for p in PROFILES.values() if args.hash_backend=='shake' or p.stateful or p.n==16]
    cases=[(p.name,op) for p in sorted(profiles,key=lambda p:(p.stateful,p.h),reverse=True)
           if p.name not in args.exclude_profile for op in ('keygen','sign','verify') if not (p.h==20 and p.stateful and (op!='verify' or not args.include_h20_verify))]
    pending=list(cases);running={};results={};errors=[];started=time.monotonic()
    if args.resume:
        import shutil
        for record in json.loads(args.resume.read_text())['results']:
            case=(record['profile'],record['operation'])
            if case not in cases:continue
            record=dict(record)
            old_log=ROOT/record['log'];new_log=out/old_log.name
            if old_log.resolve()!=new_log.resolve():shutil.copyfile(old_log,new_log)
            record['log']=str(new_log.relative_to(ROOT))
            results['/'.join(case)]=record;pending.remove(case)
    def run(case):
        name,op=case;log=out/f'{name}_{op}.log';vector=vectors/name/op
        vector_files=sorted(vector.glob('*.mem'))
        vector_hashes={f.name:hashlib.sha256(f.read_bytes()).hexdigest() for f in vector_files}
        with log.open('w') as handle:
            r=subprocess.run([str(exe),f'+VECTOR={vector}'],cwd=ROOT,stdout=handle,stderr=subprocess.STDOUT)
        text=log.read_text();match=re.search(r'STATEFUL_PASS P4U1 op=(\d+) cycles=(\d+) total=(\d+) hashes=(\d+) permutations=(\d+).*?seconds=([\d.e+]+)',text)
        if r.returncode or not match:raise RuntimeError(f'{name}/{op} failed; see {log}')
        values=match.groups()
        return dict(hash_backend=args.hash_backend,profile=name,operation=op,cycles=int(values[1]),total_cycles=int(values[2]),
                    hashes=int(values[3]),permutations=int(values[4]),seconds=float(values[5]),vectors_sha256=vector_hashes,log=str(log))
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        while pending or running:
            for future,case in list(running.items()):
                if future.done():
                    del running[future]
                    try:results['/'.join(case)]=future.result();print('FULL_CASE_PASS',*case,flush=True)
                    except Exception as e:errors.append(str(e));print('FULL_CASE_FAIL',str(e),flush=True)
            available=[c for c in pending if (vectors/c[0]/c[1]/'meta.mem').exists()]
            while available and len(running)<args.workers:
                case=available.pop(0);pending.remove(case);running[pool.submit(run,case)]=case
            state=dict(hash_backend=args.hash_backend,schema='mhbs.standard.full36.v1',complete=not pending and not running,
                       passed=len(results),required=len(cases),excluded_profiles=args.exclude_profile,errors=errors,results=list(results.values()),
                       pending=['/'.join(c) for c in pending],running=['/'.join(c) for c in running.values()])
            (out/'status.json').write_text(json.dumps(state,indent=2)+'\n')
            if pending and not running and time.monotonic()-started>86400:
                raise RuntimeError('Missing independently generated vectors after 24 hours')
            if pending or running:time.sleep(1)
    if any(hashlib.sha256((ROOT/f).read_bytes()).hexdigest()!=h for f,h in identity.items()):
        raise RuntimeError('RTL/test sources changed during regression')
    if errors or len(results)!=len(cases):raise RuntimeError('Full regression failed')
    print(f'STANDARD_FULL{len(cases)}_PASS',flush=True)

if __name__=='__main__':main()
