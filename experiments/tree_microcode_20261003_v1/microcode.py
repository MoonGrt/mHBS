"""Experimental ABI 5: explicit tree scheduling, no TREE execution primitive.

64-bit word: opcode[63:56], a[55:48], b[47:40], c[39:32], immediate[31:0].
Scalars are fixed-width unsigned values. One return slot (no recursion).
Only HASH/CHAIN use SHAKE; all tree traversal is in the ROM program below.
"""
from dataclasses import dataclass
from enum import IntEnum
from types import SimpleNamespace
from collections import Counter
import hashlib,json
from pathlib import Path
from model.profiles import get_profile
from model.unified_hbs import Machine, compile_image, field

FORMAT='slh_step_v5'
class Op(IntEnum):
    HALT=0; SET=1; MOV=2; ADDI=3; ADD=4; SHR=5; SHL=6; XORI=7; ANDI=8
    BEQ=9; BNE=10; JMP=11; CALL=12; RET=13
    LOAD=14; STORE=15; MOVN=16; ZERO=17; OUTPUT=18; INPUT=19
    HASH=20; CHAIN=21; HASH_PAIR=22; TRANSFORM=23; EMIT=24; ROUTE=25
class R(IntEnum):
    LAYER=0; GROUP=1; TARGET=2; LEAF=3; INDEX=4; LEVEL=5; HEIGHT=6
    CID=7; PID=8; LIMIT=9; TEMP=10; FLAGS=11; PENDING=12; MODE=13; AUX=14; SPARE=15
    SCALAR_LEAF=16; FORS_TARGET=17; OPERATION=18; ZERO=19; A=20; HP=21; D=22; K=23
class N(IntEnum): NODE=0; LEFT=1; IO=2; RESULT0=3; RESULT1=4
class Mem(IntEnum): STACK=0; AUTH=1; VALUE=2

def encode(op,a=0,b=0,c=0,imm=0):
    if not (0<=int(op)<256 and all(0<=int(v)<256 for v in (a,b,c)) and 0<=imm<1<<32):raise ValueError('encoding range')
    return int(op)<<56|int(a)<<48|int(b)<<40|int(c)<<32|imm

def decode(w):
    if not 0<=w<1<<64:raise ValueError('word width')
    return Op(w>>56),(w>>48)&255,(w>>40)&255,(w>>32)&255,w&0xffffffff

@dataclass
class Image:
    profile:str
    program:list
    descriptors:list
    labels:dict
    format:str=FORMAT
    def validate(self):
        if self.format!=FORMAT:raise ValueError('wrong format / legacy image')
        if not 1<=len(self.program)<=256:raise ValueError('program capacity')
        if set(self.labels)-{'entry','kg','fors_loop','ht_loop','ht_full','ht_call','tree','leaf_loop','push','no_auth','next_leaf','parent','parent_hash','finish','auth_loop','return','normal_return','verify','verify_loop','verify_even','verify_parent'}:raise ValueError('unknown labels')
        for w in self.program:
            op,a,b,c,imm=decode(w)
            if op in (Op.JMP,Op.CALL,Op.BEQ,Op.BNE) and imm>=len(self.program):raise ValueError('jump bounds')
            if op in (Op.SET,Op.MOV,Op.ADDI,Op.ADD,Op.SHR,Op.SHL,Op.XORI,Op.ANDI) and a>=16:raise ValueError('scalar destination')
            if op in (Op.MOV,Op.ADDI,Op.ADD,Op.SHR,Op.SHL,Op.XORI,Op.ANDI) and b>=24:raise ValueError('scalar source')
            if op in (Op.ADD,Op.SHR,Op.SHL) and c>=24:raise ValueError('scalar source')
            if op in (Op.BEQ,Op.BNE) and (a>=24 or b>=24):raise ValueError('branch source')
            if op in (Op.LOAD,Op.STORE) and (a>2 or b>2 or c>=24):raise ValueError('memory selector')
            if op==Op.MOVN and (a>2 or b>4):raise ValueError('node selector')
            if op in (Op.ZERO,Op.OUTPUT,Op.INPUT) and a>2:raise ValueError('node selector')
        if self.descriptors[20] or self.descriptors[21]:raise ValueError('TREE descriptor forbidden')
    @property
    def depth(self):return 1<<(len(self.program)-1).bit_length()
    def write(self,path):
        self.validate();p=Path(path);p.mkdir(parents=True,exist_ok=True)
        (p/'program.mem').write_text(''.join(f'{w:016x}\n' for w in self.program+[0]*(self.depth-len(self.program))))
        # Compact descriptors keep old physical positions; TREE slots are zero.
        from model.slh64 import ADDRESSES, remap, KINDS
        words=[remap(self.descriptors[old]&((1<<60)-1),kind) if old not in (20,21) else 0 for old,kind in zip(ADDRESSES,KINDS)]
        words += [0]*(32-len(words))
        words[0] &= (1<<36)-1  # both operations enter the shared program at PC zero
        from model.profiles import SLH_PROFILE_CODES
        words[1] = next(k for k,v in SLH_PROFILE_CODES.items() if v==self.profile)
        (p/'descriptor.mem').write_text(''.join(f'{w:016x}\n' for w in words))
        (p/'template.mem').write_text('0000000000000000\n'*16)
        (p/'image.json').write_text(json.dumps(dict(format=FORMAT,profile=self.profile,used_words=len(self.program),depth=self.depth,labels=self.labels,control_bytes=self.depth*8+16*8+32*8),indent=2)+'\n')
        (p/'listing.txt').write_text('\n'.join(f'{i:03d} {decode(w)}' for i,w in enumerate(self.program))+'\n')

class Assembler:
    def __init__(self):self.words=[];self.labels={};self.fixups=[]
    def label(self,s):self.labels[s]=len(self.words)
    def emit(self,op,a=0,b=0,c=0,imm=0):
        if isinstance(imm,str):self.fixups.append((len(self.words),imm));imm=0
        self.words.append(encode(op,a,b,c,imm))
    def finish(self):
        for i,label in self.fixups:self.words[i]|=self.labels[label]
        return self.words

def compile_program(name):
    p=get_profile(name);x=Assembler();e=x.emit;l=x.label
    l('entry');e(Op.SET,R.TEMP,imm=0);e(Op.BEQ,R.OPERATION,R.TEMP,imm='kg')
    e(Op.HASH,2,40);e(Op.HASH,3,41)
    for r,v in [(R.MODE,1),(R.CID,16),(R.PID,6),(R.HEIGHT,p.a),(R.FLAGS,3),(R.LAYER,0),(R.GROUP,0)]:e(Op.SET,r,imm=v)
    l('fors_loop');e(Op.MOV,R.TARGET,R.FORS_TARGET);e(Op.CALL,imm='tree');e(Op.ROUTE,43)
    e(Op.ADDI,R.GROUP,R.GROUP,imm=1);e(Op.BNE,R.GROUP,R.K,imm='fors_loop')
    e(Op.HASH,11,42)
    for r,v in [(R.GROUP,0),(R.LAYER,0),(R.MODE,0),(R.HEIGHT,p.hp),(R.CID,17),(R.PID,10)]:e(Op.SET,r,imm=v)
    l('ht_loop');e(Op.TRANSFORM,48);e(Op.MOV,R.TARGET,R.SCALAR_LEAF)
    e(Op.SET,R.FLAGS,imm=3);e(Op.SET,R.TEMP,imm=p.d-1);e(Op.BNE,R.LAYER,R.TEMP,imm='ht_full')
    e(Op.SET,R.TEMP,imm=2);e(Op.BEQ,R.OPERATION,R.TEMP,imm='ht_full');e(Op.SET,R.FLAGS,imm=11)
    l('ht_full');l('ht_call');e(Op.CALL,imm='tree');e(Op.ROUTE,42);e(Op.TRANSFORM,49)
    e(Op.ADDI,R.LAYER,R.LAYER,imm=1);e(Op.BNE,R.LAYER,R.D,imm='ht_loop');e(Op.HALT)
    l('kg')
    for r,v in [(R.MODE,0),(R.HEIGHT,p.hp),(R.CID,17),(R.PID,10),(R.FLAGS,0),(R.LAYER,p.d-1),(R.TARGET,0),(R.GROUP,0)]:e(Op.SET,r,imm=v)
    e(Op.CALL,imm='tree');e(Op.ROUTE,44);e(Op.EMIT,50);e(Op.HALT)
    l('tree');e(Op.SET,R.TEMP,imm=2);e(Op.BEQ,R.OPERATION,R.TEMP,imm='verify');e(Op.SET,R.LEAF,imm=0)
    l('leaf_loop');e(Op.CHAIN);e(Op.MOVN,N.NODE,N.RESULT0);e(Op.SET,R.LEVEL,imm=0)
    e(Op.MOV,R.INDEX,R.LEAF);e(Op.MOV,R.PENDING,R.MODE)
    l('push');e(Op.BEQ,R.LEVEL,R.HEIGHT,imm='finish')
    e(Op.SHR,R.TEMP,R.TARGET,R.LEVEL);e(Op.XORI,R.TEMP,R.TEMP,imm=1)
    e(Op.BNE,R.INDEX,R.TEMP,imm='no_auth');e(Op.STORE,Mem.AUTH,N.NODE,R.LEVEL)
    l('no_auth');e(Op.ANDI,R.TEMP,R.INDEX,imm=1);e(Op.BNE,R.TEMP,R.ZERO,imm='parent')
    e(Op.STORE,Mem.STACK,N.NODE,R.LEVEL);e(Op.BEQ,R.PENDING,R.ZERO,imm='next_leaf')
    e(Op.MOVN,N.NODE,N.RESULT1);e(Op.ADDI,R.LEAF,R.LEAF,imm=1);e(Op.MOV,R.INDEX,R.LEAF)
    e(Op.SET,R.LEVEL,imm=0);e(Op.SET,R.PENDING,imm=0);e(Op.JMP,imm='push')
    l('next_leaf');e(Op.ADDI,R.LEAF,R.LEAF,imm=1);e(Op.JMP,imm='leaf_loop')
    l('parent');e(Op.LOAD,N.LEFT,Mem.STACK,R.LEVEL)
    e(Op.SET,R.TEMP,imm=1);e(Op.SHR,R.INDEX,R.INDEX,R.TEMP);e(Op.ADDI,R.LEVEL,R.LEVEL,imm=1)
    e(Op.ANDI,R.TEMP,R.FLAGS,imm=8);e(Op.BEQ,R.TEMP,R.ZERO,imm='parent_hash')
    e(Op.SHR,R.TEMP,R.TARGET,R.LEVEL);e(Op.BNE,R.INDEX,R.TEMP,imm='parent_hash')
    e(Op.ZERO,N.NODE);e(Op.JMP,imm='push')
    l('parent_hash');e(Op.SHL,R.TEMP,R.GROUP,R.HEIGHT);e(Op.SHR,R.TEMP,R.TEMP,R.LEVEL)
    e(Op.ADD,R.TEMP,R.TEMP,R.INDEX);e(Op.HASH_PAIR);e(Op.JMP,imm='push')
    l('finish');e(Op.SET,R.LEVEL,imm=0)
    l('auth_loop');e(Op.ANDI,R.TEMP,R.FLAGS,imm=2);e(Op.BEQ,R.TEMP,R.ZERO,imm='return')
    e(Op.BEQ,R.LEVEL,R.HEIGHT,imm='return');e(Op.LOAD,N.IO,Mem.AUTH,R.LEVEL);e(Op.OUTPUT,N.IO)
    e(Op.ADDI,R.LEVEL,R.LEVEL,imm=1);e(Op.JMP,imm='auth_loop')
    l('return');e(Op.ANDI,R.TEMP,R.FLAGS,imm=8);e(Op.BEQ,R.TEMP,R.ZERO,imm='normal_return')
    e(Op.SET,R.TEMP,imm=3);e(Op.LOAD,N.NODE,Mem.VALUE,R.TEMP)
    l('normal_return');e(Op.RET)
    l('verify');e(Op.MOV,R.LEAF,R.TARGET);e(Op.CHAIN);e(Op.MOVN,N.NODE,N.RESULT0)
    e(Op.MOV,R.INDEX,R.TARGET);e(Op.SET,R.LEVEL,imm=0)
    l('verify_loop');e(Op.BEQ,R.LEVEL,R.HEIGHT,imm='normal_return');e(Op.INPUT,N.IO)
    e(Op.ANDI,R.TEMP,R.INDEX,imm=1);e(Op.BEQ,R.TEMP,R.ZERO,imm='verify_even')
    e(Op.MOVN,N.LEFT,N.IO);e(Op.JMP,imm='verify_parent')
    l('verify_even');e(Op.MOVN,N.LEFT,N.NODE);e(Op.MOVN,N.NODE,N.IO)
    l('verify_parent');e(Op.SET,R.TEMP,imm=1);e(Op.SHR,R.INDEX,R.INDEX,R.TEMP);e(Op.ADDI,R.LEVEL,R.LEVEL,imm=1)
    e(Op.SHL,R.TEMP,R.GROUP,R.HEIGHT);e(Op.SHR,R.TEMP,R.TEMP,R.LEVEL);e(Op.ADD,R.TEMP,R.TEMP,R.INDEX)
    e(Op.HASH_PAIR);e(Op.JMP,imm='verify_loop')
    d=list(compile_image(name).descriptors);d[20]=d[21]=0
    image=Image(name,x.finish(),d,x.labels);image.validate();return image

class Recipes(Machine):
    """Reuse only the existing, unchanged HASH and CHAIN primitives."""
    def __init__(self,image,job,observe):
        p=get_profile(image.profile)
        self.image=SimpleNamespace(descriptors=image.descriptors,n=p.n,m=p.m)
        self.job=job;self.n=p.n;self.observe=observe;self.hashes=self.permutations=0
        self.values=[bytes(p.m) for _ in range(4)];self.scalar_tree=self.scalar_leaf=0
        self.output=bytearray();self.message=b'';self.digits=[]
    def tree(self,*args,**kwargs):raise AssertionError('legacy TREE forbidden')
    def run(self,*args,**kwargs):raise AssertionError('legacy scheduler forbidden')

class VM:
    def __init__(self,image,job,root,message,operation,signature=b'',observe=None,max_steps=200_000_000):
        image.validate();self.image=image;self.p=get_profile(image.profile);self.op=operation
        if operation not in (0,1,2) or (len(message)!=0 if operation==0 else not 1<=len(message)<=87):raise ValueError('operation/message')
        if len(root)!=self.p.n:raise ValueError('root length')
        if operation==2 and len(signature)!=self.p.signature_bytes:raise ValueError('signature length')
        self.backend=Recipes(image,job,observe);self.backend.message=message;self.backend.values[3]=root
        self.root=root;self.reg=[0]*16;self.node=[bytes(self.p.n)]*5
        self.stack={};self.auth={};self.roots={};self.pc=0;self.link=None;self.input=signature;self.cursor=0
        self.steps=0;self.counts=Counter();self.max_steps=max_steps;self.halted=False
        self.peak_stack=self.peak_auth=0;self.boundary=set()
    def regget(self,i):
        if i<16:return self.reg[i]
        b=self.backend;p=self.p
        if i==R.SCALAR_LEAF:return b.scalar_leaf
        if i==R.FORS_TARGET:
            fb=(p.k*p.a+7)//8
            return (int.from_bytes(b.values[1][:fb],'big')>>(8*fb-p.a*(self.reg[R.GROUP]+1)))&((1<<p.a)-1)
        return {R.OPERATION:self.op,R.ZERO:0,R.A:p.a,R.HP:p.hp,R.D:p.d,R.K:p.k}[i]
    def read_node(self):
        n=self.p.n
        if self.cursor+n>len(self.input):raise ValueError('truncated signature')
        v=self.input[self.cursor:self.cursor+n];self.cursor+=n;return v
    def route(self,did,value):
        d=self.image.descriptors[did];b=self.backend;p=self.p
        if field(d,53,1):self.roots[self.reg[R.GROUP]]=value
        else:b.values[field(d,56,2)]=value
        if field(d,55,1) and self.op!=2:b.output.extend(value)
        if field(d,54,1):
            fb=(p.k*p.a+7)//8;tb=(p.h-p.hp+7)//8;lb=(p.hp+7)//8
            b.scalar_tree=int.from_bytes(value[fb:fb+tb],'big')&((1<<(p.h-p.hp))-1)
            b.scalar_leaf=int.from_bytes(value[fb+tb:fb+tb+lb],'big')&((1<<p.hp)-1)
    def chain(self):
        r=self.reg;b=self.backend;p=self.p;fors=bool(r[R.MODE]);leaf=r[R.LEAF]
        self.boundary.add(('target_parity',r[R.TARGET]&1))
        if r[R.TARGET] in (0,(1<<r[R.HEIGHT])-1):self.boundary.add(('target_edge',r[R.TARGET]==0))
        if leaf>=1<<r[R.HEIGHT]:raise ValueError('leaf bounds')
        if self.op!=2:
            for lane in range(2 if fors else 1):
                capture=bool(r[R.FLAGS]&1) and leaf+lane==r[R.TARGET]
                self.node[3+lane]=b.chains(r[R.CID],r[R.LAYER],b.scalar_leaf if fors else leaf,
                    (r[R.GROUP]<<p.a)+leaf+lane if fors else 0,fors,capture,capture and bool(r[R.FLAGS]&8))
        elif fors:
            self.node[3]=b.hash_recipe(5,layer=r[R.LAYER],leaf=b.scalar_leaf,a=0,
                                      b=(r[R.GROUP]<<p.a)+r[R.TARGET],left=self.read_node())
        else:
            endpoints=[]
            for item,digit in enumerate(b.digits):
                v=self.read_node()
                for step in range(digit,15):v=b.hash_recipe(8,layer=r[R.LAYER],leaf=leaf,a=item,b=step,left=v)
                endpoints.append(v)
            self.node[3]=b.hash_recipe(9,layer=r[R.LAYER],leaf=leaf,values=endpoints)
    def run(self):
        if self.halted:raise ValueError('halted until reset')
        r=self.reg;b=self.backend;p=self.p;g=self.regget
        while not self.halted:
            if not 0<=self.pc<len(self.image.program):raise ValueError('PC bounds')
            if self.steps>=self.max_steps:raise ValueError('instruction budget / nontermination')
            op,a,s,c,imm=decode(self.image.program[self.pc]);self.pc+=1;self.steps+=1;self.counts[op.name]+=1
            if op==Op.HALT:self.halted=True
            elif op==Op.SET:r[a]=imm
            elif op==Op.MOV:r[a]=g(s)
            elif op==Op.ADDI:r[a]=(g(s)+imm)&0xffffffff
            elif op==Op.ADD:r[a]=(g(s)+g(c))&0xffffffff
            elif op==Op.SHR:r[a]=g(s)>>g(c)
            elif op==Op.SHL:r[a]=(g(s)<<g(c))&0xffffffff
            elif op==Op.XORI:r[a]=g(s)^imm
            elif op==Op.ANDI:r[a]=g(s)&imm
            elif op==Op.BEQ:
                if g(a)==g(s):self.pc=imm
            elif op==Op.BNE:
                if g(a)!=g(s):self.pc=imm
            elif op==Op.JMP:self.pc=imm
            elif op==Op.CALL:
                if self.link is not None:raise ValueError('nested call')
                self.link=self.pc;self.pc=imm;self.stack.clear();self.auth.clear()
            elif op==Op.RET:
                if self.link is None:raise ValueError('return without call')
                self.pc=self.link;self.link=None
            elif op==Op.LOAD:
                address=g(c);mem=(self.stack,self.auth,b.values)[s]
                if address>=(4 if s==Mem.VALUE else 16):raise ValueError('memory bounds')
                try:self.node[a]=mem[address][:p.n]
                except (KeyError,IndexError):raise ValueError('uninitialized node')
            elif op==Op.STORE:
                address=g(c)
                if address>=16 or a==Mem.VALUE:raise ValueError('memory bounds')
                (self.stack,self.auth)[a][address]=self.node[s]
                self.peak_stack=max(self.peak_stack,len(self.stack));self.peak_auth=max(self.peak_auth,len(self.auth))
            elif op==Op.MOVN:self.node[a]=self.node[s]
            elif op==Op.ZERO:self.node[a]=bytes(p.n)
            elif op==Op.OUTPUT:b.output.extend(self.node[a])
            elif op==Op.INPUT:self.node[a]=self.read_node()
            elif op==Op.CHAIN:self.chain()
            elif op==Op.HASH:
                v=self.read_node() if self.op==2 and a==2 else b.hash_recipe(a,leaf=b.scalar_leaf,values=[self.roots[k] for k in sorted(self.roots)])
                self.route(s,v)
            elif op==Op.HASH_PAIR:
                self.node[0]=b.hash_recipe(r[R.PID],layer=r[R.LAYER],leaf=b.scalar_leaf if r[R.MODE] else 0,
                    a=r[R.LEVEL],b=r[R.TEMP],left=self.node[1],right=self.node[0])
            elif op==Op.TRANSFORM:
                if a==48:
                    digits=[z for v in b.values[2][:p.n] for z in (v>>4,v&15)]
                    checksum=sum(15-v for v in digits)
                    b.digits=digits+[(checksum>>shift)&15 for shift in (8,4,0)]
                elif a==49:
                    b.scalar_leaf=b.scalar_tree&((1<<p.hp)-1);b.scalar_tree>>=p.hp
                else:raise ValueError('transform')
            elif op==Op.ROUTE:self.route(a,self.node[0])
            elif op==Op.EMIT:b.output.extend(b.job.secret+b.job.prf+b.job.public+b.values[3][:p.n]+b.job.public+b.values[3][:p.n])
            else:raise ValueError('opcode')
        if self.op==2:
            if self.cursor!=len(self.input) or b.output:raise ValueError('verify I/O mismatch')
            return b.values[2][:p.n]==self.root
        expected=p.keygen_bytes if self.op==0 else p.signature_bytes
        if len(b.output)!=expected:raise ValueError('output length')
        return bytes(b.output)
    def stats(self):
        return dict(hashes=self.backend.hashes,permutations=self.backend.permutations,instructions=self.steps,
            opcode_counts=dict(self.counts),peak_stack=self.peak_stack,peak_auth=self.peak_auth,
            scalar_bytes=16*4,node_scratch_bytes=5*self.p.n,control_bytes=self.image.depth*8+384,
            schedule_lower_bound_cycles=self.steps,coverage=sorted(self.boundary))
