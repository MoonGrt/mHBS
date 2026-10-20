#!/usr/bin/env python3
"""Independent real-height Verify paths for q/address and message boundaries."""
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from model.vectors import generate_verify_profile
from model.mHBS import ControlMachine,ExternalImage,compile_image
from model.executor import Job
from model.profiles import get_profile

def main():
    base=json.loads((ROOT/'model/default_jobs.json').read_text());rows=[]
    for backend in ('shake','sha2'):
        for name in ('xmss_h10','xmss_h16','xmss_h20','lms_h10','lms_h15','lms_h20'):
            p=get_profile(name,backend)
            indices=sorted({q for q in (0,1,1023,1024,32767,32768,65535,65536,(1<<p.h)-1) if q<1<<p.h})
            for q in indices:
                cfg=dict(base[name]);cfg['q']=q
                cfg['message']='' if q==1 else bytes(range(87)).hex() if q==(1<<p.h)-1 else '03'
                output=ROOT/'build/chain_model/boundary_vectors'/backend/str(q)
                generate_verify_profile(name,cfg,str(output),backend)
                folder=output/name/'verify'
                read=lambda n:[int(x,16) for x in (folder/n).read_text().split()]
                words=read('job.mem');seed=[x.to_bytes(32,'little') for x in words[:5]]
                job=Job(*seed[:4],identifier=words[5].to_bytes(16,'little'),q=q)
                vm=ControlMachine(ExternalImage.read(folder),job,seed[4],bytes.fromhex(cfg['message']),2,
                                  [x.to_bytes(32,'little') for x in read('nodes.mem')])
                vm.run();meta=read('meta.mem')
                assert (vm.hashes,vm.permutations)==tuple(meta[1:3])
                rows.append(dict(backend=backend,profile=name,q=q,message_bytes=len(bytes.fromhex(cfg['message'])),
                                 hashes=vm.hashes,permutations=vm.permutations,status='passed',vector=str(folder.relative_to(ROOT))))
            bad=Job(*(bytes(32) for _ in range(4)),q=1<<p.h)
            try:ControlMachine(compile_image(name,backend),bad,bytes(32),b'',2)
            except ValueError:pass
            else:raise AssertionError('out-of-range q accepted')
    result=dict(passed=True,cases=rows,q_overflow_rejections=12,full_tree_generated=False)
    out=ROOT/'build/chain_model/boundary_result.json';out.write_text(json.dumps(result,indent=2)+'\n')
    print('BOUNDARY_VERIFY_PASS',len(rows),'overflow_rejections',12)
if __name__=='__main__':main()
