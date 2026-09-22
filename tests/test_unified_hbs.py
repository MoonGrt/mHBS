"""Pre-RTL gate: execute ABI 3 images against independent fixed vectors."""
import hashlib
import json
from pathlib import Path
import unittest
from dataclasses import replace

from model.unified_hbs import Image, Job, Machine, compile_image, validate
from model.reference import slh_dsa, xmss, lms_shake

KAT = Path(__file__).parent / "kat"


def default_job(name):
    if name == "slh":
        v = json.loads((KAT / "slh_dsa_shake_128f_siggen_acvp_tc137.json").read_text())
        sk = bytes.fromhex(v["sk"])
        return Job(sk[:16], sk[16:32], sk[32:48], sk[32:48]), bytes.fromhex(v["message"])
    if name == "xmss":
        v = json.loads((KAT / "xmss_shake256_10_256_idx5.json").read_text())
        seed = bytes.fromhex(v["seed"])
        return Job(seed[:32], seed[32:64], seed[64:], bytes(32), q=v["signing_index"]), bytes.fromhex(v["message"])
    v = json.loads((KAT / "stateful_hbs_rtl_vectors.json").read_text())["lms_shake_research"]
    return Job(bytes.fromhex(v["seed"]), bytes(32), bytes(32), bytes.fromhex(v["randomizer"]),
               bytes.fromhex(v["identifier"]), v["initial_q"]), bytes.fromhex(v["message"])


def memory(name):
    return bytes(int(x, 16) for x in (KAT / name).read_text().split())


class UnifiedImageTests(unittest.TestCase):
    def test_all_entries_and_serialization(self):
        for name in ("slh", "xmss", "lms"):
            image = compile_image(name)
            self.assertLessEqual(16*(len(image.tokens)+len(image.templates))+8*len(image.descriptors), 4096)
            self.assertEqual(image.words(False)[-1] >> 124, 15)
            self.assertEqual(image.words(True)[-1] >> 124, 15)
            # Only raw memories are required to execute an image.
            validate(Image(name, tuple(image.tokens), tuple(image.templates), tuple(image.descriptors)))

    def test_invalid_images(self):
        image = compile_image("xmss")
        for index, value in ((0, image.descriptors[0] ^ (1 << 56)), (16, 0),
                             (20, image.descriptors[20] | (15 << 40)),
                             (64, image.descriptors[64] | (255 << 48))):
            d = list(image.descriptors)
            d[index] = value
            with self.assertRaises(ValueError): validate(replace(image, descriptors=tuple(d)))
        t = list(image.tokens)
        t[0] |= 1
        with self.assertRaises(ValueError): validate(replace(image, tokens=tuple(t)))
        t = list(image.templates)
        t[0] |= 1 << 116
        with self.assertRaises(ValueError): validate(replace(image, templates=tuple(t)))

    def test_slh_full_program(self):
        job, msg = default_job("slh")
        machine = Machine(compile_image("slh"), job)
        output = machine.run(False)
        params = slh_dsa.SLH_DSA_SHAKE_128F
        sk, pk = slh_dsa.keygen_internal(params, job.secret, job.prf, job.public)
        self.assertEqual(output, sk+pk)
        self.assertEqual(machine.hashes, 4495)
        self.assertEqual(machine.permutations, 4527)
        signature = machine.run(True, msg)
        self.assertEqual(hashlib.sha256(signature).hexdigest(),
            "3f67c5420ba7d1b58c1149e260843dd658f0ff3049326ec246adb4697f8c6419")
        self.assertEqual(machine.permutations, 105641)
        self.assertTrue(slh_dsa.verify_internal(params, msg, signature, pk))
        for length in (8, 31, 64, 87):
            message = bytes(range(length))
            self.assertEqual(machine.run(True, message), slh_dsa.sign_internal(params, message, sk))

    def test_stateful_full_programs(self):
        manifest = json.loads((KAT / "stateful_hbs_rtl_vectors.json").read_text())
        for name, stem, key in (("xmss", "xmss", "xmss"),
                                ("lms", "lms_shake", "lms_shake_research")):
            with self.subTest(name=name):
                job, msg = default_job(name)
                machine = Machine(compile_image(name, full_cache=True), job)
                with self.assertRaisesRegex(ValueError, "keygen required"): machine.run(True, msg)
                output = machine.run(False)
                self.assertEqual(output, memory(stem+"_stateful_keygen_bytes.mem"))
                self.assertEqual(machine.hashes, manifest[key]["keygen_contexts"])
                self.assertEqual(machine.permutations, manifest[key]["keygen_permutations"])
                self.assertEqual(len(machine.cache), 2047)
                # Independently rebuild every tree node, not just its root.
                nodes = {}
                address = [0]*8
                counts = [0, 0]
                def observe(kind, data, result):
                    counts[0] += 1
                    counts[1] += len(data)//136+1
                    if name == "xmss":
                        if kind == "prf":
                            address[:] = [int.from_bytes(data[-32+i:-32+i+4] if i<28 else data[-4:], "big")
                                          for i in range(0, 32, 4)]
                        elif kind == "thash_h":
                            if address[3] == 2:
                                nodes[address[5]+1, address[6]] = result
                            elif address[3] == 1 and address[5] == 6:
                                nodes[0, address[4]] = result
                    elif kind in ("merkle_leaf", "merkle_internal"):
                        number = int.from_bytes(data[16:20], "big")
                        level = 10-(number.bit_length()-1)
                        nodes[level, number-(1 << (10-level))] = result
                if name == "xmss":
                    xmss._treehash(xmss.XMSS_SHAKE256_10_256, job.secret, job.public, job.q, observe)
                else:
                    lms_shake.tree_and_authentication(job.identifier, job.secret, job.q, observe=observe)
                self.assertEqual(nodes, machine.cache)
                self.assertEqual(counts, [machine.hashes, machine.permutations])
                before = machine.q
                with self.assertRaisesRegex(ValueError, "commit"): machine.run(True, msg, commit=False)
                self.assertEqual(machine.q, before)
                signature = machine.run(True, msg)
                self.assertEqual(signature, memory(stem+"_stateful_sign_bytes.mem"))
                self.assertEqual(machine.hashes, manifest[key]["sign_contexts"])
                self.assertEqual(machine.permutations, manifest[key]["sign_permutations"])
                self.assertEqual(machine.q, before+1)
                self.assertEqual(machine.run(True, msg), memory(stem+"_stateful_sign_q6_bytes.mem"))
                # Cached authentication and q boundary exercise the same program.
                for q in (0, 1023):
                    machine.q = q
                    signature = machine.run(True, msg)
                    if name == "xmss":
                        self.assertTrue(xmss.xmss_verify(output[-64:], msg, signature))
                    else:
                        self.assertTrue(lms_shake.verify(output[-56:], msg, signature))
                with self.assertRaisesRegex(ValueError, "exhausted"): machine.run(True, msg)
                self.assertEqual(machine.q, 1024)
                # A post-commit execution failure burns q and invalidates cache.
                machine.q = 7
                machine.cache.pop((0, 6))
                with self.assertRaises(KeyError): machine.run(True, msg)
                self.assertEqual(machine.q, 8)
                self.assertFalse(machine.cache_valid)
                self.assertEqual(machine.output, b"")

    def test_selected_authentication_cache(self):
        for name, stem in (("xmss", "xmss"), ("lms", "lms_shake")):
            job, message = default_job(name)
            machine = Machine(compile_image(name), job)
            self.assertEqual(machine.run(False), memory(stem+"_stateful_keygen_bytes.mem"))
            self.assertEqual(len(machine.cache), 11)
            self.assertEqual(machine.run(True, message), memory(stem+"_stateful_sign_bytes.mem"))
            before = machine.q
            with self.assertRaisesRegex(ValueError, "another index"): machine.run(True, message)
            self.assertEqual(machine.q, before)


if __name__ == "__main__":
    unittest.main()
