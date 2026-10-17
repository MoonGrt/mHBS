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
sys.path.insert(0,str(ROOT/'scripts'))
from common_partition import partition


def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,default=ROOT/'build/image-chain-tree/top_equivalence')
    parser.add_argument('--vector',type=Path,
        default=ROOT/'build/image-chain-tree/micro_v4/vectors/slh_128f/sign')
    parser.add_argument('--verilator',default='verilator')
    parser.add_argument('--jobs',type=int,default=4)
    args=parser.parse_args(); out=args.out.resolve(); vector=args.vector.resolve()
    out.mkdir(parents=True,exist_ok=True)
    source_manifest=ROOT/'sources.txt'
    rtl=[p for p in source_manifest.read_text().split() if p != 'rtl/top/common.sv']
    top=next(p for p in rtl if p.endswith('/top.sv'))
    bench='tb/tb_top_signature.sv'
    support=['sources.txt','scripts/common_partition.py',
        'rtl/executor/instructions.svh',
        'scripts/check_top_signature.py',bench,
        'tb/vectors/slh_128f/program.mem',
        'tb/vectors/slh_128f/descriptor.mem']
    inputs=[ROOT/p for p in sorted(set(rtl+support))]
    inputs.extend(vector/p for p in ('job.mem','metadata.mem','expected.mem','message.mem','result.json'))
    identity={str(p):sha(p) for p in inputs}
    if sha(vector/'expected.mem')==hashlib.sha256(b'').hexdigest():
        raise ValueError('empty oracle vector')
    expected=bytes(int(x,16) for x in (vector/'expected.mem').read_text().split())
    expected_sha=hashlib.sha256(expected).hexdigest()
    oracle=json.loads((vector/'result.json').read_text())
    if expected_sha!=oracle['output_sha256'] or len(expected)!=17088:
        raise ValueError('oracle signature/metadata mismatch')
    if expected_sha!='3f67c5420ba7d1b58c1149e260843dd658f0ff3049326ec246adb4697f8c6419':
        raise ValueError('vector is not the default 128f KAT')
    common,_=partition((ROOT/top).read_text()); common_file=out/'common.sv'
    common_file.write_text(common)
    exe=out/'obj/Vtb_top_signature'
    command=[args.verilator,'--binary','--timing','-O3','-j',str(args.jobs),
        '-Wno-fatal','-Wno-WIDTH','-Wno-UNOPTFLAT','--top-module','tb_top_signature',
        '--Mdir',str(exe.parent),*rtl,str(common_file),bench]
    with (out/'compile.log').open('w') as log:
        subprocess.run(command,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,check=True)
    rows={}
    for label,stall in (('normal',0),('stalled_message',1)):
        log_path=out/(label+'.log')
        with log_path.open('w') as log:
            subprocess.run([str(exe),'+VECTOR='+str(vector),f'+STALL={stall}'],cwd=ROOT,
                stdout=log,stderr=subprocess.STDOUT,check=True)
        matches=re.findall(r'MICRO_TOP_EQUIVALENCE_PASS cycles=(\d+) signature_nodes=(\d+) bytes=(\d+) hashes=(\d+) permutations=(\d+) boot=(\d+) sign=(\d+) waits=(\d+) stall=(\d+)',log_path.read_text())
        if len(matches)!=1: raise ValueError(f'missing equivalence result: {log_path}')
        row=dict(zip(('cycles','signature_nodes','bytes','hashes','permutations','boot_cycles',
            'sign_cycles','wait_cycles','stall'),map(int,matches[0])))
        row.update(passed=True,log_sha256=sha(log_path)); rows[label]=row
        print('MICRO_TOP_EQUIVALENCE_PASS',label,row['cycles'],flush=True)
    if rows['stalled_message']['wait_cycles']<=rows['normal']['wait_cycles']:
        raise ValueError('stalled-message case did not exercise input waiting')
    abort_log=out/'tree_abort.log'
    with abort_log.open('w') as log:
        subprocess.run([str(exe),'+VECTOR='+str(vector),'+STALL=0','+TREE_ABORT'],cwd=ROOT,
            stdout=log,stderr=subprocess.STDOUT,check=True)
    matches=re.findall(r'MICRO_TOP_TREE_ABORT_PASS partial_nodes=(\d+) partial_bytes=(\d+) code=([0-9a-f]{4}) aborted_hashes=(\d+) replay_cycles=(\d+) replay_nodes=(\d+) replay_bytes=(\d+) replay_hashes=(\d+) replay_permutations=(\d+)',abort_log.read_text())
    if len(matches)!=1:raise ValueError('missing public TREE abort/reset/replay result')
    values=matches[0]
    abort_case=dict(zip(('partial_nodes','partial_bytes','aborted_hashes','replay_cycles',
        'replay_nodes','replay_bytes','replay_hashes','replay_permutations'),
        map(int,(*values[:2],*values[3:]))))
    abort_case.update(passed=True,error_code=values[2],log_sha256=sha(abort_log),
        binary_sha256=sha(exe),replay_output_sha256=expected_sha)
    if not (abort_case['error_code']=='3007' and 0<abort_case['partial_nodes']<17088//16
        and abort_case['partial_bytes']==abort_case['partial_nodes']*16
        and abort_case['aborted_hashes']>0 and abort_case['replay_bytes']==len(expected)
        and abort_case['replay_nodes']==len(expected)//16
        and abort_case['replay_hashes']==oracle['hashes']
        and abort_case['replay_permutations']==oracle['permutations']
        and abort_case['replay_cycles']==rows['normal']['cycles']):
        raise ValueError('public TREE abort/reset/replay counters differ')
    print('MICRO_TOP_TREE_ABORT_PASS',abort_case['partial_nodes'],abort_case['replay_cycles'],flush=True)
    if any(sha(path)!=digest for path,digest in identity.items()):
        raise ValueError('sources/images/vectors changed during top equivalence verification')
    result=dict(passed=True,profile='slh_128f',operation='sign',cases=rows,abort_case=abort_case,
        source_sha256=identity,binary_sha256=sha(exe),generated_common_sha256=sha(common_file),
        expected_output_sha256=expected_sha,
        verilator_version=subprocess.check_output([args.verilator,'--version'],text=True).strip())
    (out/'results.json').write_text(json.dumps(result,indent=2,sort_keys=True)+'\n')


if __name__=='__main__': main()
