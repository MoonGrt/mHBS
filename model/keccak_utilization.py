"""Ideal simultaneous-batch Keccak lower bounds (not an RTL timing simulator).

Run: python3 -m model.keccak_utilization --help
All dependency edges have explicit provenance, never inferred from equal bytes.
"""
from __future__ import annotations

import argparse
from array import array
from collections import Counter
import csv
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path

from model.profiles import PROFILES, get_profile
from model.unified_hbs import Machine, Job, Shape, field, compile_image
from model.stateful import cold_image
from model.reference.stateful_shake import digits, parse_signature

ROOT = Path(__file__).resolve().parents[1]
VECTORS = ROOT / 'manifests/experiments/fixed_p4u2_20261009/vectors/jobs'
POINTS = [(p, 1) for p in (1, 2, 3, 4, 6, 8, 12)] + [(p, 2) for p in (1, 2, 3, 4, 6, 12)]


def ceildiv(a, b):
    return (a + b - 1) // b


class DependencyGraph:
    """Unit-duration permutation DAG in creation/topological order; node 0 is input."""
    def __init__(self):
        self.offsets = array('I', [0, 0])
        self.parents = array('I')
        self.depth = array('I', [0])
        self.hashes = 0

    def add(self, dependencies=()):
        deps = sorted(set(dependencies) - {0})
        node = len(self.depth)
        if any(d < 0 or d >= node for d in deps):
            raise ValueError('dependencies must refer to earlier nodes')
        self.parents.extend(deps)
        self.offsets.append(len(self.parents))
        self.depth.append(1 + max((self.depth[d] for d in deps), default=0))
        return node

    @property
    def permutations(self):
        return len(self.depth) - 1

    def statistics(self):
        tails = array('I', [1]) * len(self.depth)
        for i in range(self.permutations, 0, -1):
            length = tails[i] + 1
            for k in range(self.offsets[i], self.offsets[i + 1]):
                parent = self.parents[k]
                if tails[parent] < length:
                    tails[parent] = length
        return GraphStatistics(self.permutations, self.hashes,
                               Counter(self.depth[1:]), Counter(tails[1:]),
                               Counter(zip(self.depth[1:], tails[1:])))


@dataclass
class GraphStatistics:
    permutations: int
    hashes: int
    depths: Counter
    tails: Counter
    windows: Counter | None = None

    def bound(self, p, u):
        if type(p) is not int or type(u) is not int or p < 1 or u < 1 or 24 % (p*u):
            raise ValueError('P/U must be positive integers and P*U must divide 24')
        n = self.permutations
        work = ceildiv(n, p)
        critical = max(self.depths, default=0)
        # Nodes of depth >= d cannot run in the first d-1 batches.
        # Reverse the DAG for the analogous mandatory trailing batches.
        def window(hist):
            remaining, result = 0, 0
            for d in sorted(hist, reverse=True):
                remaining += hist[d]
                result = max(result, d - 1 + ceildiv(remaining, p))
            return result
        release, tail = window(self.depths), window(self.tails)
        # A node with forward depth >= a and reverse depth >= b must lie
        # inside batches [a, B-b+1]. Counting this intersection captures a
        # compulsory serial prefix AND suffix without imposing phase barriers.
        joint = 0
        if self.windows:
            groups = {}
            for (a, b), count in self.windows.items():
                groups.setdefault(a, []).append((b, count))
            accumulated = Counter()
            for a in sorted(groups, reverse=True):
                accumulated.update(dict(groups[a]))
                demand = 0
                for b in sorted(accumulated, reverse=True):
                    demand += accumulated[b]
                    joint = max(joint, a+b-2+ceildiv(demand, p))
        batches = max(work, critical, release, tail, joint)
        utilization = n / (p*batches) if batches else 0.0
        return dict(p=p, u=u, hashes=self.hashes, permutations=n,
                    work_batches_lb=work, critical_path_batches=critical,
                    release_batches_lb=release, tail_batches_lb=tail, dependency_window_batches_lb=joint,
                    batches_lb=batches, cycles_lb=batches*(24//u),
                    utilization_upper=utilization, idle_lower=1-utilization,
                    optimality='proven' if p == 1 or n == critical else 'lower_bound_only')


class Value(bytes):
    """A digest and its producer. Slicing retains provenance, including zero-step chains."""
    def __new__(cls, data, node=0):
        value = super().__new__(cls, data)
        value.node = node
        return value

    def __getitem__(self, key):
        result = super().__getitem__(key)
        return Value(result, self.node) if isinstance(key, slice) else result


def producer(value):
    return getattr(value, 'node', 0)


class DependencyMachine(Machine):
    """Existing microcode work/output, with explicit recipe-level data provenance."""
    def __init__(self, image, job, graph):
        super().__init__(image, job, index_policy='fixed_q_no_guard', recompute_auth=True)
        self.graph = graph
        self.address_dependency = 0
        self.chain_control = 0
        self.verifying = False

    def shake(self, parts, length, controls=()):
        """A block depends only on bytes in that block and the preceding permutation.

        Controls gate the invocation itself (e.g. message-dependent chain range).
        Absorb padding at an exact rate boundary always needs a new permutation.
        """
        parts = list(parts)
        data = b''.join(parts)
        spans, offset = [], 0
        for part in parts:
            spans.append((offset, offset+len(part), producer(part)))
            offset += len(part)
        node = 0
        for start in range(0, len(data)+1, 136):
            deps = [node, *controls]
            deps.extend(d for lo, hi, d in spans if lo < start+136 and hi > start)
            node = self.graph.add(deps)
        for _ in range(max(0, ceildiv(length, 136)-1)):
            node = self.graph.add([node])
        self.graph.hashes += 1
        self.hashes += 1
        self.permutations = self.graph.permutations
        return Value(hashlib.shake_256(data).digest(length), node)

    def hash_recipe(self, rid, *, layer=0, leaf=0, a=0, b=0, left=b'', right=b'', values=None):
        r = self.image.descriptors[rid]
        shape, domain, arity = Shape(field(r,56,4)), field(r,48,8), field(r,40,8)
        j, n = self.job, self.n
        be = lambda x, size=4: x.to_bytes(size, 'big')
        # Top SLH tree has constant tree address 0; lower trees/FORS need Hmsg.
        addr_dep = self.address_dependency if self.verifying or self.chain_control or layer < get_profile(self.image.name).d-1 or domain in (3,4,6) else 0
        addr = Value(b''.join(be(x) for x in (layer,0,self.scalar_tree>>32,self.scalar_tree&0xffffffff,domain,leaf,a,b)), addr_dep)
        mask = b''.join(be(x) for x in (0,0,0,domain,leaf,a,b))
        # Every signing chain always generates its seed, even for digit zero.
        # It does not wait for the digest selecting the number of chain steps.
        seed_shape = shape in (Shape.ADDRESS_SEED, Shape.MASKED_SEED, Shape.PREFIX_SEED)
        control = (self.chain_control,) if self.chain_control and not seed_shape else ()
        if shape == Shape.ADDRESS_SEED: parts=[j.public,addr,j.secret]
        elif shape == Shape.ADDRESS_VALUE: parts=[j.public,addr,left]+([right] if arity==2 else [])
        elif shape == Shape.MESSAGE_PRF: parts=[j.prf,j.random,self.message]
        elif shape == Shape.MESSAGE_DIGEST: parts=[self.values[0][:n],j.public,self.values[3][:n],self.message]
        elif shape == Shape.INDEX_PRF: parts=[be(3,n),j.prf,be(self.active_q,32)]
        elif shape == Shape.ROOT_MESSAGE: parts=[be(2,n),self.values[0][:n],self.values[3][:n],be(self.active_q,n),self.message]
        elif shape == Shape.MASKED_SEED: parts=[be(4,n),j.secret,j.public,mask,be(0)]
        elif shape == Shape.MASKED_VALUE:
            # Keys/masks depend on address, not on the incoming chain node.
            key=self.shake([be(3,n),j.public,mask,be(0)],n,control)
            masks=[self.shake([be(3,n),j.public,mask,be(k)],n,control) for k in range(1,arity+1)]
            # XOR is zero time, but both input producers remain dependencies.
            parts=[be(arity-1,n),key]
            for value,m in zip([left,right],masks):
                parts.append(bytes(x^y for x,y in zip(value,m)))
            result=self.shake(parts,n,(*control,producer(left),producer(right),*(producer(m) for m in masks)))
            return result
        elif shape == Shape.PREFIX_SEED: parts=[j.identifier,be(leaf),be(a,2),b'\xff',j.secret]
        elif shape == Shape.PREFIX_VALUE: parts=[j.identifier,be(leaf),be(a,2),be(b,1),left]
        elif shape == Shape.PREFIX_MESSAGE: parts=[j.identifier,be(self.active_q),b'\x81\x81',j.random,self.message]
        elif shape == Shape.ADDRESS_LIST: parts=[j.public,addr,*(values or [])]
        elif shape == Shape.PREFIX_LIST: parts=[j.identifier,be(leaf),b'\x80\x80',*(values or [])]
        elif shape == Shape.PREFIX_LEAF: parts=[j.identifier,be(b),b'\x82\x82',left]
        elif shape == Shape.PREFIX_PARENT: parts=[j.identifier,be(b),b'\x83\x83',left,right]
        else: raise ValueError(shape)
        result=self.shake(parts,field(r,32,6),control)
        if shape == Shape.MESSAGE_DIGEST:
            self.address_dependency=producer(result)
        return result

    def chains(self, did, layer, leaf, index, fors, capture, sign_only):
        previous=self.chain_control
        # The subset of executed steps depends on the digest/checksum. Full
        # chains do not: selecting a capture position is zero-time consumption.
        if sign_only:
            self.chain_control=producer(self.values[2])
        try:
            return super().chains(did,layer,leaf,index,fors,capture,sign_only)
        finally:
            self.chain_control=previous


@dataclass
class Inputs:
    job: Job
    root: bytes
    message: bytes
    signature: bytes = b''
    source: str = 'custom'

    def identity(self):
        payload = dict(secret=self.job.secret.hex(),prf=self.job.prf.hex(),public=self.job.public.hex(),
                       random=self.job.random.hex(),identifier=self.job.identifier.hex(),q=self.job.q,
                       root=self.root.hex(),message=self.message.hex(),signature=self.signature.hex())
        return hashlib.sha256(json.dumps(payload,sort_keys=True).encode()).hexdigest()


def load_inputs(name, path=None):
    profile=get_profile(name)
    if path:
        data=json.loads(Path(path).read_text())
        job=Job(*(bytes.fromhex(data[k]) for k in ('secret','prf','public','random')),
                identifier=bytes.fromhex(data.get('identifier','00'*16)),q=data.get('q',0))
        return Inputs(job,bytes.fromhex(data['root']),bytes.fromhex(data['message']),
                      bytes.fromhex(data.get('signature','')),str(path))
    folder=VECTORS/profile.name/'1'
    words=[int(x,16) for x in (folder/'job.mem').read_text().split()]
    n=profile.n
    job=Job(*(x.to_bytes(32,'little')[:n] for x in words[:4]),
            identifier=words[5].to_bytes(32,'little')[:16],q=words[6])
    root=words[4].to_bytes(32,'little')[:n]
    message=bytes(int(x,16) for x in (folder/'message.mem').read_text().split())[:words[8]]
    signature=bytes(int(x,16) for x in (folder/'expected.mem').read_text().split())
    return Inputs(job,root,message,signature,str(folder.relative_to(ROOT)))


def verify_graph(m, profile, inputs):
    """Repository verification recipes, explicit address and digit dependencies."""
    n=profile.n
    sig=inputs.signature
    if len(sig)!=profile.signature_bytes:
        raise ValueError('verify requires a full signature of the profile length')
    m.verifying=True
    m.message=inputs.message
    m.values[3]=inputs.root
    m.active_q=inputs.job.q
    if profile.family!='slh':
        q,r,chains,auth=parse_signature(profile.name,sig)
        if q!=inputs.job.q: raise ValueError('signature q and job q differ')
        m.values[0]=r
        if profile.family=='xmss':
            digest=m.hash_recipe(3)
            step,reduce=5,6
        else:
            # Verification takes R from the signature, not job.random.
            j=inputs.job
            m.job=Job(j.secret,j.prf,j.public,r,j.identifier,j.q)
            digest=m.hash_recipe(2)
            step,reduce=4,5
        endpoints=[]
        m.chain_control=producer(digest)
        for i,(value,start) in enumerate(zip(chains,digits(digest,profile.omega))):
            for j in range(start,(1<<profile.omega)-1):
                value=m.hash_recipe(step,leaf=q,a=i,b=j,left=value)
            endpoints.append(Value(value, producer(digest)) if start == (1<<profile.omega)-1 else value)
        m.chain_control=0
        if profile.family=='xmss':
            level=0
            while len(endpoints)>1:
                endpoints=[m.hash_recipe(reduce,leaf=q,a=level,b=i//2,left=endpoints[i],right=endpoints[i+1]) for i in range(0,len(endpoints)-1,2)]+(endpoints[-1:] if len(endpoints)&1 else [])
                level+=1
            value=endpoints[0]
        else:
            value=m.hash_recipe(reduce,leaf=q,values=endpoints)
            value=m.hash_recipe(6,leaf=q,b=1024+q,left=value)
        for level,sibling in enumerate(auth):
            left,right=(sibling,value) if q>>level&1 else (value,sibling)
            value=m.hash_recipe(7,a=level,b=q>>(level+1),left=left,right=right) if profile.family=='xmss' else m.hash_recipe(7,b=(1024+q)>>(level+1),left=left,right=right)
        return value==inputs.root
    # SLH FORS recovery followed by the hypertree WOTS/authentication paths.
    m.values[0]=sig[:n]
    digest=m.hash_recipe(3)
    fb=ceildiv(profile.k*profile.a,8)
    tb=ceildiv(profile.h-profile.hp,8)
    m.scalar_tree=int.from_bytes(digest[fb:fb+tb],'big')&((1<<(profile.h-profile.hp))-1)
    leaf=int.from_bytes(digest[fb+tb:],'big')&((1<<profile.hp)-1)
    indices=int.from_bytes(digest[:fb],'big')
    offset=n
    roots=[]
    for tree in range(profile.k):
        selected=(indices>>(8*fb-profile.a*(tree+1)))&((1<<profile.a)-1)
        value=m.hash_recipe(5,leaf=leaf,b=tree*(1<<profile.a)+selected,left=sig[offset:offset+n]);offset+=n
        for level in range(profile.a):
            sibling=sig[offset:offset+n];offset+=n
            left,right=(sibling,value) if selected>>level&1 else (value,sibling)
            value=m.hash_recipe(6,leaf=leaf,a=level+1,b=(tree*(1<<profile.a)+selected)>>(level+1),left=left,right=right)
        roots.append(value)
    value=m.hash_recipe(11,leaf=leaf,values=roots)
    for layer in range(profile.d):
        endpoints=[]
        m.chain_control=producer(value)
        for i,start in enumerate(digits(value,4)):
            item=sig[offset:offset+n];offset+=n
            for j in range(start,15):
                item=m.hash_recipe(8,layer=layer,leaf=leaf,a=i,b=j,left=item)
            endpoints.append(Value(item, producer(value)) if start == 15 else item)
        m.chain_control=0
        value=m.hash_recipe(9,layer=layer,leaf=leaf,values=endpoints)
        for level in range(profile.hp):
            sibling=sig[offset:offset+n];offset+=n
            left,right=(sibling,value) if leaf>>level&1 else (value,sibling)
            value=m.hash_recipe(10,layer=layer,a=level+1,b=leaf>>(level+1),left=left,right=right)
        leaf=m.scalar_tree&((1<<profile.hp)-1)
        m.scalar_tree>>=profile.hp
    return value==inputs.root


def build_graph(name, operation, inputs=None, recompute_auth=False):
    profile=get_profile(name)
    if operation not in ('keygen','sign','verify'): raise ValueError('operation')
    inputs=inputs or load_inputs(profile.name)
    if len(inputs.root)!=profile.n or not 1<=len(inputs.message)<=87 or not 0<=inputs.job.q<1024:
        raise ValueError('invalid root, message length or q')
    if profile.family=='slh' and (inputs.job.q or any(inputs.job.identifier)):
        raise ValueError('SLH does not use q/identifier')
    graph=DependencyGraph()
    image=cold_image(profile.name) if profile.stateful and recompute_auth else compile_image(profile.name)
    m=DependencyMachine(image,inputs.job,graph)
    m.values[3]=inputs.root
    if operation=='verify':
        if not verify_graph(m,profile,inputs): raise ValueError('invalid signature for supplied inputs')
    else:
        if operation=='sign' and profile.stateful and not recompute_auth:
            # Caller-supplied authentication path is ready at time zero. The
            # existing cached-tree recipe emits these bytes without any hashes.
            m.cache_valid=True
            m.cache={(level,(inputs.job.q>>level)^1):bytes(profile.n) for level in range(profile.h)}
        result=m.run(operation=='sign',inputs.message if operation=='sign' else b'')
        if operation=='sign' and inputs.signature:
            if profile.stateful and not recompute_auth:
                result=result[:-profile.h*profile.n]
                expected=inputs.signature[:-profile.h*profile.n]
            else: expected=inputs.signature
            if result!=expected: raise AssertionError('signature bytes differ from input vector')
        if operation=='keygen' and m.values[3]!=inputs.root:
            raise AssertionError('keygen root differs from input vector')
    return graph


def analyze(name, operation, p=1, u=1, *, recompute_auth=False, inputs=None):
    profile=get_profile(name)
    GraphStatistics(0,0,Counter(),Counter()).bound(p,u)
    inputs=inputs or load_inputs(name)
    graph=build_graph(name,operation,inputs,recompute_auth)
    return dict(profile=profile.name,operation=operation,
                recompute_auth=recompute_auth if profile.stateful and operation=='sign' else None,
                input_sha256=inputs.identity(),input_source=inputs.source,**graph.statistics().bound(p,u))


def write_reports(prefix, rows):
    prefix=Path(prefix);prefix.parent.mkdir(parents=True,exist_ok=True)
    metadata=dict(model='ideal_simultaneous_permutation_batches',
                  cycles='batches_lb * (24/U)',utilization='N/(P*batches_lb)',idle='1-utilization_upper',
                  limitation='Bounds need not be attainable. No RTL, I/O, storage or non-Keccak cycles.',rows=rows)
    prefix.with_suffix('.json').write_text(json.dumps(metadata,indent=2,ensure_ascii=False)+'\n')
    with prefix.with_suffix('.csv').open('w',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=list(rows[0]),lineterminator='\n');writer.writeheader();writer.writerows(rows)
    lines=['# 算法 Keccak 理论周期下限','',
           '理想同时批次：每批最多 P 个置换，耗时 24/U 周期；其他计算零周期。',
           '下界未必可达；空闲率是有效轮容量的理论下界，不是 RTL 实测。认证路径重算仅影响 XMSS/LMS Sign，默认关闭。','',
           '| 参数集 | 操作 | 重算认证路径 | P | U | Hash | 置换 | 批次下界 | 周期下限 | 利用率上界 | 空闲率下界 |',
           '|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|']
    for r in rows:
        lines.append(f"| {r['profile']} | {r['operation']} | {r['recompute_auth'] if r['recompute_auth'] is not None else '—'} | {r['p']} | {r['u']} | {r['hashes']} | {r['permutations']} | {r['batches_lb']} | {r['cycles_lb']} | {r['utilization_upper']:.6%} | {r['idle_lower']:.6%} |")
    prefix.with_suffix('.md').write_text('\n'.join(lines)+'\n')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile',choices=['all',*PROFILES],default='all')
    parser.add_argument('--operation',choices=['all','keygen','sign','verify'],default='all')
    parser.add_argument('--p',type=int);parser.add_argument('--u',type=int)
    parser.add_argument('--recompute-auth',action='store_true',help='XMSS/LMS Sign: include cold authentication-tree recomputation')
    parser.add_argument('--both-auth',action='store_true',help='report both modes for XMSS/LMS Sign')
    parser.add_argument('--input',type=Path,help='custom input JSON for one selected profile')
    parser.add_argument('--output',type=Path,default=Path('docs/report/Keccak_Theoretical_Bounds'))
    args=parser.parse_args()
    if (args.p is None)!=(args.u is None): parser.error('--p and --u must be specified together')
    if args.input and args.profile=='all': parser.error('--input requires one profile')
    points=POINTS if args.p is None else [(args.p,args.u)]
    for p,u in points: GraphStatistics(0,0,Counter(),Counter()).bound(p,u)
    rows=[]
    for name in PROFILES if args.profile=='all' else [args.profile]:
        inputs=load_inputs(name,args.input)
        for operation in ('keygen','sign','verify') if args.operation=='all' else [args.operation]:
            modes=[False,True] if args.both_auth and get_profile(name).stateful and operation=='sign' else [args.recompute_auth]
            for mode in modes:
                graph=build_graph(name,operation,inputs,mode)
                stats=graph.statistics()
                for p,u in points:
                    rows.append(dict(profile=name,operation=operation,recompute_auth=mode if get_profile(name).stateful and operation=='sign' else None,input_sha256=inputs.identity(),input_source=inputs.source,**stats.bound(p,u)))
                print(f"PASS {name} {operation} auth={mode} hashes={graph.hashes} permutations={graph.permutations}",flush=True)
                del graph
    write_reports(args.output,rows)


if __name__=='__main__': main()
