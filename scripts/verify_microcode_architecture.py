#!/usr/bin/env python3
"""Prove that images select macro sequence, repetition, recipe and result routing.

These small ABI programs are architecture probes, not HBS algorithm KATs.
Their emitted bytes also have a direct hashlib oracle independent of the VM.
"""
import hashlib,json,re,subprocess
from dataclasses import replace
from pathlib import Path
from autonomous_flow import ROOT,BASE,BUILD,logic,logic_id,sha,write,run,sources
import sys
sys.path.insert(0,str(ROOT))
from model.autonomous_hbs import pack
from model.unified_hbs import (Machine,Macro,Kind,Source,record,route,segment,
    command,Token,TOKEN_SINGLE,TOKEN_RUN,TOKEN_LOOP,TOKEN_HALT,issue_word)
from tests.test_unified_hbs import default_job

def main():
    identity=logic();out=BASE/'architecture'/logic_id(identity);out.mkdir(parents=True,exist_ok=True)
    job,msg=default_job('slh_128f');original=pack('slh_128f',job,msg)
    records={};expected_traces={}
    for variant in ('base','program','template','recipe','route','loop','run'):
        d=list(original.descriptors)
        d[44]=route(3,emit=variant=='route')
        d[50]=record(Kind.EMIT,base=(64,52,8),count=(1,48,4))
        d[64]=segment(Source.ROOT,16)
        for i in range(65,70):d[i]=0
        if variant=='recipe':d[4]=(d[4]&~(255<<48)) | (5<<48)
        templates=[issue_word(command(Macro.HASH,7 if variant=='template' else 4,44),first=True),
            issue_word(command(Macro.EMIT,50)),issue_word(command(Macro.HASH,7,44))]
        sequence=[Token(TOKEN_SINGLE,template=0)]
        if variant=='program':sequence += [Token(TOKEN_SINGLE,template=2)]
        if variant=='loop':sequence += [Token(TOKEN_SINGLE,template=2),Token(TOKEN_LOOP,back_count=1,loop_repeats=2)]
        if variant=='run':sequence += [Token(TOKEN_RUN,template=2,repeat=3)]
        sequence += [Token(TOKEN_SINGLE,template=1),Token(TOKEN_HALT)]
        size=32 if variant=='route' else 16
        d[0]=record(Kind.IMAGE,version=(4,56,4),keygen=(0,47,9),sign=(len(sequence),38,9),kg_bytes=(size,18,18),sg_bytes=(size,0,18))
        tokens=[t.encode() for t in sequence*2]
        program=list(original.program);program[:32]=tokens+[0]*(32-len(tokens))
        program[41]=(len(msg)<<11)|(len(tokens)<<18)|(len(templates)<<24)
        image=replace(original,program=tuple(program),templates=tuple(templates+[0]*(64-len(templates))),descriptors=tuple(d))
        decoded,actual_job,message=image.decode()
        machine=Machine(decoded,actual_job,index_policy='fixed_q_no_guard')
        results=[];counts=[];traces=[]
        for sign in (False,True):
            results.append(machine.run(sign,message if sign else b''))
            counts += [machine.hashes,machine.permutations]
            traces += [(int(sign),(w>>52)&((1<<48)-1)) for w in decoded.words(sign)[:-1]]
        domain=5 if variant in ('program','template','recipe','loop','run') else 6
        address=bytes(16)+domain.to_bytes(4,'big')+bytes(12)
        oracle=hashlib.shake_256(job.public+address+job.secret).digest(16)
        if variant=='route':oracle*=2
        assert results==[oracle,oracle],variant
        directory=out/'images'/variant;image.write(directory)
        for name,data in zip(('keygen','sign'),results):
            (directory/(name+'.mem')).write_text(''.join(f'{v:02x}\n' for v in data))
        meta=[size,size,*counts,0,0,16,len(message)]
        (directory/'metadata.mem').write_text(''.join(f'{v:08x}\n' for v in meta))
        records[variant]=dict(model_pass=True,oracle_sha256=hashlib.sha256(oracle).hexdigest(),counts=counts,
            image_sha256={p.name:sha(p) for p in directory.glob('*.mem')},macro_trace=traces)
        expected_traces[variant]=traces
    assert expected_traces['program']!=expected_traces['base']
    assert expected_traces['template']!=expected_traces['base']
    assert expected_traces['loop']==expected_traces['run']
    assert records['recipe']['oracle_sha256']!=records['base']['oracle_sha256']
    assert records['route']['oracle_sha256']!=records['base']['oracle_sha256']
    write(out/'model_gate.json',dict(passed=True,probes=records))
    binary=BUILD/('architecture_'+logic_id(identity)+'.vvp')
    benches=['tb/integration/tb_uhbs_autonomous.sv','tb/integration/tb_uhbs_microcode_probe.sv']
    run(['iverilog','-g2012','-s','tb_uhbs_microcode_probe','-o',str(binary),*sources(),*benches],out/'compile.log')
    for variant,data in records.items():
        log=out/(variant+'.log')
        run(['vvp',str(binary),'+IMAGE='+str((out/'images'/variant).relative_to(ROOT))],log)
        text=log.read_text();trace=[(int(phase),int(cmd,16)) for phase,cmd in re.findall(r'MACRO_TRACE phase=(\d+) command=([0-9a-f]+)',text)]
        assert 'AUTONOMOUS_PASS' in text and trace==expected_traces[variant],variant
        data.update(rtl_pass=True,log_sha256=sha(log))
    write(out/'results.json',dict(passed=True,logic_sha256=identity,bench_sha256={p:sha(ROOT/p) for p in benches},script_sha256=sha(Path(__file__)),probes=records))
    print('MICROCODE_ARCHITECTURE_PASS',len(records))
if __name__=='__main__':main()
