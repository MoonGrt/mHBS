#!/usr/bin/env python3
"""Exercise layout-5 control faults and RAM/CALL boundaries in production RTL."""
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
import argparse,json,os,re,subprocess,time
from pathlib import Path
from ablation_paths import ROOT, DESIGN, source_files, headers, bench, build_dir, rtl, prepare_vector
def digest(path):return sha256(path.read_bytes()).hexdigest()
def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--jobs',type=int,default=2)
    args=parser.parse_args()
    if DESIGN=='t': parser.error('The TREE design has no software-control instruction interface')
    if not 1<=args.jobs<=4:parser.error('--jobs must be 1..4')
    work=build_dir('chain_controls');work.mkdir(parents=True,exist_ok=True)
    sources=source_files()
    names=[*sources,*headers(),bench('tb_chain_controls.sv'),'scripts/check_chain_controls.py']
    identity={name:digest(ROOT/name) for name in names}
    configurations=[(backend,syn) for backend in ('shake','sha2') for syn in (False,True)]
    def run(config):
        backend,syn=config;folder=work/f'{backend}_synthesis{int(syn)}';folder.mkdir(parents=True,exist_ok=True)
        executable=folder/'obj/Vtb_chain_controls'
        key=sha256(json.dumps([identity,backend,syn],sort_keys=True).encode()).hexdigest()
        manifest=folder/'source.sha256'
        started=time.monotonic()
        if not executable.exists() or not manifest.exists() or manifest.read_text().strip()!=key:
            cmd=[os.environ.get('VERILATOR','verilator'),'--binary','--timing','-O3','-j','2','-Wno-fatal',
                 '--top-module','tb_chain_controls','--Mdir',str(folder/'obj')]
            if backend=='sha2':cmd.append('-DMHBS_SHA2')
            if syn:cmd.append('-DSYNTHESIS')
            cmd.extend([*sources,bench('tb_chain_controls.sv')])
            with (folder/'compile.log').open('w') as log:
                result=subprocess.run(cmd,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT)
            if result.returncode:return dict(backend=backend,synthesis=syn,passed=False,stage='compile',log=str(folder/'compile.log'))
            manifest.write_text(key+'\n')
        result=subprocess.run([str(executable)],cwd=ROOT,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
        (folder/'run.log').write_text(result.stdout)
        marker=re.search(r'CHAIN_CONTROLS_PASS cases=(\d+) accepted=(\d+) rejected=(\d+) hash_requests=0',result.stdout)
        print((marker.group(0) if marker else result.stdout[-1200:])+f' backend={backend} synthesis={int(syn)}',flush=True)
        return dict(backend=backend,synthesis=syn,passed=result.returncode==0 and bool(marker),
                    counts=dict(zip(('cases','accepted','rejected'),map(int,marker.groups()))) if marker else {},
                    elapsed_seconds=time.monotonic()-started,log=str(folder/'run.log'))
    with ThreadPoolExecutor(max_workers=args.jobs) as pool:results=list(pool.map(run,configurations))
    unchanged=all(digest(ROOT/name)==value for name,value in identity.items())
    report=dict(schema='mhbs.soft_chain_controls.v1',source_sha256=identity,source_unchanged=unchanged,
                passed=sum(row['passed'] for row in results),total=len(results),results=results,
                checks='bounded narrow arithmetic; two-level call/ret/high8-bitPC; RAM107; readonly/bounds/overflow; PC; CHAIN/TREE/header/backend/encoding rejection; quiescent faults')
    (work/'VALIDATION.json').write_text(json.dumps(report,indent=2)+'\n')
    if not unchanged or not all(row['passed'] for row in results):raise SystemExit(1)
if __name__=='__main__':main()
