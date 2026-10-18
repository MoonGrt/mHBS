"""ABI 4 HBS programs: image layer/group control and bounded tree/chain macros."""
from __future__ import annotations

from model.microcode import (Op,ABI, MAGIC, PROFILE_CODES, Addr, Assembler, ChainLeaf, ChainMode, Cond, Height,
    Index, Lanes, LayerInit, ListLeaf, Mask, MicroImage, N, NodeSource, ReduceNext,
    Space, StepSource, Target, TreeFlags, TreeKind, TreeMode)
from model.profiles import get_profile


class Compiler:
    def __init__(self, profile, serial=False):
        self.p=profile; self.serial=serial; self.asm=Assembler()

    def e(self,op,d=0,a=0,b=0,imm=0): self.asm.emit(op,d,a,b,imm)
    def label(self,stem): return self.asm.fresh(stem)
    def at(self,label): self.asm.label(label)
    def br(self,condition,label,*,lane=0,invert=False): self.asm.branch(condition,label,lane,invert)
    def jump(self,label): self.asm.jump(label)
    def nm(self,d,a): self.e('NMOV',d,a)
    def mask(self,value): self.e('MASK',Mask.FIXED,imm=value)
    def load(self,node,space,index=Index.LEVEL,immediate=0): self.e('LOAD',node,space,index,immediate)
    def store(self,space,node,index=Index.LEVEL,immediate=0): self.e('STORE',space,node,index,immediate)

    def hash(self,recipe):
        if not self.serial or recipe not in (4,5,7,8):
            self.e('HASH',recipe); self.e('WAIT')
        else:
            # A selector restricts this ISSUE without changing the retained mask.
            for lane in range(2):
                skip=self.label('serial_skip')
                self.br(Cond.LANE_ENABLED,skip,lane=lane,invert=True)
                self.e('HASH',recipe,Lanes.L0+lane); self.e('WAIT'); self.at(skip)

    def push(self,*,fors=False,auth=True,shortcut=False,paired_odd=False):
        """Explicit merges: current node in L0, MASK=1; paired leaves in L0/L1."""
        merge,save,nohash,advanced=[self.label(x) for x in
            ('push_merge','push_save','parent_hash','parent_advanced')]
        self.e('NODE_BEGIN',NodeSource.CURSOR,TreeKind.FORS if fors else TreeKind.HT)
        def capture_auth():
            if auth:
                skip=self.label('not_auth')
                self.br(Cond.AUTH_MATCH,skip,invert=True)
                self.store(Space.AUTH,N.L0); self.at(skip)
        def parent(source,*,stack=True):
            self.nm(N.RIGHT,source)
            if stack: self.load(N.L0,Space.STACK)
            self.e('NODE_PARENT'); self.e('ADRS',Addr.FORS_NODE if fors else Addr.HT_NODE)
            self.hash(6 if fors else 10)
        if paired_odd:
            # Both freshly hashed siblings are already in the lane registers.
            # One explicit parent uses them directly, without a STACK[0] trip.
            parent(N.L1,stack=False); capture_auth()
            self.br(Cond.INDEX_ODD,save,invert=True)
        else:
            capture_auth(); self.br(Cond.INDEX_ODD,save,invert=True)
        self.at(merge)
        if shortcut:
            self.br(Cond.SAME_PARENT,nohash,invert=True)
            self.nm(N.L0,N.ZERO); self.e('NODE_PARENT'); self.jump(advanced)
            self.at(nohash)
        parent(N.L0)
        self.at(advanced); capture_auth(); self.br(Cond.INDEX_ODD,merge)
        self.at(save); self.store(Space.STACK,N.L0)

    def emit_auth(self):
        loop=self.label('emit_auth'); self.e('LEVEL_INIT'); self.at(loop)
        self.load(N.TMPNODE,Space.AUTH); self.e('EMIT',a=N.TMPNODE)
        self.e('LEVEL_NEXT'); self.br(Cond.LEVEL_MORE,loop)

    def fors_sign(self,*,fixed_pair_mask=False):
        group,leaves,cap1,nocap=[self.label(x) for x in
            ('fors_group','fors_leaves','fors_capture1','fors_no_capture')]
        self.e('GROUP_INIT'); self.e('HEIGHT',Height.FORS)
        # A K1 parent ISSUE explicitly selects L0, so its traversal can keep
        # both logical slots enabled until the final list compression.
        if fixed_pair_mask: self.mask(3)
        self.at(group); self.e('TARGET',Target.FORS); self.e('CURSOR_INIT')
        self.at(leaves); self.e('ADRS',Addr.FORS_CURSOR)
        if not fixed_pair_mask: self.mask(3)
        self.hash(4)
        self.br(Cond.FORS_PAIR_TARGET,nocap,invert=True)
        self.e('NODE_BEGIN',NodeSource.TARGET,TreeKind.FORS)
        self.br(Cond.INDEX_ODD,cap1)
        self.nm(N.CAP0,N.L0); self.jump(nocap)
        self.at(cap1); self.nm(N.CAP0,N.L1)
        self.at(nocap); self.hash(5)
        if not fixed_pair_mask: self.mask(1)
        # Even/odd pairing is explicit in the image. Both leaf results feed
        # their first parent directly, then the image merges higher levels.
        # Secret capture above left LEVEL=0 and INDEX=TARGET on the selected pair.
        noauth,auth0=[self.label(x) for x in ('fors_no_leaf_auth','fors_auth0')]
        self.br(Cond.FORS_PAIR_TARGET,noauth,invert=True)
        self.br(Cond.INDEX_ODD,auth0)
        self.store(Space.AUTH,N.L1); self.jump(noauth)
        self.at(auth0); self.store(Space.AUTH,N.L0); self.at(noauth)
        self.e('CURSOR_NEXT',imm=1)
        self.push(fors=True,paired_odd=True)
        self.e('CURSOR_NEXT',imm=1); self.br(Cond.CURSOR_MORE,leaves)
        self.store(Space.LIST,N.L0,Index.GROUP)
        self.e('EMIT',a=N.CAP0); self.emit_auth()
        self.e('GROUP_NEXT'); self.br(Cond.GROUP_MORE,group)
        self.e('ADRS',Addr.FORS_LIST); self.mask(1); self.hash(11); self.nm(N.V2,N.L0)

    def capture(self):
        for lane in range(2):
            skip=self.label('capture_skip')
            if lane: self.br(Cond.LANE_ENABLED,skip,lane=lane,invert=True)
            self.br(Cond.STEP_EQ_DIGIT,skip,lane=lane,invert=True)
            self.nm(N.CAP0+lane,N.L0+lane); self.at(skip)

    def wots_leaf_chains(self,*,capture=False,prefix_only=False):
        pairs,steps,finished=[self.label(x) for x in ('wots_pairs','wots_steps','wots_finished')]
        self.e('CHAIN_INIT'); self.at(pairs)
        self.e('MASK',Mask.PAIR); self.e('STEP_INIT',Lanes.CURRENT,StepSource.ZERO)
        self.e('ADRS',Addr.WOTS_CURSOR)
        if not capture and not self.serial:
            # A head WAIT consumes the preceding explicit PRF/F request. The
            # next F and its loopback execute before that F's explicit WAIT,
            # hiding fetch redirection while preserving one group in flight.
            self.e('HASH',7); self.at(steps); self.e('WAIT')
            self.e('HASH',8); self.e('STEP_NEXT',Lanes.CURRENT)
            self.e('ADRS',Addr.WOTS_CURSOR); self.br(Cond.STEP_MORE,steps)
            self.e('WAIT')
        else:
            self.hash(7)
            if capture: self.e('DIGIT_LOAD',Lanes.CURRENT); self.capture()
            self.at(steps)
            if prefix_only:
                self.e('MASK',Mask.PREFIX); self.br(Cond.MASK_ZERO,finished)
            self.hash(8); self.e('STEP_NEXT',Lanes.CURRENT)
            # HASH retained the old address; prepare the next step during its wait.
            self.e('ADRS',Addr.WOTS_CURSOR)
            if capture: self.capture()
            if prefix_only: self.jump(steps)
            else: self.br(Cond.STEP_MORE,steps)
        self.at(finished)
        if capture:
            noemit=self.label('no_wots_emit'); self.e('EMIT',a=N.CAP0)
            if prefix_only: self.e('MASK',Mask.PAIR)
            self.br(Cond.LANE_ENABLED,noemit,lane=1,invert=True)
            self.e('EMIT',a=N.CAP1); self.at(noemit)
        if not prefix_only:
            self.store(Space.LIST,N.L0,Index.CHAIN0)
            nostore=self.label('no_second_store')
            self.br(Cond.LANE_ENABLED,nostore,lane=1,invert=True)
            self.store(Space.LIST,N.L1,Index.CHAIN1); self.at(nostore)
        self.e('CHAIN_NEXT',imm=2); self.br(Cond.CHAIN_MORE,pairs)

    def wots_tree(self,*,signing,last_layer=False):
        leaves,selected,reduce,after_leaf=[self.label(x) for x in
            ('wots_leaves','wots_selected_leaf','wots_reduce','wots_after_leaf')]
        self.e('HEIGHT',Height.HT); self.e('CURSOR_INIT'); self.at(leaves)
        if signing: self.br(Cond.TARGET_LEAF,selected)
        self.wots_leaf_chains()
        if signing:
            self.jump(reduce); self.at(selected)
            self.wots_leaf_chains(capture=True,prefix_only=last_layer)
            # The final selected leaf supplies signature prefixes only. Its
            # endpoint list and own compression are not consumed afterwards.
            if last_layer: self.nm(N.L0,N.ZERO); self.jump(after_leaf)
        self.at(reduce); self.e('ADRS',Addr.WOTS_LIST,ListLeaf.CURSOR); self.mask(1)
        self.hash(9)
        if last_layer: self.at(after_leaf)
        self.push(auth=signing,shortcut=last_layer)
        self.e('CURSOR_NEXT',imm=1); self.br(Cond.CURSOR_MORE,leaves)
        if signing: self.emit_auth()

    def keygen(self):
        self.asm.label('keygen'); self.e('LAYER_INIT',LayerInit.TOP)
        self.wots_tree(signing=False); self.nm(N.V3,N.L0)
        for node in (N.SECRET,N.PRF,N.PUBLIC,N.V3,N.PUBLIC,N.V3): self.e('EMIT',a=node)
        self.e('END')

    def sign(self):
        self.asm.label('sign'); self.mask(1); self.hash(2)
        self.nm(N.V0,N.L0); self.e('EMIT',a=N.V0); self.hash(3); self.e('PARSE')
        self.fors_sign(); layer=self.label('sign_layer'); top=self.label('sign_top_layer')
        self.at(layer); self.e('DIGITS'); self.e('TARGET',Target.LEAF)
        self.br(Cond.FINAL_LAYER,top)
        self.wots_tree(signing=True)
        self.nm(N.V2,N.L0); self.e('TREE_NEXT'); self.e('LAYER_NEXT'); self.jump(layer)
        # Two bounded loop bodies specialize a public layer condition; neither
        # expands a Hash trajectory or delegates traversal to hardware.
        self.at(top); self.wots_tree(signing=True,last_layer=True); self.e('END')

    def verify_auth(self,*,fors=False):
        # Each iteration reads one streamed sibling and issues one parent.
        # The loopback tests metadata while the parent is in flight; its head
        # WAIT publishes L0 before either operand can be read or overwritten.
        loop,odd,hashed,body=[self.label(x) for x in
            ('verify_auth','verify_odd','verify_parent','verify_auth_body')]
        self.jump(body); self.at(loop); self.e('WAIT'); self.at(body)
        self.br(Cond.INDEX_ODD,odd)
        self.e('INPUT',N.RIGHT); self.jump(hashed)
        self.at(odd); self.nm(N.RIGHT,N.L0); self.e('INPUT',N.L0)
        self.at(hashed); self.e('NODE_PARENT')
        self.e('ADRS',Addr.FORS_NODE if fors else Addr.HT_NODE)
        self.e('HASH',6 if fors else 10,Lanes.L0); self.br(Cond.LEVEL_MORE,loop)
        self.e('WAIT')

    def verify(self):
        self.asm.label('verify'); self.e('INPUT',N.V0); self.mask(1); self.hash(3); self.e('PARSE')
        self.e('HEIGHT',Height.FORS); self.e('GROUP_INIT'); group=self.label('verify_fors')
        self.at(group); self.e('TARGET',Target.FORS); self.e('INPUT',N.L0)
        self.e('ADRS',Addr.FORS_TARGET); self.mask(1); self.hash(5)
        self.e('NODE_BEGIN',NodeSource.TARGET,TreeKind.FORS); self.verify_auth(fors=True)
        self.store(Space.LIST,N.L0,Index.GROUP); self.e('GROUP_NEXT'); self.br(Cond.GROUP_MORE,group)
        self.e('ADRS',Addr.FORS_LIST); self.mask(1); self.hash(11); self.nm(N.V2,N.L0)
        layer,pair,steps,finished=[self.label(x) for x in
            ('verify_layer','verify_pair','verify_steps','verify_endpoints')]
        self.at(layer); self.e('HEIGHT',Height.HT); self.e('TARGET',Target.LEAF); self.e('DIGITS'); self.e('CHAIN_INIT')
        self.at(pair); self.e('MASK',Mask.PAIR); self.e('DIGIT_LOAD',Lanes.CURRENT)
        self.e('STEP_INIT',Lanes.CURRENT,StepSource.DIGIT); self.e('INPUT',N.L0)
        second_done=self.label('verify_second_done')
        self.br(Cond.LANE_ENABLED,second_done,lane=1,invert=True); self.e('INPUT',N.L1)
        self.at(second_done); self.e('MASK',Mask.SUFFIX)
        self.br(Cond.MASK_ZERO,finished); self.e('ADRS',Addr.WOTS_LEAF); self.at(steps)
        self.hash(8); self.e('STEP_NEXT',Lanes.CURRENT)
        self.e('MASK',Mask.SUFFIX); self.e('ADRS',Addr.WOTS_LEAF)
        self.br(Cond.MASK_ZERO,steps,invert=True)
        self.at(finished); self.store(Space.LIST,N.L0,Index.CHAIN0)
        no_second=self.label('verify_no_second_store'); self.e('MASK',Mask.PAIR)
        self.br(Cond.LANE_ENABLED,no_second,lane=1,invert=True)
        self.store(Space.LIST,N.L1,Index.CHAIN1); self.at(no_second)
        self.e('CHAIN_NEXT',imm=2); self.br(Cond.CHAIN_MORE,pair)
        self.e('ADRS',Addr.WOTS_LIST,ListLeaf.LEAF); self.mask(1); self.hash(9)
        self.e('NODE_BEGIN',NodeSource.LEAF,TreeKind.HT); self.verify_auth()
        self.nm(N.V2,N.L0); done=self.label('verify_done'); self.br(Cond.FINAL_LAYER,done)
        self.e('TREE_NEXT'); self.e('LAYER_NEXT'); self.jump(layer)
        self.at(done); self.e('ROOT_COMPARE'); self.e('END')


class K1Compiler(Compiler):
    """One explicit Hash per ISSUE, with one complete WOTS chain per image loop.

    FORS explicitly alternates its leaf pair through ABI 2's two logical result
    slots. Both slots are served by one physical lane; neither ISSUE repeats.
    Compiler(serial=True) also pairs WOTS chains as a scheduling alternative.
    """
    def hash(self,recipe):
        if getattr(self,'paired_fors',False) and recipe in (4,5):
            # FORS sign fixes MASK=3. Submit each leaf as a separate onehot
            # ISSUE; no lane test or hardware continuation is needed.
            for lane in (Lanes.L0,Lanes.L1):
                self.e('HASH',recipe,lane); self.e('WAIT')
        else:
            self.e('HASH',recipe,Lanes.L0); self.e('WAIT')

    def fors_sign(self):
        """Explicit paired leaves, stack merges, and out-of-line captures.

        Capture branches are rare: only one leaf pair per FORS tree supplies
        the secret and leaf sibling. Their image blocks join the same visible
        loops after WAIT; hardware never continues a chain or merges a tree.
        """
        (group,leaves,prf_capture,prf_odd,prf_done,leaf_capture,leaf_odd,
         parent_ready,merge_wait,merge,save,parent_capture,check)=[self.label(x) for x in
            ('fors_group','fors_leaves','fors_prf_capture','fors_prf_odd','fors_prf_done',
             'fors_leaf_capture','fors_leaf_odd','fors_parent_ready','fors_merge_wait',
             'fors_merge','fors_save','fors_parent_capture','fors_parent_check')]
        self.e('GROUP_INIT'); self.e('HEIGHT',Height.FORS); self.mask(3)
        self.at(group); self.e('TARGET',Target.FORS); self.e('CURSOR_INIT'); self.jump(leaves)
        # Parent results are read only after this explicit join. Stack
        # access and the next parent ISSUE remain separate image operations.
        self.at(merge_wait); self.e('WAIT'); self.at(merge)
        self.nm(N.RIGHT,N.L0); self.load(N.L0,Space.STACK)
        self.e('NODE_PARENT'); self.e('ADRS',Addr.FORS_NODE)
        self.e('HASH',6,Lanes.L0); self.jump(check)
        # The pending parent may only update metadata or branch. Every
        # node capture waits for the committed result before touching AUTH.
        self.at(parent_capture); self.e('WAIT'); self.store(Space.AUTH,N.L0)
        self.br(Cond.INDEX_ODD,merge); self.jump(save)
        self.at(prf_capture); self.e('WAIT'); self.e('NODE_BEGIN',NodeSource.TARGET,TreeKind.FORS)
        self.br(Cond.INDEX_ODD,prf_odd); self.nm(N.CAP0,N.L0); self.jump(prf_done)
        self.at(prf_odd); self.nm(N.CAP0,N.L1); self.jump(prf_done)
        self.at(leaf_capture); self.e('WAIT'); self.br(Cond.INDEX_ODD,leaf_odd)
        self.store(Space.AUTH,N.L1); self.jump(parent_ready)
        self.at(leaf_odd); self.store(Space.AUTH,N.L0)
        self.at(parent_ready); self.e('CURSOR_NEXT',imm=1)
        self.e('NODE_BEGIN',NodeSource.CURSOR,TreeKind.FORS); self.e('NODE_PARENT'); self.e('ADRS',Addr.FORS_NODE)
        self.nm(N.RIGHT,N.L1); self.e('HASH',6,Lanes.L0); self.jump(check)
        self.at(leaves); self.e('ADRS',Addr.FORS_CURSOR)
        self.e('HASH',4,Lanes.L0); self.e('WAIT')
        self.e('HASH',4,Lanes.L1); self.br(Cond.FORS_PAIR_TARGET,prf_capture)
        self.e('WAIT'); self.at(prf_done)
        self.e('HASH',5,Lanes.L0); self.e('WAIT')
        self.e('HASH',5,Lanes.L1); self.br(Cond.FORS_PAIR_TARGET,leaf_capture)
        # The request retained its old address. Advance only named metadata
        # during F1; read its node and assemble the parent after WAIT below.
        self.e('CURSOR_NEXT',imm=1); self.e('NODE_BEGIN',NodeSource.CURSOR,TreeKind.FORS)
        self.e('NODE_PARENT'); self.e('ADRS',Addr.FORS_NODE); self.e('WAIT')
        self.nm(N.RIGHT,N.L1); self.e('HASH',6,Lanes.L0)
        # Both merge decisions are explicit branches under the current
        # parent Hash. Each successor performs WAIT before a node operation.
        self.at(check); self.br(Cond.AUTH_MATCH,parent_capture)
        self.br(Cond.INDEX_ODD,merge_wait); self.e('WAIT')
        self.at(save); self.store(Space.STACK,N.L0)
        self.e('CURSOR_NEXT',imm=1); self.br(Cond.CURSOR_MORE,leaves)
        self.store(Space.LIST,N.L0,Index.GROUP); self.e('EMIT',a=N.CAP0); self.emit_auth()
        self.e('GROUP_NEXT'); self.br(Cond.GROUP_MORE,group)
        self.e('ADRS',Addr.FORS_LIST); self.mask(1); self.hash(11); self.nm(N.V2,N.L0)

    def wots_leaf_chains(self,*,capture=False,prefix_only=False):
        if capture:
            return self.wots_capture_chains(prefix_only=prefix_only)
        chains,steps=[self.label(x) for x in ('wots_chains','wots_steps')]
        self.e('CHAIN_INIT'); self.mask(1)
        self.e('STEP_INIT',Lanes.L0,StepSource.ZERO); self.at(chains)
        self.e('ADRS',Addr.WOTS_CURSOR)
        # The loopback and next ADRS execute while the explicit F is in
        # flight. WAIT publishes its node before the following ISSUE.
        self.e('HASH',7,Lanes.L0); self.at(steps); self.e('WAIT')
        self.e('HASH',8,Lanes.L0); self.e('STEP_NEXT',Lanes.L0)
        self.e('ADRS',Addr.WOTS_CURSOR); self.br(Cond.STEP_MORE,steps)
        # The final F already snapped its step. Clear the next chain's step
        # while it runs, then WAIT before storing the endpoint in LIST.
        self.e('STEP_INIT',Lanes.L0,StepSource.ZERO)
        self.e('WAIT'); self.store(Space.LIST,N.L0,Index.CHAIN0)
        self.e('CHAIN_NEXT',imm=1); self.br(Cond.CHAIN_MORE,chains)

    def wots_capture_chains(self,*,prefix_only=False):
        """Capture once after the explicit prefix, then hash an explicit suffix."""
        chain,prefix,prefix_issue,prefix_done,suffix,suffix_issue,suffix_done=[self.label(x) for x in
            ('capture_chain','capture_prefix','capture_prefix_issue','capture_prefix_done',
             'capture_suffix','capture_suffix_issue','capture_suffix_done')]
        self.e('CHAIN_INIT'); self.mask(1); self.at(chain)
        self.e('STEP_INIT',Lanes.L0,StepSource.ZERO); self.e('ADRS',Addr.WOTS_CURSOR)
        # DIGIT_LOAD precedes ISSUE; it is not legal while a Hash is pending.
        # The digit-zero branch can then execute during the PRF, and every
        # prefix path joins through WAIT before capturing its result.
        self.e('DIGIT_LOAD',Lanes.L0); self.e('HASH',7,Lanes.L0)
        self.br(Cond.STEP_EQ_DIGIT,prefix_done)
        self.at(prefix); self.e('WAIT'); self.at(prefix_issue)
        self.e('HASH',8,Lanes.L0); self.e('STEP_NEXT',Lanes.L0)
        self.e('ADRS',Addr.WOTS_CURSOR); self.br(Cond.STEP_EQ_DIGIT,prefix,invert=True)
        self.at(prefix_done); self.e('WAIT'); self.nm(N.CAP0,N.L0)
        if not prefix_only:
            self.br(Cond.STEP_MORE,suffix_done,invert=True)
            # One fixed entry ISSUE avoids an uncovered jump into the loop.
            # The remaining suffix is still an explicit bounded image loop.
            self.e('HASH',8,Lanes.L0); self.e('STEP_NEXT',Lanes.L0)
            self.e('ADRS',Addr.WOTS_CURSOR)
            tail=self.label('suffix_tail')
            self.br(Cond.STEP_MORE,tail,invert=True)
            self.at(suffix); self.e('WAIT'); self.at(suffix_issue)
            self.e('HASH',8,Lanes.L0); self.e('STEP_NEXT',Lanes.L0)
            self.e('ADRS',Addr.WOTS_CURSOR); self.br(Cond.STEP_MORE,suffix)
            self.at(tail); self.e('WAIT'); self.at(suffix_done)
        self.e('EMIT',a=N.CAP0)
        if not prefix_only: self.store(Space.LIST,N.L0,Index.CHAIN0)
        self.e('CHAIN_NEXT',imm=1); self.br(Cond.CHAIN_MORE,chain)

    def verify(self):
        self.asm.label('verify'); self.e('INPUT',N.V0); self.mask(1); self.hash(3); self.e('PARSE')
        self.e('HEIGHT',Height.FORS); self.e('GROUP_INIT'); group=self.label('verify_fors')
        self.at(group); self.e('TARGET',Target.FORS); self.e('INPUT',N.L0)
        self.e('ADRS',Addr.FORS_TARGET); self.hash(5)
        self.e('NODE_BEGIN',NodeSource.TARGET,TreeKind.FORS); self.verify_auth(fors=True)
        self.store(Space.LIST,N.L0,Index.GROUP); self.e('GROUP_NEXT'); self.br(Cond.GROUP_MORE,group)
        self.e('ADRS',Addr.FORS_LIST); self.hash(11); self.nm(N.V2,N.L0)
        layer,chain,steps,finished=[self.label(x) for x in
            ('verify_layer','verify_chain','verify_steps','verify_endpoint')]
        self.at(layer); self.e('HEIGHT',Height.HT); self.e('TARGET',Target.LEAF)
        self.e('DIGITS'); self.e('CHAIN_INIT')
        self.at(chain); self.e('DIGIT_LOAD',Lanes.L0)
        self.e('STEP_INIT',Lanes.L0,StepSource.DIGIT); self.e('INPUT',N.L0)
        self.br(Cond.STEP_MORE,finished,invert=True)
        # A fixed first ISSUE avoids an uncovered entry jump. Subsequent
        # loopbacks run under the preceding Hash; head WAIT publishes its node
        # before the next ISSUE. The image still decides every suffix step.
        issue=self.label('verify_issue'); tail=self.label('verify_tail')
        self.e('ADRS',Addr.WOTS_LEAF)
        self.e('HASH',8,Lanes.L0); self.e('STEP_NEXT',Lanes.L0)
        self.e('ADRS',Addr.WOTS_LEAF); self.br(Cond.STEP_MORE,tail,invert=True)
        self.at(steps); self.e('WAIT'); self.at(issue)
        self.e('HASH',8,Lanes.L0); self.e('STEP_NEXT',Lanes.L0)
        self.e('ADRS',Addr.WOTS_LEAF); self.br(Cond.STEP_MORE,steps)
        self.at(tail); self.e('WAIT')
        self.at(finished); self.store(Space.LIST,N.L0,Index.CHAIN0)
        self.e('CHAIN_NEXT',imm=1); self.br(Cond.CHAIN_MORE,chain)
        self.e('ADRS',Addr.WOTS_LIST,ListLeaf.LEAF); self.hash(9)
        self.e('NODE_BEGIN',NodeSource.LEAF,TreeKind.HT); self.verify_auth()
        self.nm(N.V2,N.L0); done=self.label('verify_done'); self.br(Cond.FINAL_LAYER,done)
        self.e('TREE_NEXT'); self.e('LAYER_NEXT'); self.jump(layer)
        self.at(done); self.e('ROOT_COMPARE'); self.e('END')


class ChainCompiler(K1Compiler):
    """The image selects each WOTS chain; CHAIN owns only its bounded steps."""
    def wots_leaf_chains(self,*,capture=False,prefix_only=False):
        chain=self.label('macro_wots_chain')
        self.e('CHAIN_INIT');self.mask(1);self.at(chain)
        if capture: self.e('DIGIT_LOAD',Lanes.L0)
        mode=ChainMode.CAP_PREFIX if prefix_only else ChainMode.CAP_FULL if capture else ChainMode.FULL
        self.e('CHAIN',mode,Lanes.L0,ChainLeaf.CURSOR)
        if capture: self.e('EMIT',a=N.CAP0)
        if not prefix_only: self.store(Space.LIST,N.L0,Index.CHAIN0)
        self.e('CHAIN_NEXT',imm=1);self.br(Cond.CHAIN_MORE,chain)

    def verify(self):
        # Reuse the image's complete FORS and tree reconstruction. Only the
        # bounded WOTS suffix body is replaced; I/O and list traversal stay
        # visible micro-operations outside CHAIN.
        self.asm.label('verify');self.e('INPUT',N.V0);self.mask(1);self.hash(3);self.e('PARSE')
        self.e('HEIGHT',Height.FORS);self.e('GROUP_INIT');group=self.label('verify_fors')
        self.at(group);self.e('TARGET',Target.FORS);self.e('INPUT',N.L0)
        self.e('ADRS',Addr.FORS_TARGET);self.hash(5)
        self.e('NODE_BEGIN',NodeSource.TARGET,TreeKind.FORS);self.verify_auth(fors=True)
        self.store(Space.LIST,N.L0,Index.GROUP);self.e('GROUP_NEXT');self.br(Cond.GROUP_MORE,group)
        self.e('ADRS',Addr.FORS_LIST);self.hash(11);self.nm(N.V2,N.L0)
        layer,chain,done=[self.label(x) for x in ('verify_layer','verify_chain','verify_done')]
        self.at(layer);self.e('HEIGHT',Height.HT);self.e('TARGET',Target.LEAF)
        self.e('DIGITS');self.e('CHAIN_INIT');self.at(chain)
        self.e('DIGIT_LOAD',Lanes.L0);self.e('INPUT',N.L0)
        self.e('CHAIN',ChainMode.SUFFIX,Lanes.L0,ChainLeaf.LEAF)
        self.store(Space.LIST,N.L0,Index.CHAIN0)
        self.e('CHAIN_NEXT',imm=1);self.br(Cond.CHAIN_MORE,chain)
        self.e('ADRS',Addr.WOTS_LIST,ListLeaf.LEAF);self.hash(9)
        self.e('NODE_BEGIN',NodeSource.LEAF,TreeKind.HT);self.verify_auth()
        self.nm(N.V2,N.L0);self.br(Cond.FINAL_LAYER,done)
        self.e('TREE_NEXT');self.e('LAYER_NEXT');self.jump(layer)
        self.at(done);self.e('ROOT_COMPARE');self.e('END')


class TreeCompiler(ChainCompiler):
    """TREE owns one tree; the image still selects FORS groups and HT layers."""
    def wots_tree(self,*,signing,last_layer=False):
        self.e('TREE',TreeKind.HT,TreeMode.SIGN if signing else TreeMode.ROOT,
            TreeFlags.TOP_SHORTCUT if last_layer else 0)

    def fors_sign(self):
        group=self.label('tree_fors_group')
        self.e('GROUP_INIT');self.at(group);self.e('TARGET',Target.FORS)
        self.e('TREE',TreeKind.FORS,TreeMode.SIGN)
        self.store(Space.LIST,N.L0,Index.GROUP)
        self.e('GROUP_NEXT');self.br(Cond.GROUP_MORE,group)
        self.e('ADRS',Addr.FORS_LIST);self.mask(1);self.hash(11);self.nm(N.V2,N.L0)

    def verify(self):
        self.asm.label('verify');self.e('INPUT',N.V0);self.mask(1);self.hash(3);self.e('PARSE')
        self.e('GROUP_INIT');group=self.label('tree_verify_fors')
        self.at(group);self.e('TARGET',Target.FORS);self.e('TREE',TreeKind.FORS,TreeMode.VERIFY)
        self.store(Space.LIST,N.L0,Index.GROUP)
        self.e('GROUP_NEXT');self.br(Cond.GROUP_MORE,group)
        self.e('ADRS',Addr.FORS_LIST);self.mask(1);self.hash(11);self.nm(N.V2,N.L0)
        layer,done=[self.label(x) for x in ('tree_verify_layer','tree_verify_done')]
        self.at(layer);self.e('TARGET',Target.LEAF);self.e('DIGITS')
        self.e('TREE',TreeKind.HT,TreeMode.VERIFY);self.nm(N.V2,N.L0)
        self.br(Cond.FINAL_LAYER,done)
        self.e('TREE_NEXT');self.e('LAYER_NEXT');self.jump(layer)
        self.at(done);self.e('ROOT_COMPARE');self.e('END')


def _image(p,asm,entries,base=None):
    asm.schedule_metadata_overlap(); words=asm.assemble(); desc=list(base.descriptors) if base else [0]*32
    entries=[asm.labels[x] for x in entries] if entries else [0,0,0]
    desc[0]=(MAGIC<<32)|(ABI<<27)|(entries[0]<<18)|(entries[1]<<9)|entries[2]
    if not base:
        desc[1]=PROFILE_CODES[p.name]
        recipes={2:(3,0,1,p.n,(2*p.n+87)//136+1),3:(4,0,1,p.m,(3*p.n+87)//136+1),
            4:(1,6,1,p.n,1),5:(2,3,1,p.n,1),6:(2,3,2,p.n,1),7:(1,5,1,p.n,1),8:(2,0,1,p.n,1),
            9:(12,1,p.chains,p.n,(p.n+32+p.n*p.chains)//136+1),10:(2,2,2,p.n,1),
            11:(12,4,p.k,p.n,(p.n+32+p.n*p.k)//136+1)}
        for rid,(shape,domain,arity,out,blocks) in recipes.items():
            desc[rid]=(shape<<56)|(domain<<48)|(arity<<40)|(out<<32)|(blocks<<24)
        desc[13]=p.keygen_bytes|(p.signature_bytes<<32)
        desc[14]=sum(x<<(8*i) for i,x in enumerate((p.n,p.hp,p.d,p.k,p.a,p.m,p.h,p.chains)))
    desc[12]=len(words)
    return MicroImage(words+(0,)*(512-len(words)),tuple(desc)).validate()


def _compile_slh(name,*,serial=False,chain_macros=True,tree_macros=True):
    p=get_profile(name)
    if name not in PROFILE_CODES: raise ValueError('SLH-only microprogram')
    c=Compiler(p,serial=True) if serial else (TreeCompiler(p) if tree_macros and chain_macros
        else ChainCompiler(p) if chain_macros else K1Compiler(p))
    c.keygen(); c.sign(); c.verify()
    return _image(p,c.asm,('keygen','sign','verify'))


def compile_test_tree(name='slh_128f',height=3,*,level_order=False):
    """Two loop-based image algorithms, with no expanded Hash task trajectory."""
    if not 1<=height<=4: raise ValueError('test tree height must be 1..4')
    p=get_profile(name); c=Compiler(p); c.e('HEIGHT',Height.LITERAL,imm=height)
    c.e('CURSOR_INIT'); c.mask(1); leaves=c.label('test_leaves'); c.at(leaves)
    c.e('ADRS',Addr.FORS_CURSOR); c.hash(4); c.hash(5)
    if level_order:
        c.store(Space.LIST,N.L0,Index.CURSOR)
    else:
        c.push(fors=True,auth=False)
    c.e('CURSOR_NEXT',imm=1); c.br(Cond.CURSOR_MORE,leaves)
    if level_order:
        c.e('REDUCE_INIT',TreeKind.FORS); row=c.label('test_row'); pair=c.label('test_pair')
        c.at(row); c.e('REDUCE_NEXT',ReduceNext.LEVEL); c.at(pair)
        c.load(N.L0,Space.LIST,Index.REDUCE_LEFT); c.load(N.RIGHT,Space.LIST,Index.REDUCE_RIGHT)
        c.e('ADRS',Addr.REDUCE_NODE,TreeKind.FORS); c.hash(6)
        c.store(Space.LIST,N.L0,Index.REDUCE_OUT)
        c.e('REDUCE_NEXT',ReduceNext.INDEX); c.br(Cond.REDUCE_MORE,pair)
        c.br(Cond.REDUCE_AGAIN,row)
    for _ in range(6): c.e('EMIT',a=N.L0)
    c.e('END')
    return _image(p,c.asm,None,compile_micro(name))


class StatefulCompiler(Compiler):
    """Standard XMSS/LMS: all chain, L-tree and tree loops live in image."""
    def __init__(self,profile,chain_unroll=1):
        super().__init__(profile,serial=True); self.chain_unroll=chain_unroll
        self.xmss=profile.family=='xmss'

    def hash(self,recipe):
        self.e('HASH',recipe,Lanes.L0); self.e('WAIT')

    def chain_f(self,*,wait=True):
        if self.xmss:
            self.nm(N.NODE,N.L0)
            self.hash(4); self.nm(N.V2,N.L0)
            self.hash(5); self.nm(N.RIGHT,N.L0)
            self.e('XMSS_MASK',0)
        self.e('HASH',8,Lanes.L0)
        if wait: self.e('WAIT')

    def parent_h(self,*,preloaded=False,wait=True):
        if self.xmss:
            if not preloaded: self.nm(N.NODE,N.L0); self.nm(N.TMPNODE,N.RIGHT)
            self.hash(4); self.nm(N.V2,N.L0)
            self.hash(5); self.nm(N.RIGHT,N.L0); self.e('XMSS_MASK',0)
            self.nm(N.NODE,N.L0)
            self.hash(6); self.nm(N.RIGHT,N.L0); self.e('XMSS_MASK',1)
            self.nm(N.RIGHT,N.L0); self.nm(N.L0,N.NODE)
        self.e('HASH',10,Lanes.L0)
        if wait: self.e('WAIT')

    def leaf_compress(self,*,verify=False):
        if self.xmss:
            row,pair,odd,stored,done=[self.label(x) for x in ('ltree_row','ltree_pair','ltree_odd','ltree_stored','ltree_done')]
            self.e('REDUCE_INIT',TreeKind.LTREE); self.at(row); self.at(pair)
            self.load(N.NODE,Space.LIST,Index.REDUCE_LEFT)
            self.br(Cond.LTREE_PAIR,odd,invert=True)
            self.load(N.TMPNODE,Space.LIST,Index.REDUCE_RIGHT)
            self.e('ADRS',Addr.LTREE_LEAF if verify else Addr.LTREE_CURSOR)
            self.parent_h(preloaded=True)
            self.at(stored)
            self.store(Space.LIST,N.L0,Index.REDUCE_OUT)
            self.e('REDUCE_NEXT',ReduceNext.INDEX); self.br(Cond.LTREE_MORE,pair)
            self.e('REDUCE_NEXT',ReduceNext.LTREE_LEVEL); self.br(Cond.REDUCE_AGAIN,row)
            self.jump(done)
            self.at(odd); self.nm(N.L0,N.NODE); self.jump(stored); self.at(done)
        else:
            self.e('ADRS',Addr.WOTS_LIST,ListLeaf.LEAF if verify else ListLeaf.CURSOR)
            self.hash(9)
            self.e('NODE_BEGIN',NodeSource.TARGET if verify else NodeSource.CURSOR,TreeKind.HT)
            self.e('ADRS',Addr.HT_NODE); self.hash(11)

    def chains_fast(self):
        chain,step=[self.label(x) for x in ("explicit_stateful_chain","explicit_stateful_step")]
        self.e('CHAIN_INIT');self.mask(1);self.at(chain)
        self.e('STEP_INIT',Lanes.L0,StepSource.ZERO);self.e('ADRS',Addr.WOTS_CURSOR);self.hash(7)
        self.at(step);self.chain_f();self.e('STEP_NEXT',Lanes.L0);self.e('ADRS',Addr.WOTS_CURSOR)
        self.br(Cond.STEP_MORE,step);self.store(Space.LIST,N.L0,Index.CHAIN0)
        self.e('CHAIN_NEXT',imm=1);self.br(Cond.CHAIN_MORE,chain)

    def chains(self,*,signing=False):
        if not signing: return self.chains_fast()
        chain,step,done=[self.label(x) for x in ('stateful_chain','stateful_step','stateful_endpoint')]
        self.e('CHAIN_INIT'); self.at(chain); self.e('STEP_INIT',Lanes.L0,StepSource.ZERO)
        self.e('ADRS',Addr.WOTS_CURSOR); self.e('DIGIT_LOAD',Lanes.L0); self.hash(7)
        self.at(step)
        no_capture=self.label('not_capture')
        self.br(Cond.STEP_EQ_DIGIT,no_capture,invert=True); self.e('EMIT',a=N.L0); self.at(no_capture)
        self.br(Cond.STEP_MORE,done,invert=True)
        self.e('ADRS',Addr.WOTS_CURSOR); self.chain_f(); self.e('STEP_NEXT',Lanes.L0)
        self.jump(step); self.at(done)
        self.store(Space.LIST,N.L0,Index.CHAIN0)
        self.e('CHAIN_NEXT',imm=1); self.br(Cond.CHAIN_MORE,chain)

    def push_stateful(self,*,signing=False):
        if not signing:
            merge_wait,tail,save=[self.label(x) for x in
                ('stateful_merge_wait','stateful_merge_tail','stateful_save')]
            self.e('NODE_BEGIN',NodeSource.CURSOR,TreeKind.HT)
            self.br(Cond.INDEX_ODD,save,invert=True)
            def parent():
                if self.xmss:
                    self.nm(N.TMPNODE,N.L0); self.load(N.NODE,Space.STACK)
                else:
                    self.nm(N.RIGHT,N.L0); self.load(N.L0,Space.STACK)
                self.e('NODE_PARENT'); self.e('ADRS',Addr.HT_NODE)
                self.parent_h(preloaded=self.xmss,wait=False)
            # A single entry body avoids an uncovered jump into a WAIT head.
            # Remaining parents are generated by a visible conditional loop.
            parent(); self.br(Cond.INDEX_ODD,tail,invert=True)
            self.at(merge_wait); self.e('WAIT'); parent()
            self.br(Cond.INDEX_ODD,merge_wait)
            self.at(tail); self.e('WAIT')
            self.at(save); self.store(Space.STACK,N.L0)
            return
        merge,save=[self.label(x) for x in ('stateful_merge','stateful_save')]
        self.e('NODE_BEGIN',NodeSource.CURSOR,TreeKind.HT)
        def capture_auth():
            if signing:
                skip=self.label('not_auth'); self.br(Cond.AUTH_MATCH,skip,invert=True)
                self.store(Space.AUTH,N.L0); self.at(skip)
        capture_auth(); self.br(Cond.INDEX_ODD,save,invert=True)
        self.at(merge)
        if self.xmss:
            self.nm(N.TMPNODE,N.L0); self.load(N.NODE,Space.STACK)
        else:
            self.nm(N.RIGHT,N.L0); self.load(N.L0,Space.STACK)
        self.e('NODE_PARENT'); self.e('ADRS',Addr.HT_NODE); self.parent_h(preloaded=self.xmss)
        capture_auth(); self.br(Cond.INDEX_ODD,merge)
        self.at(save); self.store(Space.STACK,N.L0)

    def tree(self,*,signing=False):
        leaves=self.label('stateful_leaves')
        self.e('HEIGHT',Height.HT); self.e('CURSOR_INIT'); self.at(leaves)
        if signing:
            selected,compress=[self.label(x) for x in ('stateful_selected_leaf','stateful_compress')]
            # Only the selected leaf requires DIGIT/CAP decisions. All other
            # leaves use the same explicit full-chain image loop as Keygen.
            self.br(Cond.TARGET_LEAF,selected)
            self.chains_fast(); self.jump(compress)
            self.at(selected); self.chains(signing=True); self.at(compress)
        else: self.chains_fast()
        self.leaf_compress(); self.push_stateful(signing=signing)
        self.e('CURSOR_NEXT',imm=1); self.br(Cond.CURSOR_MORE,leaves)
        if signing: self.emit_auth()

    def keygen(self):
        self.asm.label('keygen'); self.mask(1); self.tree(); self.e('EMIT',a=N.L0); self.e('END')

    def sign(self):
        self.asm.label('sign'); self.mask(1)
        if self.xmss: self.hash(2); self.nm(N.V0,N.L0)
        else: self.nm(N.V0,N.RANDOM)
        self.e('EMIT',a=N.V0); self.hash(3); self.nm(N.V2,N.L0); self.e('DIGITS')
        self.e('TARGET',Target.LEAF); self.tree(signing=True); self.e('END')

    def verify(self):
        self.asm.label('verify'); self.mask(1); self.e('INPUT',N.V0)
        self.hash(3); self.nm(N.V2,N.L0); self.e('DIGITS')
        self.e('HEIGHT',Height.HT); self.e('TARGET',Target.LEAF); self.e('CHAIN_INIT')
        chain,step,done=[self.label(x) for x in ('stateful_verify_chain','stateful_verify_step','stateful_verify_endpoint')]
        self.at(chain); self.e('DIGIT_LOAD',Lanes.L0); self.e('STEP_INIT',Lanes.L0,StepSource.DIGIT)
        self.e('INPUT',N.L0); self.at(step); self.br(Cond.STEP_MORE,done,invert=True)
        self.e('ADRS',Addr.WOTS_LEAF); self.chain_f(); self.e('STEP_NEXT',Lanes.L0); self.jump(step)
        self.at(done); self.store(Space.LIST,N.L0,Index.CHAIN0)
        self.e('CHAIN_NEXT',imm=1); self.br(Cond.CHAIN_MORE,chain)
        self.leaf_compress(verify=True); self.e('NODE_BEGIN',NodeSource.TARGET,TreeKind.HT)
        auth,odd,ready=[self.label(x) for x in ('stateful_verify_auth','stateful_verify_odd','stateful_verify_parent')]
        self.at(auth); self.br(Cond.INDEX_ODD,odd)
        self.e('INPUT',N.RIGHT); self.jump(ready)
        self.at(odd); self.nm(N.RIGHT,N.L0); self.e('INPUT',N.L0)
        self.at(ready); self.e('NODE_PARENT'); self.e('ADRS',Addr.HT_NODE); self.parent_h()
        self.br(Cond.LEVEL_MORE,auth); self.nm(N.V2,N.L0); self.e('ROOT_COMPARE'); self.e('END')


def _stateful_image(p,c):
    c.asm.schedule_metadata_overlap(); words=c.asm.assemble(); desc=[0]*32
    entries=[c.asm.labels[x] for x in ('keygen','sign','verify')]
    desc[0]=(MAGIC<<32)|(ABI<<27)|(entries[0]<<18)|(entries[1]<<9)|entries[2]
    desc[1]=PROFILE_CODES[p.name]
    if p.family=='xmss':
        recipes={2:(5,1,1,1),3:(8,0,1,2),4:(5,2,1,1),5:(5,3,1,1),6:(5,4,1,1),
                 7:(5,0,1,1),8:(6,0,1,1),9:(6,0,1,1),10:(7,0,2,1),11:(6,0,1,1)}
    else:
        recipes={2:(11,0,1,2),3:(11,0,1,2),4:(9,0,1,1),5:(10,0,1,1),6:(14,0,2,1),
                 7:(9,0,1,1),8:(10,0,1,1),9:(15,0,67,16),10:(14,0,2,1),11:(13,0,1,1)}
    for rid,(shape,domain,arity,blocks) in recipes.items():
        desc[rid]=(shape<<56)|(domain<<48)|(arity<<40)|(32<<32)|(blocks<<24)
    desc[12]=len(words); desc[13]=p.hardware_keygen_bytes|(p.hardware_signature_bytes<<32)
    desc[14]=sum(x<<(8*i) for i,x in enumerate((p.n,p.hp,p.d,p.k,p.a,p.m,p.h,p.chains)))
    return MicroImage(words+(0,)*(512-len(words)),tuple(desc)).validate()


class MacroStatefulCompiler(StatefulCompiler):
    """Only a single chain is a macro; all reductions remain explicit image loops."""
    def chains_fast(self): return self.chains(signing=False)
    def chains(self,*,signing=False):
        chain=self.label('macro_stateful_chain');self.e('CHAIN_INIT');self.mask(1);self.at(chain)
        if signing:self.e('DIGIT_LOAD',Lanes.L0)
        self.e('CHAIN',ChainMode.CAP_FULL if signing else ChainMode.FULL,Lanes.L0,ChainLeaf.CURSOR)
        if signing:self.e('EMIT',a=N.CAP0)
        self.store(Space.LIST,N.L0,Index.CHAIN0);self.e('CHAIN_NEXT',imm=1);self.br(Cond.CHAIN_MORE,chain)
    def verify(self):
        self.asm.label('verify');self.mask(1);self.e('INPUT',N.V0);self.hash(3)
        self.nm(N.V2,N.L0);self.e('DIGITS');self.e('HEIGHT',Height.HT);self.e('TARGET',Target.LEAF)
        self.e('CHAIN_INIT');chain=self.label('macro_stateful_verify_chain');self.at(chain)
        self.e('DIGIT_LOAD',Lanes.L0);self.e('INPUT',N.L0);self.e('CHAIN',ChainMode.SUFFIX,Lanes.L0,ChainLeaf.LEAF)
        self.store(Space.LIST,N.L0,Index.CHAIN0);self.e('CHAIN_NEXT',imm=1);self.br(Cond.CHAIN_MORE,chain)
        self.leaf_compress(verify=True);self.e('NODE_BEGIN',NodeSource.TARGET,TreeKind.HT)
        auth,odd,ready=[self.label(x) for x in ('macro_auth','macro_odd','macro_parent')]
        self.at(auth);self.br(Cond.INDEX_ODD,odd);self.e('INPUT',N.RIGHT);self.jump(ready)
        self.at(odd);self.nm(N.RIGHT,N.L0);self.e('INPUT',N.L0);self.at(ready)
        self.e('NODE_PARENT');self.e('ADRS',Addr.HT_NODE);self.parent_h();self.br(Cond.LEVEL_MORE,auth)
        self.nm(N.V2,N.L0);self.e('ROOT_COMPARE');self.e('END')

class TreeStatefulCompiler(MacroStatefulCompiler):
    """One complete stateful tree per TREE instruction, never one whole Job."""
    def tree(self,*,signing=False):
        self.e('HEIGHT',Height.HT);self.e('TREE',TreeKind.HT,TreeMode.SIGN if signing else TreeMode.ROOT)
    def verify(self):
        self.asm.label('verify');self.mask(1);self.e('INPUT',N.V0);self.hash(3)
        self.nm(N.V2,N.L0);self.e('DIGITS');self.e('TARGET',Target.LEAF);self.e('HEIGHT',Height.HT)
        self.e('TREE',TreeKind.HT,TreeMode.VERIFY);self.nm(N.V2,N.L0);self.e('ROOT_COMPARE');self.e('END')


def compile_micro(name,*,serial=False,chain_macros=True,tree_macros=True,hash_backend="shake"):
    p=get_profile(name,hash_backend)
    if p.family=="slh": return _compile_slh(p.name,serial=serial,chain_macros=chain_macros,tree_macros=tree_macros)
    cls=TreeStatefulCompiler if tree_macros and not serial else MacroStatefulCompiler if chain_macros and not serial else StatefulCompiler
    c=cls(p);c.keygen();c.sign();c.verify();return _stateful_image(p,c)

compile_image=compile_micro
Image=MicroImage
