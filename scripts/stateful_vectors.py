#!/usr/bin/env python3
"""Frozen legacy oracle + independent verifier; vectors for cold-tree RTL."""
from pathlib import Path
import sys,json,importlib.util,hashlib
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from model.unified_hbs import Job,Machine
from model.stateful import cold_image,encode,PROFILE_CODES
from model.reference.stateful_shake import verify,parse_signature
OUT=ROOT/'manifests/experiments/stateful_20261008'
def mem(path,values,width):path.write_text(''.join(f'{v:0{width}x}\n' for v in values))
def generate(name,q=0,message=b'\x42'):
    d=OUT/'vectors'/name/f'q{q}_m{len(message)}';d.mkdir(parents=True,exist_ok=True)
    if (d/'summary.json').exists():
        saved=bytes(int(x,16) for x in (d/'1/message.mem').read_text().split())[:len(message)]
        if saved==message:return d
        raise ValueError(f'vector directory already contains a different message: {d}')
    job=Job(*(bytes((i+off)&255 for i in range(32)) for off in (1,41,81,121)),identifier=bytes(range(161,177)),q=q)
    spec=importlib.util.spec_from_file_location('stateful_frozen',OUT/'baseline/unified_hbs.py');mod=importlib.util.module_from_spec(spec);sys.modules[spec.name]=mod;spec.loader.exec_module(mod)
    assert (ROOT/'model/profiles.py').read_bytes()==(OUT/'baseline/profiles.py').read_bytes(),'frozen oracle profile dependency changed'
    old=mod.Machine(mod.compile_image(name),mod.Job(job.secret,job.prf,job.public,job.random,job.identifier,q),index_policy='fixed_q_no_guard')
    kg=old.run(False);root=old.values[3][:32];sg=old.run(True,message)
    observed={};assert verify(name,message,sg,job.public,root,job.identifier,observed),name
    records={}
    for op in (0,1,2):
        p=d/str(op);p.mkdir(exist_ok=True);encode(name).write(p)
        if op<2:
            m=Machine(cold_image(name),job,index_policy='fixed_q_no_guard',recompute_auth=True);m.values[3]=root
            data=m.run(bool(op),message if op else b'');assert data==(sg if op else kg),(name,op)
            hashes,perms=m.hashes,m.permutations
        else:data=b'';hashes,perms=observed['hashes'],observed['permutations']
        _,r,chains,auth=parse_signature(name,sg);nodes=[r,*chains,*auth]
        mem(p/'expected.mem',data or b'\0',2);mem(p/'message.mem',message+bytes(87-len(message)),2)
        mem(p/'nodes.mem',[int.from_bytes(x,'little') for x in nodes],64)
        cfg=[int.from_bytes(x,'little') for x in (job.secret,job.prf,job.public,job.random,root,job.identifier)]+[q,op,len(message)]
        mem(p/'job.mem',cfg,64);mem(p/'meta.mem',[len(data),hashes,perms,len(nodes),int(op==2)],8)
        records[str(op)]=dict(hashes=hashes,permutations=perms,output_bytes=len(data))
    (d/'signature.bin').write_bytes(sg);(d/'root.bin').write_bytes(root)
    (d/'summary.json').write_text(json.dumps(records,indent=2)+'\n');print('VECTOR_PASS',name,q,len(message),flush=True);return d
if __name__=='__main__':
    import argparse
    a=argparse.ArgumentParser();a.add_argument('--name',choices=list(PROFILE_CODES.values()));a.add_argument('--q',type=int,default=0);a.add_argument('--length',type=int,default=1);args=a.parse_args()
    for name in ([args.name] if args.name else PROFILE_CODES.values()):generate(name,args.q,bytes((66+i)&255 for i in range(args.length)))
