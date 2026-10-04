"""slh64_v4.2 layout 3: code images plus independent Job/message inputs."""
from dataclasses import dataclass
from pathlib import Path
from model.slh64 import CompactImage, pack, FORMAT, TO_PHYSICAL
from model.unified_hbs import Job, Machine, compile_image

LAYOUT_REVISION = 3

@dataclass(frozen=True)
class ExternalImage:
    program: tuple[int, ...]
    templates: tuple[int, ...]
    descriptors: tuple[int, ...]

    def decode(self):
        if len(self.program)!=16 or len(self.templates)!=16 or len(self.descriptors)!=32:
            raise ValueError('layout 3 capacity')
        if any(w<0 or w>=1<<64 for a in (self.program,self.templates,self.descriptors) for w in a):
            raise ValueError('word width')
        h=self.descriptors[0]
        if h>>46:raise ValueError('header reserved')
        kg=(h>>36)&31;sg=(h>>41)&31
        if kg>=16 or sg>=16:raise ValueError('entry exceeds program capacity')
        if self.descriptors[1] in (8,9,10,11):
            from model.stateful import decode
            return decode(self)
        desc=list(self.descriptors);desc[0]&=(1<<36)-1
        # Reuse the independently checked ABI-4 expansion and reference checks.
        # The legacy decoder receives synthetic zero inputs, never caller data.
        program=list(self.program)+[0]*48
        logical=CompactImage(tuple(program),self.templates,tuple(desc)).decode()[0]
        if (kg,sg)!=(logical.entry(False),logical.entry(True)):
            raise ValueError('entry table does not match program boundaries')
        return logical

    def write(self,folder):
        self.decode();folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
        for name,words in zip(('program','template','descriptor'),(self.program,self.templates,self.descriptors)):
            (folder/(name+'.mem')).write_text(''.join(f'{w:016x}\n' for w in words))

    @classmethod
    def read(cls,folder):
        return cls(*(tuple(int(w,16) for w in (Path(folder)/(n+'.mem')).read_text().split()) for n in ('program','template','descriptor')))


def convert_legacy(image):
    if any(image.program[16:32]):raise ValueError('program exceeds 16-word capacity')
    logical,job,root,message,sign=image.decode()
    d=list(image.descriptors)
    d[0]|=(logical.entry(False)<<36)|(logical.entry(True)<<41)
    result=ExternalImage(image.program[:16],image.templates,tuple(d));result.decode()
    return result,job,root,message,sign


def compile_external(name):
    from model.stateful import PROFILE_CODES,encode
    if name in PROFILE_CODES.values():return encode(name)
    n=compile_image(name).n
    zero=bytes(n)
    return convert_legacy(pack(name,Job(zero,zero,zero,zero),b'\0',zero,False))[0]


class ExternalMachine:
    def __init__(self,image,job,root,message,sign,observe=None):
        logical=image.decode()
        if not logical.stateful and (job.q or any(job.identifier)):raise ValueError('SLH-only job')
        if logical.stateful and not 0<=job.q<1024:raise ValueError('index exhausted')
        if len(root)!=logical.n:raise ValueError('root size')
        if not (1<=len(message)<=87 if sign else len(message)==0):raise ValueError('message length')
        self.machine=Machine(logical,job,observe, index_policy='fixed_q_no_guard' if logical.stateful else 'guarded', recompute_auth=logical.stateful)
        self.message=message;self.sign=bool(sign);self.halted=False
        if sign:self.machine.values[3]=root

    def run(self):
        if self.halted:raise ValueError('halted until reset')
        self.halted=True
        return self.machine.run(self.sign,self.message)
