#!/usr/bin/env python3
"""Validate ROM/backend admission and scalar error handshakes without tree work."""
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--jobs',type=int,default=2)
    args=parser.parse_args()
    if not 1<=args.jobs<=4:
        parser.error('--jobs must be 1..4')
    work=ROOT/'build/hash_backend_contracts'
    work.mkdir(parents=True,exist_ok=True)
    from model.mHBS import compile_image
    from model.profiles import get_profile
    static=[]
    for backend in ('shake','sha2'):
        for name,code in (('xmss_h20',0x1a),('lms_h20',0x1d)):
            profile=get_profile(name,backend)
            image=compile_image(name,hash_backend=backend)
            assert profile.h==20 and image.descriptors[1]==code+(32 if backend=='sha2' else 0)
            assert len(image.program)==16 and len(image.templates)==16 and len(image.descriptors)==32
            static.append(dict(backend=backend,profile=name,height=20,descriptor=image.descriptors[1],
                               verification='static ROM encoding; universal RTL elaboration; no simulated Job'))
    for name in ('slh_192f','slh_256f','slh_192s','slh_256s'):
        try:
            compile_image(name,hash_backend='sha2')
        except ValueError:
            static.append(dict(backend='sha2',profile=name,rejected=True))
        else:
            raise AssertionError('Unsupported SHA2 SLH profile accepted: '+name)
    names=[name.strip() for name in (ROOT/'sources.txt').read_text().splitlines() if name.strip()]
    checked=[*names,'sources.txt','scripts/check_hash_backend_contracts.py','tb/tb_hash_backend_contracts.sv']
    source_sha={name:sha256((ROOT/name).read_bytes()).hexdigest() for name in checked}
    public=bytes(range(65,97));left=bytes(range(161,193));right=bytes(range(193,225))
    address=bytes([3])+bytes.fromhex('0123456789abcdef')+bytes([0x83])
    address+=(513).to_bytes(4,'big')+(67).to_bytes(4,'big')+(0x12345678).to_bytes(4,'big')
    expected=sha256(public[:16]+bytes(48)+address+left[:16]+right[:16]).digest()[:16]
    expected_hex=(expected+bytes(16))[::-1].hex()
    configurations=[(backend,synthesis) for backend in ('shake','sha2') for synthesis in (False,True)]

    def run(configuration):
        backend,synthesis=configuration
        folder=work/f'{backend}_synthesis{int(synthesis)}'
        folder.mkdir(parents=True,exist_ok=True)
        command=[os.environ.get('VERILATOR','verilator'),'--binary','--timing','-O3','-j','2','-Wno-fatal',
                 '--top-module','tb_hash_backend_contracts','--Mdir',str(folder/'obj')]
        if backend=='sha2': command.append('-DMHBS_SHA2')
        if synthesis: command.append('-DSYNTHESIS')
        command.extend([*names,'tb/tb_hash_backend_contracts.sv'])
        started=time.monotonic()
        with (folder/'compile.log').open('w') as log:
            result=subprocess.run(command,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT)
        if result.returncode:
            return dict(backend=backend,synthesis=synthesis,passed=False,stage='compile',log=str(folder/'compile.log'))
        result=subprocess.run([str(folder/'obj/Vtb_hash_backend_contracts'),f'+FIXED_EXPECTED={expected_hex}'],
                              cwd=ROOT,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
        (folder/'run.log').write_text(result.stdout)
        print(result.stdout.strip(),flush=True)
        match=re.search(r'admissions=(\d+) accepted=(\d+) rejected=(\d+) recipes=(\d+) h20_jobs=0',result.stdout)
        return dict(backend=backend,synthesis=synthesis,passed=result.returncode==0 and bool(match),
                    counts=dict(zip(('admissions','accepted','rejected','recipes'),map(int,match.groups()))) if match else {},
                    elapsed_seconds=time.monotonic()-started,log=str(folder/'run.log'))

    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        results=list(pool.map(run,configurations))
    unchanged=all(sha256((ROOT/name).read_bytes()).hexdigest()==digest for name,digest in source_sha.items())
    report=dict(schema='mhbs.hash_backend_contracts.v1',passed=sum(r['passed'] for r in results),total=len(results),
                source_unchanged=unchanged,source_sha256=source_sha,static_checks=static,results=results,
                scope='Job admission and recipe-unit checks only; no h20 Jobs or full trees execute')
    (work/'VALIDATION.json').write_text(json.dumps(report,indent=2)+'\n')
    if not unchanged or not all(r['passed'] for r in results):
        raise SystemExit(1)


if __name__=='__main__':
    main()
