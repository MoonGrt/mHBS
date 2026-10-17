"""Instruction-level model of the typed HBS processor; SHAKE is the only oracle."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib

from model.microcode import (Addr, ChainLeaf, ChainMode, Cond, Height, Instruction, LayerInit, ListLeaf, Mask, N, Lanes,
    Op, PENDING_SAFE, ReduceNext, SPACE_DEPTHS, StepSource, Target, TreeFlags, TreeKind, TreeMode)


@dataclass(frozen=True)
class Job:
    secret: bytes
    prf: bytes
    public: bytes
    random: bytes
    identifier: bytes = bytes(16)
    q: int = 0


@dataclass
class Context:
    """Named, independently bounded fields, never a general register file."""
    layer: int = 0
    tree: int = 0
    leaf: int = 0
    group: int = 0
    target: int = 0
    cursor: int = 0
    chain: int = 0
    step0: int = 0
    step1: int = 0
    digit0: int = 0
    digit1: int = 0
    level: int = 0
    index: int = 0
    path: int = 0
    fors_base: int = 0
    mask: int = 0
    reduce_index: int = 0
    reduce_span: int = 0
    height: int = 0
    addr_leaf0: int = 0
    addr_leaf1: int = 0
    addr_a0: int = 0
    addr_a1: int = 0
    addr_b0: int = 0
    addr_b1: int = 0
    root_equal: bool = False


class MicroMachine:
    def __init__(self, image, job, root, message, operation, signature=b"", observe=None,
                 task_observe=None, *, record_tasks=False, instruction_limit=200_000_000):
        image.validate()
        if operation not in (0,1,2): raise ValueError("operation")
        self.image=image; self.job=job; self.operation=operation
        self.params=tuple((image.descriptors[14]>>(8*i))&255 for i in range(8))
        self.n,self.hp,self.d,self.k,self.a,self.m,self.h,self.chains=self.params
        if any(len(v)!=self.n for v in (job.secret,job.prf,job.public,job.random,root)):
            raise ValueError("Job/root node width")
        if job.q or any(job.identifier): raise ValueError("SLH-only Job")
        if not (len(message)==0 if operation==0 else 1<=len(message)<=87):
            raise ValueError("message length")
        if operation==2 and len(signature)!=(image.descriptors[13]>>32):
            raise ValueError("Verify signature byte count")
        if operation!=2 and signature: raise ValueError("signature supplied to non-Verify")
        self.message=bytes(message); self.signature=bytes(signature); self.signature_cursor=0
        self.ctx=Context()
        self.nodes=[bytes(self.n) for _ in range(16)]
        self.nodes[N.V3]=bytes(root)
        for i,v in ((N.SECRET,job.secret),(N.PRF,job.prf),(N.PUBLIC,job.public),(N.RANDOM,job.random)):
            self.nodes[i]=bytes(v)
        self.spaces=[[bytes(self.n) for _ in range(depth)] for depth in SPACE_DEPTHS]
        self.digest=b""; self.digits=[]; self.digit_valid=0; self.pending=None
        self.observe=observe; self.task_observe=task_observe
        self.task_trace=[] if record_tasks else None
        self.hash_count=0; self.permutation_count=0; self.instructions=0; self.root_compare_valid=False
        self.macro_count=0;self.macro_hashes=0
        self.tree_count=0;self.tree_hashes=0;self.tree_chains=0
        self.output=bytearray(); self.halted=False; self.error=None
        self.instruction_limit=instruction_limit
        self.decoded=tuple((int(i.op),i.d,i.a,i.b,i.imm)
                           for i in map(Instruction.decode,image.program[:image.used]))

    def _issue(self, recipe_id, mask):
        if self.pending is not None: raise ValueError("second outstanding Hash group")
        if mask not in (1,2): raise ValueError("K1U1 Hash mask must select exactly one logical lane")
        c=self.ctx; n=self.nodes; recipe=self.image.descriptors[recipe_id]
        shape=(recipe>>56)&15; domain=(recipe>>48)&255; arity=(recipe>>40)&255
        out=(recipe>>32)&63; tasks=[]
        for lane in range(2):
            if not mask&(1<<lane): continue
            if lane and shape not in (1,2): raise ValueError("unsupported lane1 recipe")
            layer,tree=c.layer,c.tree
            leaf=(c.addr_leaf0,c.addr_leaf1)[lane]
            a=(c.addr_a0,c.addr_a1)[lane]; b=(c.addr_b0,c.addr_b1)[lane]
            if layer>=32 or leaf>=1024 or a>=128 or b>0xffffffff:
                raise ValueError("Hash address field range")
            address=b"".join(x.to_bytes(4,"big") for x in (layer,0,tree>>32,tree&0xffffffff,domain,leaf,a,b))
            if shape==1: data=self.job.public+address+self.job.secret
            elif shape==2:
                if lane and arity==2: raise ValueError("lane1 parent Hash")
                data=self.job.public+address+n[N.L0+lane]+(n[N.RIGHT] if arity==2 else b"")
            elif shape==3: data=self.job.prf+self.job.random+self.message
            elif shape==4: data=n[N.V0]+self.job.public+n[N.V3]+self.message
            elif shape==12: data=self.job.public+address+b"".join(self.spaces[0][:arity])
            else: raise ValueError("unsupported recipe shape")
            if len(data)//136+1>((recipe>>24)&63): raise ValueError("recipe block bound")
            tasks.append((lane,recipe_id,recipe,layer,tree,leaf,a,b,out,data))
        self.pending=tasks

    def _wait(self):
        if self.pending is None: raise ValueError("WAIT without Hash group")
        for lane,rid,recipe,layer,tree,leaf,a,b,out,data in self.pending:
            result=hashlib.shake_256(data).digest(out)
            self.nodes[N.L0+lane]=result[:self.n].ljust(self.n,b"\0")
            if (recipe>>56)&15==4: self.digest=result
            self.hash_count+=1; self.permutation_count+=len(data)//136+1
            if self.observe: self.observe(rid,data,result)
            task=(recipe,layer,tree,leaf,a,b,result.ljust(49,b"\0"))
            if self.task_trace is not None: self.task_trace.append(task)
            if self.task_observe: self.task_observe(task)
        self.pending=None

    def _chain(self, mode, selector, leaf_source, *, _tree=False, _recipes=None):
        """One bounded WOTS chain, independent of the explicit instruction loop.

        Validate both recipes before work, retain private address/step values,
        and publish only the selected result, optional capture and final step.
        Every internal SHAKE reports the same byte and task observations as
        ordinary ISSUE/WAIT; no tree helper or old macro interpreter is used.
        """
        if self.pending is not None: raise ValueError('CHAIN before WAIT')
        mask=self.lane_mask(selector)
        if mask not in (1,2): raise ValueError('CHAIN requires exactly one logical slot')
        slot=int(mask==2); c=self.ctx; chain=c.chain+slot
        if not 0<=chain<self.chains: raise ValueError('CHAIN index out of bounds')
        leaf=c.cursor if leaf_source==ChainLeaf.CURSOR else c.leaf
        if not 0<=leaf<1024: raise ValueError('CHAIN leaf out of bounds')
        if not 0<=c.layer<32 or not 0<=c.tree<1<<64: raise ValueError('CHAIN context out of bounds')
        digit=(c.digit0,c.digit1)[slot]
        if mode!=ChainMode.FULL and (not self.digits or not self.digit_valid&mask or not 0<=digit<=15):
            raise ValueError('CHAIN before valid digit load')
        layer,tree=c.layer,c.tree
        recipes={rid:(_recipes[rid] if _recipes is not None else self.image.descriptors[rid]) for rid in (7,8)}
        allowed=(15<<56)|(255<<48)|(255<<40)|(63<<32)|(63<<24)
        for rid,shape,domain in ((7,1,5),(8,2,0)):
            recipe=recipes[rid]
            if (recipe&~allowed or (recipe>>56)&15!=shape or (recipe>>48)&255!=domain
                or (recipe>>40)&255!=1 or (recipe>>32)&63!=self.n
                or not 1<=((recipe>>24)&63)<=32):
                raise ValueError('CHAIN recipe mismatch')
        if _tree: self.tree_chains+=1
        else: self.macro_count+=1
        def hashed(rid,step,payload):
            recipe=recipes[rid];domain=(recipe>>48)&255
            address=b''.join(x.to_bytes(4,'big') for x in
                (layer,0,tree>>32,tree&0xffffffff,domain,leaf,chain,step))
            data=self.job.public+address+payload
            value=hashlib.shake_256(data).digest(self.n)
            self.hash_count+=1;self.permutation_count+=len(data)//136+1
            if _tree: self.tree_hashes+=1
            else: self.macro_hashes+=1
            if self.observe: self.observe(rid,data,value)
            task=(recipe,layer,tree,leaf,chain,step,value.ljust(49,b'\0'))
            if self.task_trace is not None: self.task_trace.append(task)
            if self.task_observe: self.task_observe(task)
            return value
        value=self.nodes[N.L0+slot];captured=None
        if mode==ChainMode.SUFFIX: start=digit
        else:
            value=hashed(7,0,self.job.secret);start=0
            if mode!=ChainMode.FULL and digit==0: captured=value
        end=digit if mode==ChainMode.CAP_PREFIX else 15
        for step in range(start,end):
            value=hashed(8,step,value)
            if mode in (ChainMode.CAP_FULL,ChainMode.CAP_PREFIX) and step+1==digit:
                captured=value
        # No architectural node or step changes until the entire macro succeeds.
        self.nodes[N.L0+slot]=value
        if captured is not None: self.nodes[N.CAP0+slot]=captured
        self._commit(**{'step'+str(slot):end})

    def _tree(self, kind, mode, flags=0):
        """Execute one bounded HT/FORS tree using only individual SHAKE calls.

        Outer context and prepared digits are owned by the image.  This model
        deliberately does not dispatch an old algorithm/macro interpreter;
        Hash order, stack merges and stream boundaries are spelled out here.
        A runtime failure aborts the Job and may leave scratch/output modified.
        """
        c=self.ctx; nodes=self.nodes
        if self.pending is not None: raise ValueError('TREE before WAIT')
        if kind not in (TreeKind.HT,TreeKind.FORS) or mode not in tuple(TreeMode):
            raise ValueError('TREE kind/mode')
        if (kind==TreeKind.FORS and mode==TreeMode.ROOT or flags not in (0,1)
            or flags and (kind!=TreeKind.HT or mode!=TreeMode.SIGN)):
            raise ValueError('TREE kind/mode/flags')
        if int(mode)!=self.operation: raise ValueError('TREE mode does not match Job')
        if not 0<=c.layer<self.d or not 0<=c.tree<1<<64 or not 0<=c.leaf<1<<self.hp:
            raise ValueError('TREE outer context out of bounds')
        if kind==TreeKind.FORS and not 0<=c.group<self.k:
            raise ValueError('TREE FORS group out of bounds')
        height=self.hp if kind==TreeKind.HT else self.a
        if not 1<=height<=14 or kind==TreeKind.HT and height>10:
            raise ValueError('TREE height out of bounds')
        if mode!=TreeMode.ROOT and not 0<=c.target<1<<height:
            raise ValueError('TREE target out of bounds')
        if kind==TreeKind.HT and mode!=TreeMode.ROOT and (
            len(self.digits)!=self.chains or any(not 0<=digit<=15 for digit in self.digits)):
            raise ValueError('TREE before valid DIGITS')
        if flags and c.layer!=self.d-1: raise ValueError('TREE shortcut outside final layer')
        expected={7:(1,5,1),8:(2,0,1),9:(12,1,self.chains),10:(2,2,2)} if kind==TreeKind.HT else {
            **({4:(1,6,1)} if mode==TreeMode.SIGN else {}),5:(2,3,1),6:(2,3,2)}
        allowed=(15<<56)|(255<<48)|(255<<40)|(63<<32)|(63<<24)
        recipes={rid:self.image.descriptors[rid] for rid in expected}
        for rid,(shape,domain,arity) in expected.items():
            recipe=recipes[rid];blocks=(recipe>>24)&63
            length=self.n+32+(self.n if shape==1 else arity*self.n)
            if (recipe&~allowed or (recipe>>56)&15!=shape or (recipe>>48)&255!=domain
                or (recipe>>40)&255!=arity or (recipe>>32)&63!=self.n
                or not length//136+1<=blocks<=32):
                raise ValueError('TREE recipe mismatch/capacity')
        # All checks above precede the first scratch write, stream access or Hash.
        outer={key:getattr(c,key) for key in ('layer','tree','leaf','group','target')}
        layer,tree,leaf,group,target=(outer[key] for key in ('layer','tree','leaf','group','target'))
        shortcut=bool(flags&TreeFlags.TOP_SHORTCUT)
        self.tree_count+=1
        def hashed(rid,addr_leaf,a,b,payload):
            recipe=recipes[rid];domain=(recipe>>48)&255
            address=b''.join(x.to_bytes(4,'big') for x in
                (layer,0,tree>>32,tree&0xffffffff,domain,addr_leaf,a,b))
            data=self.job.public+address+payload
            value=hashlib.shake_256(data).digest(self.n)
            self.hash_count+=1;self.permutation_count+=len(data)//136+1;self.tree_hashes+=1
            if self.observe: self.observe(rid,data,value)
            task=(recipe,layer,tree,addr_leaf,a,b,value.ljust(49,b'\0'))
            if self.task_trace is not None: self.task_trace.append(task)
            if self.task_observe: self.task_observe(task)
            return value
        def take():
            offset=self.signature_cursor
            if offset+self.n>len(self.signature): raise ValueError('Verify input exhausted')
            self.signature_cursor+=self.n
            return self.signature[offset:offset+self.n]
        def parent(value,left,index,level):
            # index is the already advanced parent index.
            return hashed(6 if kind==TreeKind.FORS else 10,
                leaf if kind==TreeKind.FORS else 0,level,
                (group<<(self.a-level))+index if kind==TreeKind.FORS else index,left+value)
        def capture(value,index,level):
            if mode==TreeMode.SIGN and index==((target>>level)^1):
                self.spaces[2][level]=value
        def push(value,index,level=0):
            capture(value,index,level)
            while index&1:
                same_parent=index>>1==(target>>level)>>1
                value=(bytes(self.n) if shortcut and same_parent else
                    parent(value,self.spaces[1][level],index>>1,level+1))
                index>>=1;level+=1;capture(value,index,level)
            self.spaces[1][level]=value
            return value
        def chain(index,cursor,mode,source=ChainLeaf.CURSOR,value=None):
            self._commit(chain=index,cursor=cursor,mask=1,digit0=self.digits[index]
                if mode!=ChainMode.FULL else 0)
            self.digit_valid=1 if mode!=ChainMode.FULL else 0
            if value is not None: nodes[N.L0]=value
            self._chain(mode,Lanes.L0,source,_tree=True,_recipes=recipes)
            return nodes[N.L0]
        if mode==TreeMode.VERIFY:
            if kind==TreeKind.HT:
                for index in range(self.chains):
                    self.spaces[0][index]=chain(index,0,ChainMode.SUFFIX,ChainLeaf.LEAF,take())
                root=hashed(9,leaf,0,0,b''.join(self.spaces[0][:self.chains]))
            else:
                root=hashed(5,leaf,0,(group<<self.a)+target,take())
            index=target
            for level in range(1,height+1):
                sibling=take()
                left,right=(sibling,root) if index&1 else (root,sibling)
                index>>=1;root=parent(right,left,index,level)
        elif kind==TreeKind.HT:
            for cursor in range(1<<height):
                selected=mode==TreeMode.SIGN and cursor==target
                chain_mode=(ChainMode.CAP_PREFIX if shortcut else ChainMode.CAP_FULL) if selected else ChainMode.FULL
                for index in range(self.chains):
                    value=chain(index,cursor,chain_mode)
                    if selected: self.output.extend(nodes[N.CAP0])
                    if not (selected and shortcut): self.spaces[0][index]=value
                value=bytes(self.n) if selected and shortcut else hashed(
                    9,cursor,0,0,b''.join(self.spaces[0][:self.chains]))
                root=push(value,cursor)
            if mode==TreeMode.SIGN:
                for level in range(height): self.output.extend(self.spaces[2][level])
            if shortcut: root=nodes[N.V3]
        else:
            captured=None
            for cursor in range(0,1<<height,2):
                # Preserve the K1 image's PRF0, PRF1, F0, F1, first-parent order.
                secret0=hashed(4,leaf,0,(group<<self.a)+cursor,self.job.secret)
                secret1=hashed(4,leaf,0,(group<<self.a)+cursor+1,self.job.secret)
                if cursor==(target&~1): captured=(secret0,secret1)[target&1]
                value0=hashed(5,leaf,0,(group<<self.a)+cursor,secret0)
                value1=hashed(5,leaf,0,(group<<self.a)+cursor+1,secret1)
                if cursor==(target&~1): self.spaces[2][0]=(value1,value0)[target&1]
                value=parent(value1,value0,cursor>>1,1)
                root=push(value,cursor>>1,1)
            self.output.extend(captured)
            for level in range(height): self.output.extend(self.spaces[2][level])
        # The result and preserved outer fields form TREE's complete ABI.
        for name in c.__dataclass_fields__:
            setattr(c,name,outer.get(name,1 if name=='mask' else False if name=='root_equal' else 0))
        for node in (N.L1,N.RIGHT,N.CAP0,N.CAP1,N.NODE,N.TMPNODE): nodes[node]=bytes(self.n)
        nodes[N.L0]=root;self.digit_valid=0;self.root_compare_valid=False

    def lane_mask(self,selector):
        return self.ctx.mask if not selector else self.ctx.mask&(1<<(selector-1))

    def _commit(self,**updates):
        limits={'layer':31,'tree':(1<<64)-1,'leaf':1023,'group':63,'target':16383,
            'cursor':32767,'chain':127,'step0':15,'step1':15,'digit0':15,'digit1':15,
            'level':15,'index':16383,'path':16383,'fors_base':(1<<20)-1,'mask':3,
            'reduce_index':127,'reduce_span':127,'height':14,'addr_leaf0':1023,
            'addr_leaf1':1023,'addr_a0':127,'addr_a1':127,'addr_b0':0xffffffff,'addr_b1':0xffffffff}
        if any(not 0<=v<=limits.get(k,v) for k,v in updates.items()):
            raise ValueError('typed update out of bounds')
        for name,value in updates.items(): setattr(self.ctx,name,value)

    def predicate(self,condition,lane=0):
        c=self.ctx
        if condition==Cond.CURSOR_MORE: return c.cursor<(1<<c.height)
        if condition==Cond.CHAIN_MORE: return c.chain<self.chains
        if condition==Cond.GROUP_MORE: return c.group<self.k
        if condition==Cond.LAYER_MORE: return c.layer<self.d
        if condition==Cond.FINAL_LAYER: return c.layer==self.d-1
        if condition==Cond.LEVEL_MORE: return c.level<c.height
        if condition==Cond.TARGET_LEAF: return c.cursor==c.target
        if condition==Cond.INDEX_ODD: return bool(c.index&1)
        if condition==Cond.AUTH_MATCH: return c.index==(c.path^1)
        if condition==Cond.SAME_PARENT: return c.index>>1==c.path>>1
        if condition==Cond.STEP_EQ_DIGIT:
            if not self.digit_valid&(1<<lane): raise ValueError("comparison before digit load")
            return (c.step0,c.step1)[lane]==(c.digit0,c.digit1)[lane]
        if condition==Cond.STEP_MORE: return (c.step0,c.step1)[lane]<15
        if condition==Cond.LANE_ENABLED: return bool(c.mask&(1<<lane))
        if condition==Cond.MASK_ZERO: return not c.mask
        if condition==Cond.FORS_PAIR_TARGET: return c.cursor==(c.target&~1)
        if condition==Cond.REDUCE_MORE: return c.reduce_index<c.reduce_span
        if condition==Cond.REDUCE_AGAIN: return c.reduce_span>1
        if condition==Cond.ROOT_EQUAL:
            if not self.root_compare_valid: raise ValueError("root comparison unavailable")
            return c.root_equal
        raise ValueError('invalid predicate')

    def _address(self,kind,variant):
        c=self.ctx; leaf0=leaf1=a0=a1=b0=b1=0
        if kind in (Addr.WOTS_CURSOR,Addr.WOTS_LEAF):
            leaf0=leaf1=c.cursor if kind==Addr.WOTS_CURSOR else c.leaf
            if c.chain>=self.chains: raise ValueError('chain address out of bounds')
            a0=c.chain; a1=c.chain+1; b0=c.step0; b1=c.step1
        elif kind in (Addr.FORS_CURSOR,Addr.FORS_TARGET):
            leaf0=leaf1=c.leaf
            index=c.cursor if kind==Addr.FORS_CURSOR else c.target
            if index>=(1<<self.a) or c.group>=self.k: raise ValueError('FORS address out of bounds')
            b0=(c.group<<self.a)+index; b1=b0+(kind==Addr.FORS_CURSOR)
        elif kind==Addr.FORS_NODE:
            if c.group>=self.k: raise ValueError("FORS group out of bounds")
            leaf0=leaf1=c.leaf; a0=a1=c.level; b0=b1=c.fors_base+c.index
        elif kind==Addr.HT_NODE:
            if c.level>c.height: raise ValueError("tree level out of bounds")
            a0=a1=c.level; b0=b1=c.index
        elif kind==Addr.WOTS_LIST:
            leaf0=leaf1=c.cursor if variant==ListLeaf.CURSOR else c.leaf
        elif kind==Addr.FORS_LIST: leaf0=leaf1=c.leaf
        elif kind==Addr.REDUCE_NODE:
            if c.reduce_index>=c.reduce_span or not c.level: raise ValueError("reduction address out of bounds")
            leaf0=leaf1=c.leaf if variant==TreeKind.FORS else 0
            a0=a1=c.level; b0=b1=c.reduce_index+(c.fors_base if variant==TreeKind.FORS else 0)
        else: raise ValueError('invalid address operation')
        self._commit(addr_leaf0=leaf0,addr_leaf1=leaf1,addr_a0=a0,addr_a1=a1,addr_b0=b0,addr_b1=b1)

    def _node_index(self,kind,imm):
        c=self.ctx
        return (c.level,c.chain,c.chain+1,c.group,c.cursor,c.reduce_index*2,
                c.reduce_index*2+1,c.reduce_index,imm)[kind]

    def _write_node(self,d,value):
        self.nodes[d]=value
        if d in (N.V2,N.V3): self.root_compare_valid=False

    def run(self):
        if self.halted: raise ValueError('halted until reset')
        self.halted=True; self.root_compare_valid=False
        c=self.ctx; n=self.nodes; spaces=self.spaces; code=self.decoded
        pc=self.image.entries[self.operation]; count=0; limit=self.instruction_limit
        try:
            while True:
                if not 0<=pc<len(code): raise ValueError('PC outside code')
                op,d,a,b,imm=code[pc]; pc+=1; count+=1
                if count>limit: raise ValueError('instruction execution limit')
                if self.pending is not None and op not in PENDING_SAFE:
                    raise ValueError('unsafe operation before WAIT')
                if op==Op.LAYER_INIT:
                    self._commit(layer=self.d-1 if d==LayerInit.TOP else 0)
                elif op==Op.LAYER_NEXT:
                    if c.layer>=self.d: raise ValueError('layer update out of bounds')
                    self._commit(layer=c.layer+1)
                elif op==Op.TREE_NEXT:
                    self._commit(leaf=c.tree&((1<<self.hp)-1),tree=c.tree>>self.hp)
                elif op==Op.GROUP_INIT: self._commit(group=0)
                elif op==Op.GROUP_NEXT:
                    if c.group>=self.k: raise ValueError('group update out of bounds')
                    self._commit(group=c.group+1)
                elif op==Op.CURSOR_INIT: self._commit(cursor=0)
                elif op==Op.CURSOR_NEXT:
                    if c.cursor+imm>(1<<c.height): raise ValueError('cursor update out of bounds')
                    self._commit(cursor=c.cursor+imm)
                elif op==Op.CHAIN_INIT:
                    self._commit(chain=0); self.digit_valid=0
                elif op==Op.CHAIN_NEXT:
                    if c.chain>=self.chains or c.chain+imm>self.chains+1:
                        raise ValueError('chain update out of bounds')
                    self._commit(chain=c.chain+imm); self.digit_valid=0
                elif op==Op.HEIGHT:
                    self._commit(height=self.hp if d==Height.HT else self.a if d==Height.FORS else imm)
                elif op==Op.TARGET:
                    if d==Target.LEAF: self._commit(target=c.leaf)
                    else:
                        if len(self.digest)!=self.m or c.group>=self.k: raise ValueError('TARGET index/digest')
                        fb=(self.k*self.a+7)//8
                        target=(int.from_bytes(self.digest[:fb],'big')>>(8*fb-self.a*(c.group+1)))&((1<<self.a)-1)
                        self._commit(target=target)
                elif op==Op.DIGITS:
                    digits=[v for byte in n[N.V2] for v in (byte>>4,byte&15)]
                    checksum=sum(15-v for v in digits)
                    self.digits=digits+[(checksum>>s)&15 for s in (8,4,0)]; self.digit_valid=0
                elif op==Op.DIGIT_LOAD:
                    if not self.digits: raise ValueError("DIGIT before digits")
                    mask=self.lane_mask(d); updates={}
                    for lane in range(2):
                        if mask&(1<<lane):
                            if c.chain+lane>=len(self.digits): raise ValueError('DIGIT index/uninitialized digits')
                            updates['digit'+str(lane)]=self.digits[c.chain+lane]
                    self._commit(**updates); self.digit_valid|=mask
                elif op==Op.STEP_INIT:
                    mask=self.lane_mask(d)
                    if a==StepSource.DIGIT and (not self.digits or mask&~self.digit_valid): raise ValueError('STEP before digit load')
                    self._commit(**{'step'+str(lane):(c.digit0,c.digit1)[lane] if a==StepSource.DIGIT else 0
                        for lane in range(2) if mask&(1<<lane)})
                elif op==Op.STEP_NEXT:
                    mask=self.lane_mask(d); updates={}
                    for lane in range(2):
                        if mask&(1<<lane):
                            step=(c.step0,c.step1)[lane]
                            if step>=15: raise ValueError('step update out of bounds')
                            updates['step'+str(lane)]=step+1
                    self._commit(**updates)
                elif op==Op.MASK:
                    pair=(1 if c.chain<self.chains else 0)|(2 if c.chain+1<self.chains else 0)
                    if d==Mask.FIXED: mask=imm
                    elif d==Mask.PAIR: mask=pair
                    elif d==Mask.SUFFIX: mask=pair&((c.step0<15)|(2*(c.step1<15)))
                    else:
                        if not self.digits or pair&~self.digit_valid: raise ValueError("prefix before digit load")
                        mask=pair&((c.step0<c.digit0)|(2*(c.step1<c.digit1)))
                    self._commit(mask=mask)
                elif op==Op.NODE_BEGIN:
                    index=(c.cursor,c.target,c.leaf,imm)[d]
                    if not c.height or index>=(1<<c.height) or c.target>=(1<<c.height) or (a==TreeKind.FORS and c.group>=self.k):
                        raise ValueError('node source out of bounds')
                    self._commit(level=0,index=index,path=c.target,fors_base=c.group<<self.a if a==TreeKind.FORS else 0)
                elif op==Op.NODE_PARENT:
                    if c.level>=c.height: raise ValueError('parent update out of bounds')
                    self._commit(level=c.level+1,index=c.index>>1,path=c.path>>1,fors_base=c.fors_base>>1)
                elif op==Op.LEVEL_INIT: self._commit(level=0)
                elif op==Op.LEVEL_NEXT:
                    if c.level>=c.height: raise ValueError('level update out of bounds')
                    self._commit(level=c.level+1)
                elif op==Op.ADRS: self._address(d,a)
                elif op==Op.REDUCE_INIT:
                    if not c.height or (1<<c.height)>SPACE_DEPTHS[0] or (d==TreeKind.FORS and c.group>=self.k):
                        raise ValueError('reduction span out of bounds')
                    self._commit(reduce_span=1<<c.height,reduce_index=0,level=0,
                        fors_base=c.group<<self.a if d==TreeKind.FORS else 0)
                elif op==Op.REDUCE_NEXT:
                    if d==ReduceNext.INDEX:
                        if c.reduce_index>=c.reduce_span: raise ValueError('reduction index out of bounds')
                        self._commit(reduce_index=c.reduce_index+1)
                    else:
                        if c.reduce_span<=1 or c.level>=c.height: raise ValueError('reduction level out of bounds')
                        self._commit(reduce_span=c.reduce_span>>1,reduce_index=0,level=c.level+1,fors_base=c.fors_base>>1)
                elif op==Op.PARSE:
                    if len(self.digest)!=self.m: raise ValueError('PARSE before H_msg')
                    fb=(self.k*self.a+7)//8; tb=(self.h-self.hp+7)//8; lb=(self.hp+7)//8
                    self._commit(tree=int.from_bytes(self.digest[fb:fb+tb],'big')&((1<<(self.h-self.hp))-1),
                        leaf=int.from_bytes(self.digest[fb+tb:fb+tb+lb],'big')&((1<<self.hp)-1))
                elif op==Op.NMOV: self._write_node(d,n[a])
                elif op==Op.LOAD:
                    index=self._node_index(b,imm)
                    if index>=len(spaces[a]): raise ValueError('node load out of bounds')
                    self._write_node(d,spaces[a][index])
                elif op==Op.STORE:
                    index=self._node_index(b,imm)
                    if index>=len(spaces[d]): raise ValueError('node store out of bounds')
                    spaces[d][index]=n[a]
                elif op==Op.HASH: self._issue(d,self.lane_mask(a))
                elif op==Op.WAIT: self._wait()
                elif op==Op.CHAIN: self._chain(d,a,b)
                elif op==Op.TREE: self._tree(d,a,b)
                elif op==Op.INPUT:
                    if self.operation!=2: raise ValueError('INPUT outside Verify')
                    offset=self.signature_cursor
                    if offset+self.n>len(self.signature): raise ValueError('Verify input exhausted')
                    self._write_node(d,self.signature[offset:offset+self.n]); self.signature_cursor+=self.n
                elif op==Op.EMIT:
                    if self.operation==2: raise ValueError('EMIT during Verify')
                    self.output.extend(n[a])
                elif op==Op.ROOT_COMPARE:
                    if self.operation!=2: raise ValueError("root comparison outside Verify")
                    c.root_equal=n[N.V2]==n[N.V3]; self.root_compare_valid=True
                elif op==Op.JMP: pc=imm
                elif op==Op.BR:
                    if self.predicate(d,a)!=bool(b): pc=imm
                elif op==Op.END:
                    self.instructions=count
                    if self.operation==2:
                        if not self.root_compare_valid: raise ValueError('Verify END before root comparison')
                        if self.signature_cursor!=len(self.signature): raise ValueError('unconsumed Verify input')
                        return c.root_equal
                    expected=(self.image.descriptors[13]>>(32*self.operation))&0xffffffff
                    if len(self.output)!=expected: raise ValueError('output length')
                    return bytes(self.output)
                else: raise ValueError('invalid typed opcode')
        except Exception as exc:
            self.instructions=count; self.error=str(exc)
            raise
