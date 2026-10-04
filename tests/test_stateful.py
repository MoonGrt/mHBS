"""Experimental image ABI, signature parsing and independent verification."""
from pathlib import Path
from dataclasses import replace
import unittest
from model.stateful import PROFILE_CODES,encode,cold_image,descriptor_map
from model.reference.stateful_shake import parse_signature,verify,digits
ROOT=Path(__file__).resolve().parents[1]
class StatefulTests(unittest.TestCase):
 def test_images_and_capacity(self):
  for code,name in PROFILE_CODES.items():
   e=encode(name);i=e.decode()
   self.assertEqual(e.descriptors[1],code);self.assertEqual((len(e.program),len(e.templates),len(e.descriptors)),(16,16,32))
   self.assertEqual(i,cold_image(name));self.assertLessEqual(len(descriptor_map(i)),32)
   self.assertEqual(i.omega,2 if name.endswith('2') else 4)
   self.assertTrue(any(t&(1<<16) for t in e.templates))
   bad=list(e.templates);bad[0]^=1<<17
   with self.assertRaises(ValueError):replace(e,templates=tuple(bad)).decode()
 def test_digits(self):
  for bits,count in ((2,133),(4,67)):
   for msg in (bytes(32),b'\xff'*32,bytes(range(32))):
    ds=digits(msg,bits);self.assertEqual(len(ds),count)
    maximum=(1<<bits)-1;self.assertTrue(all(0<=x<=maximum for x in ds))
    c=0
    for d in ds[256//bits:]:c=(c<<bits)|d
    self.assertEqual(c,sum(maximum-d for d in ds[:256//bits]))
 def test_frozen_vectors_and_rejection(self):
  for name in PROFILE_CODES.values():
   d=ROOT/'manifests/experiments/stateful_20261008/vectors'/name/'q0_m1'
   sig=(d/'signature.bin').read_bytes();root=(d/'root.bin').read_bytes();public=bytes(range(81,113));ident=bytes(range(161,177))
   self.assertTrue(verify(name,b'B',sig,public,root,ident))
   self.assertFalse(verify(name,b'C',sig,public,root,ident))
   for off in (0,4,36,len(sig)-1):
    s=bytearray(sig);s[off]^=1;self.assertFalse(verify(name,b'B',bytes(s),public,root,ident))
   for s in (sig[:-1],sig+b'\0',(1024).to_bytes(4,'big')+sig[4:]):
    with self.assertRaises(ValueError):parse_signature(name,s)
   if name.startswith('lms'):
    s=bytearray(sig);s[4]^=1
    with self.assertRaises(ValueError):parse_signature(name,bytes(s))
    s=bytearray(sig);tree_offset=40+32*(133 if name.endswith('2') else 67);s[tree_offset]^=1
    with self.assertRaises(ValueError):parse_signature(name,bytes(s))
    self.assertFalse(verify(name,b'B',sig,public,root,bytes(16)))
if __name__=='__main__':unittest.main()
