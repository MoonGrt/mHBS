#!/usr/bin/env python3
"""Build and verify instruction images, the instruction VM, and a shared RTL core."""
from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from model.mHBS import compile_micro, compile_test_tree
from model.executor import MicroMachine
from model.profiles import SLH_NAMES, get_profile
from model.stateful import STATEFUL_NAMES
from model.vectors import generate_fixture,check_fixture,write_fixture
ALL_NAMES=(*SLH_NAMES,*STATEFUL_NAMES)
from model.reference import slh_dsa
from model.vectors import default_job, Observation, KAT

def profile_arg(value):
    if value=='all': return value
    if 'omega' in value.lower():
        raise argparse.ArgumentTypeError('omega 配置已移除；请迁移为 xmss_h10/h16/h20 或 lms_h10/h15/h20')
    try: return get_profile(value).name
    except ValueError as error: raise argparse.ArgumentTypeError(str(error)) from error


OPERATIONS = ('keygen', 'sign', 'verify')
MACRO_FIELDS = ('macro_count','macro_busy_cycles','macro_hashes')
MACRO_PATTERN = r'MICRO_MACRO_METRICS macro_count=(\d+) macro_busy_cycles=(\d+) macro_hashes=(\d+)'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True)+'\n')


def run(command, log):
    log = Path(log); log.parent.mkdir(parents=True, exist_ok=True)
    with log.open('w') as out:
        subprocess.run(command, cwd=ROOT, stdout=out, stderr=subprocess.STDOUT, check=True)


def sources():
    return (ROOT/'sources.txt').read_text().split()


def source_identity():
    paths = sources() + ['sources.txt', 'scripts/run_hash_backends.py',
        'tb/tb.sv', 'tb/hash_trace.cpp', 'rtl/executor/instructions.svh',
        'model/microcode.py', 'model/mHBS.py', 'model/executor.py',
        'model/reference/slh_dsa.py', 'model/profiles.py', 'model/vectors.py',
        'model/stateful.py','model/reference/xmss.py','model/reference/lms.py',
        'model/reference/stateful_shake.py','model/default_jobs.json']
    return {p: sha(ROOT/p) for p in sorted(set(paths))}


def model_inputs(folder):
    folder=Path(folder)
    return {str(p.relative_to(folder)):sha(p) for directory in ('images','vectors')
            for p in sorted((folder/directory).rglob('*')) if p.is_file()}


def require_models(folder, identity):
    folder=Path(folder); gate=json.loads((folder/'models.json').read_text())
    if not gate.get('passed') or gate.get('source_sha256')!=identity:
        raise ValueError('model evidence is stale; regenerate models with a fresh tag')
    if gate.get('input_sha256')!=model_inputs(folder):
        raise ValueError('generated image/vector evidence changed; regenerate models')
    return gate


def macro_work(machine):
    """The instruction VM counts work, not implementation clock cycles."""
    return dict(macro_count=machine.macro_count,macro_hashes=machine.macro_hashes)


def macro_metrics(output, expected, stats, log, *, compare=True):
    hits = re.findall(MACRO_PATTERN,output)
    if not hits:
        if 'macro_count' in expected:
            raise ValueError('missing ABI 3 macro metrics: '+str(log))
        return dict.fromkeys(MACRO_FIELDS,0)  # Historical fixture/log compatibility.
    row = dict(zip(MACRO_FIELDS,map(int,hits[-1])))
    if not stats:
        if any(row.values()): raise ValueError('PROFILE_ENABLE=0 macro counters are not zero')
    elif compare:
        for field in ('macro_count','macro_hashes'):
            if field in expected and row[field] != expected[field]:
                raise ValueError('VM/RTL macro work differs: '+field+' '+str(log))
    return row


def task_trace_update(digest, task):
    recipe,layer,tree,leaf,a,b,result=task[:7]
    digest.update(struct.pack('<QIQIII',recipe,layer,tree,leaf,a,b)+result)
    if len(task)==8: digest.update(struct.pack('<I',task[7]))


def stateful_models_profile(name,folder):
    folder=Path(folder);profile=get_profile(name)
    image=compile_micro(name);image.write(folder/'images'/name)
    rows={}
    for label in (OPERATIONS if profile.h==10 else ('verify',)):
        fixture=generate_fixture(name,label,synthetic=profile.h!=10)
        checked=check_fixture(fixture)
        row=write_fixture(fixture,folder/'vectors'/name/label,checked=checked,write_image=False)
        output=fixture['expected'] if label!='verify' else b''
        row.update(passed=True,profile=name,operation=OPERATIONS.index(label),
            instruction_words=image.used,output_sha256=hashlib.sha256(output).hexdigest(),
            **macro_work(checked['machine']))
        write(folder/'vectors'/name/label/'result.json',row);rows[label]=row
        print('MICRO_MODEL_PASS',name,label,'words',image.used,'instructions',row['instructions'],flush=True)
    write(folder/'models'/f'{name}.json',rows)
    return name,rows


def models_profile(name, folder, serial=False, chain_macros=True):
    """The VM only executes instructions; this gate owns independent oracles."""
    folder = Path(folder); profile = get_profile(name)
    if profile.stateful: return stateful_models_profile(name,folder)
    image = compile_micro(name, serial=serial, chain_macros=chain_macros)
    image_dir = folder/'images'/name; image.write(image_dir)
    job, message = default_job(name)
    params = getattr(slh_dsa, f'SLH_DSA_SHAKE_{profile.n*8}{name[-1].upper()}')
    ref_kg_obs = Observation(profile.n)
    sk, pk = slh_dsa.keygen_internal(params, job.secret, job.prf, job.public, ref_kg_obs)
    root = pk[profile.n:]
    ref_sg_obs = Observation(profile.n)
    signature = slh_dsa.sign_internal(params, message, sk, job.random, ref_sg_obs)
    ref_vf_obs = Observation(profile.n)
    assert slh_dsa.verify_internal(params, message, signature, pk, ref_vf_obs)
    if name.endswith('f'):
        kat = json.loads(next(KAT.glob(f'slh_dsa_shake_{profile.n*8}f_siggen_acvp_tc*.json')).read_text())
        assert sk+pk == bytes.fromhex(kat['sk']+kat['pk'])
        assert hashlib.sha256(signature).hexdigest() == kat['signature_sha256']
    rows = {}
    for operation, label in enumerate(OPERATIONS):
        digest = hashlib.sha256(); obs = Observation(profile.n)
        machine = MicroMachine(image, job, root if operation else bytes(profile.n),
            message if operation else b'', operation, signature if operation==2 else b'',
            observe=obs, task_observe=lambda task: task_trace_update(digest, task),
            instruction_limit=2_000_000_000)
        start = time.monotonic(); actual = machine.run()
        assert actual == (sk+pk if operation==0 else signature if operation==1 else True), (name,label)
        ref_obs = (ref_kg_obs, ref_sg_obs, ref_vf_obs)[operation]
        # Sign skips the selected final-layer ancestors; each node it DOES
        # compute must agree with the independent algorithm's node hashes.
        for address, value in obs.nodes.items():
            assert ref_obs.nodes.get(address) == value, (name,label,address)
        if operation!=1:
            assert obs.counts == ref_obs.counts, (name,label,obs.counts,ref_obs.counts)
        baseline = ROOT/'manifests/experiments/unified_hbs_v4.2/external_job_message/vectors'/name/label/'metadata.mem'
        if operation!=2 and baseline.exists():
            old = [int(x,16) for x in baseline.read_text().split()]
            assert obs.counts == old[1:3], (name,label,'v4.2 optimization counts',obs.counts,old[1:3])
        vector = folder/'vectors'/name/label; vector.mkdir(parents=True, exist_ok=True)
        expected = sk+pk if operation==0 else signature if operation==1 else b''
        (vector/'expected.mem').write_text(''.join(f'{x:02x}\n' for x in expected) or '00\n')
        (vector/'message.mem').write_text(''.join(f'{x:02x}\n' for x in (message if operation else b'\0')))
        if operation==2:
            (vector/'nodes.mem').write_text(''.join(f'{int.from_bytes(signature[i:i+profile.n],"little"):064x}\n'
                for i in range(0,len(signature),profile.n)))
        job_words = [int.from_bytes(x,'little') for x in
            (job.secret,job.prf,job.public,job.random,root if operation else bytes(profile.n))]
        job_words += [operation,len(message) if operation else 0,profile.n]
        (vector/'job.mem').write_text(''.join(f'{w:064x}\n' for w in job_words))
        metadata = [len(expected),machine.hash_count,machine.permutation_count,operation,profile.n,
                    len(signature)//profile.n if operation==2 else 0]
        (vector/'metadata.mem').write_text(''.join(f'{w:08x}\n' for w in metadata))
        row = dict(passed=True, operation=operation, profile=name, instruction_words=image.used,
            instructions=machine.instructions, hashes=machine.hash_count, permutations=machine.permutation_count,
            hash_trace_sha256=digest.hexdigest(), seconds=time.monotonic()-start,
            output_sha256=hashlib.sha256(expected).hexdigest(), merkle_nodes=len(obs.nodes),**macro_work(machine))
        write(vector/'result.json',row); rows[label]=row
        print('MICRO_MODEL_PASS',name,label,'words',image.used,'instructions',machine.instructions,flush=True)
    write(folder/'models'/f'{name}.json',rows)
    return name, rows


def build_binary(folder, swap=0, stats=True, *, synthesis=False):
    if swap:
        raise ValueError("fixed K1U1 has one physical Hash lane and cannot swap lanes")
    folder=Path(folder)
    identity=(source_identity(),swap,stats,synthesis)
    key=hashlib.sha256(json.dumps(identity,sort_keys=True).encode()).hexdigest()[:16]
    build=folder/'binaries'/key; exe=build/'obj/Vtb'
    if not exe.exists():
        build.mkdir(parents=True,exist_ok=True)
        rtl=[p for p in sources() if p!='rtl/top/top.sv']
        flags=['-DSYNTHESIS'] if synthesis else []
        run(['verilator','--binary','--timing','-O3','-j','4','-Wno-fatal','-Wno-WIDTH',
            '-Wno-UNOPTFLAT',*flags,'--top-module','tb',f'-GSWAP={swap}',
            f'-GPROFILE_ENABLE={int(stats)}','--Mdir',str(exe.parent),*rtl,
            'tb/tb.sv',str(ROOT/'tb/hash_trace.cpp'),'-LDFLAGS','-lcrypto'],build/'compile.log')
    return exe


def simulate(folder, name, label, exe, *, suffix='', options=(), image_folder=None,
             vector_folder=None, trace=True, expected_instructions=None):
    folder=Path(folder); vector=(vector_folder or folder/'vectors')/name/label
    expected=json.loads((vector/'result.json').read_text())
    log=folder/'logs'/f'{name}_{label}{suffix}.log'
    run([str(exe),'+IMAGE='+str((image_folder or folder/'images')/name),
         '+VECTOR='+str(vector),*options],log)
    output=log.read_text()
    if any(o.startswith('+FAULT=') for o in options):
        assert 'MICRO_FAULT_PASS' in output
        return dict(passed=True,log_sha256=sha(log))
    hits=re.findall(r'MICRO_RTL_PASS operation=(\d+) n=(\d+) bytes=(\d+) nodes=(\d+) hashes=(\d+) permutations=(\d+) cycles=(\d+) waits=(\d+) swap=(\d+) stats=(\d+)',output)
    assert hits,str(log)
    row=dict(zip(('operation','n','bytes','nodes','hashes','permutations','cycles','waits','swap','stats'),map(int,hits[-1])))
    traces=re.findall(r'MICRO_HASH_TRACE ([0-9a-f]{64})',output)
    if trace: assert traces and all(t==expected['hash_trace_sha256'] for t in traces),(str(log),'per-Hash context/result mismatch',traces,expected['hash_trace_sha256'])
    metrics=re.findall(r'MICRO_METRICS instructions=(\d+) hash_waits=(\d+) overlap=(\d+) lane0_round_cycles=(\d+) lane1_round_cycles=(\d+)',output)
    assert metrics,str(log)
    row.update(zip(('instructions','hash_wait_cycles','overlap_instructions','lane0_round_cycles','lane1_round_cycles'),map(int,metrics[-1])))
    row.update(macro_metrics(output,expected,row['stats'],log,compare=trace))
    if row['macro_busy_cycles'] > row['cycles']:
        raise ValueError('macro busy cycles exceed operation cycles')
    count=expected_instructions
    if count is None and (image_folder is None or vector_folder is not None): count=expected.get('instructions')
    if trace and count is not None: assert row['instructions']==count,(str(log),'instruction retire count',row['instructions'],count)
    if row['lane1_round_cycles']!=0:
        raise ValueError('K1U1 observed activity on a second physical Hash lane')
    row['physical_lanes']=1; row['unroll']=1
    row['lane_round_utilization']=row['lane0_round_cycles']/row['cycles']
    image_path=(image_folder or folder/'images')/name
    row.update(passed=True,log_sha256=sha(log),binary_sha256=sha(exe),hash_trace_sha256=traces[-1],
        image_sha256={p.name:sha(p) for p in image_path.iterdir() if p.is_file()},
        vector_sha256={p.name:sha(p) for p in vector.iterdir() if p.is_file()})
    print('MICRO_SIM_PASS',name,label,suffix,'cycles',row['cycles'],flush=True)
    return row


def stateful_variant(folder,name,label,exe,*,q=0,synthetic=False,configuration=None,case_name=None,options=()):
    """Independent standard fixture with an explicitly selected macro schedule."""
    folder=Path(folder);configuration=configuration or {}
    fixture=generate_fixture(name,label,q=q,synthetic=synthetic)
    configuration=dict(configuration)
    image=compile_micro(name,**configuration)
    digest=hashlib.sha256()
    machine=MicroMachine(image,fixture['job'],fixture['root'],fixture['message'],fixture['operation'],
        fixture['signature'] if label=='verify' else b'',
        task_observe=lambda t:task_trace_update(digest,t),instruction_limit=(1<<64)-1)
    output=machine.run()
    if output!=fixture['expected'] or (machine.hash_count,machine.permutation_count)!=tuple(fixture['independent_counts']):
        raise ValueError('explicit/macro image differs from independent standard oracle')
    checked=dict(image=image,machine=machine,output=output,counts=(machine.hash_count,machine.permutation_count),
        instructions=machine.instructions,work_trace_sha256=machine.trace_digest.hexdigest(),
        hash_trace_sha256=digest.hexdigest(),independent_order_matches=machine.trace_digest.hexdigest()==fixture['independent_trace_sha256'])
    case_name=case_name or f'{name}_q{q}_{label}'
    variant=folder/'variants'/case_name;image.write(variant/'images'/name)
    row=write_fixture(fixture,variant/'vectors'/name/label,checked=checked,write_image=False)
    row.update(passed=True,profile=name,operation=fixture['operation'],
        output_sha256=hashlib.sha256(output if label!='verify' else b'').hexdigest(),
        **macro_work(machine))
    write(variant/'vectors'/name/label/'result.json',row)
    return simulate(folder,name,label,exe,suffix='_'+case_name,options=options,
        image_folder=variant/'images',vector_folder=variant/'vectors')


def stateful_boundary_signs(folder,names,exe):
    rows={}
    for name in names:
        p=get_profile(name)
        if not p.stateful: continue
        for q in (1,(1<<p.h)-1):
            key=f'stateful_{name}_q{q}_verify'
            rows[key]=stateful_variant(folder,name,'verify',exe,q=q,synthetic=True,
                case_name=key,options=('+STALL=1','+NOISE=1','+TAIL_NOISE=1'))
            if p.h==10:
                key=f'stateful_{name}_q{q}_sign'
                rows[key]=stateful_variant(folder,name,'sign',exe,q=q,case_name=key,options=('+STALL=1',))
        if p.h==10:
            key=f'stateful_{name}_explicit_verify'
            rows[key]=stateful_variant(folder,name,'verify',exe,q=1,synthetic=True,
                configuration={'chain_macros':False},case_name=key)
    return rows


def image_variants(folder, name, exe):
    """Same executable, alternative chain scheduling and tree algorithms."""
    folder=Path(folder); rows={}
    job,message=default_job(name); n=get_profile(name).n
    keygen=bytes(int(x,16) for x in (folder/'vectors'/name/'keygen/expected.mem').read_text().split())
    signature=bytes(int(x,16) for x in (folder/'vectors'/name/'sign/expected.mem').read_text().split())
    root=keygen[3*n:4*n]
    for variant_name,configuration in (('explicit',dict(chain_macros=False)),
            ('serial',dict(serial=True,chain_macros=False))):
        image=compile_micro(name,**configuration)
        variant_root=folder/'variants'/variant_name; image.write(variant_root/'images'/name)
        for operation,label in enumerate(OPERATIONS):
            digest=hashlib.sha256()
            machine=MicroMachine(image,job,root if operation else bytes(n),
                message if operation else b'',operation,signature if operation==2 else b'',
                task_observe=lambda task:task_trace_update(digest,task),instruction_limit=2_000_000_000)
            assert machine.run()==(keygen if operation==0 else signature if operation==1 else True)
            vector=variant_root/'vectors'/name/label
            shutil.copytree(folder/'vectors'/name/label,vector,dirs_exist_ok=True)
            oracle=json.loads((vector/'result.json').read_text())
            assert (machine.hash_count,machine.permutation_count)==(oracle['hashes'],oracle['permutations'])
            if variant_name == 'explicit':
                assert digest.hexdigest()==oracle['hash_trace_sha256'], 'macro/explicit Hash order differs'
            oracle.update(instructions=machine.instructions,instruction_words=image.used,
                hash_trace_sha256=digest.hexdigest(),**macro_work(machine))
            write(vector/'result.json',oracle)
            rows[variant_name+'_'+label]=simulate(folder,name,label,exe,suffix='_'+variant_name,
                image_folder=variant_root/'images',vector_folder=variant_root/'vectors')
    tasks=[]; outputs=[]
    for level_order in (False,True):
        label='tree_level' if level_order else 'tree_stack'
        variant=folder/'variants'/label; image=compile_test_tree(name,height=3,level_order=level_order)
        image.write(variant/'images'/name)
        digest=hashlib.sha256()
        m=MicroMachine(image,job,bytes(n),b'',0,record_tasks=True,
            task_observe=lambda task:task_trace_update(digest,task))
        actual=m.run(); tasks.append(sorted(m.task_trace)); outputs.append(actual)
        vector=variant/'vectors'/name/'keygen'; vector.mkdir(parents=True,exist_ok=True)
        (vector/'expected.mem').write_text(''.join(f'{x:02x}\n' for x in actual))
        words=[int.from_bytes(x,'little') for x in (job.secret,job.prf,job.public,job.random,bytes(n))]+[0,0,n]
        (vector/'job.mem').write_text(''.join(f'{w:064x}\n' for w in words))
        (vector/'metadata.mem').write_text(''.join(f'{w:08x}\n' for w in
            (len(actual),m.hash_count,m.permutation_count,0,n,0)))
        write(vector/'result.json',dict(hash_trace_sha256=digest.hexdigest(),instructions=m.instructions,**macro_work(m)))
        rows[label]=simulate(folder,name,'keygen',exe,suffix='_'+label,
            image_folder=variant/'images',vector_folder=variant/'vectors')
    assert tasks[0]==tasks[1] and outputs[0]==outputs[1]
    # Independent bytes-only small FORS tree. No ISA/compiler helpers.
    def addressed(domain,height,index,payload):
        adrs=b''.join(x.to_bytes(4,'big') for x in (0,0,0,0,domain,0,height,index))
        return hashlib.shake_256(job.public+adrs+payload).digest(n)
    leaves=[addressed(3,0,i,addressed(6,0,i,job.secret)) for i in range(8)]
    for level in range(1,4):
        leaves=[addressed(3,level,i//2,leaves[i]+leaves[i+1]) for i in range(0,len(leaves),2)]
    assert outputs[0]==leaves[0]*6
    return rows


def message_variant(folder, name, length, exe):
    """Exercise block/beat boundaries and independent optional randomness."""
    folder=Path(folder); p=get_profile(name); n=p.n; job,_=default_job(name)
    # Deliberately use a randomizer different from PK.seed.
    from dataclasses import replace
    job=replace(job,random=bytes(x^0x5a for x in job.random))
    raw=(folder/'vectors'/name/'keygen'/'expected.mem').read_text().split()
    sk=bytes(int(x,16) for x in raw)[:4*n]; root=sk[-n:]
    message=bytes((i*7+length)&255 for i in range(length))
    params=getattr(slh_dsa,f'SLH_DSA_SHAKE_{n*8}{name[-1].upper()}')
    signature=slh_dsa.sign_internal(params,message,sk,job.random)
    assert slh_dsa.verify_internal(params,message,signature,job.public+root)
    variant=folder/'variants'/f'message_{name}_{length}'; image=compile_micro(name); image.write(variant/'images'/name)
    rows={}
    for operation,label in ((1,'sign'),(2,'verify')):
        digest=hashlib.sha256()
        m=MicroMachine(image,job,root,message,operation,signature if operation==2 else b'',
            task_observe=lambda t:task_trace_update(digest,t),instruction_limit=2_000_000_000)
        assert m.run()==(signature if operation==1 else True)
        vector=variant/'vectors'/name/label; vector.mkdir(parents=True,exist_ok=True)
        output=signature if operation==1 else b''
        (vector/'expected.mem').write_text(''.join(f'{x:02x}\n' for x in output) or '00\n')
        (vector/'message.mem').write_text(''.join(f'{x:02x}\n' for x in message))
        (vector/'nodes.mem').write_text(''.join(f'{int.from_bytes(signature[i:i+n],"little"):064x}\n' for i in range(0,len(signature),n)))
        words=[int.from_bytes(x,'little') for x in (job.secret,job.prf,job.public,job.random,root)]+[operation,length,n]
        (vector/'job.mem').write_text(''.join(f'{x:064x}\n' for x in words))
        (vector/'metadata.mem').write_text(''.join(f'{x:08x}\n' for x in
            (len(output),m.hash_count,m.permutation_count,operation,n,len(signature)//n if operation==2 else 0)))
        write(vector/'result.json',dict(instructions=m.instructions,hash_trace_sha256=digest.hexdigest(),**macro_work(m)))
        rows[f'{name}_message_{length}_{label}']=simulate(folder,name,label,exe,
            suffix=f'_message_{length}',options=('+STALL=1','+TAIL_NOISE=1','+NOISE=1'),
            image_folder=variant/'images',vector_folder=variant/'vectors')
    return rows


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=('images','models','rtl','all'))
    parser.add_argument('--tag',default='image_chain')
    parser.add_argument('--profile',type=profile_arg,choices=('all',*ALL_NAMES,'xmss','lms'),default='all')
    parser.add_argument('--operation',choices=('all',*OPERATIONS),default='all')
    parser.add_argument('--jobs',type=int,default=3)
    parser.add_argument('--extended',action='store_true')
    parser.add_argument('--stateful-boundaries',action='store_true',help='q=1/max real-height Verify, h10 complete Sign and explicit Verify; never large-tree Sign')
    args=parser.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.-]*',args.tag): parser.error('invalid tag')
    folder=ROOT/'build/hashflow'/args.tag; folder.mkdir(parents=True,exist_ok=True)
    identity=source_identity()
    selected=args.profile if args.profile=='all' else get_profile(args.profile).name
    names=[n for n in ALL_NAMES if selected in ('all',n)]
    if selected!='all' and get_profile(selected).stateful and get_profile(selected).h!=10 and args.operation in ('keygen','sign'):
        parser.error('higher-tree complete Keygen/Sign remain stopped; use --operation verify')
    if args.action=='images':
        for name in names:
            image=compile_micro(name); image.write(ROOT/'tb/vectors'/name)
            print('MICRO_IMAGE',name,image.used,image.entries)
        return
    if args.action in ('models','all'):
        with concurrent.futures.ProcessPoolExecutor(args.jobs) as pool:
            futures=[pool.submit(models_profile,n,folder) for n in names]
            models=dict(f.result() for f in futures)
        if source_identity()!=identity: raise ValueError('sources changed during model gate; use a fresh tag')
        write(folder/'models.json',dict(passed=True,profiles=models,source_sha256=identity,
            input_sha256=model_inputs(folder)))
    if args.action in ('rtl','all'):
        gate=require_models(folder,identity)
        if not set(names).issubset(gate['profiles']):
            raise ValueError('requested profiles are missing from model evidence; regenerate models')
        exe=build_binary(folder)
        cases={}
        tasks=[(n,o) for n in names for o in OPERATIONS
            if args.operation in ('all',o) and o in gate['profiles'][n]]
        with concurrent.futures.ThreadPoolExecutor(args.jobs) as pool:
            pending={(n,o):pool.submit(simulate,folder,n,o,exe) for n,o in tasks}
            for (n,o),future in pending.items(): cases[n+'/'+o]=future.result()
        if args.extended and any(n in SLH_NAMES for n in names):
            # Representative protocol checks include all input domains and
            # asymmetric paired Verify chains without rebuilding for each Job.
            name=next(n for n in names if n in SLH_NAMES)
            for label,options in [('stall',('+STALL=1',)),('reset',('+INTERRUPT=1',)),
                                   ('replay',('+REPLAY=1',)),('truncated',('+CUT=5',))]:
                cases[label]=simulate(folder,name,'verify',exe,suffix='_'+label,options=options)
            for label,options in [('signature',('+FLIP=2','+EXPECT=0')),
                                  ('message',('+BAD_MESSAGE=1','+EXPECT=0')),
                                  ('root',('+ROOT_BIT=0','+EXPECT=0'))]:
                cases[label]=simulate(folder,name,'verify',exe,suffix='_'+label,options=options,trace=False)
            cases['fault']=simulate(folder,name,'verify',exe,suffix='_fault',options=('+FAULT=1',),trace=False)
            cases['lane_fault']=simulate(folder,name,'verify',exe,suffix='_lane_fault',options=('+FAULT=2',),trace=False)
            for label,code in (('old_abi',4),('reserved_bits',5),('bad_selector',6),('counter_overflow',7),('paired_issue',8),('old_abi2',9),('wrong_abi4',10),('wrong_abi5',11)):
                cases[label]=simulate(folder,name,'verify',exe,suffix='_'+label,options=(f'+FAULT={code}',),trace=False)
            for label,options in [('length0',('+FAULT=3','+BAD_LENGTH=0')),
                                  ('length88',('+FAULT=3','+BAD_LENGTH=88')),
                                  ('operation3',('+FAULT=3','+BAD_OPERATION=3'))]:
                cases[label]=simulate(folder,name,'verify',exe,suffix='_'+label,options=options,trace=False)
            cases['padding']=simulate(folder,name,'verify',exe,suffix='_padding',
                options=('+NOISE=1','+ROOT_NOISE=1','+TAIL_NOISE=1'))
            cases['sign_reset']=simulate(folder,name,'sign',exe,suffix='_reset',options=('+INTERRUPT=1',))
            for operation,case in (('verify','macro_reset'),('sign','macro_sign_reset')):
                cases[case]=simulate(folder,name,operation,exe,suffix='_'+case,options=('+CHAIN_INTERRUPT=1',))
            for stats,label in [(False,'no_stats')]:
                binary=build_binary(folder,0,stats)
                cases[label]=simulate(folder,name,'verify',binary,suffix='_'+label)
            cases.update(image_variants(folder,name,exe))
            if name.endswith('f'):
                for length in (7,8,9,87): cases.update(message_variant(folder,name,length,exe))
            for other in (n for n in names if n in SLH_NAMES):
                if other!=name and other.endswith('f'):
                    cases.update(message_variant(folder,other,87,exe))
                n=get_profile(other).n
                if n>16:
                    cases[other+'_root128']=simulate(folder,other,'verify',exe,suffix='_root128',
                        options=('+ROOT_BIT=128','+EXPECT=0'),trace=False)
                if n==32:
                    cases[other+'_root192']=simulate(folder,other,'verify',exe,suffix='_root192',
                        options=('+ROOT_BIT=192','+EXPECT=0'),trace=False)
        if args.stateful_boundaries: cases.update(stateful_boundary_signs(folder,names,exe))
        if source_identity()!=identity: raise ValueError('sources changed during RTL gate; use a fresh tag')
        write(folder/'rtl.json',dict(passed=True,cases=cases,source_sha256=identity))


if __name__=='__main__':main()
