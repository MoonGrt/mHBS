"""v4.1 autonomous images: unchanged ABI 4 instructions plus program data.

Numbers in .mem files are logical words. Job/message bytes occupy increasing
little-endian byte positions; algorithm integer encodings remain big endian.
"""
from dataclasses import dataclass
from pathlib import Path
from model.unified_hbs import Image, Job, Machine, compile_image, validate

VERSION='v4.1'
ABI_VERSION=4
PROGRAM_WORDS,TEMPLATE_WORDS,DESCRIPTOR_WORDS=64,64,128

@dataclass(frozen=True)
class ProgramImage:
    program: tuple[int,...]
    templates: tuple[int,...]
    descriptors: tuple[int,...]

    @classmethod
    def read(cls, directory):
        p=Path(directory)
        return cls(*(tuple(int(x,16) for x in (p/(name+'.mem')).read_text().split())
                     for name in ('program','template','descriptor')))

    def write(self, directory):
        p=Path(directory);p.mkdir(parents=True,exist_ok=True)
        for name,words,width in (('program',self.program,32),('template',self.templates,32),('descriptor',self.descriptors,16)):
            (p/(name+'.mem')).write_text(''.join(f'{w:0{width}x}\n' for w in words))

    def decode(self):
        for words,count,bits in ((self.program,64,128),(self.templates,64,128),(self.descriptors,128,64)):
            if len(words)!=count or any(w<0 or w>=1<<bits for w in words):raise ValueError('ROM capacity/word width')
        # Control word: q[10:0], message_bytes[17:11], instructions[23:18], templates[30:24].
        control=self.program[41]
        q=control&2047;size=(control>>11)&127;count=(control>>18)&63;templates=(control>>24)&127
        if control>>31 or not 1<=count<=32 or not 1<=templates<=64:raise ValueError('program control')
        if not 1<=size<=87:raise ValueError('message length')
        if any(self.program[count:32]) or any(self.program[42:44]) or any(self.program[50:]):raise ValueError('program reserved data')
        if any(self.templates[templates:]):raise ValueError('template padding')
        image=Image('program',self.program[:count],self.templates[:templates],self.descriptors)
        validate(image)
        family=(self.descriptors[1]>>56)&7
        allowed={1:{1,2,3,4,12},2:{5,6,7,8},3:{9,10,11,13,14,15}}[family]
        if any((w>>60)==1 and ((w>>56)&15) not in allowed for w in self.descriptors):
            raise ValueError('recipe/profile mismatch')
        if image.stateful and q>=1024:raise ValueError('index exhausted')
        if not image.stateful and q:raise ValueError('stateless index')
        fields=[]
        for start in (32,34,36,38):
            data=b''.join(x.to_bytes(16,'little') for x in self.program[start:start+2])
            if any(data[image.n:]):raise ValueError('node padding')
            fields.append(data[:image.n])
        message=b''.join(x.to_bytes(16,'little') for x in self.program[44:50])
        if any(message[size:]):raise ValueError('message padding')
        job=Job(*fields,self.program[40].to_bytes(16,'little'),q)
        return image,job,message[:size]


def pack(name,job,message):
    image=compile_image(name)
    if len(image.tokens)>32 or len(image.templates)>64:raise ValueError('instruction/template capacity')
    program=list(image.tokens)+[0]*(64-len(image.tokens))
    for start,data in zip((32,34,36,38),(job.secret,job.prf,job.public,job.random)):
        if len(data)!=image.n:raise ValueError('job node width')
        data=data.ljust(32,b'\0')
        program[start:start+2]=[int.from_bytes(data[i:i+16],'little') for i in (0,16)]
    if len(job.identifier)!=16:raise ValueError('identifier length')
    program[40]=int.from_bytes(job.identifier,'little')
    if not 0<=job.q<=1024 or not 1<=len(message)<=87:raise ValueError('job index/message bound')
    program[41]=job.q | (len(message)<<11) | (len(image.tokens)<<18) | (len(image.templates)<<24)
    for i in range(6):program[44+i]=int.from_bytes(message[16*i:16*(i+1)].ljust(16,b'\0'),'little')
    result=ProgramImage(tuple(program),image.templates+(0,)*(64-len(image.templates)),image.descriptors)
    result.decode()
    return result


class AutonomousMachine:
    """One reset epoch; no external Job, message or persistence interface."""
    def __init__(self, image: ProgramImage, observe=None):
        self.image,self.job,self.message=image.decode()
        self.machine=Machine(self.image,self.job,observe)
        self.done=False;self.error=False;self.stats={}

    def run(self):
        if self.done or self.error:raise ValueError('halted until reset')
        try:
            kg=self.machine.run(False)
            self.stats['keygen']=(self.machine.hashes,self.machine.permutations)
            sg=self.machine.run(True,self.message)
            self.stats['sign']=(self.machine.hashes,self.machine.permutations)
            self.done=True
            return kg,sg
        except Exception:
            self.error=True
            raise
