#!/usr/bin/env python3
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
"""ABI 4 functional, programmability and typed-state boundary gates."""
from copy import deepcopy
from dataclasses import asdict, replace
import hashlib
from pathlib import Path
import tempfile
import unittest

from model.microcode import (ABI, MAGIC, Addr, Assembler, ChainLeaf, ChainMode, Cond, Height, Index,
    Instruction, Lanes, Mask, MicroImage, N, NodeSource, Op, Space, StepSource,
    TreeKind, overlap_safe)
from model.mHBS import K1Compiler, compile_micro, compile_test_tree
from model.executor import MicroMachine
from model.profiles import SLH_NAMES, get_profile
from model.reference import slh_dsa
from model.vectors import default_job


def synthetic_image(code,base=None):
    base=base or compile_micro('slh_128f'); words=code.assemble(); desc=list(base.descriptors)
    desc[0]=(MAGIC<<32)|(ABI<<27); desc[12]=len(words)
    return MicroImage(words+(0,)*(512-len(words)),tuple(desc)).validate()


def finish(a,node=N.ZERO):
    for _ in range(6): a.emit(Op.EMIT,a=node)
    a.emit(Op.END)


class MicroProgramTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.job,cls.message=default_job('slh_128f'); cls.image=compile_micro('slh_128f')
        cls.sk,cls.pk=slh_dsa.keygen_internal(slh_dsa.SLH_DSA_SHAKE_128F,
            cls.job.secret,cls.job.prf,cls.job.public)
        cls.root=cls.pk[16:]
        cls.signature=slh_dsa.sign_internal(slh_dsa.SLH_DSA_SHAKE_128F,cls.message,cls.sk,cls.job.random)

    def machine(self,image=None,operation=0,signature=b'',**kw):
        return MicroMachine(image or self.image,self.job,self.root,
            self.message if operation else b'',operation,signature=signature,**kw)

    def test_all_profiles_fit_and_roundtrip(self):
        for name in SLH_NAMES:
            for serial in (False,True):
                with self.subTest(name=name,serial=serial):
                    image=compile_micro(name,serial=serial)
                    self.assertLessEqual(image.used,512); self.assertEqual(len(set(image.entries)),3)
                    self.assertIn('HASH',image.disassemble()); self.assertIn('NODE_PARENT' if serial else 'TREE',image.disassemble())
                    self.assertFalse(hasattr(Op,'ADD')); self.assertFalse(hasattr(Op,'MOV'))
                    with tempfile.TemporaryDirectory() as folder:
                        image.write(folder); self.assertEqual(MicroImage.read(folder),image)
                        self.assertEqual(len((Path(folder)/'program.mem').read_text().splitlines()),512)

    def test_keygen_sign_verify_and_counts(self):
        for op,expected,counts in ((0,self.sk+self.pk,(4495,4527)),
                                  (1,self.signature,(104937,105641)),(2,True,(6441,6533))):
            with self.subTest(operation=op):
                m=self.machine(operation=op,signature=self.signature if op==2 else b'')
                issue=m._issue; masks=[]
                def onehot_issue(recipe,mask):
                    masks.append(mask); return issue(recipe,mask)
                m._issue=onehot_issue
                self.assertEqual(m.run(),expected)
                self.assertEqual((m.hash_count,m.permutation_count),counts)
                self.assertTrue(all(mask in (1,2) for mask in masks),
                    'the default K1 image must issue exactly one Hash at a time')
                self.assertEqual(set(masks),set() if op==0 else {1})
                self.assertEqual((m.macro_count,m.macro_hashes),(0,0))
                self.assertGreater(m.tree_count,0)
                self.assertGreater(m.tree_chains,0)
                self.assertLessEqual(m.tree_hashes,m.hash_count)
                self.assertFalse(hasattr(m,'scalars'))
                with self.assertRaisesRegex(ValueError,'halted'): m.run()

    def test_serial_image_preserves_signature_and_verify(self):
        image=compile_micro('slh_128f',serial=True)
        self.assertNotEqual(image.program,self.image.program)
        sign=self.machine(image,operation=1); self.assertEqual(sign.run(),self.signature)
        self.assertEqual(sign.hash_count,104937)
        verify=self.machine(image,operation=2,signature=self.signature)
        self.assertTrue(verify.run()); self.assertEqual(verify.hash_count,6441)
        self.assertLessEqual(max(verify.ctx.step0,verify.ctx.step1),15)

    def test_explicit_sign_reads_digits_only_for_selected_leaf(self):
        m=self.machine(compile_micro('slh_128f',chain_macros=False),operation=1); code=m.decoded; reads=[]; captures=[]
        class ObserveCode:
            def __len__(self): return len(code)
            def __getitem__(self,pc):
                op,d,a,_,_=code[pc]
                if op==Op.DIGIT_LOAD: reads.append((m.ctx.cursor,m.ctx.target))
                if op==Op.NMOV and d==N.CAP0 and m.digits:
                    captures.append((m.ctx.cursor,m.ctx.target,m.ctx.step0,m.ctx.digit0))
                return code[pc]
        m.decoded=ObserveCode(); self.assertEqual(m.run(),self.signature)
        p=get_profile('slh_128f')
        self.assertEqual(len(reads),p.chains*p.d)
        self.assertTrue(all(leaf==target for leaf,target in reads))
        self.assertEqual(len(captures),p.chains*p.d)
        self.assertTrue(all(leaf==target and step==digit
            for leaf,target,step,digit in captures))

    def test_capture_split_all_digits_and_odd_chain_tail(self):
        class CapturesAtEnd(K1Compiler):
            # Keep the complete chain algorithm, then expose its last CAP as
            # six nodes to satisfy the ordinary Keygen output contract.
            def e(self,op,d=0,a=0,b=0,imm=0):
                if op!='EMIT': super().e(op,d,a,b,imm)
        for name in ('slh_128f','slh_192f','slh_256f'):
            p=get_profile(name); job,_=default_job(name)
            self.assertEqual(p.chains%2,1)
            for prefix_only in (False,True):
                c=CapturesAtEnd(p); c.e('DIGITS')
                c.wots_leaf_chains(capture=True,prefix_only=prefix_only)
                finish(c.asm,N.CAP0); c.asm.schedule_metadata_overlap()
                image=synthetic_image(c.asm,compile_micro(name))
                for digit in range(16):
                    with self.subTest(profile=name,prefix_only=prefix_only,digit=digit):
                        # All ff has checksum zero; reducing one payload nibble
                        # makes the final checksum chain's digit exactly digit.
                        value=bytes([((15-digit)<<4)|15])+bytes([255])*(p.n-1)
                        m=MicroMachine(image,job,bytes(p.n),b'',0); m.nodes[N.V2]=value
                        actual=m.run()
                        def address(domain,step):
                            return b''.join(x.to_bytes(4,'big') for x in
                                (0,0,0,0,domain,0,p.chains-1,step))
                        # Independent one-chain oracle: no microcode or VM
                        # helper decides the captured node or endpoint.
                        endpoint=hashlib.shake_256(job.public+address(5,0)+job.secret).digest(p.n)
                        captured=endpoint if digit==0 else None
                        for step in range(15):
                            endpoint=hashlib.shake_256(job.public+address(0,step)+endpoint).digest(p.n)
                            if step+1==digit: captured=endpoint
                        self.assertEqual(actual,captured*6)
                        self.assertEqual((m.ctx.chain,m.ctx.digit0),(p.chains,digit))
                        self.assertEqual(m.ctx.step0,digit if prefix_only else 15)
                        self.assertEqual(m.hash_count,p.chains+(30*p.n if prefix_only else 15*p.chains))
                        self.assertEqual(m.permutation_count,m.hash_count)
                        if not prefix_only:
                            self.assertEqual(m.spaces[Space.LIST][p.chains-1],endpoint)

    def test_final_selected_leaf_does_not_write_dead_wots_endpoints(self):
        m=self.machine(compile_micro('slh_128f',tree_macros=False),operation=1); code=m.decoded; stores=[]
        class ObserveCode:
            def __len__(self): return len(code)
            def __getitem__(self,pc):
                op,d,a,b,_=code[pc]
                if op==Op.STORE and d==Space.LIST and b in (Index.CHAIN0,Index.CHAIN1):
                    stores.append((m.ctx.layer,m.ctx.cursor,m.ctx.target))
                return code[pc]
        m.decoded=ObserveCode(); self.assertEqual(m.run(),self.signature)
        self.assertEqual(len(stores),(22*8-1)*35)
        self.assertFalse(any(layer==21 and leaf==target for layer,leaf,target in stores))

    def test_verify_tampering(self):
        for position in (0,16,16*7,len(self.signature)-1):
            changed=bytearray(self.signature); changed[position]^=1
            self.assertFalse(self.machine(operation=2,signature=bytes(changed)).run())
        changed=bytes([self.message[0]^1])+self.message[1:]
        self.assertFalse(MicroMachine(self.image,self.job,self.root,changed,2,signature=self.signature).run())

    def test_small_tree_schedules_are_bounded_loop_programs(self):
        sizes=[]
        for height in range(1,5):
            a=compile_test_tree(height=height); b=compile_test_tree(height=height,level_order=True)
            self.assertNotEqual(a.program,b.program); sizes.append((a.used,b.used))
            left=self.machine(a,record_tasks=True); right=self.machine(b,record_tasks=True)
            self.assertEqual(left.run(),right.run())
            self.assertEqual(left.hash_count,3*(1<<height)-1)
            self.assertEqual(sorted(left.task_trace),sorted(right.task_trace))
        self.assertEqual(len(set(sizes)),1,'image size must not expand with the Hash trajectory')

    def test_default_program_contains_safe_overlap(self):
        image=compile_micro('slh_128f',tree_macros=False)
        instructions=[Instruction.decode(w) for w in image.program[:image.used]]
        self.assertTrue(any(left.op==Op.HASH and overlap_safe(right)
            for left,right in zip(instructions,instructions[1:])))

    def test_overlap_preserves_symbolic_and_numeric_targets(self):
        for numeric in (False,True):
            a=Assembler(); a.emit(Op.HEIGHT,Height.LITERAL,imm=1); a.emit(Op.MASK,imm=1)
            a.emit(Op.HASH,4); a.emit(Op.WAIT)
            if not numeric: a.label('again')
            a.emit(Op.CURSOR_NEXT,imm=1); a.branch(Cond.CURSOR_MORE,4 if numeric else 'again')
            finish(a,N.L0); a.schedule_metadata_overlap()
            m=self.machine(synthetic_image(a)); m.run(); self.assertEqual(m.ctx.cursor,2)

    def test_overlap_snapshots_addresses_and_retains_inactive_lane(self):
        a=Assembler(); a.emit(Op.HEIGHT,Height.LITERAL,imm=3); a.emit(Op.MASK,imm=1)
        a.emit(Op.ADRS,Addr.FORS_CURSOR); a.emit(Op.HASH,4)
        a.emit(Op.CURSOR_NEXT,imm=2); a.emit(Op.ADRS,Addr.FORS_CURSOR)
        a.emit(Op.MASK,imm=3); a.branch(Cond.CURSOR_MORE,'pending_join')
        a.emit(Op.CURSOR_NEXT,imm=2); a.label('pending_join'); a.emit(Op.WAIT); finish(a,N.L0)
        m=self.machine(synthetic_image(a),record_tasks=True); m.nodes[N.L1]=bytes([0x7b])*16
        m.run(); self.assertEqual(m.hash_count,1); self.assertEqual(m.task_trace[0][5],0)
        self.assertEqual(m.ctx.addr_b0,2); self.assertEqual(m.nodes[N.L1],bytes([0x7b])*16)

    def test_one_physical_lane_can_target_the_other_logical_result(self):
        a=Assembler(); a.emit(Op.HEIGHT,Height.LITERAL,imm=3); a.emit(Op.MASK,imm=3)
        a.emit(Op.ADRS,Addr.FORS_CURSOR); a.emit(Op.HASH,4,Lanes.L1)
        a.emit(Op.CURSOR_NEXT,imm=2); a.emit(Op.ADRS,Addr.FORS_CURSOR)
        a.emit(Op.WAIT); finish(a,N.L1)
        m=self.machine(synthetic_image(a),record_tasks=True); sentinel=bytes([0x7b])*16
        m.nodes[N.L0]=sentinel; m.run()
        self.assertEqual(m.hash_count,1); self.assertEqual(m.permutation_count,1)
        self.assertEqual(m.task_trace[0][5],1,'Hash must use the selected slot and its captured address')
        self.assertEqual(m.ctx.addr_b1,3); self.assertEqual(m.nodes[N.L0],sentinel)
        self.assertEqual(bytes(m.output),m.nodes[N.L1]*6)

    def test_k1_rejects_paired_hash_without_mutating_hash_or_node_state(self):
        a=Assembler(); a.emit(Op.MASK,imm=3); a.emit(Op.HASH,4); a.emit(Op.WAIT); finish(a)
        m=self.machine(synthetic_image(a)); expected=asdict(m.ctx); expected['mask']=3
        nodes=deepcopy(m.nodes); storage=deepcopy(m.spaces)
        with self.assertRaisesRegex(ValueError,'K1U1.*exactly one'): m.run()
        self.assertEqual(asdict(m.ctx),expected); self.assertEqual(m.nodes,nodes)
        self.assertEqual(m.spaces,storage); self.assertIsNone(m.pending)
        self.assertEqual((m.hash_count,m.permutation_count),(0,0))

    def test_reject_legacy_abi_and_reserved_or_untyped_operands(self):
        mutations=[replace(self.image,program=self.image.program[:-1])]
        legacy=list(self.image.descriptors);legacy[0]=(legacy[0]&~(31<<27))|(2<<27)
        mutations.append(replace(self.image,descriptors=tuple(legacy)))
        for slot,value in ((0,(self.image.descriptors[0]&~(31<<27))|(1<<27)),(12,513),(15,1)):
            d=list(self.image.descriptors); d[slot]=value; mutations.append(replace(self.image,descriptors=tuple(d)))
        for ins in (Instruction(Op.LAYER_INIT,2),Instruction(Op.NMOV,N.SECRET,N.L0),
                    Instruction(Op.STEP_NEXT,b=1),Instruction(Op.ADRS,Addr.FORS_LIST,a=1),
                    Instruction(Op.LOAD,N.L0,Space.LIST,Index.LEVEL),
                    Instruction(Op.LOAD,N.L0,Space.STACK,Index.CHAIN0),
                    Instruction(Op.JMP,imm=self.image.used)):
            p=list(self.image.program); p[0]=ins.encode(); mutations.append(replace(self.image,program=tuple(p)))
        for invalid in mutations:
            with self.subTest(invalid=invalid.program[:1]):
                with self.assertRaises(ValueError): invalid.validate()

    def test_chain_all_modes_digits_sizes_and_logical_slots(self):
        for name in ('slh_128f','slh_192f','slh_256f'):
            p=get_profile(name);job,_=default_job(name)
            for slot in (0,1):
                for digit in range(16):
                    for mode in ChainMode:
                        with self.subTest(profile=name,slot=slot,digit=digit,mode=mode):
                            m=MicroMachine(compile_micro(name),job,bytes(p.n),b'',0,record_tasks=True)
                            m.ctx.mask=1<<slot;m.ctx.chain=4;m.ctx.cursor=9;m.ctx.leaf=11
                            m.ctx.tree=0xfedcba9876543210;m.ctx.layer=3
                            m.ctx.digit0=m.ctx.digit1=digit;m.digits=[0]*(2*p.n+3);m.digit_valid=1<<slot
                            m.nodes[N.L0+slot]=bytes([0xa5])*p.n
                            m.nodes[N.CAP0+slot]=bytes([0x7b])*p.n
                            before_ctx=asdict(m.ctx);before_nodes=list(m.nodes)
                            def hashed(domain,step,value):
                                adrs=b''.join(x.to_bytes(4,'big') for x in
                                    (3,0,0xfedcba98,0x76543210,domain,11,4+slot,step))
                                return hashlib.shake_256(job.public+adrs+value).digest(p.n)
                            value=before_nodes[N.L0+slot] if mode==ChainMode.SUFFIX else hashed(5,0,job.secret)
                            cap=value if digit==0 and mode in (ChainMode.CAP_FULL,ChainMode.CAP_PREFIX) else before_nodes[N.CAP0+slot]
                            start=digit if mode==ChainMode.SUFFIX else 0
                            end=digit if mode==ChainMode.CAP_PREFIX else 15
                            for step in range(start,end):
                                value=hashed(0,step,value)
                                if step+1==digit and mode in (ChainMode.CAP_FULL,ChainMode.CAP_PREFIX):cap=value
                            m._chain(mode,Lanes.CURRENT,ChainLeaf.LEAF)
                            expected_nodes=list(before_nodes);expected_nodes[N.L0+slot]=value
                            expected_nodes[N.CAP0+slot]=cap
                            self.assertEqual(m.nodes,expected_nodes)
                            before_ctx['step'+str(slot)]=end;self.assertEqual(asdict(m.ctx),before_ctx)
                            self.assertEqual(m.hash_count,(mode!=ChainMode.SUFFIX)+end-start)
                            self.assertEqual(m.permutation_count,m.hash_count)
                            self.assertEqual(len(m.task_trace),m.hash_count)

    def test_chain_faults_validate_before_work_and_commit(self):
        for mutation in ('mask0','mask3','last_slot','wide_chain','cursor','digit','prf','f'):
            m=self.machine(record_tasks=True);m.ctx.mask=1;m.ctx.cursor=7
            m.ctx.chain=1;m.ctx.digit0=5;m.digits=[0]*35;m.digit_valid=1
            if mutation=='mask0':m.ctx.mask=0
            if mutation=='mask3':m.ctx.mask=3
            if mutation=='last_slot':m.ctx.mask=2;m.ctx.chain=m.chains-1;m.digit_valid=2
            if mutation=='wide_chain':m.ctx.mask=2;m.ctx.chain=127;m.digit_valid=2
            if mutation=='cursor':m.ctx.cursor=1024
            if mutation=='digit':m.digit_valid=0
            if mutation in ('prf','f'):
                desc=list(m.image.descriptors);desc[7 if mutation=='prf' else 8]^=1<<48
                m.image=replace(m.image,descriptors=tuple(desc))
            before=(asdict(m.ctx),list(m.nodes),deepcopy(m.spaces))
            with self.subTest(mutation=mutation),self.assertRaises(ValueError):
                m._chain(ChainMode.CAP_FULL,Lanes.CURRENT,ChainLeaf.CURSOR)
            self.assertEqual((asdict(m.ctx),m.nodes,m.spaces),before)
            self.assertEqual((m.hash_count,m.permutation_count,m.task_trace),(0,0,[]))
        # Even suffix digit 15 checks both recipes before its zero-work exit.
        m=self.machine();m.ctx.mask=1;m.ctx.digit0=15;m.digits=[0]*35;m.digit_valid=1
        desc=list(m.image.descriptors);desc[7]^=1<<48;m.image=replace(m.image,descriptors=tuple(desc))
        with self.assertRaisesRegex(ValueError,'recipe'):m._chain(ChainMode.SUFFIX,Lanes.L0,ChainLeaf.LEAF)
        self.assertEqual(m.hash_count,0)

    def test_chain_transaction_and_pending_hazards(self):
        m=self.machine();m.ctx.mask=1;m.ctx.step0=8;m.nodes[N.CAP0]=bytes([23])*16
        before=(asdict(m.ctx),list(m.nodes))
        def fail(_rid,_data,_result):raise RuntimeError('injected observer failure')
        m.observe=fail
        with self.assertRaisesRegex(RuntimeError,'injected'):m._chain(ChainMode.FULL,Lanes.L0,ChainLeaf.CURSOR)
        self.assertEqual((asdict(m.ctx),m.nodes),before)
        for code in ('pending','wait'):
            a=Assembler();a.emit(Op.MASK,imm=1)
            if code=='pending':a.emit(Op.HASH,4)
            a.emit(Op.CHAIN,ChainMode.FULL,Lanes.L0,ChainLeaf.CURSOR)
            a.emit(Op.WAIT);finish(a)
            with self.assertRaises(ValueError):synthetic_image(a)

    def test_macro_and_explicit_images_keep_ordered_hash_bytes(self):
        actual=[]
        for macros in (False,True):
            image=compile_micro('slh_128f',chain_macros=macros);traces=[]
            m=self.machine(image,operation=1,observe=lambda rid,data,result:traces.append((rid,data,result)))
            self.assertEqual(m.run(),self.signature);actual.append(traces)
        self.assertEqual(actual[0],actual[1])

    def test_recipe_capacity_outputs_and_reserved_bits(self):
        wide=compile_micro('slh_256f')
        for base,rid,word in ((wide,9,(wide.descriptors[9]&~(63<<24))|(1<<24)),
                (wide,3,(wide.descriptors[3]&~(63<<24))|(1<<24)),
                (self.image,3,(self.image.descriptors[3]&~(63<<32))|(16<<32)),
                (self.image,5,(self.image.descriptors[5]&~(63<<32))|(49<<32)),
                (self.image,5,self.image.descriptors[5]|(1<<30)),
                (self.image,5,self.image.descriptors[5]|(1<<38))):
            d=list(base.descriptors); d[rid]=word
            with self.assertRaises(ValueError): replace(base,descriptors=tuple(d)).validate()

    def test_reject_hash_hazards_on_all_cfg_paths(self):
        for sequence in ((Op.WAIT,),(Op.HASH,Op.HASH,Op.WAIT),(Op.HASH,Op.EMIT,Op.WAIT),
                         (Op.HASH,Op.PARSE,Op.WAIT),(Op.HASH,Op.END)):
            a=Assembler(); a.emit(Op.MASK,imm=1)
            for op in sequence: a.emit(op,4 if op==Op.HASH else 0,a=N.L0 if op==Op.EMIT else 0)
            a.emit(Op.END)
            with self.subTest(sequence=sequence):
                with self.assertRaises(ValueError): synthetic_image(a)

    def test_faulting_updates_are_atomic_without_wrap(self):
        for op,fields,initial in ((Op.CURSOR_NEXT,{'imm':1},{'cursor':16384,'height':14}),
                (Op.CHAIN_NEXT,{'imm':2},{'chain':36}),
                (Op.STEP_NEXT,{}, {'step0':14,'step1':15,'mask':3}),
                (Op.NODE_PARENT,{}, {'level':14,'height':14,'index':3,'path':2,'fors_base':0x40000}),
                (Op.LEVEL_NEXT,{}, {'level':14,'height':14}),
                (Op.GROUP_NEXT,{}, {'group':33}),
                (Op.LAYER_NEXT,{}, {'layer':22})):
            a=Assembler(); a.emit(op,**fields); finish(a)
            m=self.machine(synthetic_image(a))
            for name,value in initial.items(): setattr(m.ctx,name,value)
            state=asdict(m.ctx); nodes=deepcopy(m.nodes); storage=deepcopy(m.spaces)
            with self.subTest(op=op):
                with self.assertRaisesRegex(ValueError,'bounds'): m.run()
                self.assertEqual(asdict(m.ctx),state); self.assertEqual(m.nodes,nodes); self.assertEqual(m.spaces,storage)

    def test_max_cursor_terminal_and_odd_chain_tail(self):
        a=Assembler(); a.emit(Op.CURSOR_NEXT,imm=2); a.emit(Op.CHAIN_NEXT,imm=2); finish(a)
        m=self.machine(synthetic_image(a)); m.ctx.height=14; m.ctx.cursor=16382; m.ctx.chain=34
        m.run(); self.assertEqual(m.ctx.cursor,16384); self.assertEqual(m.ctx.chain,36)
        a=Assembler(); a.emit(Op.STEP_NEXT); finish(a)
        m=self.machine(synthetic_image(a)); m.ctx.mask=1; m.ctx.step0=14; m.ctx.step1=15
        m.run(); self.assertEqual((m.ctx.step0,m.ctx.step1),(15,15))

    def test_tree_address_keeps_all_64_bits(self):
        a=Assembler(); a.emit(Op.MASK,imm=1); a.emit(Op.HASH,4); a.emit(Op.WAIT)
        a.emit(Op.TREE_NEXT); finish(a,N.L0)
        m=self.machine(synthetic_image(a),record_tasks=True); m.ctx.tree=(1<<64)-1
        m.run(); self.assertEqual(m.task_trace[0][2],(1<<64)-1)
        self.assertEqual(m.ctx.tree,((1<<64)-1)>>3); self.assertEqual(m.ctx.leaf,7)

    def test_digit_zero_fifteen_suffix_and_inactive_step_retention(self):
        a=Assembler(); a.emit(Op.MASK,Mask.PAIR); a.emit(Op.DIGIT_LOAD)
        a.emit(Op.STEP_INIT,Lanes.CURRENT,StepSource.DIGIT); a.emit(Op.MASK,Mask.SUFFIX)
        a.emit(Op.STEP_NEXT); finish(a)
        m=self.machine(synthetic_image(a)); m.digits=[0,15]+[0]*33
        m.run(); self.assertEqual((m.ctx.step0,m.ctx.step1),(1,15)); self.assertEqual(m.ctx.mask,1)

    def test_digit_and_prefix_operations_reject_uninitialized_values(self):
        for op,d,a in ((Op.DIGIT_LOAD,0,0),(Op.STEP_INIT,0,StepSource.DIGIT),(Op.MASK,Mask.PREFIX,0)):
            code=Assembler(); code.emit(Op.MASK,imm=3); code.emit(op,d,a); finish(code)
            for empty_selection in (False,True):
                m=self.machine(synthetic_image(code))
                if empty_selection:
                    # Fixed mask 3 is overwritten by the source program; use
                    # L1 restricted by a retained L0 mask, or an empty pair.
                    empty=Assembler(); empty.emit(Op.MASK,imm=1)
                    empty.emit(op,Lanes.L1 if op!=Op.MASK else d,a); finish(empty)
                    m=self.machine(synthetic_image(empty))
                    if op==Op.MASK: m.ctx.chain=36
                with self.assertRaisesRegex(ValueError,'digit|DIGIT'): m.run()

    def test_domain_specific_guards_do_not_modify_context(self):
        cases=[(Op.NODE_BEGIN,0,0,0,{'height':0}),
            (Op.NODE_BEGIN,0,0,0,{'height':2,'target':4}),
            (Op.NODE_BEGIN,0,TreeKind.FORS,0,{'height':2,'group':33}),
            (Op.ADRS,Addr.FORS_CURSOR,0,0,{'height':14,'cursor':64}),
            (Op.ADRS,Addr.FORS_TARGET,0,0,{'height':14,'target':64}),
            (Op.ADRS,Addr.FORS_NODE,0,0,{'height':6,'group':33}),
            (Op.ADRS,Addr.HT_NODE,0,0,{'height':3,'level':4}),
            (Op.ADRS,Addr.REDUCE_NODE,TreeKind.HT,0,{'level':1,'reduce_span':2,'reduce_index':2}),
            (Op.ADRS,Addr.REDUCE_NODE,TreeKind.FORS,0,{'reduce_span':2,'reduce_index':0}),
            (Op.REDUCE_INIT,TreeKind.HT,0,0,{'height':0}),
            (Op.REDUCE_INIT,TreeKind.FORS,0,0,{'height':3,'group':33}),
            (Op.ROOT_COMPARE,0,0,0,{}),
            (Op.BR,Cond.ROOT_EQUAL,0,1,{})]
        for op,d,a,imm,initial in cases:
            code=Assembler(); code.emit(op,d,a,imm=imm); finish(code)
            m=self.machine(synthetic_image(code))
            for name,value in initial.items(): setattr(m.ctx,name,value)
            original=asdict(m.ctx)
            with self.subTest(op=op,d=d):
                with self.assertRaises(ValueError): m.run()
                self.assertEqual(asdict(m.ctx),original)

    def test_runtime_node_space_bounds(self):
        a=Assembler(); a.emit(Op.LOAD,N.L0,Space.LIST,Index.CURSOR); finish(a)
        m=self.machine(synthetic_image(a)); m.ctx.cursor=68; nodes=deepcopy(m.nodes)
        with self.assertRaisesRegex(ValueError,'bounds'): m.run()
        self.assertEqual(m.nodes,nodes)



"""ABI 4 TREE semantics, boundaries and independent primitive-level oracles."""
from copy import deepcopy
from dataclasses import asdict, replace
import hashlib
import unittest

from model.microcode import (ABI, ACCESS, Addr, Assembler, Instruction, Lanes, N, Op,
    Space, TreeFlags, TreeKind, TreeMode, sv_definitions)
from model.mHBS import compile_micro
from model.executor import MicroMachine
from model.profiles import SLH_NAMES, get_profile
from model.vectors import default_job


def oracle_hash(job,n,layer,tree,domain,leaf,a,b,payload):
    adrs=b''.join(value.to_bytes(4,'big') for value in
        (layer,0,tree>>32,tree&0xffffffff,domain,leaf,a,b))
    return hashlib.shake_256(job.public+adrs+payload).digest(n)


def ht_oracle(job,p,layer,tree,target,digits):
    """Materialize a small oracle tree, independent of VM stack scheduling."""
    row=[];signature=[]
    for leaf in range(1<<p.hp):
        endpoints=[]
        for chain in range(p.chains):
            node=oracle_hash(job,p.n,layer,tree,5,leaf,chain,0,job.secret)
            if leaf==target and digits[chain]==0: signature.append(node)
            for step in range(15):
                node=oracle_hash(job,p.n,layer,tree,0,leaf,chain,step,node)
                if leaf==target and digits[chain]==step+1: signature.append(node)
            endpoints.append(node)
        row.append(oracle_hash(job,p.n,layer,tree,1,leaf,0,0,b''.join(endpoints)))
    auth=[];level=0
    while len(row)>1:
        auth.append(row[(target>>level)^1]);level+=1
        row=[oracle_hash(job,p.n,layer,tree,2,0,level,index//2,row[index]+row[index+1])
            for index in range(0,len(row),2)]
    return row[0],b''.join(signature+auth)


def fors_oracle(job,p,layer,tree,leaf,group,target):
    row=[];secret=None
    for index in range(1<<p.a):
        value=oracle_hash(job,p.n,layer,tree,6,leaf,0,(group<<p.a)+index,job.secret)
        if index==target: secret=value
        row.append(oracle_hash(job,p.n,layer,tree,3,leaf,0,(group<<p.a)+index,value))
    auth=[];level=0
    while len(row)>1:
        auth.append(row[(target>>level)^1]);level+=1
        row=[oracle_hash(job,p.n,layer,tree,3,leaf,level,
            (group<<(p.a-level))+index//2,row[index]+row[index+1])
            for index in range(0,len(row),2)]
    return row[0],b''.join([secret]+auth)


class TreeTests(unittest.TestCase):
    def machine(self,name='slh_128f',operation=0,signature=b''):
        p=get_profile(name);job,msg=default_job(name)
        signature=signature.ljust(p.signature_bytes,b'\0') if operation==2 else b''
        return MicroMachine(compile_micro(name),job,bytes([0x37])*p.n,
            msg if operation else b'',operation,signature=signature,record_tasks=True)

    def test_all_profiles_three_loop_images_and_enum_contract(self):
        self.assertEqual((ABI,int(Op.CHAIN),int(Op.TREE)),(4,36,37))
        self.assertTrue({'rindex','span','root_equal'}<=ACCESS[Op.TREE][1])
        for name in SLH_NAMES:
            images=[compile_micro(name),compile_micro(name,tree_macros=False),
                compile_micro(name,chain_macros=False),compile_micro(name,serial=True)]
            self.assertEqual([image.used for image in images],[65,278,348,412])
            self.assertEqual(images[0].entries,(0,10,39))
            for image in images: self.assertLessEqual(image.used,512)
            self.assertIn('d=FORS, a=SIGN, b=NONE',images[0].disassemble())
            self.assertIn('d=HT, a=SIGN, b=TOP_SHORTCUT',images[0].disassemble())
            self.assertFalse(any(Instruction.decode(word).op==Op.TREE for word in images[1].program[:images[1].used]))
            self.assertIn('CHAIN ',images[1].disassemble())
            self.assertNotIn('CHAIN ',images[2].disassemble())

    def test_tree_operand_permissions_and_pending_conflicts(self):
        for ins in (Instruction(Op.TREE,2),Instruction(Op.TREE,TreeKind.FORS,TreeMode.ROOT),
            Instruction(Op.TREE,TreeKind.FORS,TreeMode.SIGN,1),
            Instruction(Op.TREE,TreeKind.HT,TreeMode.VERIFY,1),
            Instruction(Op.TREE,TreeKind.HT,TreeMode.SIGN,2),Instruction(Op.TREE,imm=1)):
            a=Assembler();a.code.append(ins);finish(a)
            with self.subTest(ins=ins),self.assertRaises(ValueError): synthetic_image(a)
        for sequence in ((Op.HASH,Op.TREE,Op.WAIT),(Op.TREE,Op.WAIT)):
            a=Assembler()
            for op in sequence:a.emit(op,4 if op==Op.HASH else 0)
            finish(a)
            with self.assertRaises(ValueError):synthetic_image(a)
        for abi in (1,2,3):
            base=compile_micro('slh_128f');desc=list(base.descriptors)
            desc[0]=(desc[0]&~(31<<27))|(abi<<27)
            with self.assertRaisesRegex(ValueError,'ABI'):replace(base,descriptors=tuple(desc)).validate()

    def test_ht_root_sign_verify_against_flat_oracle_sizes_digits_and_tree64(self):
        for name in ('slh_128f','slh_192f','slh_256f'):
            p=get_profile(name);job,_=default_job(name);tree=0xfedcba9876543210
            digits=[index%16 for index in range(p.chains)];target=(1<<p.hp)-1
            root,signature=ht_oracle(job,p,1,tree,target,digits)
            for mode in TreeMode:
                with self.subTest(name=name,mode=mode):
                    m=self.machine(name,int(mode),signature)
                    m.ctx.layer=1;m.ctx.tree=tree;m.ctx.leaf=target;m.ctx.target=target;m.digits=list(digits)
                    m._tree(TreeKind.HT,mode)
                    self.assertEqual(m.nodes[N.L0],root)
                    self.assertEqual(bytes(m.output),signature if mode==TreeMode.SIGN else b'')
                    self.assertEqual(m.signature_cursor,len(signature) if mode==TreeMode.VERIFY else 0)
                    self.assertEqual(m.tree_chains,p.chains*(1 if mode==TreeMode.VERIFY else 1<<p.hp))
                    self.assertEqual((m.macro_count,m.macro_hashes),(0,0))
                    self.assertEqual(m.tree_hashes,m.hash_count)
                    self.assertTrue(all(task[2]==tree for task in m.task_trace))
                    if mode==TreeMode.ROOT:
                        self.assertEqual(m.hash_count,(1<<p.hp)*(16*p.chains+1)+(1<<p.hp)-1)

    def test_top_shortcut_preserves_signature_and_returns_external_root(self):
        m=self.machine(operation=1);p=get_profile('slh_128f');m.ctx.layer=p.d-1
        m.ctx.target=0;m.digits=[index%16 for index in range(p.chains)]
        root,signature=ht_oracle(m.job,p,p.d-1,0,0,m.digits)
        self.assertNotEqual(root,m.nodes[N.V3]);external=m.nodes[N.V3]
        m._tree(TreeKind.HT,TreeMode.SIGN,TreeFlags.TOP_SHORTCUT)
        self.assertEqual(bytes(m.output),signature);self.assertEqual(m.nodes[N.L0],external)
        self.assertFalse(any(((task[0]>>56)&15)==12 and task[3]==0 for task in m.task_trace))
        expected=(1<<p.hp)*(16*p.chains+1)+(1<<p.hp)-1
        expected-=sum(15-digit for digit in m.digits)+1+p.hp
        self.assertEqual(m.hash_count,expected)

    def test_fors_edges_and_max_height_against_flat_oracle(self):
        for name,target_last in (('slh_128f',False),('slh_128f',True),('slh_192s',True)):
            p=get_profile(name);job,_=default_job(name);target=(1<<p.a)-1 if target_last else 0
            tree=0xfedcba9876543210;leaf=(1<<p.hp)-1;group=p.k-1
            root,signature=fors_oracle(job,p,1,tree,leaf,group,target)
            for mode in (TreeMode.SIGN,TreeMode.VERIFY):
                with self.subTest(name=name,last=target_last,mode=mode):
                    m=self.machine(name,int(mode),signature)
                    m.ctx.layer=1;m.ctx.tree=tree;m.ctx.leaf=leaf;m.ctx.group=group;m.ctx.target=target
                    before=list(m.spaces[Space.LIST]);m._tree(TreeKind.FORS,mode)
                    self.assertEqual(m.nodes[N.L0],root);self.assertEqual(m.spaces[Space.LIST],before)
                    self.assertEqual(bytes(m.output),signature if mode==TreeMode.SIGN else b'')
                    self.assertEqual(m.signature_cursor,len(signature) if mode==TreeMode.VERIFY else 0)
                    self.assertEqual(m.hash_count,3*(1<<p.a)-1 if mode==TreeMode.SIGN else p.a+1)
                    self.assertEqual(m.tree_chains,0)

    def test_success_cleanup_preserves_only_documented_state(self):
        m=self.machine();c=m.ctx
        c.layer=2;c.tree=0xfedcba9876543210;c.leaf=4;c.group=3;c.target=6
        outer={key:getattr(c,key) for key in ('layer','tree','leaf','group','target')}
        for key in c.__dataclass_fields__:
            if key not in outer:setattr(c,key,1)
        for i in range(11):m.nodes[i]=bytes([i+1])*m.n
        preserved=list(m.nodes[:4]);m.digest=b'digest';m.digits=list(range(16))*2+[0,1,2]
        digits=list(m.digits);m.digit_valid=3
        m._tree(TreeKind.HT,TreeMode.ROOT)
        for key,value in asdict(c).items():
            self.assertEqual(value,outer.get(key,1 if key=='mask' else 0),key)
        self.assertEqual(m.nodes[:4],preserved);self.assertEqual(m.digest,b'digest');self.assertEqual(m.digits,digits)
        for i in (N.L1,N.RIGHT,N.CAP0,N.CAP1,N.NODE,N.TMPNODE):self.assertEqual(m.nodes[i],bytes(m.n))
        self.assertEqual(m.digit_valid,0);self.assertFalse(m.root_compare_valid)

    def test_preflight_rejects_all_tree_recipes_before_any_side_effect(self):
        for kind,mode,rids in ((TreeKind.HT,TreeMode.ROOT,(7,8,9,10)),
            (TreeKind.FORS,TreeMode.SIGN,(4,5,6)),(TreeKind.FORS,TreeMode.VERIFY,(5,6))):
            for rid in rids:
                for bit in (0,24,32,40,48,56):
                    m=self.machine(operation=int(mode));desc=list(m.image.descriptors);desc[rid]^=1<<bit
                    m.image=replace(m.image,descriptors=tuple(desc));before=(asdict(m.ctx),deepcopy(m.nodes),deepcopy(m.spaces))
                    with self.subTest(kind=kind,mode=mode,rid=rid,bit=bit),self.assertRaises(ValueError):m._tree(kind,mode)
                    self.assertEqual((asdict(m.ctx),m.nodes,m.spaces),before)
                    self.assertEqual((m.hash_count,m.tree_count,m.signature_cursor,m.output),(0,0,0,b''))

    def test_context_and_job_preflight_rejects_without_side_effects(self):
        for mutation in ('mode','leaf','layer','tree','target','group','digits','flag','shortcut_layer','pending'):
            m=self.machine(operation=1);kind=TreeKind.HT;flags=0
            m.digits=[0]*m.chains
            if mutation=='mode':mode=TreeMode.ROOT
            else:mode=TreeMode.SIGN
            if mutation=='leaf':m.ctx.leaf=1<<m.hp
            if mutation=='layer':m.ctx.layer=m.d
            if mutation=='tree':m.ctx.tree=1<<64
            if mutation=='target':m.ctx.target=1<<m.hp
            if mutation=='group':kind=TreeKind.FORS;m.ctx.group=m.k
            if mutation=='digits':m.digits=[]
            if mutation=='flag':flags=2
            if mutation=='shortcut_layer':flags=1
            if mutation=='pending':m.pending=[]
            before=(asdict(m.ctx),deepcopy(m.nodes),deepcopy(m.spaces))
            with self.subTest(mutation=mutation),self.assertRaises(ValueError):m._tree(kind,mode,flags)
            self.assertEqual((asdict(m.ctx),m.nodes,m.spaces),before)
            self.assertEqual((m.hash_count,m.tree_count,m.signature_cursor,m.output),(0,0,0,b''))

    def test_tree_locks_recipe_context_and_hashes_at_start(self):
        a=self.machine();a._tree(TreeKind.HT,TreeMode.ROOT)
        b=self.machine();changed=False
        def mutate(_rid,_data,_result):
            nonlocal changed
            if not changed:
                changed=True;desc=list(b.image.descriptors)
                for rid in (7,8,9,10):desc[rid]^=1<<48
                b.image=replace(b.image,descriptors=tuple(desc))
        b.observe=mutate;b._tree(TreeKind.HT,TreeMode.ROOT)
        self.assertEqual(a.task_trace,b.task_trace);self.assertEqual(a.nodes[N.L0],b.nodes[N.L0])

    def test_independent_rtl_fixtures_reproduce_all_seven_tree_cases(self):
        from scripts.generate_tree_vectors import cases, render, OUTPUT
        self.assertEqual(OUTPUT.read_text(),render())
        for index,case in enumerate(cases()):
            m=self.machine(operation=case['mode'],signature=b''.join(case['inputs']))
            m.job=replace(m.job,secret=bytes(range(16)),public=bytes(range(64,80)))
            m.nodes[N.V3]=bytes(range(128,144))
            m.hp=case['hp'];m.a=case['a']
            for key in ('layer','leaf','target','group'):setattr(m.ctx,key,case[key])
            m.ctx.tree=0xfedcba9876543210
            values=[v for byte in m.job.public for v in (byte>>4,byte&15)]
            checksum=sum(15-v for v in values);m.digits=values+[(checksum>>shift)&15 for shift in (8,4,0)]
            with self.subTest(index=index):
                m._tree(case['kind'],case['mode'],case['flags'])
                self.assertEqual(m.nodes[N.L0],case['root'])
                self.assertEqual(bytes(m.output),b''.join(case['outputs']))
                self.assertEqual(m.signature_cursor,16*case['input_count'])
                self.assertEqual((m.hash_count,m.permutation_count),
                    (case['hash_count'],case['permutation_count']))

    def test_runtime_fault_aborts_job_and_reset_replay(self):
        a=Assembler();a.emit(Op.TREE,TreeKind.HT,TreeMode.ROOT);finish(a,N.L0)
        image=synthetic_image(a);job,_=default_job('slh_128f')
        m=MicroMachine(image,job,bytes(16),b'',0)
        def fail(_rid,_data,_value):
            if m.hash_count==19:raise RuntimeError('injected mid-tree failure')
        m.observe=fail
        with self.assertRaisesRegex(RuntimeError,'mid-tree'):m.run()
        self.assertTrue(m.halted);self.assertIsNotNone(m.error);self.assertEqual(m.hash_count,19)
        self.assertEqual(m.output,b'')
        with self.assertRaisesRegex(ValueError,'halted'):m.run()
        replay=MicroMachine(image,job,bytes(16),b'',0);self.assertEqual(len(replay.run()),96)
        self.assertEqual(replay.tree_count,1)



if __name__=='__main__':
    import json
    run=unittest.main(exit=False).result
    root=Path(__file__).resolve().parents[1]
    paths=[*[p.relative_to(root) for p in sorted((root/'model').rglob('*.py'))],Path(__file__).resolve().relative_to(root)]
    receipt={'passed':run.wasSuccessful(),'tests':run.testsRun,'errors':len(run.errors),'failures':len(run.failures),'source_sha256':{str(p):hashlib.sha256((root/p).read_bytes()).hexdigest() for p in paths}}
    out=Path(__file__).resolve().parents[1]/'build/image-chain-tree/model_units.json'
    out.parent.mkdir(parents=True,exist_ok=True);out.write_text(json.dumps(receipt,indent=2,sort_keys=True)+'\n')
    sys.exit(0 if run.wasSuccessful() else 1)
