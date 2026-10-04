"""Independent direct verifier for the repository's experimental SHAKE256 variants.

No microcode, recipe descriptors or Machine calls. These are NOT registered RFC
parameter encodings. The caller owns durable, non-repeating signing indices.
"""
from hashlib import shake_256

def be(x,n=4):return x.to_bytes(n,'big')
def H(x):return shake_256(x).digest(32)
def digits(digest,bits):
    ds=[(b>>s)&((1<<bits)-1) for b in digest for s in range(8-bits,-1,-bits)]
    c=sum(((1<<bits)-1)-d for d in ds);count=(len(ds)*((1<<bits)-1)).bit_length()//bits+1
    return ds+[(c>>s)&((1<<bits)-1) for s in range((count-1)*bits,-1,-bits)]
def xor(a,b):return bytes(x^y for x,y in zip(a,b))
def masked(public,domain,leaf,level,index,left,right=None):
    addr=bytes(12)+be(domain)+be(leaf)+be(level)+be(index)
    key=H(be(3,32)+public+addr+be(0));m0=H(be(3,32)+public+addr+be(1))
    if right is None:return H(bytes(32)+key+xor(left,m0))
    m1=H(be(3,32)+public+addr+be(2))
    return H(be(1,32)+key+xor(left,m0)+xor(right,m1))

def parse_signature(name,sig):
    if name not in ('xmss_omega2','xmss_omega4','lms_omega2','lms_omega4'):raise ValueError('profile')
    bits=2 if name.endswith('2') else 4;count=133 if bits==2 else 67;xmss=name.startswith('xmss')
    if len(sig)!=(4 if xmss else 12)+32*(1+count+10):raise ValueError('signature length')
    q=int.from_bytes(sig[:4],'big')
    if q>=1024:raise ValueError('signature index')
    offset=4
    if not xmss:
        if sig[4:8]!=be(0x80000002 if bits==2 else 0x80000003):raise ValueError('OTS type')
        offset=8
    random=sig[offset:offset+32];offset+=32
    chains=[sig[offset+32*i:offset+32*(i+1)] for i in range(count)];offset+=32*count
    if not xmss:
        if sig[offset:offset+4]!=be(0x80000006):raise ValueError('tree type')
        offset+=4
    auth=[sig[offset+32*i:offset+32*(i+1)] for i in range(10)]
    return q,random,chains,auth

def verify(name,message,signature,public_seed,public_root,identifier=bytes(16),observe=None):
    if len(public_seed)!=32 or len(public_root)!=32 or len(identifier)!=16 or not 1<=len(message)<=87:return False
    try:q,r,chains,auth=parse_signature(name,signature)
    except ValueError:return False
    bits=2 if name.endswith('2') else 4;maximum=(1<<bits)-1
    xmss=name.startswith('xmss')
    # Optional observer counts primitive SHAKE invocations independently of RTL.
    hashes=0;perms=0
    def h(data):
        nonlocal hashes,perms
        hashes+=1;perms+=len(data)//136+1
        return H(data)
    def mask(domain,leaf,level,index,left,right=None):
        addr=bytes(12)+be(domain)+be(leaf)+be(level)+be(index)
        key=h(be(3,32)+public_seed+addr+be(0));m0=h(be(3,32)+public_seed+addr+be(1))
        if right is None:return h(bytes(32)+key+xor(left,m0))
        m1=h(be(3,32)+public_seed+addr+be(2))
        return h(be(1,32)+key+xor(left,m0)+xor(right,m1))
    digest=h(be(2,32)+r+public_root+be(q,32)+message if xmss else identifier+be(q)+b'\x81\x81'+r+message)
    endpoints=[]
    for i,(value,start) in enumerate(zip(chains,digits(digest,bits))):
        for j in range(start,maximum):value=mask(0,q,i,j,value) if xmss else h(identifier+be(q)+be(i,2)+be(j,1)+value)
        endpoints.append(value)
    if xmss:
        level=0
        while len(endpoints)>1:
            endpoints=[mask(1,q,level,i//2,endpoints[i],endpoints[i+1]) for i in range(0,len(endpoints)-1,2)]+(endpoints[-1:] if len(endpoints)&1 else [])
            level+=1
        value=endpoints[0]
    else:
        value=h(identifier+be(q)+b'\x80\x80'+b''.join(endpoints))
        value=h(identifier+be(1024+q)+b'\x82\x82'+value)
    for level,sibling in enumerate(auth):
        left,right=(sibling,value) if (q>>level)&1 else (value,sibling)
        value=mask(2,0,level,q>>(level+1),left,right) if xmss else h(identifier+be((1024+q)>>(level+1))+b'\x83\x83'+left+right)
    if observe is not None:observe.update(hashes=hashes,permutations=perms)
    return value==public_root
