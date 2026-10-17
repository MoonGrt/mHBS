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
from model.reference import slh_dsa
from model.vectors import default_job, Observation, KAT
from scripts.common_partition import partition

OPERATIONS = ('keygen', 'sign', 'verify')
MACRO_FIELDS = ('macro_count','macro_busy_cycles','macro_hashes')
MACRO_PATTERN = r'MICRO_MACRO_METRICS macro_count=(\d+) macro_busy_cycles=(\d+) macro_hashes=(\d+)'
TREE_FIELDS = ('tree_count','tree_busy_cycles','tree_hashes','tree_chains','tree_input_wait_cycles','tree_child_busy_cycles')
TREE_PATTERN = (r'MICRO_TREE_METRICS tree_count=(\d+) tree_busy_cycles=(\d+) '
    r'tree_hashes=(\d+) tree_chains=(\d+) tree_input_wait_cycles=(\d+) tree_child_busy_cycles=(\d+)')
TREE_EXTRA_CASES = frozenset({'old_abi3','tree_bad_kind','tree_bad_mode','tree_bad_flags',
    'tree_bad_recipe','tree_reset','tree_sign_reset','tree_snapshot','tree_fault',
    'chain_keygen','chain_sign','chain_verify'})


def expected_cases():
    """The ABI 4 gate's complete case set, independent of historical reporters."""
    normal={name+'/'+operation for name in SLH_NAMES for operation in OPERATIONS}
    extended={'stall','reset','replay','truncated','signature','message','root','fault','lane_fault',
        'length0','length88','operation3','padding','sign_reset','no_stats',
        'serial_keygen','serial_sign','serial_verify','tree_stack','tree_level',
        'old_abi','reserved_bits','bad_selector','counter_overflow','old_abi2','paired_issue',
        'macro_reset','macro_sign_reset','explicit_keygen','explicit_sign','explicit_verify'}
    for name in SLH_NAMES:
        lengths=(7,8,9,87) if name==SLH_NAMES[0] else (87,) if name.endswith('f') else ()
        extended.update(f'{name}_message_{length}_{operation}'
            for length in lengths for operation in ('sign','verify'))
        if get_profile(name).n>16: extended.add(name+'_root128')
        if get_profile(name).n==32: extended.add(name+'_root192')
    return normal,extended|TREE_EXTRA_CASES


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
    return [p for p in (ROOT/'sources.txt').read_text().split() if p != 'rtl/top/common.sv']


def source_identity():
    paths = sources() + ['rtl/top/common.sv','sources.txt','docs/ISA.md', 'scripts/run_hash_backends.py',
        'scripts/common_partition.py', 'tb/tb.sv',
        'tb/hash_trace.cpp', 'rtl/executor/instructions.svh', 'model/microcode.py',
        'model/mHBS.py', 'model/executor.py', 'model/reference/slh_dsa.py',
        'model/profiles.py', 'model/vectors.py']
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


def tree_work(machine):
    """TREE owns its child chains; these counters are not standalone CHAIN work."""
    return dict(tree_count=machine.tree_count,tree_hashes=machine.tree_hashes,
                tree_chains=machine.tree_chains)


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


def tree_metrics(output, expected, stats, log, *, compare=True):
    hits=re.findall(TREE_PATTERN,output)
    if not hits:
        if 'tree_count' in expected:
            raise ValueError('missing ABI 4 TREE metrics: '+str(log))
        return dict.fromkeys(TREE_FIELDS,0)  # Historical fixture/log compatibility.
    row=dict(zip(TREE_FIELDS,map(int,hits[-1])))
    if not stats:
        if any(row.values()): raise ValueError('PROFILE_ENABLE=0 TREE counters are not zero')
    elif compare:
        for field in ('tree_count','tree_hashes','tree_chains'):
            if field in expected and row[field]!=expected[field]:
                raise ValueError('VM/RTL TREE work differs: '+field+' '+str(log))
    if row['tree_input_wait_cycles']>row['tree_busy_cycles']:
        raise ValueError('TREE input waits exceed its inclusive busy cycles')
    if row['tree_child_busy_cycles']>row['tree_busy_cycles']:
        raise ValueError('TREE child-chain busy cycles exceed its inclusive busy cycles')
    return row


def task_trace_update(digest, task):
    recipe, layer, tree, leaf, a, b, result = task
    digest.update(struct.pack('<QIQIII', recipe, layer, tree, leaf, a, b) + result)


def models_profile(name, folder, serial=False, chain_macros=True, tree_macros=True):
    """The VM only executes instructions; this gate owns independent oracles."""
    folder = Path(folder); profile = get_profile(name)
    image = compile_micro(name, serial=serial, chain_macros=chain_macros,tree_macros=tree_macros)
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
            output_sha256=hashlib.sha256(expected).hexdigest(), merkle_nodes=len(obs.nodes),
            **macro_work(machine),**tree_work(machine))
        write(vector/'result.json',row); rows[label]=row
        print('MICRO_MODEL_PASS',name,label,'words',image.used,'instructions',machine.instructions,flush=True)
    write(folder/'models'/f'{name}.json',rows)
    return name, rows


def build_binary(folder, swap=0, stats=True):
    if swap:
        raise ValueError("fixed K1U1 has one physical Hash lane and cannot swap lanes")
    folder = Path(folder)
    identity = (source_identity(), swap, stats)
    key = hashlib.sha256(json.dumps(identity,sort_keys=True).encode()).hexdigest()[:16]
    build = folder/'binaries'/key; exe=build/'obj/Vtb'
    if not exe.exists():
        build.mkdir(parents=True,exist_ok=True)
        top_path = next(p for p in sources() if p.endswith('/top.sv'))
        common,_=partition((ROOT/top_path).read_text()); (build/'common.sv').write_text(common)
        rtl=[p for p in sources() if p!=top_path]+[str(build/'common.sv')]
        run(['verilator','--binary','--timing','-O3','-j','2','-Wno-fatal','-Wno-WIDTH',
            '-Wno-UNOPTFLAT','--top-module','tb',f'-GSWAP={swap}',
            f'-GPROFILE_ENABLE={int(stats)}','--Mdir',str(exe.parent),*rtl,
            'tb/tb.sv',str(ROOT/'tb/hash_trace.cpp'),
            '-LDFLAGS','-lcrypto'],build/'compile.log')
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
    row.update(tree_metrics(output,expected,row['stats'],log,compare=trace))
    owner_traces=re.findall(r'MICRO_OWNER_TRACE ([0-9a-f]{64})',output)
    if 'tree_count' in expected and not owner_traces:
        raise ValueError('missing per-physical-Hash ownership trace: '+str(log))
    if owner_traces: row['owner_trace_sha256']=owner_traces[-1]
    if row['macro_busy_cycles'] > row['cycles']:
        raise ValueError('macro busy cycles exceed operation cycles')
    if row['tree_busy_cycles']>row['cycles'] or row['tree_busy_cycles']+row['macro_busy_cycles']>row['cycles']:
        raise ValueError('exclusive standalone CHAIN and inclusive TREE busy periods overlap')
    if row['stats'] and row['tree_hashes']+row['macro_hashes']>row['hashes']:
        raise ValueError('Hash work has more than one macro owner')
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


def image_variants(folder, name, exe):
    """Same executable, alternative chain scheduling and tree algorithms."""
    folder=Path(folder); rows={}
    job,message=default_job(name); n=get_profile(name).n
    keygen=bytes(int(x,16) for x in (folder/'vectors'/name/'keygen/expected.mem').read_text().split())
    signature=bytes(int(x,16) for x in (folder/'vectors'/name/'sign/expected.mem').read_text().split())
    root=keygen[3*n:4*n]
    # Exact, multiplicity-preserving comparison across all three architecture
    # images. Different schedules need not have the same ordered task trace.
    def work_digest(tasks):
        keys=[]
        for task in tasks:
            digest=hashlib.sha256();task_trace_update(digest,task);keys.append(digest.digest())
        return hashlib.sha256(b''.join(sorted(keys))).hexdigest()
    expected_work={};comparisons={}
    default_image_sha256={path.name:sha(path) for path in (folder/'images'/name).iterdir() if path.is_file()}
    for operation,label in enumerate(OPERATIONS):
        reference=MicroMachine(compile_micro(name),job,root if operation else bytes(n),
            message if operation else b'',operation,signature if operation==2 else b'',
            record_tasks=True,instruction_limit=2_000_000_000)
        reference.run();expected_work[label]=dict(hash_task_multiset_sha256=work_digest(reference.task_trace),
            hashes=reference.hash_count,permutations=reference.permutation_count)
    for variant_name,configuration in (('chain',dict(tree_macros=False)),
            ('explicit',dict(chain_macros=False)),
            ('serial',dict(serial=True,chain_macros=False))):
        image=compile_micro(name,**configuration)
        variant_root=folder/'variants'/variant_name; image.write(variant_root/'images'/name)
        for operation,label in enumerate(OPERATIONS):
            digest=hashlib.sha256()
            machine=MicroMachine(image,job,root if operation else bytes(n),
                message if operation else b'',operation,signature if operation==2 else b'',
                task_observe=lambda task:task_trace_update(digest,task),record_tasks=True,
                instruction_limit=2_000_000_000)
            assert machine.run()==(keygen if operation==0 else signature if operation==1 else True)
            vector=variant_root/'vectors'/name/label
            shutil.copytree(folder/'vectors'/name/label,vector,dirs_exist_ok=True)
            oracle=json.loads((vector/'result.json').read_text())
            assert (machine.hash_count,machine.permutation_count)==(oracle['hashes'],oracle['permutations'])
            taskset=work_digest(machine.task_trace)
            assert taskset==expected_work[label]['hash_task_multiset_sha256'],(variant_name,label,'cross-image Hash multiset differs')
            oracle.update(instructions=machine.instructions,instruction_words=image.used,
                hash_trace_sha256=digest.hexdigest(),hash_task_multiset_sha256=taskset,
                default_task_multiset_sha256=expected_work[label]['hash_task_multiset_sha256'],
                default_image_sha256=default_image_sha256,
                **macro_work(machine),**tree_work(machine))
            write(vector/'result.json',oracle)
            rows[variant_name+'_'+label]=simulate(folder,name,label,exe,suffix='_'+variant_name,
                image_folder=variant_root/'images',vector_folder=variant_root/'vectors')
            comparisons[variant_name+'_'+label]=dict(passed=True,
                default_hash_task_multiset_sha256=expected_work[label]['hash_task_multiset_sha256'],
                variant_hash_task_multiset_sha256=taskset,hashes=machine.hash_count,
                permutations=machine.permutation_count,image_sha256=rows[variant_name+'_'+label]['image_sha256'],
                vector_result_sha256=sha(vector/'result.json'))
    write(folder/'variants/work_comparison.json',dict(passed=True,
        format='hbs_abi4_image_task_multiset_v1',profile=name,source_sha256=source_identity(),
        fingerprint='SHA256(u64le(recipe)||u32le(layer)||u64le(tree)||u32le(leaf)||u32le(a)||u32le(b)||result49)',
        reduction='SHA256(concatenated sorted 32-byte task fingerprints, retaining duplicates)',
        default_image_sha256=default_image_sha256,default=expected_work,cases=comparisons))
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
        write(vector/'result.json',dict(hash_trace_sha256=digest.hexdigest(),instructions=m.instructions,
            **macro_work(m),**tree_work(m)))
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
        write(vector/'result.json',dict(instructions=m.instructions,hash_trace_sha256=digest.hexdigest(),
            **macro_work(m),**tree_work(m)))
        rows[f'{name}_message_{length}_{label}']=simulate(folder,name,label,exe,
            suffix=f'_message_{length}',options=('+STALL=1','+TAIL_NOISE=1','+NOISE=1'),
            image_folder=variant/'images',vector_folder=variant/'vectors')
    return rows


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=('images','models','rtl','all'))
    parser.add_argument('--tag',default='micro_v4')
    parser.add_argument('--profile',choices=('all',*SLH_NAMES),default='all')
    parser.add_argument('--operation',choices=('all',*OPERATIONS),default='all')
    parser.add_argument('--jobs',type=int,default=3)
    parser.add_argument('--extended',action='store_true')
    args=parser.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.-]*',args.tag): parser.error('invalid tag')
    folder=ROOT/'build/image-chain-tree'/args.tag; folder.mkdir(parents=True,exist_ok=True)
    identity=source_identity()
    names=[n for n in SLH_NAMES if args.profile in ('all',n)]
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
        tasks=[(n,o) for n in names for o in OPERATIONS if args.operation in ('all',o)]
        with concurrent.futures.ThreadPoolExecutor(args.jobs) as pool:
            pending={(n,o):pool.submit(simulate,folder,n,o,exe) for n,o in tasks}
            for (n,o),future in pending.items(): cases[n+'/'+o]=future.result()
        if args.extended:
            # Representative protocol checks include all input domains and
            # asymmetric paired Verify chains without rebuilding for each Job.
            name=names[0]
            for label,options in [('stall',('+STALL=1',)),('reset',('+INTERRUPT=1',)),
                                   ('replay',('+REPLAY=1',)),('truncated',('+CUT=5',))]:
                cases[label]=simulate(folder,name,'verify',exe,suffix='_'+label,options=options)
            for label,options in [('signature',('+FLIP=2','+EXPECT=0')),
                                  ('message',('+BAD_MESSAGE=1','+EXPECT=0')),
                                  ('root',('+ROOT_BIT=0','+EXPECT=0'))]:
                cases[label]=simulate(folder,name,'verify',exe,suffix='_'+label,options=options,trace=False)
            cases['fault']=simulate(folder,name,'verify',exe,suffix='_fault',options=('+FAULT=1',),trace=False)
            cases['lane_fault']=simulate(folder,name,'verify',exe,suffix='_lane_fault',options=('+FAULT=2',),trace=False)
            for label,code in (('old_abi',4),('reserved_bits',5),('bad_selector',6),('counter_overflow',7),('paired_issue',8),('old_abi2',9)):
                cases[label]=simulate(folder,name,'verify',exe,suffix='_'+label,options=(f'+FAULT={code}',),trace=False)
            for label,code in (('old_abi3',10),('tree_bad_kind',11),('tree_bad_mode',12),
                               ('tree_bad_flags',13),('tree_bad_recipe',14)):
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
            for operation,case in (('verify','tree_reset'),('sign','tree_sign_reset')):
                cases[case]=simulate(folder,name,operation,exe,suffix='_'+case,options=('+TREE_INTERRUPT=1',))
            cases['tree_snapshot']=simulate(folder,name,'sign',exe,suffix='_tree_snapshot',options=('+TREE_SNAPSHOT=1',))
            cases['tree_fault']=simulate(folder,name,'sign',exe,suffix='_tree_fault',options=('+FAULT=16',),trace=False)
            for stats,label in [(False,'no_stats')]:
                binary=build_binary(folder,0,stats)
                cases[label]=simulate(folder,name,'verify',binary,suffix='_'+label)
            cases.update(image_variants(folder,name,exe))
            if name.endswith('f'):
                for length in (7,8,9,87): cases.update(message_variant(folder,name,length,exe))
            for other in names:
                if other!=name and other.endswith('f'):
                    cases.update(message_variant(folder,other,87,exe))
                n=get_profile(other).n
                if n>16:
                    cases[other+'_root128']=simulate(folder,other,'verify',exe,suffix='_root128',
                        options=('+ROOT_BIT=128','+EXPECT=0'),trace=False)
                if n==32:
                    cases[other+'_root192']=simulate(folder,other,'verify',exe,suffix='_root192',
                        options=('+ROOT_BIT=192','+EXPECT=0'),trace=False)
        if source_identity()!=identity: raise ValueError('sources changed during RTL gate; use a fresh tag')
        write(folder/'rtl.json',dict(passed=True,cases=cases,source_sha256=identity))


if __name__=='__main__':main()
