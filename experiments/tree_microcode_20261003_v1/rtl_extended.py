#!/usr/bin/env python3
"""External-input integration: actual RTL root transfer and stalled message streams."""
import concurrent.futures,json,shutil,sys
from pathlib import Path
WORKSPACE=Path(__file__).resolve().parents[2]/'build/tree_microcode_20261003_v1'
sys.path.insert(0,str(WORKSPACE/'scripts'))
from v42_external_flow import ROOT,BASE,BUILD,NAMES,identity,sha,write,simulate_case,capture
sys.path.insert(0,str(ROOT))
from model.unified_hbs import Machine,compile_image
from model.reference import slh_dsa
from tests.slh_fixtures import default_job
f=capture(sys.argv[1]);normal=json.loads((f/'simulation.json').read_text());assert normal['passed'] and normal['rtl_sha256']==identity()
assert set(normal['cases'])=={n+'_'+o for n in NAMES for o in ('keygen','sign')},'run rtl-all-profiles first'

def vector(folder,name,job,root,msg):
 m=Machine(compile_image(name),job);m.values[3]=root;expected=m.run(True,msg)
 params=getattr(slh_dsa,f'SLH_DSA_SHAKE_{len(root)*8}{name[-1].upper()}');sk=job.secret+job.prf+job.public+root
 assert expected==slh_dsa.sign_internal(params,msg,sk)
 folder.mkdir(parents=True,exist_ok=True)
 cfg=json.loads((BASE/'vectors'/name/'sign/job.json').read_text());cfg.update(public_root=root.hex(),message_bytes=len(msg))
 write(folder/'job.json',cfg)
 (folder/'expected.mem').write_text(''.join(f'{b:02x}\n' for b in expected))
 (folder/'message.mem').write_text(''.join(f'{b:02x}\n' for b in msg))
 (folder/'metadata.mem').write_text(''.join(f'{x:08x}\n' for x in (len(expected),m.hashes,m.permutations,1,len(root),len(msg))))
 return folder

def profile(name):
 result={};job,msg=default_job(name);n=len(job.secret)
 kg_file=f/'logs'/(name+'_keygen.actual.mem');kg=bytes(int(x,16) for x in kg_file.read_text().split());root=kg[3*n:4*n]
 assert root==kg[5*n:6*n]
 v=vector(f/'extended_vectors'/name/'rtl_root',name,job,root,msg)
 for label,swap,opts in [('root_transfer',0,()),('swap',1,()),('stall',0,('+STALL=1','+TAIL_NOISE=1')),('replay',0,('+INTERRUPT=1','+REPLAYS=2'))]:
  k,r=simulate_case(f,name+'_'+label,v,swap,opts)
  assert r['sign_cycles']-r['wait_cycles']==normal['cases'][name+'_sign']['sign_cycles']
  r['keygen_output_sha256']=sha(kg_file);result[k]=r
 k,r=simulate_case(f,name+'_keygen_replay',BASE/'vectors'/name/'keygen',1,('+INTERRUPT=1','+REPLAYS=2'))
 assert r['keygen_cycles']==normal['cases'][name+'_keygen']['keygen_cycles'];result[k]=r
 for size in (1,7,8,9,87):
  v=vector(f/'extended_vectors'/name/str(size),name,job,root,bytes(range(size)))
  k,r=simulate_case(f,name+'_message_'+str(size),v,0,('+TAIL_NOISE=1',));result[k]=r
  if size==87:
   k,t=simulate_case(f,name+'_message_87_stall',v,0,('+TAIL_NOISE=1','+STALL=1'))
   assert t['sign_cycles']-t['wait_cycles']==r['sign_cycles'];result[k]=t
 for label,kw in [('no_profile',dict(profile_enable=False)),('partition',dict(partitioned=True))]:
  k,r=simulate_case(f,name+'_'+label,BASE/'vectors'/name/'sign',**kw)
  assert r['sign_cycles']==normal['cases'][name+'_sign']['sign_cycles'];result[k]=r
 from v42_external_flow import build_binary,run
 cfg=json.loads((BASE/'vectors'/name/'sign/job.json').read_text())
 exe=build_binary(f,cfg)
 for fault in (1,2):
  log=f/'logs'/f'{name}_fault_{fault}.log'
  run([str(exe),'+IMAGE='+str(BASE/'images'/name),'+VECTOR='+str(BASE/'vectors'/name/'sign'),f'+FAULT={fault}'],log)
  assert 'V42_FAULT_PASS' in log.read_text()
  result[f'{name}_fault_{fault}']=dict(passed=True,log_sha256=sha(log))
 return result
if '--append-stall'  in sys.argv:
 previous=json.loads((f/'extended.json').read_text());assert previous['rtl_sha256']==identity()
 shutil.copy2(f/'extended.json',f/'extended_previous.json');cases=previous['cases']
 for name in NAMES:
  v=f/'extended_vectors'/name/'87'
  k,r=simulate_case(f,name+'_message_87_stall',v,0,('+TAIL_NOISE=1','+STALL=1'))
  assert r['sign_cycles']-r['wait_cycles']==cases[name+'_message_87']['sign_cycles'];cases[k]=r
else:
 with concurrent.futures.ThreadPoolExecutor(3) as pool:
  cases={k:v for group in pool.map(profile,NAMES) for k,v in group.items()}
write(f/'extended.json',dict(passed=True,rtl_sha256=identity(),cases=cases,driver_sha256=sha(Path(__file__))))
print('EXTERNAL_EXTENDED_PASS',len(cases),flush=True)
