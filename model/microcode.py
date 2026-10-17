"""HBS ABI 3: typed state and a bounded, single-slot WOTS chain operation."""
from __future__ import annotations
from dataclasses import dataclass
from enum import IntEnum
from pathlib import Path

class Op(IntEnum):
    LAYER_INIT=1; LAYER_NEXT=2; TREE_NEXT=3; GROUP_INIT=4; GROUP_NEXT=5
    CURSOR_INIT=6; CURSOR_NEXT=7; CHAIN_INIT=8; CHAIN_NEXT=9; HEIGHT=10
    TARGET=11; DIGITS=12; DIGIT_LOAD=13; STEP_INIT=14; STEP_NEXT=15; MASK=16
    NODE_BEGIN=17; NODE_PARENT=18; LEVEL_INIT=19; LEVEL_NEXT=20; ADRS=21
    REDUCE_INIT=22; REDUCE_NEXT=23; PARSE=24; NMOV=25; LOAD=26; STORE=27
    HASH=28; WAIT=29; INPUT=30; EMIT=31; ROOT_COMPARE=32; END=33; JMP=34; BR=35; CHAIN=36; XMSS_MASK=38

class LayerInit(IntEnum): FIRST=0; TOP=1
class Height(IntEnum): HT=0; FORS=1; LITERAL=2
class Target(IntEnum): FORS=0; LEAF=1
class Lanes(IntEnum): CURRENT=0; L0=1; L1=2
class ChainMode(IntEnum): FULL=0; CAP_FULL=1; CAP_PREFIX=2; SUFFIX=3
class ChainLeaf(IntEnum): CURSOR=0; LEAF=1
class StepSource(IntEnum): ZERO=0; DIGIT=1
class Mask(IntEnum): FIXED=0; PAIR=1; SUFFIX=2; PREFIX=3
class NodeSource(IntEnum): CURSOR=0; TARGET=1; LEAF=2; IMMEDIATE=3
class TreeKind(IntEnum): HT=0; FORS=1; LTREE=2
class Addr(IntEnum):
    WOTS_CURSOR=0; WOTS_LEAF=1; FORS_CURSOR=2; FORS_TARGET=3
    FORS_NODE=4; HT_NODE=5; WOTS_LIST=6; FORS_LIST=7; REDUCE_NODE=8; LTREE_CURSOR=9; LTREE_LEAF=10
class ListLeaf(IntEnum): CURSOR=0; LEAF=1
class ReduceNext(IntEnum): INDEX=0; LEVEL=1; LTREE_LEVEL=2
class Index(IntEnum):
    LEVEL=0; CHAIN0=1; CHAIN1=2; GROUP=3; CURSOR=4
    REDUCE_LEFT=5; REDUCE_RIGHT=6; REDUCE_OUT=7; IMMEDIATE=8
class Cond(IntEnum):
    CURSOR_MORE=0; CHAIN_MORE=1; GROUP_MORE=2; LAYER_MORE=3; FINAL_LAYER=4
    LEVEL_MORE=5; TARGET_LEAF=6; INDEX_ODD=7; AUTH_MATCH=8; SAME_PARENT=9
    STEP_EQ_DIGIT=10; STEP_MORE=11; LANE_ENABLED=12; MASK_ZERO=13
    FORS_PAIR_TARGET=14; REDUCE_MORE=15; REDUCE_AGAIN=16; ROOT_EQUAL=17; LTREE_PAIR=18; LTREE_MORE=19
class N(IntEnum):
    V0=0; V1=1; V2=2; V3=3; L0=4; L1=5; RIGHT=6; CAP0=7; CAP1=8
    NODE=9; TMPNODE=10; SECRET=11; PRF=12; PUBLIC=13; RANDOM=14; ZERO=15
class Space(IntEnum): LIST=0; STACK=1; AUTH=2
SPACE_DEPTHS=(68,21,20)
PROFILE_CODES={"slh_128f":0,"slh_192f":1,"slh_256f":2,"slh_128s":4,"slh_192s":5,"slh_256s":6}
PROFILE_CODES.update({"xmss_h10":8,"xmss_h16":9,"xmss_h20":10,"lms_h10":11,"lms_h15":12,"lms_h20":13})
MAGIC=0x48425350
ABI=3
BRANCHES={Op.JMP,Op.BR}
META_OPS=frozenset({Op.LAYER_INIT,Op.LAYER_NEXT,Op.TREE_NEXT,Op.GROUP_INIT,Op.GROUP_NEXT,
    Op.CURSOR_INIT,Op.CURSOR_NEXT,Op.CHAIN_INIT,Op.CHAIN_NEXT,Op.HEIGHT,Op.STEP_INIT,
    Op.STEP_NEXT,Op.MASK,Op.NODE_BEGIN,Op.NODE_PARENT,Op.LEVEL_INIT,Op.LEVEL_NEXT,
    Op.ADRS,Op.REDUCE_INIT,Op.REDUCE_NEXT})
PENDING_SAFE=META_OPS|BRANCHES|{Op.WAIT}
# Read/write sets describe named hardware objects, never register numbers.
# They also keep overlap scheduling independent of opcode ordering.
ACCESS={
    Op.LAYER_INIT:({'profile'},{'layer'}),Op.LAYER_NEXT:({'layer','profile'},{'layer'}),
    Op.TREE_NEXT:({'tree','profile'},{'tree','leaf'}),
    Op.GROUP_INIT:(set(),{'group'}),Op.GROUP_NEXT:({'group','profile'},{'group'}),
    Op.CURSOR_INIT:(set(),{'cursor'}),Op.CURSOR_NEXT:({'cursor','height'},{'cursor'}),
    Op.CHAIN_INIT:(set(),{'chain'}),Op.CHAIN_NEXT:({'chain','profile'},{'chain'}),
    Op.HEIGHT:({'profile'},{'height'}),Op.TARGET:({'hmsg','group','leaf','profile'},{'target'}),
    Op.DIGITS:({'nodes','profile'},{'digits'}),Op.DIGIT_LOAD:({'digits','chain','mask'},{'digit'}),
    Op.STEP_INIT:({'digit','mask'},{'step'}),Op.STEP_NEXT:({'step','mask'},{'step'}),
    Op.MASK:({'chain','step','digit','profile'},{'mask'}),
    Op.NODE_BEGIN:({'cursor','target','leaf','group','height','profile'},{'index','path','level','base'}),
    Op.NODE_PARENT:({'index','path','level','base','height'},{'index','path','level','base'}),
    Op.LEVEL_INIT:(set(),{'level'}),Op.LEVEL_NEXT:({'level','height'},{'level'}),
    Op.ADRS:({'cursor','leaf','chain','step','group','level','base','index','rindex','profile'},{'adrs'}),
    Op.REDUCE_INIT:({'height','group','profile'},{'span','rindex','level','base'}),
    Op.REDUCE_NEXT:({'span','rindex','level','base','height'},{'span','rindex','level','base'}),
    Op.PARSE:({'hmsg','profile'},{'tree','leaf'}),Op.NMOV:({'nodes'},{'nodes'}),
    Op.LOAD:({'storage','chain','group','cursor','level','rindex'},{'nodes'}),
    Op.STORE:({'nodes','chain','group','cursor','level','rindex'},{'storage'}),
    Op.HASH:({'nodes','storage','message','adrs','layer','tree','mask'},{'pending'}),
    Op.WAIT:({'pending'},{'nodes','hmsg','pending'}),Op.INPUT:(set(),{'nodes'}),
    Op.EMIT:({'nodes'},set()),Op.ROOT_COMPARE:({'nodes'},{'root_equal'}),
    Op.END:({'root_equal'},set()),Op.JMP:(set(),set()),
    Op.XMSS_MASK:({'nodes'},{'nodes'}),
    Op.CHAIN:({'nodes','chain','digit','mask','cursor','leaf','layer','tree','profile'},
        {'nodes','step'}),
    Op.BR:({'cursor','chain','group','layer','level','height','target','index','path',
            'step','digit','mask','rindex','span','root_equal','profile'},set()),
}
ACCESS={op:(frozenset(read),frozenset(write)) for op,(read,write) in ACCESS.items()}
def overlap_safe(ins):
    read,write=ACCESS[ins.op]
    return ins.op in META_OPS and not (read|write)&{'nodes','storage','message','hmsg','pending'}
FIELDS={op:"" for op in Op}
FIELDS.update({Op.LAYER_INIT:"d",Op.CURSOR_NEXT:"i",Op.CHAIN_NEXT:"i",Op.HEIGHT:"di",
    Op.TARGET:"d",Op.DIGIT_LOAD:"d",Op.STEP_INIT:"da",Op.STEP_NEXT:"d",Op.MASK:"di",
    Op.NODE_BEGIN:"dai",Op.ADRS:"da",Op.REDUCE_INIT:"d",Op.REDUCE_NEXT:"d",
    Op.NMOV:"da",Op.LOAD:"dabi",Op.STORE:"dabi",Op.HASH:"da",Op.INPUT:"d",
    Op.EMIT:"a",Op.JMP:"i",Op.BR:"dabi",Op.CHAIN:"dab",Op.XMSS_MASK:"d"})

@dataclass(frozen=True)
class Instruction:
    op:Op
    d:int=0
    a:int=0
    b:int=0
    imm:int=0
    def encode(self):
        if any(not 0<=x<256 for x in (self.d,self.a,self.b)) or not 0<=self.imm<1<<32:
            raise ValueError("instruction field width")
        return (int(self.op)<<56)|(self.d<<48)|(self.a<<40)|(self.b<<32)|self.imm
    @classmethod
    def decode(cls,word):
        if not isinstance(word,int) or not 0<=word<1<<64: raise ValueError("instruction word width")
        try: op=Op(word>>56)
        except ValueError as e: raise ValueError("invalid typed opcode") from e
        return cls(op,(word>>48)&255,(word>>40)&255,(word>>32)&255,word&0xffffffff)

def encoding_rules():
    """One encoding/permission table consumed by Python and generated RTL."""
    rules={op:[] for op in Op}
    for op in Op:
        rules[op]+=[f"{f} == 0" for f in "dabi" if f not in FIELDS[op]]
    limits={Op.LAYER_INIT:{'d':1},Op.HEIGHT:{'d':2},Op.TARGET:{'d':1},Op.DIGIT_LOAD:{'d':2},
        Op.STEP_INIT:{'d':2,'a':1},Op.STEP_NEXT:{'d':2},Op.MASK:{'d':3},
        Op.NODE_BEGIN:{'d':3,'a':1},Op.ADRS:{'d':10,'a':1},Op.REDUCE_INIT:{'d':2},
        Op.REDUCE_NEXT:{'d':2},Op.NMOV:{'d':10,'a':15},Op.LOAD:{'d':10,'a':2,'b':8},
        Op.STORE:{'d':2,'a':15,'b':8},Op.HASH:{'d':11,'a':2},Op.INPUT:{'d':10},
        Op.EMIT:{'a':15},Op.JMP:{'i':511},Op.BR:{'d':19,'a':1,'b':1,'i':511},
        Op.XMSS_MASK:{'d':1},Op.CHAIN:{'d':3,'a':2,'b':1}}
    for op,fields in limits.items(): rules[op]+=[f"{f} <= {n}" for f,n in fields.items()]
    for op in (Op.CURSOR_NEXT,Op.CHAIN_NEXT): rules[op]+=["i >= 1","i <= 2"]
    rules[Op.HEIGHT]+=["(d == 2 and i >= 1 and i <= 20) or (d != 2 and i == 0)"]
    rules[Op.MASK]+=["(d == 0 and i <= 3) or (d != 0 and i == 0)"]
    rules[Op.NODE_BEGIN]+=["(d == 3 and i <= 1048575) or (d != 3 and i == 0)"]
    rules[Op.ADRS]+=["d == 6 or d == 8 or a == 0"]
    rules[Op.HASH]+=["d >= 2"]
    rules[Op.BR]+=["d == 10 or d == 11 or d == 12 or a == 0"]
    for op,space in ((Op.LOAD,'a'),(Op.STORE,'d')):
        rules[op]+=[f"{space} == 0 or b == 0", f"{space} != 0 or b != 0",
            f"(b == 8 and i < (68 if {space} == 0 else (21 if {space} == 1 else 20))) or (b != 8 and i == 0)"]
    return rules
RULES=encoding_rules()

def validate_instruction(ins,used,profile=None):
    env=dict(d=ins.d,a=ins.a,b=ins.b,i=ins.imm)
    if any(not eval(rule,{'__builtins__':{}},env) for rule in RULES[ins.op]):
        raise ValueError(f"illegal typed operands: {ins.op.name}")
    if ins.op in BRANCHES and ins.imm>=used: raise ValueError("branch outside code")
    if profile is not None:
        if profile.family == "slh":
            if (ins.op == Op.XMSS_MASK or ins.op == Op.ADRS and ins.d > 8
                or ins.op in (Op.REDUCE_INIT,Op.REDUCE_NEXT) and ins.d > 1
                or ins.op == Op.BR and ins.d > 17
                or ins.op == Op.HEIGHT and ins.d == 2 and ins.imm > 4
                or ins.op == Op.NODE_BEGIN and ins.d == 3 and ins.imm > 16383):
                raise ValueError("stateful-only instruction/operand")
        elif profile.family != "xmss" and (ins.op == Op.XMSS_MASK
            or ins.op == Op.ADRS and ins.d in (9,10)
            or ins.op in (Op.REDUCE_INIT,Op.REDUCE_NEXT) and ins.d == 2
            or ins.op == Op.BR and ins.d in (18,19)):
            raise ValueError("XMSS-only instruction/operand")

def validate_recipe(recipe,p):
    allowed=(15<<56)|(255<<48)|(255<<40)|(63<<32)|(63<<24)
    if recipe & ~allowed: raise ValueError("recipe reserved bits")
    shape=(recipe>>56)&15;domain=(recipe>>48)&255;arity=(recipe>>40)&255
    output=(recipe>>32)&63;blocks=(recipe>>24)&63
    if not 1<=blocks<=32: raise ValueError("recipe block bound")
    if p.family=="slh":
        if shape not in (1,2,3,4,12) or output!=(p.m if shape==4 else p.n): raise ValueError("SLH recipe")
        if shape in (1,3,4) and arity!=1 or shape==2 and arity not in (1,2) or shape==12 and not 1<=arity<=68: raise ValueError("recipe arity")
        length=2*p.n+32 if shape==1 else p.n+32+arity*p.n if shape in (2,12) else 2*p.n+87 if shape==3 else 3*p.n+87
    elif p.family=="xmss":
        if shape not in (5,6,7,8) or output!=32 or arity!=(2 if shape==7 else 1): raise ValueError("XMSS recipe")
        if shape==5 and domain>4 or shape!=5 and domain: raise ValueError("XMSS domain")
        length={5:128 if domain==0 else 96,6:96,7:128,8:215}[shape]
    else:
        if shape not in (9,10,11,13,14,15) or output!=32 or domain or arity!=(2 if shape==14 else 67 if shape==15 else 1): raise ValueError("LMS recipe")
        length={9:55,10:55,11:141,13:54,14:86,15:2166}[shape]
    if blocks<length//136+1: raise ValueError("recipe block capacity")

@dataclass(frozen=True)
class MicroImage:
    program: tuple[int, ...]
    descriptors: tuple[int, ...]

    @property
    def used(self): return self.descriptors[12]

    @property
    def hash_backend(self): return "shake"

    @property
    def entries(self):
        h = self.descriptors[0]
        return ((h >> 18) & 511, (h >> 9) & 511, h & 511)

    def validate(self):
        if len(self.program) != 512 or len(self.descriptors) != 32:
            raise ValueError("micro image capacity")
        if any(not isinstance(w, int) or not 0 <= w < 1 << 64 for w in self.program + self.descriptors):
            raise ValueError("micro image word width")
        h = self.descriptors[0]
        if h >> 32 != MAGIC or ((h >> 27) & 31) != ABI:
            raise ValueError("micro image magic/ABI")
        if self.descriptors[1] not in PROFILE_CODES.values(): raise ValueError("SLH profile code")
        if not 1 <= self.used <= 512: raise ValueError("instruction count")
        if any(e >= self.used for e in self.entries): raise ValueError("entry outside code")
        if any(self.program[self.used:]): raise ValueError("nonzero program padding")
        if any(self.descriptors[15:]): raise ValueError("nonzero descriptor padding")
        from model.profiles import get_profile
        name = next(k for k, v in PROFILE_CODES.items() if v == self.descriptors[1])
        p = get_profile(name)
        expected = sum(x << (8*i) for i, x in enumerate((p.n,p.hp,p.d,p.k,p.a,p.m,p.h,p.chains)))
        if self.descriptors[14] != expected: raise ValueError("profile parameter mismatch")
        if self.descriptors[13] != (p.hardware_keygen_bytes | (p.hardware_signature_bytes << 32)):
            raise ValueError("output byte counts")
        for recipe in self.descriptors[2:12]: validate_recipe(recipe,p)
        decoded=tuple(Instruction.decode(w) for w in self.program[:self.used])
        for ins in decoded: validate_instruction(ins,self.used,p)
        pending=[(pc,False) for pc in self.entries];seen=set()
        while pending:
            pc,active=pending.pop()
            if (pc,active) in seen: continue
            if not 0<=pc<self.used: raise ValueError("fallthrough outside code")
            seen.add((pc,active));ins=decoded[pc]
            if active and ins.op not in PENDING_SAFE: raise ValueError("unsafe operation before WAIT")
            if ins.op==Op.HASH:
                if active: raise ValueError("second outstanding hash")
                active=True
            elif ins.op==Op.WAIT:
                if not active: raise ValueError("WAIT without HASH")
                active=False
            if ins.op==Op.END: continue
            if ins.op in BRANCHES: pending.append((ins.imm,active))
            if ins.op!=Op.JMP: pending.append((pc+1,active))
        return self
    def write(self,folder):
        self.validate();folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
        for name,ws in (("program",self.program),("descriptor",self.descriptors)):
            (folder/(name+".mem")).write_text("".join(f"{w:016x}\n" for w in ws))
        (folder/"program.asm").write_text(self.disassemble())
    @classmethod
    def read(cls,folder):
        return cls(*(tuple(int(w,16) for w in (Path(folder)/(n+".mem")).read_text().split())
            for n in ("program","descriptor"))).validate()
    def disassemble(self):
        self.validate(); rows=[]
        enums={Op.LAYER_INIT:LayerInit,Op.HEIGHT:Height,Op.TARGET:Target,Op.MASK:Mask,
            Op.NODE_BEGIN:NodeSource,Op.ADRS:Addr,Op.REDUCE_INIT:TreeKind,Op.REDUCE_NEXT:ReduceNext,
            Op.DIGIT_LOAD:Lanes,Op.STEP_INIT:Lanes,Op.STEP_NEXT:Lanes,Op.BR:Cond,
            Op.CHAIN:ChainMode}
        for pc,word in enumerate(self.program[:self.used]):
            x=Instruction.decode(word);args=[]
            for f,v in zip('dabi',(x.d,x.a,x.b,x.imm)):
                if f not in FIELDS[x.op]: continue
                label={'i':'imm'}.get(f,f); value=str(v)
                if f=='d' and x.op in enums: value=enums[x.op](v).name
                if x.op==Op.HASH and f=='a': value=Lanes(v).name
                if x.op==Op.CHAIN and f=='a': value=Lanes(v).name
                if x.op==Op.CHAIN and f=='b': value=ChainLeaf(v).name
                if x.op in (Op.LOAD,Op.STORE) and f=='b': value=Index(v).name
                args.append(label+'='+value)
            rows.append((f"{pc:03d}: {x.op.name:<13} "+', '.join(args)).rstrip())
        return '\n'.join(rows)+'\n'

class Assembler:
    def __init__(self): self.code=[];self.labels={};self.fixups=[];self.sequence=0
    def label(self,name):
        if name in self.labels: raise ValueError("duplicate label")
        self.labels[name]=len(self.code);return name
    def fresh(self,stem='label'):
        self.sequence+=1;return f'{stem}_{self.sequence}'
    def emit(self,op,d=0,a=0,b=0,imm=0):
        op=Op[op] if isinstance(op,str) else Op(op)
        if isinstance(imm,str): self.fixups.append((len(self.code),imm));imm=0
        self.code.append(Instruction(op,int(d),int(a),int(b),int(imm)))
    def branch(self,condition,target,lane=0,invert=False):
        self.emit(Op.BR,condition,lane,int(invert),target)
    def jump(self,target): self.emit(Op.JMP,imm=target)
    def schedule_scalar_overlap(self): return self.schedule_metadata_overlap()
    def schedule_metadata_overlap(self):
        symbolic={pc for pc,_ in self.fixups}
        labelled=set(self.labels.values())|{x.imm for pc,x in enumerate(self.code) if x.op in BRANCHES and pc not in symbolic}
        order=[];i=0
        while i<len(self.code):
            if self.code[i].op==Op.HASH and i+1<len(self.code) and self.code[i+1].op==Op.WAIT and i+1 not in labelled:
                j=i+2
                while j<len(self.code) and j not in labelled and overlap_safe(self.code[j]): j+=1
                order.extend([i,*range(i+2,j),i+1]);i=j
            else: order.append(i);i+=1
        mapping={old:new for new,old in enumerate(order)};mapping[len(self.code)]=len(self.code)
        self.code=[Instruction(x.op,x.d,x.a,x.b,mapping.get(x.imm,x.imm)) if x.op in BRANCHES and pc not in symbolic else x
            for pc in order for x in (self.code[pc],)]
        self.labels={name:mapping[pc] for name,pc in self.labels.items()}
        self.fixups=[(mapping[pc],name) for pc,name in self.fixups];return self
    def assemble(self):
        code=list(self.code)
        for pc,name in self.fixups:
            if name not in self.labels: raise ValueError(f'undefined label {name}')
            x=code[pc];code[pc]=Instruction(x.op,x.d,x.a,x.b,self.labels[name])
        if len(code)>512: raise ValueError(f'micro program exceeds 512 words: {len(code)}')
        for x in code: validate_instruction(x,len(code))
        return tuple(x.encode() for x in code)

def sv_definitions():
    import re
    rows=['// Generated from model/microcode.py; do not edit.']
    for enum,prefix in ((Op,'OP'),(Cond,'COND'),(Index,'IDX')):
        rows.extend(f"localparam [7:0] {prefix}_{v.name}=8'd{int(v)};" for v in enum)
    rows+=['function automatic typed_metadata(input [7:0] op);','    case(op)',
        '        '+','.join('OP_'+x.name for x in sorted(META_OPS|BRANCHES,key=int))+':typed_metadata=1;',
        '        default:typed_metadata=0;','    endcase','endfunction',
        'function automatic typed_encoding_valid(input [63:0] word);',
        '    reg [7:0] d,a,b;reg [31:0] i;','    begin',
        '    d=word[55:48];a=word[47:40];b=word[39:32];i=word[31:0];',
        '    case(word[63:56])']
    for op in Op:
        clauses=[]
        for rule in RULES[op]:
            # One conditional expression is used for memory-space capacity.
            rule=re.sub(r'\(68 if ([ad]) == 0 else \(21 if [ad] == 1 else 20\)\)',r'(\1 == 0 ? 68 : (\1 == 1 ? 21 : 20))',rule)
            rule=rule.replace(' and ',' && ').replace(' or ',' || ')
            clauses.append('('+rule+')')
        rows.append('        OP_'+op.name+':typed_encoding_valid='+(' && '.join(clauses) or "1'b1")+';')
    rows+=['        default:typed_encoding_valid=0;','    endcase','    end','endfunction','']
    return '\n'.join(rows)
if __name__=='__main__':
    import argparse
    ap=argparse.ArgumentParser();ap.add_argument('--sv-out',type=Path,required=True);a=ap.parse_args()
    a.sv_out.parent.mkdir(parents=True,exist_ok=True);a.sv_out.write_text(sv_definitions())
