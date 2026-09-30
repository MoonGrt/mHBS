"""v4.2 physical images, retaining the five ABI 4 macro semantics.

There is no hardware admission path. decode() is the offline trust boundary.
Bit allocations are intentionally identical for all six SLH parameter sets.
"""
from dataclasses import dataclass
from pathlib import Path
from model.unified_hbs import Image, Job, Machine, compile_image, field, validate
from model.static_task_microcode import StaticTaskToken as Token, issue_word
from model.profiles import get_profile, SLH_PROFILE_CODES

FORMAT = 'slh64_v4.2'
LAYOUT_REVISION = 2
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
class CompactImage:
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
        code=self.descriptors[1]
        if code not in SLH_PROFILE_CODES:raise ValueError('SLH profile code')
        d[1]=compile_image(SLH_PROFILE_CODES[code]).descriptors[1]
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
        image=Image(FORMAT,tuple(tokens),tuple(templates),tuple(d))
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

def pack(name, job, message, root, sign):
    p=get_profile(name)
    if p.family!='slh' or job.q or any(job.identifier): raise ValueError('SLH-only job')
    image=compile_image(name)
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
    desc[1] = next(code for code,profile in SLH_PROFILE_CODES.items() if profile==p.name)
    for start,data in zip(range(32,52,4),(job.secret,job.prf,job.public,job.random,root if sign else bytes(p.n))):
        if len(data)!=p.n: raise ValueError('node size')
        data=data.ljust(32,b'\0')
        prog[start:start+4]=[int.from_bytes(data[i:i+8],'little') for i in range(0,32,8)]
    message=message if sign else b''
    prog[52]=int(sign)|(image.entry(sign)<<1)|(len(message)<<6)
    for i in range(11):prog[53+i]=int.from_bytes(message[i*8:i*8+8].ljust(8,b'\0'),'little')
    result=CompactImage(tuple(prog),tuple(tpl),tuple(desc));result.decode();return result

class CompactMachine:
    def __init__(self,image,observe=None):
        logical,job,root,self.message,self.sign=image.decode()
        self.machine=Machine(logical,job,observe)
        if self.sign:self.machine.values[3]=root
        self.halted=False

    def run(self):
        if self.halted:raise ValueError('halted until reset')
        self.halted=True
        return self.machine.run(self.sign,self.message)
