"""Independent pre-RTL validation of all ABI 4 products."""
from dataclasses import replace
import hashlib
import json
import unittest

from model.profiles import PROFILES
from model.unified_hbs import Machine, compile_image, validate, field
from model.reference import slh_dsa, xmss, lms_shake
from tests.test_unified_hbs import default_job, KAT, memory


class SevenProfileTests(unittest.TestCase):
    def test_bounds_and_serialization(self):
        for name, p in PROFILES.items():
            image = compile_image(name)
            self.assertEqual(image.output_bytes(True), p.signature_bytes)
            self.assertEqual(image.stateful, p.stateful)
            self.assertEqual(image.n, p.n)
            for index, change in ((0, (3 << 56) | (image.descriptors[0] & ~(15 << 56))),
                                  (1, image.descriptors[1] & ~(15 << 44)),
                                  (16, image.descriptors[16] | (255 << 20))):
                d = list(image.descriptors); d[index] = change
                with self.assertRaises(ValueError): validate(replace(image, descriptors=tuple(d)))

    def test_all_products(self):
        for name, p in PROFILES.items():
            with self.subTest(profile=name):
                print(f"MODEL_VERIFY_BEGIN {name}", flush=True)
                job, msg = default_job(name)
                machine = Machine(compile_image(name, full_cache=p.stateful), job)
                kg = machine.run(False)
                kg_counts = [machine.hashes, machine.permutations]
                counts, nodes, address = [0, 0], {}, [0]*8
                def observe(kind, data, result):
                    counts[0] += 1; counts[1] += len(data)//136+1
                    if p.family == "xmss":
                        if kind == "prf":
                            address[:] = [int.from_bytes(data[-32+i:][:4], "big") for i in range(0,32,4)]
                        elif kind == "thash_h":
                            if address[3] == 2: nodes[address[5]+1,address[6]] = result
                            elif address[3] == 1 and address[5] == (p.chains-1).bit_length()-1:
                                nodes[0,address[4]] = result
                    elif p.family == "lms" and kind in ("merkle_leaf", "merkle_internal"):
                        number = int.from_bytes(data[16:20], "big")
                        level = 10-(number.bit_length()-1)
                        nodes[level,number-(1 << (10-level))] = result
                if p.family == "slh":
                    params = getattr(slh_dsa, f"SLH_DSA_SHAKE_{p.n*8}F")
                    sk, pk = slh_dsa.keygen_internal(params,job.secret,job.prf,job.public,observe)
                    self.assertEqual(kg, sk+pk)
                    self.assertEqual(kg_counts, counts)
                    kat = json.loads(next(KAT.glob(f"slh_dsa_shake_{p.n*8}f_siggen_acvp_tc*.json")).read_text())
                    self.assertEqual(kg,bytes.fromhex(kat['sk']+kat['pk']))
                    sg = machine.run(True,msg)
                    self.assertEqual(hashlib.sha256(sg).hexdigest(),kat['signature_sha256'])
                    if p.n != 16: self.assertEqual(sg,memory(f"slh_{p.n*8}f_acvp_signature.mem"))
                    self.assertEqual(sg,slh_dsa.sign_internal(params,msg,sk))
                    self.assertTrue(slh_dsa.verify_internal(params,msg,sg,pk))
                    for size in (8,31,64,87):
                        message = bytes(range(size))
                        self.assertEqual(machine.run(True,message),slh_dsa.sign_internal(params,message,sk))
                else:
                    if p.family == "xmss":
                        params = xmss.XMSS_SHAKE256_10_256_W4_STUDY if p.omega==2 else xmss.XMSS_SHAKE256_10_256
                        root, auth = xmss._treehash(params,job.secret,job.public,job.q,observe)
                        self.assertEqual(kg,job.q.to_bytes(4,'big')+job.secret+job.prf+root+job.public+root+job.public)
                    else:
                        params = lms_shake.LMS_SHAKE_H10_W2 if p.omega==2 else lms_shake.LMS_SHAKE_H10_W4
                        root, auth = lms_shake.tree_and_authentication(job.identifier,job.secret,job.q,params,observe)
                        self.assertEqual(kg,job.q.to_bytes(4,'big')+job.identifier+job.secret+root+lms_shake.public_key_encoding(job.identifier,root,params))
                    self.assertEqual(kg_counts,counts)
                    self.assertEqual(machine.cache,nodes)
                    for q in (job.q,0,1023):
                        machine.q=q
                        with self.assertRaisesRegex(ValueError,'commit'): machine.run(True,msg,commit=False)
                        self.assertEqual(machine.q,q)
                        sg=machine.run(True,msg)
                        counts[:]=[0,0]
                        auth=tuple(nodes[level,(q>>level)^1] for level in range(10))
                        if p.family=='xmss':
                            r=xmss._prf(params,job.prf,q.to_bytes(32,'big'),observe)
                            digest=xmss._hash_message(params,r,root,q,msg,observe)
                            addr=[0,0,0,0,q,0,0,0]
                            expected=q.to_bytes(4,'big')+r+xmss._wots_sign(params,digest,job.secret,job.public,addr,observe)+b''.join(auth)
                            self.assertTrue(xmss.xmss_verify(kg[-64:],msg,sg,params))
                        else:
                            state=q.to_bytes(4,'big')+job.identifier+job.secret+root
                            expected,_=lms_shake.sign(state,msg,job.random,params,observe,cached_authentication=auth)
                            self.assertTrue(lms_shake.verify(kg[-56:],msg,sg,params))
                        self.assertEqual(sg,expected)
                        self.assertEqual([machine.hashes,machine.permutations],counts)
                        self.assertEqual(machine.q,q+1)
                    with self.assertRaisesRegex(ValueError,'exhausted'): machine.run(True,msg)
                    machine.q=7;machine.cache.pop((0,6))
                    with self.assertRaises(KeyError): machine.run(True,msg)
                    self.assertEqual(machine.q,8)
                    self.assertFalse(machine.cache_valid)
                    self.assertEqual(machine.output,b'')
                    # Switch the same verified nodes to the production selected-path policy.
                    machine.image=compile_image(name);machine.cache_valid=True;machine.cache_q=5;machine.q=5
                    machine.cache={key:node for key,node in nodes.items() if key[0]==10 or key[1]==((5>>key[0])^1)}
                    self.assertEqual(len(machine.cache),11)
                    machine.run(True,msg)
                    with self.assertRaisesRegex(ValueError,'another index'):machine.run(True,msg)
                print(f"MODEL_VERIFY_PASS {name}",flush=True)


if __name__ == '__main__': unittest.main()
