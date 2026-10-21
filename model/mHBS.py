"""Physical image encoding; the public API defaults to external Job inputs.

The embedded-input 64-word SLH format is retained privately to validate the
16-word external-input format. Bit allocations match all six SLH profiles.
"""
from dataclasses import dataclass
from pathlib import Path
from model.executor import Image as LogicalImage, Job, Machine, compile_image as compile_logical_image, field, validate
from model.microcode import StaticTaskToken as Token, issue_word
from model.profiles import get_profile, SLH_PROFILE_CODES

FORMAT = 'slh64_v4.2'
_EMBEDDED_LAYOUT_REVISION = 2
# Fixed union across profiles and both operations; zero is the output-size record.
ADDRESSES = (0, 1, *range(2, 12), 16, 17, 20, 21, *range(40, 45), 48, 49, 50, *range(64, 70))
TO_PHYSICAL = {old: new for new, old in enumerate(ADDRESSES)}
KINDS = (10, 11, *([1]*10), 4, 4, 5, 5, *([6]*5), 8, 8, 9, *([2]*6))
REF_FIELDS = {4: (52, 44, 36, 28), 5: (52, 44), 9: (52,)}

def remap(word, kind, reverse=False):
    for shift in REF_FIELDS.get(kind, ()):
        ref = field(word, shift, 8)
        if ref:
            if reverse:
                if ref >= len(ADDRESSES): raise ValueError('descriptor reference')
                ref = ADDRESSES[ref]
            else:
                if ref not in TO_PHYSICAL: raise ValueError('descriptor reference')
                ref = TO_PHYSICAL[ref]
            word = (word & ~(255 << shift)) | (ref << shift)
    return word

@dataclass(frozen=True)
class _EmbeddedImage:
    program: tuple[int, ...]
    templates: tuple[int, ...]
    descriptors: tuple[int, ...]

    def write(self, folder):
        self.decode()
        folder=Path(folder);folder.mkdir(parents=True, exist_ok=True)
        for name, words in zip(('program','template','descriptor'),(self.program,self.templates,self.descriptors)):
            (folder/(name+'.mem')).write_text(''.join(f'{w:016x}\n' for w in words))

    @classmethod
    def read(cls, folder):
        return cls(*(tuple(int(w,16) for w in (Path(folder)/(n+'.mem')).read_text().split())
                     for n in ('program','template','descriptor')))

    def decode(self):
        for words, count in ((self.program,64),(self.templates,16),(self.descriptors,32)):
            if len(words)!=count or any(w<0 or w>=1<<64 for w in words): raise ValueError('image capacity')
        control=self.program[52]
        sign=bool(control&1);entry=field(control,1,5);size=field(control,6,7)
        if control>>13 or not (1<=size<=87 if sign else size==0): raise ValueError('operation/control')
        d=[0]*128
        for index,(old,kind) in enumerate(zip(ADDRESSES,KINDS)):
            w=self.descriptors[index]
            if w>>60: raise ValueError('descriptor reserved type')
            d[old]=remap(w,kind,True) | (kind<<60)
        if any(self.descriptors[len(ADDRESSES):]): raise ValueError('descriptor padding')
        # The physical header stores output sizes only, profile omits family/w.
        if self.descriptors[0]>>36: raise ValueError('header reserved')
        encoded_code=self.descriptors[1]
        if encoded_code >> 6:raise ValueError('profile reserved bits')
        hash_backend='sha2' if encoded_code & 32 else 'shake'
        code=encoded_code & 31
        if code not in SLH_PROFILE_CODES:raise ValueError('SLH profile code')
        d[1]=compile_logical_image(SLH_PROFILE_CODES[code], hash_backend=hash_backend).descriptors[1]
        n=field(d[1],48,8)
        if n not in (16,24,32): raise ValueError('node width')
        templates=[]
        for w in self.templates:
            if w>>16: raise ValueError('template reserved')
            op=w&7;did=field(w,3,5);rid=field(w,8,5);flags=field(w,13,3)
            if not w:
                templates.append(0);continue
            if not 1<=op<=5 or did>=len(ADDRESSES) or rid>=len(ADDRESSES): raise ValueError('template reference')
            flags=(flags&3)|((flags&4)<<1)
            cmd=(op<<44)|(ADDRESSES[did]<<36)|(ADDRESSES[rid]<<28)|(flags<<24)
            templates.append(issue_word(cmd))
        tokens=[]
        for w in self.program[:32]:
            kind=w>>62
            if kind<2:
                if w&((1<<30)-1): raise ValueError('instruction reserved')
                tid=field(w,58,4)
                if not self.templates[tid]:
                    if w==0: break
                    raise ValueError('empty template')
                t=Token(kind,template=tid,coord0=field(w,47,11)<<13,
                        repeat=field(w,41,6)+1,stride0=field(w,30,11)<<13)
            elif kind==2:
                if w&((1<<40)-1): raise ValueError('loop reserved')
                t=Token(kind,back_count=field(w,57,5)+1,loop_repeats=field(w,51,6),delta0=field(w,40,11)<<13)
            else:
                if w!=(3<<62): raise ValueError('halt reserved')
                t=Token(3)
            tokens.append(t.encode())
        if any(self.program[len(tokens):32]): raise ValueError('program padding')
        # Entry layout is encoded by the actual HALT, not hardwired in hardware.
        try: sg_entry=tokens.index(3<<126)+1
        except ValueError: raise ValueError('missing keygen halt') from None
        if entry != (sg_entry if sign else 0): raise ValueError('operation entry')
        d[0] |= (4<<56)|(sg_entry<<38)
        # The serial sequencer has implicit completion dependencies.
        for start in (0,sg_entry):
            tid=field(tokens[start],120,6)
            templates[tid] &= ~((255<<116)|(255<<108))
        image=LogicalImage(FORMAT,tuple(tokens),tuple(templates),tuple(d), hash_backend)
        validate(image)
        if any(field(w,56,4) not in (1,2,3,4,12) for w in d if w>>60==1): raise ValueError('SLH recipe')
        if any(field(w,76,4)&4 for op in (False,True) for w in image.words(op)[:-1]): raise ValueError('SLH flags')
        for w in d:
            if w>>60==4 and (field(w,20,8)>67 or field(w,12,2)>1 or field(w,28,8) or
                            (field(w,12,2)==0 and (field(w,36,8) or field(w,20,8)!=1)) or
                            (field(w,12,2)==1 and not field(w,36,8))):
                raise ValueError('SLH chain')
            if w>>60==5 and (field(w,29,3) or field(w,32,2)>1 or field(w,36,2)>1): raise ValueError('SLH tree')
        slots=[]
        for start in range(32,52,4):
            data=b''.join(w.to_bytes(8,'little') for w in self.program[start:start+4])
            if any(data[n:]): raise ValueError('node padding')
            slots.append(data[:n])
        if not sign and any(slots[4]):raise ValueError('Keygen root slot must be zero')
        raw=b''.join(w.to_bytes(8,'little') for w in self.program[53:])
        if any(raw[size:]): raise ValueError('message padding')
        return image,Job(*slots[:4]),slots[4],raw[:size],sign

def _pack_embedded(name, job, message, root, sign, hash_backend="shake"):
    p=get_profile(name, hash_backend)
    if p.family!='slh' or job.q or any(job.identifier): raise ValueError('SLH-only job')
    image=compile_logical_image(name, hash_backend=hash_backend)
    prog=[0]*64;tpl=[0]*16;desc=[0]*32
    for i,w in enumerate(image.tokens):
        kind=w>>126
        if kind<2:
            c=field(w,96,24);s=field(w,42,24)
            if (c|s)&8191 or field(w,72,24) or field(w,18,24): raise ValueError('unsupported coordinate')
            prog[i]=(kind<<62)|(field(w,120,6)<<58)|((c>>13)<<47)|(field(w,66,6)<<41)|((s>>13)<<30)
        elif kind==2:
            delta=field(w,84,24);back=field(w,114,12)
            if delta&8191 or back>=32 or field(w,60,24): raise ValueError('unsupported loop')
            prog[i]=(2<<62)|(back<<57)|(field(w,108,6)<<51)|((delta>>13)<<40)
        else: prog[i]=3<<62
    for i,w in enumerate(image.templates):
        op=field(w,96,4);did=field(w,88,8);rid=field(w,80,8);flags=field(w,76,4)
        if flags&4: raise ValueError('stateful flags')
        tpl[i]=op|(TO_PHYSICAL[did]<<3)|(TO_PHYSICAL[rid]<<8)|(((flags&3)|((flags&8)>>1))<<13)
    for i,(old,kind) in enumerate(zip(ADDRESSES,KINDS)):
        desc[i]=remap(image.descriptors[old]&((1<<60)-1),kind)
    desc[0] &= (1<<36)-1
    desc[1] = next(code for code,profile in SLH_PROFILE_CODES.items() if profile==p.name) | (int(hash_backend == 'sha2') << 5)
    for start,data in zip(range(32,52,4),(job.secret,job.prf,job.public,job.random,root if sign else bytes(p.n))):
        if len(data)!=p.n: raise ValueError('node size')
        data=data.ljust(32,b'\0')
        prog[start:start+4]=[int.from_bytes(data[i:i+8],'little') for i in range(0,32,8)]
    message=message if sign else b''
    prog[52]=int(sign)|(image.entry(sign)<<1)|(len(message)<<6)
    for i in range(11):prog[53+i]=int.from_bytes(message[i*8:i*8+8].ljust(8,b'\0'),'little')
    result=_EmbeddedImage(tuple(prog),tuple(tpl),tuple(desc));result.decode();return result


# The production image keeps program and descriptor words in ROM. Job data,
# message and public root arrive through separate ports.
LAYOUT_REVISION = 3


@dataclass(frozen=True)
class _MainExternalImage:
    program: tuple[int, ...]
    templates: tuple[int, ...]
    descriptors: tuple[int, ...]

    @property
    def hash_backend(self):
        """The ROM marker is the sole backend identity for serialized images."""
        return 'sha2' if self.descriptors[1] & 32 else 'shake'

    def decode(self, hash_backend=None):
        if hash_backend is not None and hash_backend not in ('shake', 'sha2'):
            raise ValueError('unknown hash backend')
        if len(self.program) != 16 or len(self.templates) != 16 or len(self.descriptors) != 32:
            raise ValueError('layout 3 capacity')
        if any(w < 0 or w >= 1 << 64 for a in
               (self.program, self.templates, self.descriptors) for w in a):
            raise ValueError('word width')
        h = self.descriptors[0]
        if h >> 46:
            raise ValueError('header reserved')
        kg = (h >> 36) & 31
        sg = (h >> 41) & 31
        if kg >= 16 or sg >= 16:
            raise ValueError('entry exceeds program capacity')
        code=self.descriptors[1]
        if code >> 6:raise ValueError('profile reserved bits')
        encoded_backend=self.hash_backend
        if hash_backend is not None and hash_backend != encoded_backend:
            raise ValueError('ROM hash backend mismatch')
        if (code & 31) in (0x18,0x19,0x1a,0x1b,0x1c,0x1d):
            from model.stateful import decode
            return decode(self)
        desc = list(self.descriptors)
        desc[0] &= (1 << 36) - 1
        # Expand into the checked embedded-input decoder using zero Job fields.
        program = list(self.program) + [0] * 48
        logical = _EmbeddedImage(tuple(program), self.templates, tuple(desc)).decode()[0]
        if (kg, sg) != (logical.entry(False), logical.entry(True)):
            raise ValueError('entry table does not match program boundaries')
        return logical

    def write(self, folder):
        self.decode()
        folder = Path(folder)
        folder.mkdir(parents=True, exist_ok=True)
        for name, words in zip(('program', 'template', 'descriptor'),
                               (self.program, self.templates, self.descriptors)):
            (folder / (name + '.mem')).write_text(''.join(f'{w:016x}\n' for w in words))

    @classmethod
    def read(cls, folder):
        return cls(*(tuple(int(w, 16) for w in
                           (Path(folder) / (n + '.mem')).read_text().split())
                     for n in ('program', 'template', 'descriptor')))


def _convert_embedded(image):
    if any(image.program[16:32]):
        raise ValueError('program exceeds 16-word capacity')
    logical, job, root, message, sign = image.decode()
    d = list(image.descriptors)
    d[0] |= (logical.entry(False) << 36) | (logical.entry(True) << 41)
    result = _MainExternalImage(image.program[:16], image.templates, tuple(d))
    result.decode()
    return result


def _compile_main_image(name, hash_backend="shake"):
    """Build the external-input 16/16/32-word image for any supported profile."""
    from model.stateful import PROFILE_CODES, encode
    name=get_profile(name, hash_backend).name
    if name in PROFILE_CODES.values():
        return encode(name, hash_backend)
    n = compile_logical_image(name, hash_backend=hash_backend).n
    zero = bytes(n)
    return _convert_embedded(
        _pack_embedded(name, Job(zero, zero, zero, zero), b'\0', zero, False, hash_backend))



# Layout 5 retains compound single-Hash recipes. All chain and tree decisions
# retire as explicit narrow-context and node instructions.
from model.control import (Op, Ctx as C, Wide as W, Cond, control, fields,
                           macro, template_id, HEADER_MAGIC, KEEP_COORD,
                           PROGRAM_WORDS, TEMPLATE_WORDS, STACK_BASE, AUTH_BASE)
from model.executor import Macro, Kind, Source, Shape, CAPTURE, AUTH, EXTERNAL_ROOT, SIGN_ONLY

LAYOUT_REVISION = 5
FORMAT = 'main_soft_chain64_v5'

class _Assembler:
    def __init__(self, mapping):
        self.code=[]; self.templates=[]; self.labels={}; self.fixups=[]; self.mapping=mapping
    def label(self,name):
        if name in self.labels:raise ValueError('duplicate label '+name)
        self.labels[name]=len(self.code)
    def c(self,op,dst=0,src=0,aux=0,imm=0,target=0,cond=0):
        if isinstance(target,str):
            self.fixups.append((len(self.code),target));target=0
        self.code.append(control(op,dst,src,aux,imm,target,cond))
    def br(self,target,cond=Cond.ALWAYS,dst=C.ZERO,src=C.ZERO,imm=None):
        self.c(Op.BR,dst,src,aux=int(imm is not None),imm=imm or 0,target=target,cond=cond)
    def m(self,op,did,rid=0,flags=0):
        word=int(op)|(self.mapping[did]<<3)|(self.mapping[rid]<<8)|((flags&3)<<13)|((flags&8)<<12)|((flags&4)<<14)
        if word not in self.templates:self.templates.append(word)
        self.code.append(macro(self.templates.index(word)))
    def finish(self):
        for pc,label in self.fixups:
            if label not in self.labels:raise ValueError('missing label '+label)
            self.code[pc]|=self.labels[label]<<13
        if len(self.code)>PROGRAM_WORDS or len(self.templates)>TEMPLATE_WORDS:
            raise ValueError(f'software-chain image capacity: {len(self.code)} program / {len(self.templates)} templates')
        return (tuple(self.code+[0]*(PROGRAM_WORDS-len(self.code))),
                tuple(self.templates+[0]*(TEMPLATE_WORDS-len(self.templates))))

def _source(name,backend):
    from model.stateful import cold_image,descriptor_map
    p=get_profile(name,backend)
    logical=cold_image(p.name,backend) if p.stateful else compile_logical_image(p.name,hash_backend=backend)
    mapping={v:i for i,v in enumerate(descriptor_map(logical))} if p.stateful else TO_PHYSICAL
    return p,logical,mapping

def _build(name,hash_backend='shake'):
    p,logical,mapping=_source(name,hash_backend)
    base=_compile_main_image(p.name,hash_backend)
    a=_Assembler(mapping)
    def set_(reg,val):a.c(Op.SET,reg,imm=val)
    def mov(dst,src):a.c(Op.MOV,dst,src)
    def wmov(dst,src):a.c(Op.WMOV,dst,src)
    def ctx(height,mode,flags,target):
        set_(C.HEIGHT,height);set_(C.LIMIT,1<<height);set_(C.MODE,mode);set_(C.FLAGS,flags);mov(C.TARGET,target)
    def calltree():a.c(Op.CALL,target='tree')
    def base_address():
        if p.family=='lms':mov(C.BASE,C.LIMIT)
        elif p.family=='slh':
            set_(C.BASE,0);a.br('base_fors',Cond.EQ,C.MODE,imm=1);a.br('base_done')
            a.label('base_fors');mov(C.BASE,C.GROUP);a.c(Op.SHL,C.BASE,imm=p.a)
            a.label('base_done')
        else:set_(C.BASE,0)
    a.br('keygen');a.br('sign');a.br('sign')
    a.label('keygen')
    if p.family=='slh':set_(C.LAYER,p.d-1)
    ctx(p.h if p.stateful else p.hp,2 if p.family=='lms' else 0,0,C.Q if p.stateful else C.SCALAR_LEAF)
    calltree();wmov(W.V3,W.V2);a.m(Macro.EMIT,50);a.c(Op.HALT)
    a.label('sign')
    a.m(Macro.HASH,2,45 if p.family=='xmss' else 42 if p.family=='lms' else 40)
    if p.family!='lms':a.m(Macro.HASH,3,42 if p.stateful else 41)
    if p.stateful:
        a.m(Macro.TRANSFORM,48);a.m(Macro.EMIT,51)
        mov(C.LEAF,C.Q);mov(C.CURSOR,C.Q);set_(C.MODE,2 if p.family=='lms' else 0)
        set_(C.FLAGS,SIGN_ONLY);a.c(Op.CALL,target='chain')
        if p.family=='lms':a.m(Macro.EMIT,52)
        ctx(p.h,2 if p.family=='lms' else 0,AUTH,C.Q)
        calltree();a.c(Op.HALT)
    else:
        set_(C.GROUP,0);ctx(p.a,1,CAPTURE|AUTH,C.FORS_TARGET)
        a.label('fors_loop');mov(C.TARGET,C.FORS_TARGET);calltree();a.c(Op.INC,C.GROUP)
        a.br('fors_loop',Cond.LT,C.GROUP,imm=p.k)
        set_(C.A,0);set_(C.B,0);a.m(Macro.HASH,11,42);a.m(Macro.TRANSFORM,48)
        set_(C.GROUP,0);set_(C.LAYER,0);ctx(p.hp,0,CAPTURE|AUTH,C.SCALAR_LEAF)
        a.label('ht_loop');a.br('ht_normal',Cond.LT,C.LAYER,imm=p.d-1)
        set_(C.FLAGS,CAPTURE|AUTH|EXTERNAL_ROOT)
        a.label('ht_normal');mov(C.TARGET,C.SCALAR_LEAF);calltree()
        a.br('sign_done',Cond.EQ,C.LAYER,imm=p.d-1)
        a.m(Macro.TRANSFORM,49);a.m(Macro.TRANSFORM,48);a.c(Op.INC,C.LAYER);a.br('ht_loop')
        a.label('sign_done');a.c(Op.HALT)
    # One bounded software routine implements DFS. No control instruction
    # advances a leaf, climbs a parent, captures authentication or hashes twice.
    a.label('tree');a.br('verify_init',Cond.EQ,C.OPERATION,imm=2)
    set_(C.CURSOR,0)
    a.label('leaf')
    mov(C.LEAF,C.CURSOR)
    if not p.stateful:
        a.br('leaf_address',Cond.NE,C.MODE,imm=1);mov(C.LEAF,C.SCALAR_LEAF)
        a.label('leaf_address')
    base_address()
    a.c(Op.ADD,C.B,C.BASE,C.CURSOR);set_(C.A,0)
    mov(C.INDEX,C.CURSOR);mov(C.PATH,C.TARGET);set_(C.LEVEL,0)
    a.c(Op.CALL,target='chain')
    a.label('node');a.br('root',Cond.EQ,C.LEVEL,C.HEIGHT)
    a.br('verify_input',Cond.EQ,C.OPERATION,imm=2)
    a.br('auth_test',Cond.BITSET,C.FLAGS,imm=AUTH);a.br('after_auth')
    a.label('auth_test');a.br('auth_store',Cond.SIBLING,C.INDEX,C.PATH);a.br('after_auth')
    a.label('auth_store');a.c(Op.STORE,C.LEVEL,W.NODE,imm=AUTH_BASE)
    a.label('after_auth');a.br('parent_load',Cond.ODD,C.INDEX)
    a.c(Op.STORE,C.LEVEL,W.NODE,imm=STACK_BASE);a.c(Op.INC,C.CURSOR)
    a.br('leaf',Cond.LT,C.CURSOR,C.LIMIT)
    a.c(Op.HALT) # unreachable for a valid complete tree; decoder checks bounds
    a.label('parent_load');a.c(Op.LOAD,W.LEFT,C.LEVEL,imm=STACK_BASE)
    a.label('parent_setup');mov(C.A,C.LEVEL)
    if p.family!='xmss':a.c(Op.INC,C.A)
    set_(C.LEAF,0)
    if p.family=='slh':
        a.br('parent_address',Cond.NE,C.MODE,imm=1);mov(C.LEAF,C.SCALAR_LEAF)
        a.label('parent_address')
    a.c(Op.SHR,C.INDEX,imm=1);a.c(Op.SHR,C.PATH,imm=1);a.c(Op.SHR,C.BASE,imm=1)
    a.c(Op.ADD,C.B,C.BASE,C.INDEX);a.c(Op.INC,C.LEVEL)
    if p.family=='slh':
        a.br('parent_hash',Cond.EQ,C.OPERATION,imm=2)
        a.br('parent_shortcut_test',Cond.BITSET,C.FLAGS,imm=EXTERNAL_ROOT);a.br('parent_hash')
        a.label('parent_shortcut_test');a.br('parent_zero',Cond.EQ,C.INDEX,C.PATH)
        a.label('parent_hash');a.br('hash_fors',Cond.EQ,C.MODE,imm=1)
        a.m(Macro.HASH,10);a.br('parent_done')
        a.label('hash_fors');a.m(Macro.HASH,6)
    else:a.m(Macro.HASH,7)
    a.label('parent_done');wmov(W.NODE,W.LEFT);a.br('node')
    if p.family=='slh':
        a.label('parent_zero');wmov(W.NODE,W.ZERO);a.br('node')
    a.label('verify_init')
    mov(C.CURSOR,C.TARGET)
    if p.stateful:
        wmov(W.NODE,W.V2);mov(C.INDEX,C.TARGET);mov(C.PATH,C.TARGET);set_(C.LEVEL,0)
        base_address();a.br('node')
    else:a.br('leaf')
    a.label('verify_input');a.br('verify_odd',Cond.ODD,C.INDEX)
    wmov(W.LEFT,W.NODE);a.c(Op.INPUT,W.NODE);a.br('parent_setup')
    a.label('verify_odd');a.c(Op.INPUT,W.LEFT);a.br('parent_setup')
    a.label('root')
    if p.family=='slh':
        a.br('fors_root',Cond.EQ,C.MODE,imm=1);wmov(W.V2,W.NODE);a.br('root_saved')
        a.label('fors_root');a.c(Op.STORE,C.GROUP,W.NODE)
        a.label('root_saved')
    else:wmov(W.V2,W.NODE)
    a.br('return',Cond.EQ,C.OPERATION,imm=2)
    a.br('auth_output',Cond.BITSET,C.FLAGS,imm=AUTH);a.br('return')
    a.label('auth_output');set_(C.AUTH_LEVEL,0)
    a.label('auth_loop');a.c(Op.LOAD,W.NODE,C.AUTH_LEVEL,imm=AUTH_BASE);a.c(Op.OUTPUT,src=W.NODE)
    a.c(Op.INC,C.AUTH_LEVEL);a.br('auth_loop',Cond.LT,C.AUTH_LEVEL,C.HEIGHT)
    a.label('return');a.c(Op.RET)
    # A leaf is a bounded software routine. A and B are the only chain
    # coordinates; the dedicated L-tree cursors are narrow scalar contexts.
    a.label('chain')
    if p.family=='slh':
        a.br('fors_chain',Cond.EQ,C.MODE,imm=1)
    chain_descriptor=logical.descriptors[16 if p.stateful else 17]
    seed,step,reduce,leaf_recipe=(field(chain_descriptor,shift,8) for shift in (52,44,36,28))
    count=field(chain_descriptor,20,8);steps=field(chain_descriptor,15,5)
    set_(C.A,0)
    a.label('chain_item')
    a.br('chain_input',Cond.EQ,C.OPERATION,imm=2)
    set_(C.B,0);a.m(Macro.HASH,seed);a.br('capture_test')
    a.label('chain_input');a.c(Op.INPUT,W.LEFT);mov(C.B,C.DIGIT);a.br('chain_test')
    a.label('capture_test')
    # Explicit output at the selected prefix never authorizes another Hash.
    a.br('capture_emit_test',Cond.BITSET,C.FLAGS,imm=SIGN_ONLY)
    a.br('chain_test',Cond.NE,C.CURSOR,C.TARGET)
    a.br('capture_emit_test',Cond.BITSET,C.FLAGS,imm=CAPTURE);a.br('chain_test')
    a.label('capture_emit_test');a.br('chain_test',Cond.NE,C.B,C.DIGIT)
    a.c(Op.OUTPUT,src=W.LEFT)
    a.label('chain_test')
    a.br('chain_endpoint',Cond.GE,C.B,imm=steps)
    a.br('chain_step',Cond.EQ,C.OPERATION,imm=2)
    a.br('prefix_test',Cond.BITSET,C.FLAGS,imm=SIGN_ONLY)
    if p.family=='slh':
        a.br('chain_step',Cond.NE,C.CURSOR,C.TARGET)
        a.br('prefix_test',Cond.BITSET,C.FLAGS,imm=EXTERNAL_ROOT)
    a.br('chain_step')
    a.label('prefix_test');a.br('chain_endpoint',Cond.GE,C.B,C.DIGIT)
    a.label('chain_step');a.m(Macro.HASH,step);a.c(Op.INC,C.B)
    a.br('chain_test',Cond.EQ,C.OPERATION,imm=2);a.br('capture_test')
    a.label('chain_endpoint');a.c(Op.STORE,C.A,W.LEFT);a.c(Op.INC,C.A)
    a.br('chain_item',Cond.LT,C.A,imm=count)
    a.br('chain_reduce',Cond.EQ,C.OPERATION,imm=2)
    a.br('chain_return',Cond.BITSET,C.FLAGS,imm=SIGN_ONLY)
    if p.family=='slh':
        a.br('chain_reduce',Cond.NE,C.CURSOR,C.TARGET)
        a.br('chain_zero',Cond.BITSET,C.FLAGS,imm=EXTERNAL_ROOT)
    a.label('chain_reduce')
    if p.family=='xmss':
        set_(C.LT_COUNT,count);set_(C.LT_LEVEL,0)
        a.label('lt_layer');set_(C.LT_CURSOR,0)
        a.label('lt_pair');mov(C.A,C.LT_LEVEL);mov(C.B,C.LT_CURSOR);a.c(Op.SHR,C.B,imm=1)
        a.c(Op.LOAD,W.LEFT,C.LT_CURSOR);a.c(Op.INC,C.LT_CURSOR)
        a.br('lt_store',Cond.GE,C.LT_CURSOR,C.LT_COUNT)
        a.c(Op.LOAD,W.NODE,C.LT_CURSOR);a.m(Macro.HASH,reduce);a.c(Op.INC,C.LT_CURSOR)
        a.label('lt_store');a.c(Op.STORE,C.B,W.LEFT)
        a.br('lt_pair',Cond.LT,C.LT_CURSOR,C.LT_COUNT)
        a.c(Op.INC,C.LT_COUNT);a.c(Op.SHR,C.LT_COUNT,imm=1);a.c(Op.INC,C.LT_LEVEL)
        a.br('lt_layer',Cond.GE,C.LT_COUNT,imm=2)
        a.c(Op.LOAD,W.NODE,C.ZERO)
    else:
        set_(C.A,0);set_(C.B,0);a.m(Macro.HASH,reduce)
        if leaf_recipe:
            set_(C.B,1<<p.h);a.c(Op.ADD,C.B,C.B,C.LEAF);a.m(Macro.HASH,leaf_recipe)
        wmov(W.NODE,W.LEFT)
    if p.stateful:
        a.br('chain_return',Cond.NE,C.OPERATION,imm=2);wmov(W.V2,W.NODE)
    a.label('chain_return');a.c(Op.RET)
    if p.family=='slh':
        a.label('chain_zero');wmov(W.NODE,W.ZERO);a.c(Op.RET)
        fdesc=logical.descriptors[16];fseed=field(fdesc,52,8);fstep=field(fdesc,44,8)
        a.label('fors_chain');a.br('fors_input',Cond.EQ,C.OPERATION,imm=2)
        a.m(Macro.HASH,fseed);a.br('fors_step',Cond.NE,C.CURSOR,C.TARGET)
        a.br('fors_capture',Cond.BITSET,C.FLAGS,imm=CAPTURE);a.br('fors_step')
        a.label('fors_capture');a.c(Op.OUTPUT,src=W.LEFT);a.br('fors_step')
        a.label('fors_input');a.c(Op.INPUT,W.LEFT)
        a.label('fors_step');a.m(Macro.HASH,fstep);wmov(W.NODE,W.LEFT);a.c(Op.RET)
    program,templates=a.finish()
    d=list(base.descriptors)
    d[0]=(d[0]&((1<<36)-1))|(0<<36)|(1<<43)|(2<<50)|(HEADER_MAGIC<<57)
    return ExternalImage(program,templates,tuple(d)),logical,mapping,a.labels,len(a.code),len(a.templates)

@dataclass(frozen=True)
class DecodedImage:
    source: LogicalImage
    external: object
    def __getattr__(self,name):return getattr(self.source,name)
    def entry(self,sign=False,operation=None):
        op=int(sign) if operation is None else int(operation)
        return (self.external.descriptors[0]>>(36+7*op))&127

@dataclass(frozen=True)
class ExternalImage:
    program: tuple[int,...]
    templates: tuple[int,...]
    descriptors: tuple[int,...]
    @property
    def hash_backend(self):return 'sha2' if self.descriptors[1]&32 else 'shake'
    def decode(self,hash_backend=None):
        if (len(self.program),len(self.templates),len(self.descriptors))!=(256,32,32):raise ValueError('layout 5 capacity')
        if any(not 0<=w<1<<64 for group in (self.program,self.templates,self.descriptors) for w in group):raise ValueError('word width')
        if self.descriptors[0]>>57!=HEADER_MAGIC:raise ValueError('software-chain layout version')
        if tuple((self.descriptors[0]>>(36+7*op))&127 for op in range(3))!=(0,1,2):raise ValueError('entry trampolines')
        code=self.descriptors[1]
        if code>>6:raise ValueError('profile reserved bits')
        if hash_backend is not None and hash_backend!=self.hash_backend:raise ValueError('ROM hash backend mismatch')
        from model.stateful import PROFILE_CODES
        names={**SLH_PROFILE_CODES,**PROFILE_CODES}
        if code&31 not in names:raise ValueError('profile code')
        p,logical,mapping=_source(names[code&31],self.hash_backend)
        expected=_compile_main_image(p.name,self.hash_backend)
        if self.descriptors[1:]!=expected.descriptors[1:] or self.descriptors[0]&((1<<36)-1)!=expected.descriptors[0]&((1<<36)-1):raise ValueError('noncanonical recipe/profile')
        for t in self.templates:
            if not t:continue
            if t>>17 or t&7 not in (1,4,5):raise ValueError('CHAIN/TREE or illegal template')
            did=(t>>3)&31;rid=(t>>8)&31
            if did not in mapping.values() or rid not in mapping.values():raise ValueError('template reference')
        for word in self.program:
            kind=word>>62
            if kind==3:
                if word&511:raise ValueError('control reserved bits')
                op,dst,src,aux,imm,target,cond=fields(word)
                if op==Op.HALT and word!=3<<62:raise ValueError('HALT reserved bits')
                if op==Op.BR and aux>1:raise ValueError('branch operand mode')
                writable=(*range(16),26,27,28);readable=range(29)
                if op in (Op.SET,Op.MOV,Op.INC,Op.SHR,Op.XOR1,Op.ADD,Op.SHL) and dst not in writable:raise ValueError('readonly context write')
                if op in (Op.MOV,Op.ADD) and src not in readable:raise ValueError('context selector')
                if op==Op.ADD and aux not in readable:raise ValueError('context selector')
                if op==Op.SET and (imm>=1<<ControlMachine._widths[dst] or (dst in (C.HEIGHT,C.LEVEL,C.AUTH_LEVEL) and imm>20) or (dst==C.MODE and imm>2)):raise ValueError('context immediate overflow')
                if op in (Op.SHR,Op.SHL) and not 1<=imm<=20:raise ValueError('shift bound')
                if op==Op.BR and (dst not in readable or src not in readable):raise ValueError('branch context selector')
                if op in (Op.LOAD,Op.INPUT,Op.WMOV) and not 0<=dst<7:raise ValueError('wide destination')
                if op in (Op.STORE,Op.OUTPUT,Op.WMOV) and not 0<=src<=7:raise ValueError('wide source')
                if op==Op.LOAD and src not in readable:raise ValueError('memory context selector')
                if op==Op.STORE and dst not in readable:raise ValueError('memory context selector')
            elif kind<2:
                if not word:continue
                if word&((1<<28)-1) or not self.templates[template_id(word)]:raise ValueError('macro token')
            else:
                if word&((1<<40)-1) or not (word>>51)&63:raise ValueError('counted LOOP fields')
        return DecodedImage(logical,self)
    def write(self,folder):
        self.decode();folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
        for name,words in zip(('program','template','descriptor'),(self.program,self.templates,self.descriptors)):
            (folder/(name+'.mem')).write_text(''.join(f'{w:016x}\n' for w in words))
    @classmethod
    def read(cls,folder):
        return cls(*(tuple(int(w,16) for w in (Path(folder)/(n+'.mem')).read_text().split()) for n in ('program','template','descriptor')))
    @property
    def usage(self):
        decoded=self.decode();_,_,mapping=_source(decoded.name,self.hash_backend)
        _,_,_,labels,count,tcount=_build(decoded.name,self.hash_backend)
        ops={'HASH':0,'CHAIN':0,'TREE':0,'TRANSFORM':0,'EMIT':0,'control':0}
        for word in self.program[:count]:
            if word>>62==3:ops['control']+=1
            else:ops[Macro(self.templates[template_id(word)]&7).name]+=1
        used={0,1}
        def visit(index):
            if index in used:return
            used.add(index);word=decoded.source.descriptors[index];kind=word>>60
            for shift in {int(Kind.CHAIN):(52,44,36,28),int(Kind.EMIT):(52,)}.get(kind,()):
                ref=field(word,shift,8)
                if ref:visit(ref)
            if kind==Kind.EMIT:
                for ref in range(field(word,52,8),field(word,52,8)+field(word,48,4)):visit(ref)
        reverse={v:k for k,v in mapping.items()}
        for word in self.templates[:tcount]:
            visit(reverse[(word>>3)&31]);visit(reverse[(word>>8)&31])
        return dict(program_allocated=256,program_used=count,template_allocated=32,template_used=tcount,
                    descriptor_allocated=32,descriptor_used=len(used),descriptor_valid=len(mapping),
                    descriptor_nonzero=sum(bool(w) for w in self.descriptors),
                    descriptor_reachable=sorted(mapping[index] for index in used),
                    static_operations=ops,entries=labels)

def compile_image(name,hash_backend='shake'):
    return _build(name,hash_backend)[0]

compile_external=compile_image
Image=ExternalImage

class ControlMachine:
    """Execute physical tokens; tree traversal exists only in the program.

    Compound Hash recipes are shared with the main algorithm model. Chain and
    tree control exists only in the physical program, never in a VM shortcut.
    """
    _widths=(20,8,21,21,21,5,21,21,21,5,21,5,6,5,4,2,20,20,14,5,1,1,2,1,1,4,8,8,4)
    def __init__(self,image,job,root,message,operation=1,verify_nodes=(),observe=None):
        self.external=image;self.decoded=image.decode();self.profile=get_profile(self.decoded.name,image.hash_backend)
        self.vm=Machine(self.decoded.source,job,observe,index_policy='fixed_q_no_guard',recompute_auth=True)
        self.vm.active_q=job.q;self.vm.message=bytes(message);self.vm.values[3]=bytes(root)
        self.operation=int(operation);self.ctx=[0]*29;self.ram=[bytes(self.profile.n) for _ in range(128)]
        self.node=bytes(self.profile.n);self.left=bytes(self.profile.n);self.emit=bytes(self.profile.n)
        self.inputs=iter(bytes(x) for x in verify_nodes);self.input_count=0
        self.return_stack=[];self.loops=[];self.halted=False;self.steps=0
        self.operations={op.name:0 for op in Macro};self.operations['control']=0
        self.control_trace=[];self.macro_trace=[]
        _,_,mapping=_source(self.profile.name,image.hash_backend)
        self.logical_ref={v:k for k,v in mapping.items()}
        if not 0<=self.operation<=2:raise ValueError('operation')
        if self.profile.stateful and not 0<=job.q<1<<self.profile.h:raise ValueError('index exhausted')
        if not self.profile.stateful and (job.q or any(job.identifier)):raise ValueError('SLH-only job')
        if len(root)!=self.profile.n:raise ValueError('root size')
        if self.operation and not (0 if self.profile.stateful else 1)<=len(message)<=87:raise ValueError('message length')
        if not self.operation and message:raise ValueError('Keygen message must be empty')
    def __getattr__(self,name):return getattr(self.vm,name)
    def narrow(self,reg):
        if reg<16 or reg in (C.LT_COUNT,C.LT_CURSOR,C.LT_LEVEL):return self.ctx[reg]
        p=self.profile
        if reg==C.Q:return self.vm.job.q
        if reg==C.SCALAR_LEAF:return self.vm.scalar_leaf
        if reg==C.FORS_TARGET:
            fb=(p.k*p.a+7)//8
            shift=8*fb-p.a*(self.ctx[C.GROUP]+1)
            if shift<0:raise ValueError('FORS digest bounds')
            return (int.from_bytes(self.vm.values[1][:fb],'big')>>shift)&((1<<p.a)-1)
        if reg==C.PROFILE_HEIGHT:return p.h
        if reg==C.ZERO:return 0
        if reg==C.ONE:return 1
        if reg==C.OPERATION:return self.operation
        if reg==C.XMSS:return int(p.family=='xmss')
        if reg==C.STATEFUL:return int(p.stateful)
        if reg==C.DIGIT:
            index=self.ctx[C.A]
            return self.vm.digits[index] if 0<=index<len(self.vm.digits) else 0
        raise ValueError('context selector')
    def put_narrow(self,reg,value):
        if reg not in (*range(16),26,27,28) or not 0<=value<1<<self._widths[reg]:raise ValueError('context write/bounds')
        if reg in (C.HEIGHT,C.LEVEL,C.AUTH_LEVEL) and value>20:raise ValueError('tree height/level bounds')
        if reg==C.MODE and value>2:raise ValueError('address mode bounds')
        self.ctx[reg]=value
    def wide(self,reg):
        if reg==W.NODE:return self.node
        if reg==W.LEFT:return self.left[:self.profile.n]
        if W.V0<=reg<=W.V3:return self.vm.values[reg-W.V0][:self.profile.n]
        if reg==W.EMIT:return self.emit
        if reg==W.ZERO:return bytes(self.profile.n)
        raise ValueError('wide selector')
    def put_wide(self,reg,value):
        value=bytes(value)[:self.profile.n]
        if reg==W.NODE:self.node=value
        elif reg==W.LEFT:self.left=value
        elif W.V0<=reg<=W.V3:
            slot=reg-W.V0
            self.vm.values[slot]=value+(self.vm.values[slot][self.profile.n:] if slot==1 else b'')
        elif reg==W.EMIT:self.emit=value
        else:raise ValueError('wide write')
    def input(self):
        try:value=next(self.inputs)
        except StopIteration:raise ValueError('truncated Verify input') from None
        if len(value)!=self.profile.n:raise ValueError('Verify node size')
        self.input_count+=1;return value
    def memory_address(self,reg,imm):
        address=self.narrow(reg)+imm
        if not 0<=address<128 or 108<=address:raise ValueError('workspace bounds')
        if 68<=address<88 and not self.narrow(reg)<20:raise ValueError('stack level')
        if 88<=address<108 and not self.narrow(reg)<20:raise ValueError('authentication level')
        return address
    def branch(self,cond,dst,src,aux,imm):
        left=self.narrow(dst);right=imm if aux else self.narrow(src)
        return {Cond.ALWAYS:lambda:True,Cond.EQ:lambda:left==right,Cond.NE:lambda:left!=right,
                Cond.LT:lambda:left<right,Cond.GE:lambda:left>=right,Cond.ODD:lambda:bool(left&1),
                Cond.ZERO:lambda:left==0,Cond.BITSET:lambda:bool(left&imm),
                Cond.SIBLING:lambda:left==(right^1),Cond.SAME_PARENT:lambda:(left>>1)==(right>>1)}[cond]()
    def macro(self,word):
        t=self.external.templates[template_id(word)]
        op=Macro(t&7);did=self.logical_ref[(t>>3)&31];rid=self.logical_ref[(t>>8)&31]
        flags=((t>>13)&3)|(((t>>15)&1)<<3)|(((t>>16)&1)<<2)
        if not word&KEEP_COORD:
            coordinate=(word>>47)&2047;self.ctx[C.LAYER]=coordinate>>6;self.ctx[C.GROUP]=coordinate&63
        self.operations[op.name]+=1;self.macro_trace.append((self.pc,op.name,did,flags,self.ctx.copy()))
        result=bytes(self.profile.n);d=self.vm.image.descriptors[did]
        if op==Macro.HASH:
            shape=Shape(field(d,56,4))
            if self.operation==2 and shape in (Shape.MESSAGE_PRF,Shape.INDEX_PRF):result=self.input()
            else:
                if self.operation==2 and shape==Shape.PREFIX_MESSAGE:self.vm.job=__import__('dataclasses').replace(self.vm.job,random=self.input())
                result=self.vm.hash_recipe(did,layer=self.ctx[C.LAYER],leaf=self.ctx[C.LEAF],a=self.ctx[C.A],b=self.ctx[C.B],
                                           left=self.left[:self.profile.n],right=self.node,values=self.ram[:field(d,40,8)])
            self.left=result
        elif op==Macro.TRANSFORM:
            if field(d,56,4)==1:
                value=self.vm.values[field(d,48,2)][:self.profile.n];omega=self.vm.image.omega;mask=(1<<omega)-1
                self.vm.digits=[(x>>shift)&mask for x in value for shift in range(8-omega,-1,-omega)]
                checksum=sum(mask-x for x in self.vm.digits)
                len2=(len(self.vm.digits)*mask).bit_length()//omega+1
                self.vm.digits +=[(checksum>>shift)&mask for shift in range((len2-1)*omega,-1,-omega)]
            elif field(d,56,4)==2:
                shift=field(d,40,4);self.vm.scalar_leaf=self.vm.scalar_tree&((1<<shift)-1);self.vm.scalar_tree>>=shift
            else:raise ValueError('transform')
        elif op==Macro.EMIT:
            if self.operation!=2:
                for i in range(field(d,52,8),field(d,52,8)+field(d,48,4)):
                    seg=self.vm.image.descriptors[i];src=Source(field(seg,56,4));length=field(seg,48,8)
                    value={Source.SECRET:self.vm.job.secret,Source.PRF:self.vm.job.prf,Source.PUBLIC:self.vm.job.public,
                           Source.ROOT:self.vm.values[3],Source.RANDOM:self.vm.values[0] if self.profile.family=='xmss' else self.vm.job.random,
                           Source.IDENTIFIER:self.vm.job.identifier,Source.INDEX:self.vm.active_q.to_bytes(4,'big'),
                           Source.CONSTANT:field(seg,0,32).to_bytes(4,'big')}[src]
                    self.vm.output.extend(value[:length])
        else:raise ValueError('TREE unavailable')
        if rid:
            r=self.vm.image.descriptors[rid]
            if field(r,53,1):self.ram[self.ctx[C.GROUP]]=result[:self.profile.n]
            else:self.vm.values[field(r,56,2)]=result
            if self.operation!=2 and field(r,55,1):self.vm.output.extend(result[:self.profile.n])
            if field(r,54,1):
                fb=(self.profile.k*self.profile.a+7)//8;tb=(self.profile.h-self.profile.hp+7)//8;lb=(self.profile.hp+7)//8
                self.vm.scalar_tree=int.from_bytes(result[fb:fb+tb],'big')&((1<<(self.profile.h-self.profile.hp))-1)
                self.vm.scalar_leaf=int.from_bytes(result[fb+tb:fb+tb+lb],'big')&((1<<self.profile.hp)-1)
    def run(self):
        if self.halted:raise ValueError('halted until reset')
        self.pc=self.decoded.entry(operation=self.operation)
        try:
            while True:
                self.steps+=1
                if self.steps>1000000000:raise ValueError('control budget')
                if not 0<=self.pc<PROGRAM_WORDS:raise ValueError('program bounds')
                word=self.external.program[self.pc]
                kind=word>>62
                if kind<2:
                    coordinate=((word>>47)&2047)+sum(frame[2] for frame in self.loops)
                    for iteration in range(((word>>41)&63)+1):
                        issued=(word&~(2047<<47))|(((coordinate+iteration*((word>>30)&2047))&2047)<<47)
                        self.macro(issued)
                    self.pc+=1;continue
                if kind==2:
                    back=((word>>57)&31)+1
                    if back>self.pc:raise ValueError('LOOP target')
                    if self.loops and self.loops[-1][0]==self.pc:
                        frame=self.loops[-1]
                        if frame[1]>1:frame[1]-=1;frame[2]=(frame[2]+frame[3])&2047;self.pc-=back
                        else:self.loops.pop();self.pc+=1
                    else:
                        if len(self.loops)==2:raise ValueError('LOOP nesting')
                        self.loops.append([self.pc,(word>>51)&63,(word>>40)&2047,(word>>40)&2047]);self.pc-=back
                    continue
                op,dst,src,aux,imm,target,cond=fields(word);next_pc=self.pc+1
                self.operations['control']+=1
                if op==Op.HALT:
                    if self.return_stack or self.loops:raise ValueError('HALT within subroutine/loop')
                    break
                if op==Op.SET:self.put_narrow(dst,imm)
                elif op==Op.MOV:self.put_narrow(dst,self.narrow(src))
                elif op==Op.INC:self.put_narrow(dst,self.narrow(dst)+1)
                elif op==Op.SHR:self.put_narrow(dst,self.narrow(dst)>>imm)
                elif op==Op.XOR1:self.put_narrow(dst,self.narrow(dst)^1)
                elif op==Op.ADD:self.put_narrow(dst,self.narrow(src)+self.narrow(aux))
                elif op==Op.SHL:self.put_narrow(dst,self.narrow(dst)<<imm)
                elif op==Op.BR:
                    if self.branch(cond,dst,src,aux,imm):next_pc=target
                elif op==Op.CALL:
                    if len(self.return_stack)>=2:raise ValueError('CALL overflow')
                    self.return_stack.append(self.pc+1);next_pc=target
                elif op==Op.RET:
                    if not self.return_stack:raise ValueError('RET without CALL')
                    next_pc=self.return_stack.pop()
                elif op==Op.LOAD:self.put_wide(dst,self.ram[self.memory_address(src,imm)])
                elif op==Op.STORE:self.ram[self.memory_address(dst,imm)]=self.wide(src)
                elif op==Op.INPUT:self.put_wide(dst,self.input())
                elif op==Op.OUTPUT:
                    if self.operation==2:raise ValueError('Verify output')
                    self.vm.output.extend(self.wide(src))
                elif op==Op.WMOV:self.put_wide(dst,self.wide(src))
                else:raise ValueError('control opcode')
                self.pc=next_pc
            self.halted=True
            if self.operation==2:
                self.verify_pass=self.vm.values[2][:self.profile.n]==self.vm.values[3][:self.profile.n]
                if not self.verify_pass:raise ValueError('root comparison')
                try:next(self.inputs)
                except StopIteration:pass
                else:raise ValueError('excess Verify input')
                if self.vm.output:raise ValueError('Verify produced output')
            elif len(self.vm.output)!=self.vm.image.output_bytes(self.operation==1):raise ValueError('output length')
            return bytes(self.vm.output)
        except Exception:
            self.vm.output.clear();self.halted=True;raise

class ExternalMachine:
    def __init__(self,image,job,root,message,sign=True,observe=None,*,operation=None,verify_nodes=()):
        self.machine=ControlMachine(image,job,root,message,int(sign) if operation is None else operation,verify_nodes,observe)
    def run(self):return self.machine.run()
