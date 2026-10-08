"""Mathematical bounds, provenance and repository workload regression (Python only)."""
from collections import Counter
from itertools import combinations
from pathlib import Path
import tempfile
import unittest
import json

from model.keccak_utilization import (
    DependencyGraph, DependencyMachine, GraphStatistics, Value, Inputs,
    build_graph, load_inputs, get_profile, PROFILES, VECTORS, write_reports,
)
from model.unified_hbs import compile_image, Machine


def exhaustive_batches(graph, p):
    """Exhaustive finite-state scheduling oracle, independent of bound formulas."""
    n=graph.permutations
    parent_masks=[]
    for i in range(1,n+1):
        parent_masks.append(sum(1 << (d-1) for d in graph.parents[graph.offsets[i]:graph.offsets[i+1]]))
    distances={0:0}
    for done in range(1<<n):
        if done not in distances: continue
        ready=[i for i,mask in enumerate(parent_masks) if not done>>i&1 and mask&done==mask]
        # Executing more ready tasks cannot delay a successor in this ideal model.
        for batch in combinations(ready,min(p,len(ready))):
            if not batch: continue
            after=done|sum(1<<i for i in batch)
            distances[after]=min(distances.get(after,n+1),distances[done]+1)
    return distances[(1<<n)-1]


class BoundTests(unittest.TestCase):
    def test_all_small_dags(self):
        n=5
        edges=[(i,j) for j in range(1,n) for i in range(j)]
        for mask in range(1<<len(edges)):
            graph=DependencyGraph()
            for j in range(n):
                graph.add(i+1 for bit,(i,target) in enumerate(edges) if target==j and mask>>bit&1)
            stats=graph.statistics()
            for p in (1,2,3,4):
                bound=stats.bound(p,1)
                exact=exhaustive_batches(graph,p)
                self.assertLessEqual(bound['batches_lb'],exact,(mask,p,bound,exact))
                self.assertGreaterEqual(bound['idle_lower'],0)
                self.assertLessEqual(bound['utilization_upper'],1)
                if bound['optimality']=='proven':self.assertEqual(bound['batches_lb'],exact)

    def test_independent_and_serial(self):
        g=DependencyGraph()
        for _ in range(10):g.add()
        r=g.statistics().bound(4,2)
        self.assertEqual(r['cycles_lb'],36)
        self.assertAlmostEqual(r['idle_lower'],1/6)
        g=DependencyGraph();node=0
        for _ in range(10):node=g.add([node])
        r=g.statistics().bound(4,2)
        self.assertEqual(r['cycles_lb'],120)
        self.assertEqual(r['idle_lower'],0.75)

    def test_serial_prefix_parallel_middle_serial_suffix(self):
        g=DependencyGraph();a=g.add();b=g.add([a])
        middle=[g.add([b]) for _ in range(8)]
        c=g.add(middle);g.add([c])
        r=g.statistics().bound(4,1)
        self.assertEqual(r['batches_lb'],6)
        self.assertEqual(r['dependency_window_batches_lb'],6)
        self.assertEqual(exhaustive_batches(g,4),6)

    def test_validation_and_u_scaling(self):
        s=GraphStatistics(7,7,Counter({1:7}),Counter({1:7}))
        for p,u in ((0,1),(1,0),(-1,2),(5,1),(4,4),(True,1),(1,1.0)):
            with self.assertRaises(ValueError):s.bound(p,u)
        for p in (1,2,3,4,6,12):
            a,b=s.bound(p,1),s.bound(p,2)
            self.assertEqual(a['idle_lower'],b['idle_lower'])
            self.assertEqual(a['cycles_lb'],2*b['cycles_lb'])
        with self.assertRaises(ValueError):DependencyGraph().add([1])

    def test_padding_and_streaming_dependencies(self):
        for size,perms in ((0,1),(135,1),(136,2),(137,2),(272,3)):
            g=DependencyGraph();m=DependencyMachine(compile_image('slh_128f'),load_inputs('slh_128f').job,g)
            m.shake([bytes(size)],16)
            self.assertEqual(g.permutations,perms)
        g=DependencyGraph();a=g.add();b=g.add([a])
        m=DependencyMachine(compile_image('slh_128f'),load_inputs('slh_128f').job,g)
        value=m.shake([bytes(136),Value(bytes(16),b)],16)
        self.assertEqual(list(g.parents[g.offsets[3]:g.offsets[4]]),[])
        self.assertEqual(set(g.parents[g.offsets[4]:g.offsets[5]]),{2,3})
        self.assertEqual(value[:4].node,value.node)

    def test_seed_does_not_wait_for_sign_digit(self):
        g=DependencyGraph();a=g.add();b=g.add([a])
        m=DependencyMachine(compile_image('xmss_omega4'),load_inputs('xmss_omega4').job,g)
        m.chain_control=b
        m.hash_recipe(4)
        self.assertEqual(g.depth[3],1)

    def test_masks_not_serialized_after_incoming_value(self):
        g=DependencyGraph();a=g.add();b=g.add([a]);c=g.add([b])
        m=DependencyMachine(compile_image('xmss_omega4'),load_inputs('xmss_omega4').job,g)
        m.hash_recipe(5,left=Value(bytes(32),c))
        self.assertEqual(g.depth[4],1)  # key
        self.assertEqual(g.depth[5],1)  # mask
        self.assertEqual(g.depth[6],4)  # masked result waits for incoming value


class WorkloadTests(unittest.TestCase):
    def test_ten_profiles_three_operations_and_auth_modes(self):
        for name in PROFILES:
            profile=get_profile(name);inputs=load_inputs(name)
            for operation,op in (('keygen',0),('sign',1),('verify',2)):
                with self.subTest(name=name,operation=operation):
                    graph=build_graph(name,operation,inputs,recompute_auth=profile.stateful)
                    meta=[int(x,16) for x in (VECTORS/name/str(op)/'meta.mem').read_text().split()]
                    self.assertEqual((graph.hashes,graph.permutations),tuple(meta[1:3]))
                    stats=graph.statistics()
                    self.assertEqual(stats.bound(1,1)['cycles_lb'],graph.permutations*24)
                    if name=='slh_128f' and operation=='sign':
                        self.assertEqual((graph.hashes,graph.permutations),(104937,105641))
                    if profile.stateful and operation=='sign':
                        cached=build_graph(name,operation,inputs)
                        # Independent execution through unchanged cached interpreter.
                        m=Machine(compile_image(name),inputs.job,index_policy='fixed_q_no_guard')
                        m.cache_valid=True;m.values[3]=inputs.root
                        m.cache={(k,(inputs.job.q>>k)^1):bytes(profile.n) for k in range(profile.h)}
                        m.run(True,inputs.message)
                        self.assertEqual((cached.hashes,cached.permutations),(m.hashes,m.permutations))
                        self.assertLess(cached.permutations,graph.permutations)
            print('WORKLOAD_PASS',name,flush=True)

    def test_invalid_signature_and_input(self):
        i=load_inputs('lms_omega4')
        bad=Inputs(i.job,i.root,b'C',i.signature)
        with self.assertRaises(ValueError):build_graph('lms_omega4','verify',bad)
        with self.assertRaises(ValueError):build_graph('lms_omega4','invalid',i)

    def test_cached_sign_custom_q_and_message_boundaries(self):
        from dataclasses import replace
        for name in ('xmss_omega2','lms_omega4'):
            i=load_inputs(name)
            for q in (0,1,1023):
                for length in (1,87):
                    inputs=Inputs(replace(i.job,q=q),i.root,bytes(range(length)))
                    g=build_graph(name,'sign',inputs)
                    m=Machine(compile_image(name),inputs.job,index_policy='fixed_q_no_guard')
                    m.cache_valid=True;m.values[3]=inputs.root
                    m.cache={(k,(q>>k)^1):bytes(32) for k in range(10)}
                    m.run(True,inputs.message)
                    self.assertEqual((g.hashes,g.permutations),(m.hashes,m.permutations))

    def test_custom_input_roundtrip_and_report(self):
        i=load_inputs('lms_omega4')
        with tempfile.TemporaryDirectory() as folder:
            f=Path(folder)/'inputs.json'
            d={k:getattr(i.job,k).hex() for k in ('secret','prf','public','random','identifier')}
            d.update(q=i.job.q,root=i.root.hex(),message=i.message.hex(),signature=i.signature.hex())
            f.write_text(json.dumps(d))
            restored=load_inputs('lms_omega4',f)
            self.assertEqual(restored.identity(),i.identity())
            from model.keccak_utilization import analyze
            row=analyze('lms_omega4','sign',4,2,inputs=restored)
            prefix=Path(folder)/'report';write_reports(prefix,[row])
            self.assertEqual(json.loads(prefix.with_suffix('.json').read_text())['rows'],[row])
            self.assertFalse(row['recompute_auth'])


if __name__=='__main__':unittest.main()
