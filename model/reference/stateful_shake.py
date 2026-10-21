"""Independent direct verifier for SHAKE256 and SHA256 parameter sets.

No microcode, recipe descriptors or Machine calls. Uses registered SP 800-208 and RFC 9858 parameter encodings. The caller owns durable, non-repeating signing indices.
"""
from hashlib import shake_256, sha256

def be(x,n=4):return x.to_bytes(n,'big')
def H(x,hash_backend="shake"):
    if hash_backend=='shake':return shake_256(x).digest(32)
    if hash_backend=='sha2':return sha256(x).digest()
    raise ValueError('unknown hash backend')
def digits(digest,bits):
    ds=[(b>>s)&((1<<bits)-1) for b in digest for s in range(8-bits,-1,-bits)]
    c=sum(((1<<bits)-1)-d for d in ds);count=(len(ds)*((1<<bits)-1)).bit_length()//bits+1
    return ds+[(c>>s)&((1<<bits)-1) for s in range((count-1)*bits,-1,-bits)]
def xor(a,b):return bytes(x^y for x,y in zip(a,b))
def masked(public,domain,leaf,level,index,left,right=None,hash_backend="shake"):
    addr=bytes(12)+be(domain)+be(leaf)+be(level)+be(index)
    def h(data):return H(data,hash_backend)
    key=h(be(3,32)+public+addr+be(0));m0=h(be(3,32)+public+addr+be(1))
    if right is None:return h(bytes(32)+key+xor(left,m0))
    m1=h(be(3,32)+public+addr+be(2))
    return h(be(1,32)+key+xor(left,m0)+xor(right,m1))

def parse_signature(name,sig,hash_backend="shake"):
    from model.profiles import get_profile
    profile=get_profile(name,hash_backend)
    if not profile.stateful:raise ValueError('profile')
    bits=4;count=67;xmss=profile.family=='xmss'
    height=profile.h
    if len(sig)!=(4 if xmss else 12)+32*(1+count+height):raise ValueError('signature length')
    q=int.from_bytes(sig[:4],'big')
    if q>=(1<<height):raise ValueError('signature index')
    offset=4
    if not xmss:
        if sig[4:8]!=be(profile.lmots_typecode):raise ValueError('OTS type')
        offset=8
    random=sig[offset:offset+32];offset+=32
    chains=[sig[offset+32*i:offset+32*(i+1)] for i in range(count)];offset+=32*count
    if not xmss:
        if sig[offset:offset+4]!=be(profile.typecode):raise ValueError('tree type')
        offset+=4
    auth=[sig[offset+32*i:offset+32*(i+1)] for i in range(height)]
    return q,random,chains,auth

def parse_public_key(name, public_key, hash_backend="shake"):
    """Validate standard type headers before passing root/seed/I to hardware."""
    from model.profiles import get_profile
    profile=get_profile(name,hash_backend)
    if not profile.stateful or len(public_key)!=profile.keygen_bytes:
        raise ValueError('public key length/profile')
    if public_key[:4]!=be(profile.typecode):raise ValueError('public key type')
    if profile.family=='xmss':
        return public_key[4:36],public_key[36:68],bytes(16)
    if public_key[4:8]!=be(profile.lmots_typecode):raise ValueError('public key OTS type')
    return public_key[24:56],bytes(32),public_key[8:24]

def verify_serialized(name,message,signature,public_key,observe=None,hash_backend="shake",*,observe_hash=None):
    try:
        root,seed,identifier=parse_public_key(name,public_key,hash_backend)
        parse_signature(name,signature,hash_backend)
    except ValueError:
        return False
    return verify(name,message,signature,seed,root,identifier,observe,hash_backend,observe_hash=observe_hash)

def hardware_verify_input(name,signature,public_key,hash_backend="shake"):
    """Checked adapter for the existing Job metadata and node-wise Verify bus."""
    root,seed,identifier=parse_public_key(name,public_key,hash_backend)
    q,random,chains,auth=parse_signature(name,signature,hash_backend)
    return dict(q=q,public_root=root,public_seed=seed,identifier=identifier,
                nodes=(random,*chains,*auth))

def verify(name,message,signature,public_seed,public_root,identifier=bytes(16),observe=None,hash_backend="shake",*,observe_hash=None):
    if len(public_seed)!=32 or len(public_root)!=32 or len(identifier)!=16 or not 0<=len(message)<=87:return False
    try:q,r,chains,auth=parse_signature(name,signature,hash_backend)
    except ValueError:return False
    from model.profiles import get_profile
    profile=get_profile(name,hash_backend);height=profile.h
    bits=4;maximum=15
    xmss=name.startswith('xmss')
    # Optional observer counts primitive SHAKE invocations independently of RTL.
    hashes=0;perms=0
    def h(data):
        nonlocal hashes,perms
        hashes+=1;perms+=len(data)//136+1 if hash_backend=='shake' else (len(data)+72)//64
        result=H(data,hash_backend)
        if observe_hash is not None:observe_hash(0,data,result)
        return result
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
        value=h(identifier+be((1<<height)+q)+b'\x82\x82'+value)
    for level,sibling in enumerate(auth):
        left,right=(sibling,value) if (q>>level)&1 else (value,sibling)
        value=mask(2,0,level,q>>(level+1),left,right) if xmss else h(identifier+be(((1<<height)+q)>>(level+1))+b'\x83\x83'+left+right)
    if observe is not None:observe.update(hashes=hashes,permutations=perms)
    return value==public_root
