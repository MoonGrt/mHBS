#!/usr/bin/env python3
"""Check migration ABI, standard serializers, q bounds and retained SLH images."""
import json
import argparse
from dataclasses import replace
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from model.profiles import PROFILES,get_profile,profile_names
from model.executor import Job,Machine,compile_image,field,Kind
from model.mHBS import compile_external,ExternalImage
from model.reference.stateful_shake import hardware_verify_input,verify_serialized,parse_signature

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--hash',dest='hash_backend',choices=('shake','sha2'),default='shake')
    args=parser.parse_args();backend=args.hash_backend
    root=Path(__file__).resolve().parents[1]
    vectors=root/'tb/vectors' if backend=='shake' else root/'tb/vectors/sha2'
    for name in profile_names(backend):
        p=get_profile(name,backend)
        image=compile_image(p.name,hash_backend=backend);external=compile_external(p.name,backend);decoded=external.decode(backend)
        assert decoded.h==p.h and image.output_bytes(True)==p.signature_bytes
        assert decoded.hash_backend==backend and external.hash_backend==backend
        assert replace(image).hash_backend==backend
        assert replace(external).hash_backend==backend
        for bit in (6,31,63):
            descriptors=list(external.descriptors);descriptors[1]|=1<<bit
            try:replace(external,descriptors=tuple(descriptors)).decode(backend);raise AssertionError('reserved backend bits accepted')
            except ValueError:pass
        try:external.decode('sha2' if backend=='shake' else 'shake');raise AssertionError('wrong ROM backend accepted')
        except ValueError:pass
        if not p.stateful:
            for op in ('keygen','sign','verify'):
                if not (vectors/p.name/op/'descriptor.mem').exists():continue
                old=ExternalImage.read(vectors/p.name/op)
                assert old==external
                assert old.hash_backend==backend and old.decode(backend).hash_backend==backend
            continue
        assert image.hp==p.h and image.output_bytes(False)==p.keygen_bytes and p.chains==67
        for desc in image.descriptors:
            if desc>>60==Kind.TREE:assert (field(desc,40,4)|(field(desc,39,1)<<4))==p.h
        z=bytes(32)
        Machine(image,Job(z,z,z,z,q=(1<<p.h)-1))
        try:Machine(image,Job(z,z,z,z,q=1<<p.h));raise AssertionError('q overflow accepted')
        except ValueError:pass
        fake=(1<<p.h).to_bytes(4,'big')+bytes(p.signature_bytes-4)
        try:parse_signature(p.name,fake,backend);raise AssertionError('signature q overflow accepted')
        except ValueError:pass
        vector=vectors/p.name
        if not (vector/'sign/expected.mem').exists():
            print('STANDARD_CODEC_PASS',p.name,'fixture pending');continue
        def mem(op,name):return bytes(int(x,16) for x in (vector/op/name).read_text().split())
        pk,sig=mem('keygen','expected.mem'),mem('sign','expected.mem')
        job=[int(x,16) for x in (vector/'sign/job.mem').read_text().split()]
        message=mem('sign','message.mem')[:job[8]]
        assert verify_serialized(p.name,message,sig,pk,hash_backend=backend)
        assert len(hardware_verify_input(p.name,sig,pk,backend)['nodes'])==68+p.h
        assert not verify_serialized(p.name,message,sig,pk[:-1],hash_backend=backend)
        bad=bytearray(pk);bad[3]^=1;assert not verify_serialized(p.name,message,sig,bad,hash_backend=backend)
        assert not verify_serialized(p.name,message,sig[:-1],pk,hash_backend=backend)
        assert not verify_serialized(p.name,message,sig,pk,hash_backend='sha2' if backend=='shake' else 'shake')
        for other in PROFILES.values():
            if other.family==p.family and other.h!=p.h:
                assert not verify_serialized(other.name,message,sig,pk,hash_backend=backend)
        print('STANDARD_CODEC_PASS',p.name)
    assert get_profile('xmss').name=='xmss_h10' and get_profile('lms').name=='lms_h10'
    from model.stateful import encode,cold_image
    for alias in ('xmss','lms'):
        canonical=get_profile(alias,backend).name
        assert encode(alias,backend)==encode(canonical,backend)
        assert cold_image(alias,backend).hash_backend==backend
        assert get_profile(alias,backend).hash_backend==backend
    for legacy in ('xmss_omega2','xmss_omega4','lms_omega2','lms_omega4'):
        try:get_profile(legacy);raise AssertionError('legacy accepted')
        except ValueError as e:assert 'retired' in str(e)
    if backend=='sha2':
        for name in ('slh_192f','slh_256f','slh_192s','slh_256s'):
            try:get_profile(name,backend);raise AssertionError('unsupported SHA2 profile accepted')
            except ValueError:pass
        image=compile_image('lms_h10',hash_backend=backend)
        assert any(field(d,24,6)==34 for d in image.descriptors if d>>60==Kind.HASH)
    print('STANDARD_MODEL_PASS',backend)

if __name__=='__main__':main()
