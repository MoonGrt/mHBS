#!/usr/bin/env python3
"""Check standard stateful outputs and exact primitive work, independently of ROM recipes.

The reference side uses the direct RFC algorithms. The VM side executes this
branch's compiler output. Task multisets retain multiplicity and compare the
complete Hash input and result through sorted SHA256 fingerprints. High trees
are Verify-only with labelled synthetic authentication siblings.
"""
from __future__ import annotations
import argparse
import dataclasses
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from model.executor import MicroMachine
from model.mHBS import compile_micro
from model.microcode import ABI,MicroImage,Op
from model.profiles import STATEFUL_NAMES,get_profile
from model.reference.stateful_shake import reference
from model.stateful import (decode_public_key,payload_to_signature,
    public_key_from_root,signature_to_payload)
from model.vectors import _job,generate_fixture

work_file=ROOT/'scripts/check_standard_models.py'
if ABI==4:work_file=ROOT/'scripts/check_hash_work.py'
spec=importlib.util.spec_from_file_location('stateful_hash_work',work_file)
work=importlib.util.module_from_spec(spec);spec.loader.exec_module(work)

def digest(data):return hashlib.sha256(data).hexdigest()

def rejected(fn):
    try:fn()
    except (ValueError,OverflowError):return
    raise AssertionError('invalid input accepted')

def variants(name):
    values={'default':compile_micro(name),'explicit':compile_micro(name,chain_macros=False,**({'tree_macros':False} if ABI==4 else {}))}
    if ABI==4:values['chain_only']=compile_micro(name,tree_macros=False)
    return values

def compare(fixture,folder,*,images=None,reference_work=None):
    p=get_profile(fixture['profile']);module=reference(p.family)
    result={};images=images or {'default':compile_micro(p.name)}
    for variant,image in images.items():
        start=time.monotonic()
        with tempfile.TemporaryDirectory(dir=folder,prefix='.tasks_') as tmp:
            oracle=work.HashWork(Path(tmp)/'reference');candidate=work.HashWork(Path(tmp)/'candidate')
            if reference_work:
                reference_work(oracle)
            else:
                assert fixture['operation']==2
                assert module.verify(fixture['standard_pk'],fixture['message'],fixture['standard_sig'],oracle)
            machine=MicroMachine(image,fixture['job'],fixture['root'],fixture['message'],fixture['operation'],
                fixture['signature'] if fixture['operation']==2 else b'',observe=candidate,instruction_limit=(1<<64)-1)
            actual=machine.run()
            assert actual==fixture['expected'],(p.name,variant,'output')
            compared=work.compare_work(oracle,candidate)
            assert compared['tasksetsame'],(p.name,variant,'Hash work',compared)
            assert compared['reference_permutations']==compared['candidate_permutations']
            assert (machine.hash_count,machine.permutation_count)==(oracle.tasks,oracle.permutations)
            if fixture['operation']==1:
                assert payload_to_signature(p.name,fixture['job'].q,actual)==fixture['standard_sig']
            if fixture['operation']==0:
                kwargs={'public_seed':fixture['job'].public} if p.family=='xmss' else {'identifier':fixture['job'].identifier}
                assert public_key_from_root(p.name,actual,**kwargs).to_bytes()==fixture['standard_pk']
            result[variant]=dict(passed=True,profile=p.name,operation=fixture['operation'],q=fixture['job'].q,
                message_bytes=len(fixture['message']),synthetic=fixture['synthetic'],instructions=machine.instructions,
                instruction_words=image.used,macro_count=machine.macro_count,macro_hashes=machine.macro_hashes,
                tree_count=machine.tree_count,tree_hashes=machine.tree_hashes,tree_chains=machine.tree_chains,
                output_sha256=digest(bytes([actual]) if isinstance(actual,bool) else actual),
                standard_pk_sha256=digest(fixture['standard_pk']),standard_signature_sha256=digest(fixture['standard_sig']),
                seconds=time.monotonic()-start,**compared)
        print('STATEFUL_WORK_PASS',p.name,fixture['operation'],fixture['job'].q,variant,machine.hash_count,flush=True)
    return result

def boundaries(folder):
    cases={}
    for name in STATEFUL_NAMES:
        p=get_profile(name)
        qs=sorted({0,1,(1<<p.h)-1,*[q for q in (1023,1024,32767,32768,65535,65536) if q<1<<p.h]})
        for q in qs:
            # Vary empty, one-byte and maximum-size inputs at real address boundaries.
            message=(b'',b'\xa5',bytes(range(87)))[q%3]
            fixture=generate_fixture(name,2,q=q,message=message,synthetic=True)
            cases[f'{name}/verify/q{q}']=compare(fixture,folder,images=variants(name))
            assert decode_public_key(name,fixture['standard_pk']).to_bytes()==fixture['standard_pk']
            assert signature_to_payload(name,fixture['standard_sig'])==(q,fixture['signature'])
            rejected(lambda:signature_to_payload(name,fixture['standard_sig'][:-1]))
            rejected(lambda:signature_to_payload(name,(1<<p.h).to_bytes(4,'big')+fixture['standard_sig'][4:]))
            rejected(lambda:decode_public_key(name,bytes([fixture['standard_pk'][0]^1])+fixture['standard_pk'][1:]))
            bad=bytearray(fixture['standard_sig']);bad[40]^=1
            assert not reference(p.family).verify(fixture['standard_pk'],message,bytes(bad))
            invalid_job=dataclasses.replace(fixture['job'],q=1<<p.h)
            rejected(lambda:MicroMachine(compile_micro(name),invalid_job,fixture['root'],message,2,fixture['signature']))
        rejected(lambda:generate_fixture(name,2,q=1<<p.h,synthetic=True))
        if p.h!=10:
            for op in (0,1):rejected(lambda op=op:generate_fixture(name,op))
        for image in variants(name).values():
            assert len(image.program)==512 and len(image.descriptors)==32
            assert not any(image.descriptors[15:])
            desc=list(image.descriptors);desc[1]|=1<<5
            rejected(lambda:MicroImage(image.program,tuple(desc)).validate())
    for family in ('xmss','lms'):
        assert compile_micro(family)==compile_micro(family+'_h10')
        for legacy in ('omega2','omega4'):rejected(lambda:compile_micro(family+'_'+legacy))
    rejected(lambda:compile_micro('xmss_h10',hash_backend='sha2'))
    return cases

def full(name,folder):
    p=get_profile(name);assert p.h==10
    module=reference(p.family);job=_job(p,0);cases={}
    private,public=(module.keygen(name,job.secret,job.prf,job.public) if p.family=='xmss'
                    else module.keygen(name,job.secret,job.identifier))
    def key_work(obs):
        actual=(module.keygen(name,job.secret,job.prf,job.public,obs) if p.family=='xmss'
                else module.keygen(name,job.secret,job.identifier,obs))
        assert actual[1].to_bytes()==public.to_bytes()
    fixture=dict(profile=name,job=job,root=public.root,message=b'',operation=0,signature=b'',
        standard_pk=public.to_bytes(),standard_sig=b'',expected=public.root,synthetic=False)
    cases[name+'/keygen']=compare(fixture,folder,reference_work=key_work)
    for q in (0,1,(1<<p.h)-1):
        message=(b'',b'\xa5',bytes(range(87)))[(0,1,(1<<p.h)-1).index(q)]
        def sign_work(obs):
            return (module.sign(private,message,index=q,observe=obs) if p.family=='xmss'
                    else module.sign(private,message,job.random,index=q,observe=obs))
        signature=sign_work(None).signature
        _,payload=signature_to_payload(name,signature)
        fixture=dict(profile=name,job=dataclasses.replace(job,q=q),root=public.root,message=message,
            operation=1,signature=b'',standard_pk=public.to_bytes(),standard_sig=signature,expected=payload,synthetic=False)
        cases[f'{name}/sign/q{q}']=compare(fixture,folder,reference_work=sign_work)
        fixture.update(operation=2,signature=payload,expected=True)
        cases[f'{name}/verify/q{q}']=compare(fixture,folder,images=variants(name))
    return cases

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode',choices=('quick','full'),default='quick')
    parser.add_argument('--profile',choices=('all','xmss_h10','lms_h10'),default='all')
    parser.add_argument('--out',type=Path,default=ROOT/'build/stateful_models')
    args=parser.parse_args();args.out.mkdir(parents=True,exist_ok=True);start=time.monotonic()
    paths=[p for directory in ('model','rtl') for p in (ROOT/directory).rglob('*') if p.is_file() and (p.suffix in ('.py','.sv','.svh'))]
    identity={str(p.relative_to(ROOT)):digest(p.read_bytes()) for p in paths}
    cases=(boundaries(args.out) if args.mode=='quick' else {
        key:value for name in (('xmss_h10','lms_h10') if args.profile=='all' else (args.profile,)) for key,value in full(name,args.out).items()})
    # Models must remain identical for the receipt; concurrent RTL work is separately frozen by the RTL runner.
    for path,sha in identity.items():
        if path.startswith('model/'):assert digest((ROOT/path).read_bytes())==sha,('model changed during check',path)
    row=dict(passed=True,abi=ABI,backend='shake',configuration='K1U1',mode=args.mode,cases=cases,
        source_sha256=identity,elapsed_seconds=time.monotonic()-start,
        high_tree_keygen_sign='not_generated_or_run',comparison='complete_hash_input_result_multiset_with_multiplicity')
    (args.out/'results.json').write_text(json.dumps(row,indent=2,sort_keys=True)+'\n')
    print('STATEFUL_MODELS_PASS',args.out,len(cases),flush=True)
if __name__=='__main__':main()
