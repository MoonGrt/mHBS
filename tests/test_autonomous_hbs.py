"""Image-only boot against the independently verified ABI 4 execution model."""
from dataclasses import replace
import unittest
from unittest.mock import patch
from model.autonomous_hbs import pack,AutonomousMachine
from model.profiles import PROFILES
from model.unified_hbs import Machine,compile_image
from tests.test_unified_hbs import default_job

class AutonomousTests(unittest.TestCase):
    def test_seven_programs(self):
        for name,p in PROFILES.items():
            with self.subTest(profile=name):
                print('AUTONOMOUS_MODEL_BEGIN',name,flush=True)
                job,message=default_job(name)
                image=pack(name,job,message)
                decoded,actual_job,actual_message=image.decode()
                self.assertEqual((actual_job,actual_message),(job,message))
                expected_hashes=[];actual_hashes=[]
                observe=lambda log: lambda rid,data,result:log.append((rid,data,result))
                reference=Machine(compile_image(name),job,observe(expected_hashes))
                kg=reference.run(False);kgcounts=(reference.hashes,reference.permutations)
                sg=reference.run(True,message);sgcounts=(reference.hashes,reference.permutations)
                actual=AutonomousMachine(image,observe(actual_hashes))
                self.assertEqual(actual.run(),(kg,sg))
                self.assertEqual(actual.stats,dict(keygen=kgcounts,sign=sgcounts))
                self.assertEqual(actual_hashes,expected_hashes)
                self.assertEqual(actual.machine.cache,reference.cache)
                self.assertEqual(actual.machine.q,job.q)
                self.assertEqual(reference.q,job.q+int(p.stateful))
                with self.assertRaisesRegex(ValueError,'halted'):actual.run()
                print('AUTONOMOUS_MODEL_PASS',name,flush=True)

    def test_fixed_index_cache_and_failure(self):
        for name,p in PROFILES.items():
            job,msg=default_job(name)
            if p.stateful:
                for q in (0,5,1023):
                    fixed_job=replace(job,q=q)
                    machine=Machine(compile_image(name),fixed_job,index_policy='fixed_q_no_guard')
                    with self.assertRaisesRegex(ValueError,'keygen required'):
                        machine.run(True,msg,commit=False)
                    machine.cache_valid=True;machine.cache_q=q^1
                    with self.assertRaisesRegex(ValueError,'another index'):
                        machine.run(True,msg,commit=False)
                    self.assertEqual(machine.q,q)
            actual=AutonomousMachine(pack(name,job,msg))
            with patch.object(actual.machine,'run',side_effect=ValueError('execution fault')):
                with self.assertRaisesRegex(ValueError,'execution fault'):actual.run()
            self.assertTrue(actual.error)
            self.assertEqual(actual.machine.q,job.q)
            with self.assertRaisesRegex(ValueError,'halted'):actual.run()

    def test_invalid_images(self):
        for name,p in PROFILES.items():
            job,msg=default_job(name);image=pack(name,job,msg)
            for index,word in ((41,image.program[41]|(1<<100)),(41,image.program[41]&~(127<<11)),(42,1),(50,1),(31,1),(49,1<<120)):
                words=list(image.program);words[index]=word
                with self.assertRaises(ValueError):replace(image,program=tuple(words)).decode()
            d=list(image.descriptors);d[0]=(d[0]&~(15<<56)) | (3<<56)
            with self.assertRaises(ValueError):replace(image,descriptors=tuple(d)).decode()
            d=list(image.descriptors);d[0]=(d[0]&~(511<<38)) | (44<<38)
            with self.assertRaises(ValueError):replace(image,descriptors=tuple(d)).decode()
            for size in (1,16,17,87):
                message=bytes(range(size));self.assertEqual(pack(name,job,message).decode()[2],message)
            if p.stateful:
                for q in (0,5,1023):self.assertEqual(pack(name,replace(job,q=q),msg).decode()[1].q,q)
                with self.assertRaisesRegex(ValueError,'exhausted'):pack(name,replace(job,q=1024),msg)

    def test_recipe_profile_consistency(self):
        for name,p in PROFILES.items():
            job,msg=default_job(name);image=pack(name,job,msg)
            other=compile_image('xmss_omega4' if p.family=='slh' else 'slh_128f')
            records=list(image.descriptors);records[120]=other.descriptors[2]
            with self.assertRaisesRegex(ValueError,'recipe/profile mismatch'):
                replace(image,descriptors=tuple(records)).decode()
