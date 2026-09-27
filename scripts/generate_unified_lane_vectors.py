#!/usr/bin/env python3
"""Small recipe-level vectors for Icarus; independent of RTL scheduling."""
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from model.unified_hbs import Job,Machine,compile_image,field
from model.profiles import PROFILES

for name,p in PROFILES.items():
    family=p.family
    image=compile_image(name)
    n=image.n
    job=Job(bytes(range(n)),bytes(range(32,32+n)),bytes(range(64,64+n)),bytes(range(96,96+n)),bytes(range(16)),5)
    m=Machine(image,job)
    m.active_q=5; m.message=bytes(range(87)); m.values[0]=job.random; m.values[3]=bytes(range(128,128+n))
    cid=17 if family=="slh" else 16
    cd=image.descriptors[cid]
    seed,step=field(cd,52,8),field(cd,44,8)
    rows=[]
    for steps in (0,1,(1<<p.omega)-1):
        chain_index=132 if p.chains==133 else 3
        capture_after=min(7,steps)
        value=m.hash_recipe(seed,leaf=5,a=chain_index)
        capture=value
        for i in range(steps):
            value=m.hash_recipe(step,leaf=5,a=chain_index,b=i,left=value)
            if i+1==capture_after: capture=value
        rows.append((image.descriptors[seed],image.descriptors[step],1,steps,capture_after,chain_index,0,value,capture))
    parent=10 if family=="slh" else 7
    left=bytes(range(160,160+n)); right=bytes(range(192,192+n))
    value=m.hash_recipe(parent,leaf=5,a=2,b=1,left=left,right=right)
    rows.append((image.descriptors[parent],0,0,0,0,2,1,value,bytes(n)))
    message=3 if family!="lms" else 2
    value=m.hash_recipe(message,leaf=5)
    rows.append((image.descriptors[message],0,0,0,0,0,0,value,bytes(n)))
    rid=9 if family=="slh" else 5 if family=="lms" else 7
    values=[bytes((i+j)&255 for j in range(n)) for i in range(field(image.descriptors[rid],40,8))]
    value=m.hash_recipe(rid,leaf=5,values=values,left=left,right=right)
    rows.append((image.descriptors[rid],0,0,0,0,0,0,value,bytes(n)))
    if family=="slh":
        b=(p.k<<p.a)-1
        initial=m.hash_recipe(4,leaf=5,a=0,b=b)
        value=m.hash_recipe(5,leaf=5,a=0,b=b,left=initial)
        rows.append((image.descriptors[4],image.descriptors[5],1,1,0,0,b,value,initial))
    def encode(row):
        recipe,step,ch,steps,cap,a,b,value,capture=row
        return (recipe<<960)|(step<<896)|(ch<<895)|(steps<<890)|(cap<<885)|(a<<877)|(b<<845) \
            |(len(value)<<839)|(int.from_bytes(value,"little")<<256)|int.from_bytes(capture,"little")
    (ROOT/f"tb/vectors/mhbs_{name}_lane.mem").write_text("".join(f"{encode(r):0256x}\n" for r in rows))
