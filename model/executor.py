"""Instruction-level model of the typed HBS processor; each HASH is one backend primitive."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib

from model.microcode import (Addr, Cond, Height, Instruction, LayerInit, ListLeaf, Mask, N,
    Op, PENDING_SAFE, ReduceNext, SPACE_DEPTHS, StepSource, Target, TreeKind, Lanes, ChainMode, ChainLeaf)


@dataclass(frozen=True)
class Job:
    """Fixed job inputs; q persistence and random generation belong upstream."""
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
    address_type: int = 0
    root_equal: bool = False


class MicroMachine:
    def __init__(self, image, job, root, message, operation, signature=b"", observe=None,
                 task_observe=None, *, record_tasks=False, instruction_limit=200_000_000):
        image.validate()
        if operation not in (0,1,2): raise ValueError("operation")
        self.image=image; self.job=job; self.operation=operation
        self.hash_backend=image.hash_backend
        self.params=tuple((image.descriptors[14]>>(8*i))&255 for i in range(8))
        self.n,self.hp,self.d,self.k,self.a,self.m,self.h,self.chains=self.params
        from model.profiles import get_profile
        from model.microcode import PROFILE_CODES
        self.profile=get_profile(next(name for name,code in PROFILE_CODES.items() if code==(image.descriptors[1]&31)),self.hash_backend)
        self.family=self.profile.family
        if any(len(v)!=self.n for v in (job.secret,job.prf,job.public,job.random,root)):
            raise ValueError("Job/root node width")
        if len(job.identifier)!=16 or not 0<=job.q<1<<32: raise ValueError("Job identifier/index width")
        if self.family=="slh" and (job.q or any(job.identifier)): raise ValueError("SLH-only Job")
        if self.family!="slh" and operation in (1,2) and job.q>=1<<self.h: raise ValueError("signature index exhausted")
        if not (len(message)==0 if operation==0 else (0 if self.family!="slh" else 1)<=len(message)<=87):
            raise ValueError("message length")
        if operation==2 and len(signature)!=(image.descriptors[13]>>32):
            raise ValueError("Verify signature byte count")
        if operation!=2 and signature: raise ValueError("signature supplied to non-Verify")
        self.message=bytes(message); self.signature=bytes(signature); self.signature_cursor=0
        self.ctx=Context(leaf=job.q if self.family!="slh" and operation!=0 else 0)
        self.used_index=job.q if self.family!="slh" and operation==1 else None
        self.next_index=job.q+1 if self.used_index is not None else job.q
        self.exhausted=self.family!="slh" and self.next_index>=1<<self.h
        self.trace_digest=hashlib.sha256()
        self.nodes=[bytes(self.n) for _ in range(16)]
        self.nodes[N.V3]=bytes(root)
        for i,v in ((N.SECRET,job.secret),(N.PRF,job.prf),(N.PUBLIC,job.public),(N.RANDOM,job.random)):
            self.nodes[i]=bytes(v)
        self.spaces=[[bytes(self.n) for _ in range(depth)] for depth in (SPACE_DEPTHS if self.family!="slh" else (68,16,16))]
        self.digest=b""; self.digits=[]; self.digit_valid=0; self.pending=None
        self.observe=observe; self.task_observe=task_observe
        self.task_trace=[] if record_tasks else None
        self.hash_count=0; self.permutation_count=0; self.instructions=0; self.root_compare_valid=False
        self.macro_count=0;self.macro_hashes=0
        self.tree_count=0;self.tree_hashes=0;self.tree_chains=0
        self.output=bytearray(); self.halted=False; self.error=None
        if type(instruction_limit) is not int or not 1<=instruction_limit<1<<64:
            raise ValueError("unsigned-64 instruction budget must be positive")
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
            if lane and shape not in (1,2,5,6,9,10): raise ValueError("unsupported lane1 recipe")
            layer,tree=c.layer,c.tree
            leaf=(c.addr_leaf0,c.addr_leaf1)[lane]
            a=(c.addr_a0,c.addr_a1)[lane]; b=(c.addr_b0,c.addr_b1)[lane]
            if layer>=32 or leaf>=1<<20 or a>=128 or b>0xffffffff:
                raise ValueError("Hash address field range")
            address=b"".join(x.to_bytes(4,"big") for x in (layer,0,tree>>32,tree&0xffffffff,domain,leaf,a,b))
            if shape==1: data=self.job.public+address+self.job.secret
            elif shape==2:
                if lane and arity==2: raise ValueError("lane1 parent Hash")
                data=self.job.public+address+n[N.L0+lane]+(n[N.RIGHT] if arity==2 else b"")
            elif shape==3: data=self.job.prf+self.job.random+self.message
            elif shape==4: data=n[N.V0]+self.job.public+n[N.V3]+self.message
            elif shape==12: data=self.job.public+address+b"".join(self.spaces[0][:arity])
            elif shape==5:
                # XMSS address is eight words: layer, tree[64], type, ots,
                # chain/height, hash/index, keyAndMask (RFC8391/NIST208).
                address=b"".join(x.to_bytes(4,"big") for x in (0,0,0,c.address_type,
                    0 if c.address_type==2 else leaf,a,b,max(0,domain-2)))
                if domain==0: data=(4).to_bytes(32,"big")+self.job.secret+self.job.public+address
                elif domain==1: data=(3).to_bytes(32,"big")+self.job.prf+self.job.q.to_bytes(32,"big")
                else: data=(3).to_bytes(32,"big")+self.job.public+address
            elif shape==6: data=bytes(32)+n[N.V2]+n[N.L0+lane]
            elif shape==7: data=(1).to_bytes(32,"big")+n[N.V2]+n[N.L0]+n[N.RIGHT]
            elif shape==8: data=(2).to_bytes(32,"big")+n[N.V0]+n[N.V3]+self.job.q.to_bytes(32,"big")+self.message
            elif shape==9: data=self.job.identifier+leaf.to_bytes(4,"big")+a.to_bytes(2,"big")+b"\xff"+self.job.secret
            elif shape==10: data=self.job.identifier+leaf.to_bytes(4,"big")+a.to_bytes(2,"big")+b.to_bytes(1,"big")+n[N.L0+lane]
            elif shape==11: data=self.job.identifier+self.job.q.to_bytes(4,"big")+b"\x81\x81"+n[N.V0]+self.message
            elif shape==13: data=self.job.identifier+b.to_bytes(4,"big")+b"\x82\x82"+n[N.L0]
            elif shape==14: data=self.job.identifier+b.to_bytes(4,"big")+b"\x83\x83"+n[N.L0]+n[N.RIGHT]
            elif shape==15: data=self.job.identifier+leaf.to_bytes(4,"big")+b"\x80\x80"+b"".join(self.spaces[0][:arity])
            else: raise ValueError("unsupported recipe shape")
            blocks=len(data)//136+1
            if blocks>((recipe>>24)&63): raise ValueError("recipe block bound")
            tasks.append((lane,recipe_id,recipe,layer,tree,leaf,a,b,out,data,c.address_type))
        self.pending=tasks

    def _wait(self):
        if self.pending is None: raise ValueError("WAIT without Hash group")
        for lane,rid,recipe,layer,tree,leaf,a,b,out,data,address_type in self.pending:
            permutations=len(data)//136+1
            if self.hash_count==(1<<64)-1 or self.permutation_count>(1<<64)-1-permutations:
                raise OverflowError("Hash statistics exceed unsigned-64 range")
            result=hashlib.shake_256(data).digest(out)
            self.nodes[N.L0+lane]=result[:self.n].ljust(self.n,b"\0")
            if (recipe>>56)&15==4: self.digest=result
            self.hash_count+=1; self.permutation_count+=permutations
            self.trace_digest.update(len(data).to_bytes(4,"little")+data+result)
            if self.observe: self.observe(rid,data,result)
            task=(recipe,layer,tree,leaf,a,b,result.ljust(49,b"\0"))
            if self.family!="slh": task=(*task,address_type)
            if self.task_trace is not None: self.task_trace.append(task)
            if self.task_observe: self.task_observe(task)
        self.pending=None

    def _chain(self, mode, selector, leaf_source):
        """One bounded WOTS chain, independent of the explicit instruction loop.

        Validate both recipes before work, retain private address/step values,
        and publish only the selected result, optional capture and final step.
        Every internal SHAKE reports the same byte and task observations as
        ordinary ISSUE/WAIT; no tree helper or old macro interpreter is used.
        """
        if self.family!="slh": return self._chain_stateful(mode,selector,leaf_source)
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
        allowed=(15<<56)|(255<<48)|(255<<40)|(63<<32)|(63<<24)
        for rid,shape,domain in ((7,1,5),(8,2,0)):
            recipe=self.image.descriptors[rid]
            if (recipe&~allowed or (recipe>>56)&15!=shape or (recipe>>48)&255!=domain
                or (recipe>>40)&255!=1 or (recipe>>32)&63!=self.n
                or not 1<=((recipe>>24)&63)<=32):
                raise ValueError('CHAIN recipe mismatch')
        self.macro_count+=1
        def hashed(rid,step,payload):
            recipe=self.image.descriptors[rid];domain=(recipe>>48)&255
            address=b''.join(x.to_bytes(4,'big') for x in
                (c.layer,0,c.tree>>32,c.tree&0xffffffff,domain,leaf,chain,step))
            data=self.job.public+address+payload
            value=hashlib.shake_256(data).digest(self.n)
            self.hash_count+=1;self.permutation_count+=len(data)//136+1
            self.macro_hashes+=1
            self.trace_digest.update(len(data).to_bytes(4,"little")+data+value)
            if self.observe: self.observe(rid,data,value)
            task=(recipe,c.layer,c.tree,leaf,chain,step,value.ljust(49,b'\0'))
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

    def _macro_hash(self,rid,leaf,a,b,*,left=b'',right=b'',key=b'',address_type=0,tree=False):
        """One raw SHAKE call. The recipe model is independent of reference algorithms."""
        recipe=self.image.descriptors[rid];shape=(recipe>>56)&15;domain=(recipe>>48)&255
        if shape==5:
            address=b''.join(x.to_bytes(4,'big') for x in (0,0,0,address_type,0 if address_type==2 else leaf,a,b,max(0,domain-2)))
            data=(4).to_bytes(32,'big')+self.job.secret+self.job.public+address if domain==0 else (3).to_bytes(32,'big')+self.job.public+address
        elif shape==6:data=bytes(32)+key+left
        elif shape==7:data=(1).to_bytes(32,'big')+key+left+right
        elif shape==9:data=self.job.identifier+leaf.to_bytes(4,'big')+a.to_bytes(2,'big')+b'\xff'+self.job.secret
        elif shape==10:data=self.job.identifier+leaf.to_bytes(4,'big')+a.to_bytes(2,'big')+b.to_bytes(1,'big')+left
        elif shape==13:data=self.job.identifier+b.to_bytes(4,'big')+b'\x82\x82'+left
        elif shape==14:data=self.job.identifier+b.to_bytes(4,'big')+b'\x83\x83'+left+right
        elif shape==15:data=self.job.identifier+leaf.to_bytes(4,'big')+b'\x80\x80'+b''.join(self.spaces[0][:67])
        else:raise ValueError('unexpected macro recipe')
        if len(data)//136+1>((recipe>>24)&63):raise ValueError('macro recipe capacity')
        result=hashlib.shake_256(data).digest(self.n)
        self.hash_count+=1;self.permutation_count+=len(data)//136+1
        if tree:self.tree_hashes+=1
        else:self.macro_hashes+=1
        self.trace_digest.update(len(data).to_bytes(4,'little')+data+result)
        if self.observe:self.observe(rid,data,result)
        task=(recipe,self.ctx.layer,self.ctx.tree,leaf,a,b,result.ljust(49,b'\0'),address_type)
        if self.task_trace is not None:self.task_trace.append(task)
        if self.task_observe:self.task_observe(task)
        return result

    def _chain_stateful(self,mode,selector,leaf_source,*,_tree=False,_recipes=None):
        from model.microcode import validate_recipe
        if self.pending is not None:raise ValueError('CHAIN before WAIT')
        mask=self.lane_mask(selector)
        if mask not in (1,2):raise ValueError('CHAIN needs one slot')
        slot=int(mask==2);c=self.ctx;chain=c.chain+slot
        leaf=c.cursor if leaf_source==ChainLeaf.CURSOR else c.leaf
        if not 0<=leaf<1<<self.h or not 0<=chain<67:raise ValueError('CHAIN address bound')
        digit=(c.digit0,c.digit1)[slot]
        if mode!=ChainMode.FULL and (not self.digits or not self.digit_valid&mask or not 0<=digit<=15):raise ValueError('CHAIN invalid digit')
        required={7:(5,0),4:(5,2),5:(5,3),8:(6,0)} if self.family=='xmss' else {7:(9,0),8:(10,0)}
        for rid,(shape,domain) in required.items():
            recipe=self.image.descriptors[rid];validate_recipe(recipe,self.profile)
            if (recipe>>56)&15!=shape or (recipe>>48)&255!=domain:raise ValueError('CHAIN standard recipe mismatch')
        if _tree:self.tree_chains+=1
        else:self.macro_count+=1
        value=self.nodes[N.L0+slot];capture=None;start=digit if mode==ChainMode.SUFFIX else 0
        if mode!=ChainMode.SUFFIX:
            value=self._macro_hash(7,leaf,chain,0,tree=_tree)
            if mode!=ChainMode.FULL and digit==0:capture=value
        end=digit if mode==ChainMode.CAP_PREFIX else 15
        for step in range(start,end):
            if self.family=='xmss':
                key=self._macro_hash(4,leaf,chain,step,tree=_tree)
                mask_value=self._macro_hash(5,leaf,chain,step,tree=_tree)
                value=self._macro_hash(8,leaf,chain,step,key=key,left=bytes(x^y for x,y in zip(value,mask_value)),tree=_tree)
            else:value=self._macro_hash(8,leaf,chain,step,left=value,tree=_tree)
            if mode in (ChainMode.CAP_FULL,ChainMode.CAP_PREFIX) and step+1==digit:capture=value
        self.nodes[N.L0+slot]=value
        if capture is not None:self.nodes[N.CAP0+slot]=capture
        self._commit(**{'step'+str(slot):end})

    def _tree_stateful(self,kind,mode,flags=0):
        from model.microcode import validate_recipe
        if kind!=TreeKind.HT or flags or int(mode)!=self.operation or self.pending is not None:raise ValueError('stateful TREE preflight')
        c=self.ctx;target=c.target;h=self.h
        if mode!=TreeMode.ROOT and (not 0<=target<1<<h or len(self.digits)!=67):raise ValueError('TREE target/digits')
        required=(4,5,6,7,8,10) if self.family=='xmss' else (7,8,9,10,11)
        for rid in required:validate_recipe(self.image.descriptors[rid],self.profile)
        self.tree_count+=1
        outer={k:getattr(c,k) for k in ('layer','tree','leaf','group','target')}
        def take():
            p=self.signature_cursor
            if p+32>len(self.signature):raise ValueError('TREE truncated input')
            self.signature_cursor+=32;return self.signature[p:p+32]
        def hashed(rid,leaf,a,b,**kw):return self._macro_hash(rid,leaf,a,b,tree=True,**kw)
        def parent(left,right,leaf,level,index,ltree=False):
            if self.family=='lms':return hashed(10,0,level,(1<<(h-level))+index,left=left,right=right)
            at=1 if ltree else 2;adrleaf=leaf if ltree else 0;adrlevel=level if ltree else level-1
            key=hashed(4,adrleaf,adrlevel,index,address_type=at)
            m0=hashed(5,adrleaf,adrlevel,index,address_type=at)
            m1=hashed(6,adrleaf,adrlevel,index,address_type=at)
            return hashed(10,adrleaf,adrlevel,index,address_type=at,key=key,left=bytes(x^y for x,y in zip(left,m0)),right=bytes(x^y for x,y in zip(right,m1)))
        def compress(leaf):
            if self.family=='lms':
                k=hashed(9,leaf,0,0);return hashed(11,0,0,(1<<h)+leaf,left=k)
            span=67;level=0
            while span>1:
                for i in range((span+1)//2):
                    left=self.spaces[0][2*i]
                    self.spaces[0][i]=parent(left,self.spaces[0][2*i+1],leaf,level,i,True) if 2*i+1<span else left
                span=(span+1)//2;level+=1
            return self.spaces[0][0]
        def chain(i,leaf,mode,value=None):
            self._commit(chain=i,cursor=leaf,mask=1,digit0=self.digits[i] if mode!=ChainMode.FULL else 0)
            self.digit_valid=1 if mode!=ChainMode.FULL else 0
            if value is not None:self.nodes[N.L0]=value
            self._chain_stateful(mode,Lanes.L0,ChainLeaf.LEAF if self.operation==2 else ChainLeaf.CURSOR,_tree=True)
            return self.nodes[N.L0]
        if mode==TreeMode.VERIFY:
            for i in range(67):self.spaces[0][i]=chain(i,c.leaf,ChainMode.SUFFIX,take())
            root=compress(c.leaf);idx=target
            for level in range(1,h+1):
                sibling=take();left,right=(sibling,root) if idx&1 else (root,sibling);idx>>=1
                root=parent(left,right,0,level,idx)
        else:
            for leaf in range(1<<h):
                selected=mode==TreeMode.SIGN and leaf==target
                for i in range(67):
                    self.spaces[0][i]=chain(i,leaf,ChainMode.CAP_FULL if selected else ChainMode.FULL)
                    if selected:self.output.extend(self.nodes[N.CAP0])
                value=compress(leaf);idx=leaf;level=0
                def capture(v,idx,level):
                    if mode==TreeMode.SIGN and level<h and idx==((target>>level)^1):self.spaces[2][level]=v
                capture(value,idx,level)
                while idx&1:
                    value=parent(self.spaces[1][level],value,0,level+1,idx>>1);idx>>=1;level+=1;capture(value,idx,level)
                self.spaces[1][level]=value;root=value
            if mode==TreeMode.SIGN:
                for level in range(h):self.output.extend(self.spaces[2][level])
        for name in c.__dataclass_fields__:setattr(c,name,outer.get(name,1 if name=='mask' else False if name=='root_equal' else 0))
        for node in (N.L1,N.RIGHT,N.CAP0,N.CAP1,N.NODE,N.TMPNODE):self.nodes[node]=bytes(32)
        self.nodes[N.L0]=root;self.digit_valid=0;self.root_compare_valid=False

    def lane_mask(self,selector):
        return self.ctx.mask if not selector else self.ctx.mask&(1<<(selector-1))

    def _commit(self,**updates):
        limits={'layer':31,'tree':(1<<64)-1,'leaf':(1<<20)-1,'group':63,'target':(1<<20)-1,
            'cursor':1<<20,'chain':127,'step0':15,'step1':15,'digit0':15,'digit1':15,
            'level':20,'index':(1<<20)-1,'path':(1<<20)-1,'fors_base':(1<<20)-1,'mask':3,
            'reduce_index':127,'reduce_span':127,'height':20,'addr_leaf0':(1<<20)-1,
            'addr_leaf1':(1<<20)-1,'addr_a0':127,'addr_a1':127,'addr_b0':0xffffffff,'addr_b1':0xffffffff,
            'address_type':2,'root_equal':1}
        if self.family=='slh':
            limits.update(leaf=1023,target=16383,cursor=32767,level=15,index=16383,
                          path=16383,height=14,addr_leaf0=1023,addr_leaf1=1023,address_type=0)
        if any(k not in limits or not 0<=v<=limits[k] for k,v in updates.items()):
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
        if condition in (Cond.LTREE_PAIR,Cond.LTREE_MORE):
            if self.family!='xmss': raise ValueError('L-tree predicate outside XMSS')
            return 2*c.reduce_index+(condition==Cond.LTREE_PAIR)<c.reduce_span
        if condition==Cond.ROOT_EQUAL:
            if not self.root_compare_valid: raise ValueError("root comparison unavailable")
            return c.root_equal
        raise ValueError('invalid predicate')

    def _address(self,kind,variant):
        c=self.ctx; leaf0=leaf1=a0=a1=b0=b1=0; address_type=0
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
            a0=a1=c.level-(1 if self.family=="xmss" else 0); b0=b1=c.index
            if self.family=="xmss":
                if not c.level: raise ValueError("XMSS parent level zero")
                address_type=2
            elif self.family=="lms": b0=b1=(1<<(self.h-c.level))+c.index
        elif kind==Addr.WOTS_LIST:
            leaf0=leaf1=c.cursor if variant==ListLeaf.CURSOR else c.leaf
        elif kind in (Addr.LTREE_CURSOR,Addr.LTREE_LEAF):
            if self.family!="xmss" or c.reduce_span<=1 or 2*c.reduce_index+1>=c.reduce_span:
                raise ValueError("L-tree address outside valid pair")
            leaf0=leaf1=c.cursor if kind==Addr.LTREE_CURSOR else c.leaf
            a0=a1=c.level; b0=b1=c.reduce_index; address_type=1
        elif kind==Addr.FORS_LIST: leaf0=leaf1=c.leaf
        elif kind==Addr.REDUCE_NODE:
            if c.reduce_index>=c.reduce_span or not c.level: raise ValueError("reduction address out of bounds")
            leaf0=leaf1=c.leaf if variant==TreeKind.FORS else 0
            a0=a1=c.level; b0=b1=c.reduce_index+(c.fors_base if variant==TreeKind.FORS else 0)
        else: raise ValueError('invalid address operation')
        self._commit(address_type=address_type,addr_leaf0=leaf0,addr_leaf1=leaf1,addr_a0=a0,addr_a1=a1,addr_b0=b0,addr_b1=b1)

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
                    digits=[v for byte in n[N.V2][:self.n] for v in (byte>>4,byte&15)]
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
                    if d==TreeKind.LTREE:
                        if self.family!="xmss": raise ValueError("L-tree only valid for XMSS")
                        self._commit(reduce_span=self.chains,reduce_index=0,level=0,fors_base=0)
                        continue
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
                        if d==ReduceNext.LTREE_LEVEL and self.family!="xmss": raise ValueError("L-tree level only valid for XMSS")
                        self._commit(reduce_span=(c.reduce_span+(d==ReduceNext.LTREE_LEVEL))>>1,
                            reduce_index=0,level=c.level+1,fors_base=c.fors_base>>1)
                elif op==Op.PARSE:
                    if len(self.digest)!=self.m: raise ValueError('PARSE before H_msg')
                    fb=(self.k*self.a+7)//8; tb=(self.h-self.hp+7)//8; lb=(self.hp+7)//8
                    self._commit(tree=int.from_bytes(self.digest[fb:fb+tb],'big')&((1<<(self.h-self.hp))-1),
                        leaf=int.from_bytes(self.digest[fb+tb:fb+tb+lb],'big')&((1<<self.hp)-1))
                elif op==Op.XMSS_MASK:
                    if self.family!="xmss": raise ValueError("XMSS mask outside XMSS")
                    self._write_node(N.L0,bytes(x^y for x,y in zip(n[N.NODE+d],n[N.RIGHT])))
                elif op==Op.NMOV: self._write_node(d,n[a][:self.n])
                elif op==Op.CHAIN: self._chain(d,a,b)
                elif op==Op.LOAD:
                    index=self._node_index(b,imm)
                    if index>=len(spaces[a]): raise ValueError('node load out of bounds')
                    self._write_node(d,spaces[a][index])
                elif op==Op.STORE:
                    index=self._node_index(b,imm)
                    if index>=len(spaces[d]): raise ValueError('node store out of bounds')
                    spaces[d][index]=n[a][:self.n]
                elif op==Op.HASH: self._issue(d,self.lane_mask(a))
                elif op==Op.WAIT: self._wait()
                elif op==Op.INPUT:
                    if self.operation!=2: raise ValueError('INPUT outside Verify')
                    offset=self.signature_cursor
                    if offset+self.n>len(self.signature): raise ValueError('Verify input exhausted')
                    self._write_node(d,self.signature[offset:offset+self.n]); self.signature_cursor+=self.n
                elif op==Op.EMIT:
                    if self.operation==2: raise ValueError('EMIT during Verify')
                    self.output.extend(n[a][:self.n])
                elif op==Op.ROOT_COMPARE:
                    if self.operation!=2: raise ValueError("root comparison outside Verify")
                    c.root_equal=n[N.V2][:self.n]==n[N.V3][:self.n]; self.root_compare_valid=True
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


# Preserve the project's compact public model API.
Machine = MicroMachine
from model.microcode import MicroImage as Image

def compile_image(name, **kwargs):
    from model.mHBS import compile_micro
    return compile_micro(name, **kwargs)
