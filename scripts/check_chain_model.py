#!/usr/bin/env python3
"""Check physical CHAIN control images against frozen bytes and main's VM."""
import argparse
from dataclasses import replace
import json
from pathlib import Path
import sys
import time
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from model.control import Op,Ctx,Wide,Cond,control
from model.executor import Job,Machine
from model.hash_trace import HashTrace
from model.mHBS import compile_image,ControlMachine,_source
from model.profiles import get_profile,profile_names


def run_case(name,backend,operation,trace_compare=False):
    p=get_profile(name,backend)
    folder=ROOT/'tb/vectors'/('sha2' if backend=='sha2' else '')/name/operation
    words=lambda fn:[int(w,16) for w in (folder/fn).read_text().split()]
    cfg=words('job.mem');seeds=[v.to_bytes(32,'little')[:p.n] for v in cfg[:5]]
    job=Job(*seeds[:4],identifier=cfg[5].to_bytes(16,'little'),q=cfg[6])
    msg=bytes(words('message.mem'))[:cfg[8]] if operation!='keygen' else b''
    nodes=[w.to_bytes(32,'little')[:p.n] for w in words('nodes.mem')] if operation=='verify' else ()
    image=compile_image(name,backend);trace=HashTrace(backend) if trace_compare else None
    vm=ControlMachine(image,job,seeds[4],msg,('keygen','sign','verify').index(operation),nodes,trace)
    t=time.monotonic();actual=vm.run()
    expected=bytes(words('expected.mem')) if operation!='verify' else b''
    if actual!=expected:raise AssertionError(f'{backend}/{name}/{operation}: bytes')
    meta=words('meta.mem')
    if (vm.hashes,vm.permutations)!=(meta[1],meta[2]):raise AssertionError(f'counts {(vm.hashes,vm.permutations)} != {meta[1:3]}')
    extra={}
    if trace_compare and operation!='verify':
        _,logical,_=_source(name,backend);other_trace=HashTrace(backend)
        other=Machine(logical,job,other_trace,index_policy='fixed_q_no_guard',recompute_auth=p.stateful)
        other.values[3]=seeds[4]
        if other.run(operation=='sign',msg)!=expected:raise AssertionError('main VM bytes')
        if trace.report()!=other_trace.report():raise AssertionError('main / physical control primitive task multiset')
        extra['main_trace_matched']=True
    return dict(backend=backend,profile=name,operation=operation,status='passed',hashes=vm.hashes,
                permutations=vm.permutations,control_steps=vm.steps,dynamic_operations=vm.operations,
                output_bytes=len(actual),verify_nodes=vm.input_count,seconds=time.monotonic()-t,
                trace=trace.report() if trace else None,**extra)


def negative_checks():
    base=compile_image('slh_128f');job=Job(*(bytes(16) for _ in range(4)))
    cases=[]
    def bad_decode(name,image):
        try:image.decode()
        except ValueError:cases.append(dict(test=name,status='passed'));return
        raise AssertionError('accepted '+name)
    def with_program(*words):
        p=list(base.program);p[:len(words)]=words
        return replace(base,program=tuple(p))
    bad_decode('wrong_capacity',replace(base,program=base.program[:16]))
    d=list(base.descriptors);d[0]&=(1<<57)-1;bad_decode('cross_tree_image',replace(base,descriptors=tuple(d)))
    t=list(base.templates);t[0]=(t[0]&~7)|3;bad_decode('TREE_template',replace(base,templates=tuple(t)))
    bad_decode('readonly_context',with_program(control(Op.SET,Ctx.Q,imm=1)))
    bad_decode('unknown_context',with_program(control(Op.MOV,Ctx.LEAF,31)))
    bad_decode('unknown_wide',with_program(control(Op.WMOV,0,8)))
    bad_decode('zero_shift',with_program(control(Op.SHR,Ctx.CURSOR,imm=0)))
    bad_decode('height_overflow',with_program(control(Op.SET,Ctx.HEIGHT,imm=21)))
    bad_decode('mode_overflow',with_program(control(Op.SET,Ctx.MODE,imm=3)))
    for name,words in (
        ('reserved_RAM',(control(Op.LOAD,Wide.NODE,Ctx.ZERO,imm=108),)),
        ('RAM_end_overflow',(control(Op.LOAD,Wide.NODE,Ctx.ZERO,imm=128),)),
        ('counter_overflow',(control(Op.SET,Ctx.CURSOR,imm=(1<<21)-1),control(Op.INC,Ctx.CURSOR))),
        ('RET_without_CALL',(control(Op.RET),)),
        ('nested_CALL',(control(Op.CALL,target=1),control(Op.CALL,target=2))),
    ):
        vm=ControlMachine(with_program(*words),job,bytes(16),b'',0)
        try:vm.run()
        except ValueError:
            if vm.output:raise AssertionError('fault output not cleared')
            cases.append(dict(test=name,status='passed'));continue
        raise AssertionError('accepted '+name)
    return cases


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--full',action='store_true',help='all low-tree full operations; high trees Verify only')
    parser.add_argument('--trace-compare',action='store_true')
    parser.add_argument('--output',type=Path,default=ROOT/'build/chain_model/result.json')
    args=parser.parse_args();rows=[]
    for backend in ('shake','sha2'):
        names=profile_names(backend,include_h20=True) if args.full else ('slh_128f','xmss_h10','lms_h10')
        for name in names:
            p=get_profile(name,backend)
            operations=('verify',) if p.stateful and p.h>10 else ('keygen','sign','verify')
            for operation in operations:
                row=run_case(name,backend,operation,args.trace_compare);rows.append(row)
                print('CHAIN_MODEL_PASS',backend,name,operation,row['hashes'],row['permutations'],flush=True)
    negatives=negative_checks()
    usage={backend:{name:compile_image(name,backend).usage for name in profile_names(backend,include_h20=True)} for backend in ('shake','sha2')}
    result=dict(schema='mhbs.chain_template_model.v1',passed=True,cases=rows,negative=negatives,image_usage=usage,
                skipped='h16/h15/h20 full Keygen/Sign not run; h20 remains stopped')
    args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(result,indent=2)+'\n')
    print('CHAIN_MODEL_SUMMARY',len(rows),len(negatives),args.output,flush=True)
if __name__=='__main__':main()
