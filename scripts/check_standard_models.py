#!/usr/bin/env python3
"""Check migration ABI, standard serializers, q bounds and retained SLH images."""
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from model.profiles import PROFILES,get_profile
from model.executor import Job,Machine,compile_image,field,Kind
from model.mHBS import compile_external,ExternalImage
from model.reference.stateful_shake import hardware_verify_input,verify_serialized,parse_signature

def main():
    root=Path(__file__).resolve().parents[1]
    for p in PROFILES.values():
        image=compile_image(p.name);external=compile_external(p.name);decoded=external.decode()
        assert decoded.h==p.h and image.output_bytes(True)==p.signature_bytes
        if not p.stateful:
            for op in ('keygen','sign','verify'):
                old=ExternalImage.read(root/'tb/vectors'/p.name/op)
                assert old==external
            continue
        assert image.hp==p.h and image.output_bytes(False)==p.keygen_bytes and p.chains==67
        for desc in image.descriptors:
            if desc>>60==Kind.TREE:assert (field(desc,40,4)|(field(desc,39,1)<<4))==p.h
        z=bytes(32)
        Machine(image,Job(z,z,z,z,q=(1<<p.h)-1))
        try:Machine(image,Job(z,z,z,z,q=1<<p.h));raise AssertionError('q overflow accepted')
        except ValueError:pass
        fake=(1<<p.h).to_bytes(4,'big')+bytes(p.signature_bytes-4)
        try:parse_signature(p.name,fake);raise AssertionError('signature q overflow accepted')
        except ValueError:pass
        vector=root/'tb/vectors'/p.name
        if not (vector/'sign/expected.mem').exists():
            print('STANDARD_CODEC_PASS',p.name,'fixture pending');continue
        def mem(op,name):return bytes(int(x,16) for x in (vector/op/name).read_text().split())
        pk,sig=mem('keygen','expected.mem'),mem('sign','expected.mem')
        assert verify_serialized(p.name,mem('sign','message.mem')[:1],sig,pk)
        assert len(hardware_verify_input(p.name,sig,pk)['nodes'])==68+p.h
        assert not verify_serialized(p.name,b'\x42',sig,pk[:-1])
        bad=bytearray(pk);bad[3]^=1;assert not verify_serialized(p.name,b'\x42',sig,bad)
        assert not verify_serialized(p.name,b'\x42',sig[:-1],pk)
        for other in PROFILES.values():
            if other.family==p.family and other.h!=p.h:
                assert not verify_serialized(other.name,b'\x42',sig,pk)
        print('STANDARD_CODEC_PASS',p.name)
    assert get_profile('xmss').name=='xmss_h10' and get_profile('lms').name=='lms_h10'
    for legacy in ('xmss_omega2','xmss_omega4','lms_omega2','lms_omega4'):
        try:get_profile(legacy);raise AssertionError('legacy accepted')
        except ValueError as e:assert 'retired' in str(e)
    print('STANDARD_MODEL_PASS')

if __name__=='__main__':main()
