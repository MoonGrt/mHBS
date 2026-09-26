#!/usr/bin/env python3
"""Execute and seal the compact-image software gate before RTL modification."""
import hashlib
import json
import sys
from dataclasses import replace
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from model.slh64 import CompactMachine, pack, FORMAT, LAYOUT_REVISION
from model.unified_hbs import Machine, compile_image
from model.reference import slh_dsa
from tests.test_unified_hbs import default_job, KAT

OUT=ROOT/'manifests/experiments/unified_hbs_v4.2'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def digest(data):return hashlib.sha256(data).hexdigest()

class Observation:
    def __init__(self,n):
        self.n=n;self.counts=[0,0];self.trace=hashlib.sha256();self.nodes={}
    def __call__(self,kind,data,result):
        self.counts[0]+=1;self.counts[1]+=len(data)//136+1
        self.trace.update(len(data).to_bytes(4,'little')+data+result)
        # Addressed Merkle/FORS nodes have domain 2/3 and a full 32-byte ADRS.
        n=self.n
        if len(data) in (2*n+32,3*n+32):
            adr=data[n:n+32];domain=int.from_bytes(adr[16:20],'big')
            if domain in (2,3):self.nodes[adr.hex()]=result.hex()
    def record(self):
        return dict(counts=self.counts,hash_trace_sha256=self.trace.hexdigest(),
                    nodes=len(self.nodes),nodes_sha256=digest(json.dumps(self.nodes,sort_keys=True).encode()))

def main():
    OUT.mkdir(parents=True,exist_ok=True)
    records={};errors=[]
    for name in ('slh_128f','slh_192f','slh_256f'):
        job,msg=default_job(name);n=len(job.secret)
        params=getattr(slh_dsa,f'SLH_DSA_SHAKE_{n*8}F')
        independent=Observation(n)
        sk,pk=slh_dsa.keygen_internal(params,job.secret,job.prf,job.public,independent)
        kat=json.loads(next(KAT.glob(f'slh_dsa_shake_{n*8}f_siggen_acvp_tc*.json')).read_text())
        assert sk+pk==bytes.fromhex(kat['sk']+kat['pk'])
        root=pk[n:]
        legacy_observe=Observation(n)
        legacy=Machine(compile_image(name),job,legacy_observe)
        expected=legacy.run(False)
        assert expected==sk+pk and legacy_observe.counts==independent.counts
        assert legacy_observe.nodes==independent.nodes
        for sign in (False,True):
            op='sign' if sign else 'keygen'
            if sign:
                legacy_observe=Observation(n);legacy.observe=legacy_observe
                expected=legacy.run(True,msg)
                independent=Observation(n)
                ref=slh_dsa.sign_internal(params,msg,sk,observe=independent)
                assert expected==ref and digest(ref)==kat['signature_sha256']
                assert slh_dsa.verify_internal(params,msg,expected,pk)
                # Reference algorithm revisits some chains. Node values agree;
                # exact optimized counts/trace are checked against ABI 4 below.
                common=independent.nodes.keys() & legacy_observe.nodes.keys()
                assert common and all(independent.nodes[k]==legacy_observe.nodes[k] for k in common)
            image=pack(name,job,msg,root,sign)
            observer=Observation(n);machine=CompactMachine(image,observer)
            actual=machine.run()
            assert actual==expected
            assert observer.record()==legacy_observe.record()
            assert machine.machine.roots==legacy.roots
            try:machine.run()
            except ValueError:pass
            else:raise AssertionError('restarted after halt')
            folder=OUT/'images'/name/op;image.write(folder)
            (folder/'expected.mem').write_text(''.join(f'{b:02x}\n' for b in actual))
            metadata=[len(actual),*observer.counts,int(sign),n]
            (folder/'metadata.mem').write_text(''.join(f'{v:08x}\n' for v in metadata))
            r=dict(output_sha256=digest(actual),bytes=len(actual),**observer.record(),
                   image_sha256={p.name:sha(p) for p in folder.glob('*.mem')})
            records[f'{name}/{op}']=r
            print('V42_MODEL_PASS',name,op,r['bytes'],observer.counts,flush=True)
        for field_name,index,bit in [('program',0,0),('templates',0,63),('descriptors',0,63),
                                      ('program',52,63),('program',63,63),('descriptors',31,1)]:
            words=list(getattr(image,field_name));words[index]^=1<<bit
            try:replace(image,**{field_name:tuple(words)}).decode()
            except ValueError:errors.append(f'{name}:{field_name}:{index}:{bit}')
            else:raise AssertionError('invalid compact image accepted')
    sources=[*ROOT.glob('model/**/*.py'),ROOT/'tests/test_unified_hbs.py',Path(__file__)]
    record=dict(version='v4.2',physical_format=FORMAT,layout_revision=LAYOUT_REVISION,abi_semantics=4,passed=True,
                profiles=records,rejected_cases=errors,source_sha256={str(p.relative_to(ROOT)):sha(p) for p in sorted(sources)})
    (OUT/'software_gate.json').write_text(json.dumps(record,indent=2)+'\n')
    print('V42_SOFTWARE_GATE_PASS',len(records),flush=True)
if __name__=='__main__':main()
