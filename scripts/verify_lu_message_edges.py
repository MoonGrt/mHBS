#!/usr/bin/env python3
import sys,shutil,json
import run_lu_p1 as m
from model.slh64_external import ExternalImage,ExternalMachine
from model.reference import slh_dsa
from tests.slh_fixtures import default_job
label=sys.argv[1] if len(sys.argv)>1 else 'structure'
base=m.ROOT/'manifests/experiments/unified_hbs_v4.2/external_job_message'
name='slh_128f';job,_=default_job(name);cfg=json.loads((base/'vectors'/name/'sign/job.json').read_text());root=bytes.fromhex(cfg['public_root'])
image=ExternalImage.read(base/'images'/name);b=m.build(label,3,1);records=[]
for size in (1,7,8,9,87):
 msg=bytes(range(size));machine=ExternalMachine(image,job,root,msg,True);expected=machine.run()
 assert expected==slh_dsa.sign_internal(slh_dsa.SLH_DSA_SHAKE_128F,msg,job.secret+job.prf+job.public+root)
 d=m.OUT/'edge_vectors'/f'm{size}';shutil.copytree(m.OUT/'vectors'/name/'1',d,dirs_exist_ok=True)
 fields=(d/'job.mem').read_text().split();fields[8]=f'{size:064x}';(d/'job.mem').write_text('\n'.join(fields)+'\n')
 (d/'expected.mem').write_text(''.join(f'{v:02x}\n' for v in expected));(d/'message.mem').write_text(''.join(f'{v:02x}\n' for v in msg+bytes(87-size)))
 (d/'meta.mem').write_text(''.join(f'{v:08x}\n' for v in (len(expected),machine.machine.hashes,machine.machine.permutations,len(expected)//16,0)))
 log=m.OUT/label/'message_edges'/f'm{size}.log';m.run([b,f'+VECTOR={d}','+STALL=1'],log);assert 'STATEFUL_PASS' in log.read_text();records.append(dict(length=size,passed=True,vector_sha256={p.name:m.sha(p) for p in d.iterdir() if p.is_file()},log_sha256=m.sha(log)))
m.write(m.OUT/label/'message_edges/results.json',records);print('MESSAGE_EDGES_PASS',label)
