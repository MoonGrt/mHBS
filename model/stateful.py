"""Layout-3 experimental SHAKE256 XMSS/LMS; external index, cold authentication.

The legacy model remains the cached-execution oracle. New images preserve its
byte recipes and encodings but recompute the authentication tree during Sign.
"""
from dataclasses import replace
from model.executor import compile_image, field, Kind, Macro, Image, validate

PROFILE_CODES={8:'xmss_omega2',9:'xmss_omega4',10:'lms_omega2',11:'lms_omega4'}
REFS={Kind.CHAIN:(52,44,36,28),Kind.TREE:(52,44),Kind.EMIT:(52,)}

def cold_image(name):
    image=compile_image(name)
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

def encode(name):
    from model.mHBS import ExternalImage
    image=cold_image(name);order=descriptor_map(image);mapping={v:i for i,v in enumerate(order)}
    d=[0]*32;t=[0]*16;p=[0]*16
    for j,i in enumerate(order):
        w=image.descriptors[i]&((1<<60)-1)
        for shift in REFS.get(image.descriptors[i]>>60,()):
            r=field(w,shift,8)
            if r:w=(w&~(255<<shift))|(mapping[r]<<shift)
        d[j]=w
    d[0]=(d[0]&((1<<36)-1))|(image.entry(True)<<41)
    d[1]=next(c for c,n in PROFILE_CODES.items() if n==name)
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
    return ExternalImage(tuple(p),tuple(t),tuple(d))

def decode(external):
    # New families have canonical offline-generated images. Require every word
    # to match: no unknown recipe, padding, address or flag reaches hardware.
    try:name=PROFILE_CODES[external.descriptors[1]]
    except KeyError:raise ValueError('stateful profile code') from None
    expected=encode(name)
    if external!=expected:raise ValueError('noncanonical stateful image')
    return cold_image(name)
