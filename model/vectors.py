"""SLH KAT inputs and hash trace observations shared by current validation."""
import hashlib
import json
from pathlib import Path
from model.profiles import get_profile
from model.executor import Job

KAT = Path(__file__).resolve().parents[1] / 'tb/kat'


def default_job(name):
    profile = get_profile(name)
    if profile.family != 'slh':
        raise ValueError('Only SLH profiles are supported by current fixtures')
    # For s profiles these are deterministic seeds, not claimed s ACVP vectors.
    vector = json.loads(next(KAT.glob(f'slh_dsa_shake_{profile.n*8}f_siggen_acvp_tc*.json')).read_text())
    secret_key, n = bytes.fromhex(vector['sk']), profile.n
    return Job(secret_key[:n], secret_key[n:2*n], secret_key[2*n:3*n], secret_key[2*n:3*n]), bytes.fromhex(vector['message'])


class Observation:
    def __init__(self,n):
        self.n=n;self.counts=[0,0];self.trace=hashlib.sha256();self.nodes={}
    def __call__(self,kind,data,result):
        self.counts[0]+=1;self.counts[1]+=len(data)//136+1
        self.trace.update(len(data).to_bytes(4,'little')+data+result)
        # Addressed Merkle/FORS nodes have domain 2/3 and a full 32-byte ADRS.
        n=self.n
        if len(data) in (2*n+32,3*n+32):
            adr=data[n:n+32];domain=int.from_bytes(adr[16:20],'big')
            if domain in (2,3):self.nodes[adr.hex()]=result.hex()
    def record(self):
        return dict(counts=self.counts,hash_trace_sha256=self.trace.hexdigest(),
                    nodes=len(self.nodes),nodes_sha256=hashlib.sha256(json.dumps(self.nodes,sort_keys=True).encode()).hexdigest())


"""Independent fixtures for the standard SHAKE stateful extension.

Fixture construction imports only direct algorithms. ``check_fixture`` is a
separate instruction-model check: it cannot change oracle bytes or counts.
Complete h20 Keygen/Sign is intentionally unavailable from this entry point.
"""
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import struct
import time

from model.profiles import get_profile
from model.reference import slh_dsa
from model.reference.stateful_shake import reference
from model.stateful import signature_to_payload
from model.executor import Job

SECRET=bytes(range(32))
PRF=bytes(range(32,64))
PUBLIC=bytes(range(64,96))
RANDOM=bytes(range(96,128))
IDENTIFIER=bytes(range(16))
OPERATIONS={"keygen":0,"sign":1,"verify":2}


class IndependentObservation:
    """Count actual primitive calls, without retaining a full-tree trace."""
    def __init__(self,hash_backend):
        self.hash_backend=hash_backend
        self.counts=[0,0]
        self.trace=hashlib.sha256()
    def __call__(self,kind,data,result):
        self.counts[0]+=1
        self.counts[1]+=(len(data)+72)//64 if self.hash_backend == "sha2" else len(data)//136+1
        self.trace.update(len(data).to_bytes(4,"little")+data+result)
    @property
    def trace_sha256(self): return self.trace.hexdigest()


@lru_cache(maxsize=1)
def _defaults():
    return json.loads(Path(__file__).with_name("default_jobs.json").read_text())


def _job(profile,q):
    config=_defaults()[profile.name]
    return Job(*(bytes.fromhex(config[key]) for key in
                 ("secret_seed","secret_prf","public_seed","randomizer")),
               bytes.fromhex(config["identifier"]),0 if profile.family == "slh" else q)


def _slh_params(name,backend):
    return getattr(slh_dsa,f"SLH_DSA_{backend.upper()}_128{name[-1].upper()}") if backend == "sha2" else getattr(
        slh_dsa,f"SLH_DSA_SHAKE_{get_profile(name).n*8}{name[-1].upper()}")


@lru_cache(maxsize=24)
def _keys(name,backend):
    p=get_profile(name,backend); job=_job(p,0); obs=IndependentObservation(backend)
    if p.stateful:
        module=reference(p.family,backend)
        if p.family == "xmss": private,public=module.keygen(name,job.secret,job.prf,job.public,obs)
        else: private,public=module.keygen(name,job.secret,job.identifier,obs)
    else:
        private,public=slh_dsa.keygen_internal(_slh_params(name,backend),job.secret,job.prf,job.public,obs)
    return private,public,tuple(obs.counts),obs.trace_sha256


@lru_cache(maxsize=64)
def _synthetic(name,backend,q):
    p=get_profile(name,backend); module=reference(p.family,backend); job=_job(p,q)
    path=tuple(hashlib.sha256(b"ABI5 independent sibling"+name.encode()+q.to_bytes(4,"big")+bytes([level])).digest()
               for level in range(p.h))
    if p.family == "xmss":
        node=module.l_tree(module.wots_public_key(job.secret,job.public,q),job.public,q)
        for level,sibling in enumerate(path):
            left,right=(sibling,node) if q>>level&1 else (node,sibling)
            node=module.randomized_hash(left,right,job.public,kind=2,level=level,index=q>>(level+1))
        private=module.PrivateKey(module.get_params(name),job.secret,job.prf,job.public,node,q)
    else:
        node=module.leaf_hash(name,job.identifier,q,module.lmots_public_key(job.secret,job.identifier,q))
        heap=(1<<p.h)+q
        for sibling in path:
            left,right=(sibling,node) if heap&1 else (node,sibling)
            heap>>=1
            node=module.parent_hash(job.identifier,heap,left,right)
        private=module.PrivateKey(module.get_params(name),job.secret,job.identifier,node,q)
    return private,private.public_key,path


@lru_cache(maxsize=64)
def _signed(name,backend,q,message,synthetic):
    p=get_profile(name,backend); job=_job(p,q); obs=IndependentObservation(backend)
    if synthetic:
        private,public,path=_synthetic(name,backend,q)
    else:
        private,public,_,_=_keys(name,backend); path=None
    if p.stateful:
        module=reference(p.family,backend)
        if p.family == "xmss":
            result=(module.sign_with_auth(private,message,path,index=q,observe=obs) if synthetic
                    else module.sign(private,message,index=q,observe=obs))
        else:
            result=(module.sign_with_auth(private,message,job.random,path,index=q,observe=obs) if synthetic
                    else module.sign(private,message,job.random,index=q,observe=obs))
        signature=result.signature
    else:
        signature=slh_dsa.sign_internal(_slh_params(name,backend),message,private,job.random,obs)
    return signature,public,tuple(obs.counts),obs.trace_sha256


def generate_fixture(profile,operation,*,hash_backend="shake",q=0,message=None,synthetic=False):
    """Return a backend-specific independent oracle for one hardware Job.

    Keys: job, root, message, expected (bytes/True), signature (node payload),
    standard_pk, standard_sig, independent_counts, independent_trace_sha256,
    profile, hash_backend, operation and synthetic. The cached tree and signing
    result are reused across Keygen/Sign/Verify. Synthetic paths are permitted
    only for Verify and are labelled; they never claim full-tree execution.
    """
    operation=OPERATIONS.get(operation,operation)
    if operation not in (0,1,2): raise ValueError("operation")
    p=get_profile(profile,hash_backend); profile=p.name
    if type(q) is not int or q < 0 or (p.stateful and q >= 1<<p.h) or (not p.stateful and q):
        raise ValueError("signature index range")
    if synthetic and (operation != 2 or not p.stateful): raise ValueError("synthetic paths are Verify-only stateful fixtures")
    if p.stateful and p.h != 10 and not synthetic:
        raise ValueError("higher-tree complete Keygen/Sign are not generated; request synthetic Verify")
    if message is None: message=bytes.fromhex(_defaults()[profile]["message"])
    if not isinstance(message,bytes) or not (0 if p.stateful else 1)<=len(message)<=87:
        raise ValueError("message length")
    job=_job(p,q); actual_message=b"" if operation == 0 else message
    if operation == 0:
        private,public,counts,trace=_keys(profile,hash_backend)
        standard_sig=payload=b""
        expected=public.root if p.stateful else private+public
    else:
        standard_sig,public,counts,trace=_signed(profile,hash_backend,q,message,synthetic)
        payload=signature_to_payload(profile,standard_sig,hash_backend=hash_backend)[1] if p.stateful else standard_sig
        expected=payload
        if operation == 2:
            obs=IndependentObservation(hash_backend)
            valid=(reference(p.family,hash_backend).verify(public,message,standard_sig,obs) if p.stateful else
                   slh_dsa.verify_internal(_slh_params(profile,hash_backend),message,standard_sig,public,obs))
            if not valid: raise AssertionError("independent generated signature failed verification")
            expected=True; counts=tuple(obs.counts); trace=obs.trace_sha256
    encoded_pk=public.to_bytes() if p.stateful else public
    root=public.root if p.stateful else public[p.n:]
    return dict(profile=profile,hash_backend=hash_backend,operation=operation,job=job,root=root,
                message=actual_message,expected=expected,signature=payload,standard_pk=encoded_pk,
                standard_sig=standard_sig,independent_counts=counts,independent_trace_sha256=trace,
                synthetic=bool(synthetic))


def check_fixture(fixture):
    """Execute the generated image and compare only against independent data."""
    from model.mHBS import compile_micro
    from model.executor import MicroMachine
    image=compile_micro(fixture['profile'],hash_backend=fixture['hash_backend'])
    tasks=hashlib.sha256()
    def task_observe(task):
        recipe,layer,tree,leaf,a,b,result=task[:7]
        tasks.update(struct.pack('<QIQIII',recipe,layer,tree,leaf,a,b)+result+(struct.pack('<I',task[7]) if len(task)==8 else b''))
    machine=MicroMachine(image,fixture['job'],fixture['root'],fixture['message'],fixture['operation'],
                         fixture['signature'] if fixture['operation'] == 2 else b"",
                         task_observe=task_observe,
                         instruction_limit=(1<<64)-1)
    output=machine.run()
    if output != fixture['expected']: raise AssertionError("VM output differs from independent oracle")
    actual=(machine.hash_count,machine.permutation_count)
    if actual != fixture['independent_counts']:
        raise AssertionError(("VM work differs from independent oracle",actual,fixture['independent_counts']))
    return dict(image=image,machine=machine,output=output,counts=actual,
                instructions=machine.instructions,work_trace_sha256=machine.trace_digest.hexdigest(),
                hash_trace_sha256=tasks.hexdigest(),
                independent_order_matches=machine.trace_digest.hexdigest() == fixture['independent_trace_sha256'])


def write_fixture(fixture,folder,*,checked=None,write_image=True):
    """Write the existing fast-testbench memory format after independent checking."""
    started=time.monotonic()
    checked=checked or check_fixture(fixture)
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    p=get_profile(fixture['profile'],fixture['hash_backend'])
    machine=checked['machine'];job=fixture['job'];operation=fixture['operation']
    expected=fixture['expected'] if operation != 2 else b''
    payload=fixture['signature'] if operation == 2 else b''
    def memory(name,values,width):
        (folder/(name+'.mem')).write_text(''.join(f'{value:0{width}x}\n' for value in values) or '00\n')
    memory('expected',expected,2)
    memory('message',fixture['message'],2)
    seeds=(job.secret,job.prf,job.public,job.random,fixture['root'])
    words=[int.from_bytes(value,'little') for value in seeds]
    words += [operation,len(fixture['message']),p.n,job.q,int.from_bytes(job.identifier,'little')]
    memory('job',words,64)
    memory('nodes',(int.from_bytes(payload[i:i+p.n],'little') for i in range(0,len(payload),p.n)),64)
    memory('metadata',(len(expected),machine.hash_count,machine.permutation_count,operation,p.n,len(payload)//p.n),16)
    row=dict(passed=True,instructions=machine.instructions,hashes=machine.hash_count,
             permutations=machine.permutation_count,hash_trace_sha256=checked['hash_trace_sha256'],
             input_result_trace_sha256=checked['work_trace_sha256'],
             independent_counts=fixture['independent_counts'],
             independent_trace_sha256=fixture['independent_trace_sha256'],
             independent_order_matches=checked['independent_order_matches'],
             standard_pk=fixture['standard_pk'].hex(),
             standard_signature_sha256=hashlib.sha256(fixture['standard_sig']).hexdigest(),
             synthetic=fixture['synthetic'],vm_seconds=time.monotonic()-started)
    row.update({key:getattr(machine,key) for key in ('macro_count','macro_hashes','tree_count','tree_hashes','tree_chains') if hasattr(machine,key)})
    (folder/'result.json').write_text(json.dumps(row,indent=2)+'\n')
    if write_image:
        for stem,words in (("program",checked['image'].program),("descriptor",checked['image'].descriptors)):
            memory(stem,words,16)
    return row


