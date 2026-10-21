"""Layout-3 SHAKE256/SHA256 XMSS/LMS; external index, cold authentication.

The legacy model remains the cached-execution oracle. Standard images use RFC 8391/SP 800-208 and RFC 8554/9858
recipes and encodings and recompute the authentication tree during Sign.
"""
from dataclasses import replace
from model.executor import compile_image, field, Kind, Macro, Image, validate

PROFILE_CODES={0x18:'xmss_h10',0x19:'xmss_h16',0x1a:'xmss_h20',
               0x1b:'lms_h10',0x1c:'lms_h15',0x1d:'lms_h20'}
REFS={Kind.CHAIN:(52,44,36,28),Kind.TREE:(52,44),Kind.EMIT:(52,)}

def cold_image(name, hash_backend="shake"):
    image=compile_image(name, hash_backend=hash_backend)
    if not image.stateful:raise ValueError('stateful profile required')
    d=list(image.descriptors)
    for i,w in enumerate(d):
        if w>>60==Kind.TREE:d[i]=w & ~(7<<29)
    image=replace(image,descriptors=tuple(d));validate(image);return image

def descriptor_map(image):
    used={0,1}
    def visit(i):
        if i==0 or i in used:return
        used.add(i);w=image.descriptors[i];kind=w>>60
        for shift in REFS.get(kind,()):visit(field(w,shift,8))
        if kind==Kind.EMIT:
            for j in range(field(w,52,8),field(w,52,8)+field(w,48,4)):visit(j)
    for sign in (False,True):
        for w in image.words(sign)[:-1]:visit(field(w,88,8));visit(field(w,80,8))
    order=sorted(used)
    if len(order)>32:raise ValueError('descriptor capacity')
    return order

def encode(name, hash_backend="shake"):
    from model.mHBS import _MainExternalImage
    image=cold_image(name, hash_backend);order=descriptor_map(image);mapping={v:i for i,v in enumerate(order)}
    name=image.name
    d=[0]*32;t=[0]*16;p=[0]*16
    for j,i in enumerate(order):
        w=image.descriptors[i]&((1<<60)-1)
        for shift in REFS.get(image.descriptors[i]>>60,()):
            r=field(w,shift,8)
            if r:w=(w&~(255<<shift))|(mapping[r]<<shift)
        d[j]=w
    d[0]=(d[0]&((1<<36)-1))|(image.entry(True)<<41)
    d[1]=next(c for c,n in PROFILE_CODES.items() if n==name) | (int(hash_backend == "sha2") << 5)
    for j,w in enumerate(image.templates):
        flags=field(w,76,4)
        t[j]=field(w,96,4)|(mapping[field(w,88,8)]<<3)|(mapping[field(w,80,8)]<<8)|((flags&3)<<13)|((flags&8)<<12)|((flags&4)<<14)
    if len(image.tokens)>16 or len(image.templates)>16:raise ValueError('code capacity')
    for j,w in enumerate(image.tokens):
        kind=w>>126
        if kind>=2:
            if kind!=3:raise ValueError('unexpected stateful loop')
            p[j]=3<<62
        else:p[j]=(kind<<62)|(field(w,120,6)<<58)|((field(w,96,24)>>13)<<47)|(field(w,66,6)<<41)|((field(w,42,24)>>13)<<30)
    return _MainExternalImage(tuple(p),tuple(t),tuple(d))

def decode(external):
    # New families have canonical offline-generated images. Require every word
    # to match: no unknown recipe, padding, address or flag reaches hardware.
    code=external.descriptors[1]
    if code >> 6:raise ValueError('stateful profile reserved bits')
    hash_backend="sha2" if code & 32 else "shake"
    try:name=PROFILE_CODES[code & 31]
    except KeyError:raise ValueError('stateful profile code') from None
    expected=encode(name, hash_backend)
    if external!=expected:raise ValueError('noncanonical stateful image')
    return cold_image(name, hash_backend)
