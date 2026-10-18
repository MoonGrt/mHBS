#!/usr/bin/env python3
"""Check standard SHAKE stateful wire adapters with Verify-only synthetic paths.

No full tree is generated.  High-tree paths are independent synthetic siblings;
these checks establish serialization/rejection semantics, not Keygen or Sign.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from model.microcode import ABI
from model.profiles import STATEFUL_NAMES,get_profile
from model.reference.stateful_shake import reference
from model.stateful import (decode_public_key,nodes_to_signature,payload_to_signature,
    signature_to_nodes,signature_to_payload,validate_message)
from model.vectors import generate_fixture


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def rejected(function):
    try:function()
    except (ValueError,OverflowError):return
    raise AssertionError('invalid wire representation was accepted')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,default=ROOT/'build/stateful_models/adapter_rejection.json')
    args=parser.parse_args()
    sources=['model/'+name for name in ('profiles.py','microcode.py','mHBS.py','stateful.py',
        'vectors.py','executor.py','default_jobs.json','reference/xmss.py','reference/lms.py',
        'reference/stateful_shake.py')]+['scripts/check_stateful_adapter.py']
    identity={name:sha(ROOT/name) for name in sources}
    rows={};checks=0
    for name in STATEFUL_NAMES:
        p=get_profile(name);module=reference(p.family)
        qs=sorted({0,1,(1<<p.h)-1,*[q for q in (1023,1024,32767,32768,65535,65536) if q<1<<p.h]})
        for q in qs:
            message=(b'',b'\xa5',bytes(range(87)))[q%3]
            fixture=generate_fixture(name,'verify',q=q,message=message,synthetic=True)
            pk,sig=fixture['standard_pk'],fixture['standard_sig']
            assert fixture['synthetic'] and fixture['operation']==2
            assert len(pk)==p.public_key_bytes and len(sig)==p.signature_bytes
            assert sig[:4]==q.to_bytes(4,'big')
            assert module.verify(pk,message,sig)
            index,nodes=signature_to_nodes(name,sig)
            assert index==q and len(nodes)==68+p.h
            assert nodes_to_signature(name,q,nodes)==sig
            assert signature_to_payload(name,sig)==(q,fixture['signature'])
            assert payload_to_signature(name,q,fixture['signature'])==sig
            assert decode_public_key(name,pk).to_bytes()==pk
            count=7
            for bad in (sig[:-1],sig+b'\x00',(1<<p.h).to_bytes(4,'big')+sig[4:]):
                rejected(lambda bad=bad:signature_to_nodes(name,bad));count+=1
            for bad in (pk[:-1],pk+b'\x00',pk[:4][::-1]+pk[4:],b'\xff'*4+pk[4:]):
                rejected(lambda bad=bad:decode_public_key(name,bad));count+=1
            rejected(lambda:nodes_to_signature(name,1<<p.h,nodes));count+=1
            rejected(lambda:nodes_to_signature(name,-1,nodes));count+=1
            for other in STATEFUL_NAMES:
                if other!=name and get_profile(other).family==p.family:
                    rejected(lambda other=other:signature_to_nodes(other,sig));count+=1
                    rejected(lambda other=other:decode_public_key(other,pk));count+=1
            # A reversed q either exceeds the tree's range or parses as a
            # different valid q. In the latter case the cryptographic Verify
            # must fail even though the signature length is still correct.
            reversed_q=int.from_bytes(sig[:4][::-1],'big')
            if reversed_q!=q:
                bad=sig[:4][::-1]+sig[4:]
                if reversed_q>=1<<p.h:
                    rejected(lambda:signature_to_nodes(name,bad))
                else:
                    assert signature_to_nodes(name,bad)[0]==reversed_q
                    assert not module.verify(pk,message,bad)
                count+=1
            if p.family=='lms':
                middle=8+32*68
                for offset in (4,middle):
                    bad=bytearray(sig);bad[offset:offset+4]=(3 if offset==4 else 6).to_bytes(4,'big')
                    rejected(lambda bad=bad:signature_to_nodes(name,bytes(bad)));count+=1
                    bad=bytearray(sig);bad[offset:offset+4]=sig[offset:offset+4][::-1]
                    rejected(lambda bad=bad:signature_to_nodes(name,bytes(bad)));count+=1
                bad=pk[:4]+(3).to_bytes(4,'big')+pk[8:]
                rejected(lambda:decode_public_key(name,bad));count+=1
            rows[f'{name}/verify/q{q}']=dict(passed=True,synthetic=True,height=p.h,q=q,
                message_bytes=len(message),checks=count,signature_bytes=len(sig),public_key_bytes=len(pk),
                standard_type=p.typecode,lmots_type=p.lmots_typecode if p.family=='lms' else None,
                payload_sha256=hashlib.sha256(fixture['signature']).hexdigest())
            checks+=count
        if p.h>10:
            for op in ('keygen','sign'):
                rejected(lambda op=op:generate_fixture(name,op));checks+=1
    assert validate_message(b'')==b'' and validate_message(bytes(87))==bytes(87)
    rejected(lambda:validate_message(bytes(88)));checks+=3
    if any(sha(ROOT/name)!=value for name,value in identity.items()):
        raise RuntimeError('adapter sources changed during verification')
    result=dict(passed=True,abi=ABI,hash_backend='shake',cases=rows,case_count=len(rows),checks=checks,
        source_sha256=identity,high_tree_paths='Verify-only synthetic authentication siblings',
        high_tree_keygen_sign='not_generated_or_run',
        coverage=['six_profiles','standard_lengths_types','q_and_type_big_endian','q_out_of_range',
                  'cross_height_signature_and_public_key','truncation_and_extension','wrong_XMSS_OID',
                  'wrong_LMS_and_LMOTS_types','message_0_87_88','no_high_tree_full_generation'])
    args.out.parent.mkdir(parents=True,exist_ok=True)
    args.out.write_text(json.dumps(result,indent=2,sort_keys=True)+'\n')
    print('STATEFUL_ADAPTER_PASS',len(rows),'Verify-only fixtures;',checks,'checks;',args.out)


if __name__=='__main__':main()
