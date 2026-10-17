#!/usr/bin/env python3
"""Check the actual public default top and extracted common boundary together."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'scripts')]
from model.profiles import get_profile


def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile',choices=('slh_128f','xmss_h10','lms_h10'),default='slh_128f')
    parser.add_argument('--image',type=Path)
    parser.add_argument('--out',type=Path,default=ROOT/'build/hashflow/top_equivalence')
    parser.add_argument('--vector',type=Path,
        default=ROOT/'build/hashflow/image_chain/vectors/slh_128f/sign')
    parser.add_argument('--verilator',default='verilator')
    parser.add_argument('--jobs',type=int,default=4)
    parser.add_argument('--synthesis',action='store_true')
    args=parser.parse_args(); out=args.out.resolve(); vector=args.vector.resolve()
    profile=get_profile(args.profile);image=(args.image or ROOT/'tb/vectors'/args.profile).resolve()
    out.mkdir(parents=True,exist_ok=True)
    source_manifest=ROOT/'sources.txt'
    rtl=source_manifest.read_text().split()
    top=next(p for p in rtl if p.endswith('/top.sv'))
    bench='tb/tb_top_signature.sv'
    support=['sources.txt',
        'rtl/executor/instructions.svh',
        'scripts/check_top_signature.py',bench,
        str(image/'program.mem'),str(image/'descriptor.mem')]
    inputs=[ROOT/p for p in sorted(set(rtl+support))]
    inputs.extend(vector/p for p in ('job.mem','metadata.mem','expected.mem','message.mem','result.json'))
    identity={str(p):sha(p) for p in inputs}
    if sha(vector/'expected.mem')==hashlib.sha256(b'').hexdigest():
        raise ValueError('empty oracle vector')
    expected=bytes(int(x,16) for x in (vector/'expected.mem').read_text().split())
    expected_sha=hashlib.sha256(expected).hexdigest()
    oracle=json.loads((vector/'result.json').read_text())
    if expected_sha!=oracle['output_sha256'] or len(expected)!=profile.hardware_signature_bytes:
        raise ValueError('oracle signature/metadata mismatch')
    if not profile.stateful and expected_sha!='3f67c5420ba7d1b58c1149e260843dd658f0ff3049326ec246adb4697f8c6419':
        raise ValueError('vector is not the default 128f KAT')
    stateful_flags=[]
    if profile.stateful:
        words=[int(value,16) for value in (vector/'job.mem').read_text().split()]
        stateful_flags=['-DSTATEFUL_TOP']
        stateful_flags += [f"-G{name}=256'h{value:064x}" for name,value in zip(
            ('SECRET_SEED','SECRET_PRF','PUBLIC_SEED','RANDOMIZER','PUBLIC_ROOT'),words[:5])]
        stateful_flags += [f'-GPROGRAM_INIT_FILE="{image / "program.mem"}"',
                           f'-GDESCRIPTOR_INIT_FILE="{image / "descriptor.mem"}"']
    exe=out/'obj/Vtb_top_signature'
    command=[args.verilator,'--binary','--timing','-O3','-j',str(args.jobs),
        '-Wno-fatal','-Wno-WIDTH','-Wno-UNOPTFLAT',*(['-DSYNTHESIS'] if args.synthesis else []),*stateful_flags,'--top-module','tb_top_signature',
        '--Mdir',str(exe.parent),*rtl,bench]
    with (out/'compile.log').open('w') as log:
        subprocess.run(command,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,check=True)
    rows={}
    message_length=int((vector/'job.mem').read_text().split()[6],16)
    cases=(('normal',0),('stalled_message',1)) if message_length else (('normal',0),)
    for label,stall in cases:
        log_path=out/(label+'.log')
        with log_path.open('w') as log:
            subprocess.run([str(exe),'+VECTOR='+str(vector),'+IMAGE='+str(image),f'+STALL={stall}'],cwd=ROOT,
                stdout=log,stderr=subprocess.STDOUT,check=True)
        matches=re.findall(r'MICRO_TOP_EQUIVALENCE_PASS cycles=(\d+) signature_nodes=(\d+) bytes=(\d+) hashes=(\d+) permutations=(\d+) boot=(\d+) sign=(\d+) waits=(\d+) stall=(\d+)',log_path.read_text())
        if len(matches)!=1: raise ValueError(f'missing equivalence result: {log_path}')
        row=dict(zip(('cycles','signature_nodes','bytes','hashes','permutations','boot_cycles',
            'sign_cycles','wait_cycles','stall'),map(int,matches[0])))
        row.update(passed=True,log_sha256=sha(log_path)); rows[label]=row
        print('MICRO_TOP_EQUIVALENCE_PASS',label,row['cycles'],flush=True)
    if int((vector/'job.mem').read_text().split()[6],16)>0 and rows['stalled_message']['wait_cycles']<=rows['normal']['wait_cycles']:
        raise ValueError('stalled-message case did not exercise input waiting')
    if any(sha(path)!=digest for path,digest in identity.items()):
        raise ValueError('sources/images/vectors changed during top equivalence verification')
    result=dict(passed=True,profile=args.profile,operation='sign',cases=rows,
        source_sha256=identity,binary_sha256=sha(exe),common_sha256=sha(ROOT/'rtl/top/common.sv'),
        expected_output_sha256=expected_sha,
        verilator_version=subprocess.check_output([args.verilator,'--version'],text=True).strip())
    (out/'results.json').write_text(json.dumps(result,indent=2,sort_keys=True)+'\n')


if __name__=='__main__': main()
