#!/usr/bin/env python3
"""Extended verification of sealed RTL, including actual Keygen-root transfer."""
import concurrent.futures,json,shutil,subprocess,sys,tarfile
from dataclasses import replace
from pathlib import Path
from v42_flow import ROOT,BUILD,BASE,NAMES,sha,write,run
f=BUILD/sys.argv[1];inp=json.loads((f/'inputs.json').read_text());out=f/'verification';out.mkdir(exist_ok=True)
workspace=out/'source';workspace.mkdir(exist_ok=True)
with tarfile.open(f/'source_snapshot.tar.gz') as t:t.extractall(workspace,filter='data')
for path,digest in inp['rtl_sha256'].items():assert sha(workspace/path)==digest
sys.path.insert(0,str(workspace))
from model.slh64 import CompactImage,CompactMachine,TO_PHYSICAL,pack
from model.unified_hbs import field
from model.reference import slh_dsa
from tests.test_unified_hbs import default_job
bench=out/'tb_mhbs_v42.sv';shutil.copy2(ROOT/'tb/integration/tb_mhbs_v42.sv',bench)
rtl=(workspace/'manifests/v42_sources.txt').read_text().split()
for swap in (0,1):
 binary=out/f'obj_s{swap}/Vtb_mhbs_v42'
 run(['verilator','--binary','--timing','-O3','-j','8','-Wno-fatal','-Wno-WIDTH','-Wno-UNOPTFLAT','--top-module','tb_mhbs_v42',f'-GSWAP={swap}',
      '--Mdir',str(binary.parent),*rtl,str(bench)],out/f'compile_s{swap}.log',workspace)

def materialize(image,folder):
 image.write(folder);model=CompactMachine(image);expected=model.run()
 (folder/'expected.mem').write_text(''.join(f'{b:02x}\n' for b in expected))
 logical,job,root,msg,sign=image.decode()
 (folder/'metadata.mem').write_text(''.join(f'{x:08x}\n' for x in (len(expected),model.machine.hashes,model.machine.permutations,int(sign),logical.n)))
 cmds=[]
 for w in logical.words(sign)[:-1]:
  op,did,rid,flags,coord=(field(w,s,b) for s,b in ((96,4),(88,8),(80,8),(76,4),(52,24)))
  cmds.append((op<<44)|(TO_PHYSICAL[did]<<36)|(TO_PHYSICAL[rid]<<28)|(flags<<24)|coord)
 (folder/'commands.mem').write_text(''.join(f'{x:012x}\n' for x in cmds))
 return len(cmds),expected

records={}
def one(item):
 name,image,options,swap=item;folder=out/'images'/name;folder.mkdir(parents=True,exist_ok=True)
 count,expected=materialize(image,folder)
 cmd=[str(out/f'obj_s{swap}/Vtb_mhbs_v42'),'+IMAGE='+str(folder),'+TRACE='+str(folder/'commands.mem'),f'+TRACE_WORDS={count}',
      '+DUMP='+str(folder/'actual.mem'),*options]
 log=out/(name.replace('/','_')+'.log');run(cmd,log,workspace)
 token='V42_FAULT_PASS' if any(x.startswith('+FAULT=') for x in options) else 'V42_PASS'
 assert token in log.read_text()
 record=dict(passed=True,swap=swap,options=options,log_sha256=sha(log),image_sha256={p.name:sha(p) for p in folder.glob('*.mem')})
 print('V42_EXTENDED_PASS',name,flush=True)
 return name,record
# First obtain actual RTL Keygen bytes, then build cold Sign images from their roots.
with concurrent.futures.ThreadPoolExecutor(3) as pool:
 records.update(pool.map(one,[(n+'/keygen',CompactImage.read(workspace/'manifests/experiments/unified_hbs_v4.2/images'/n/'keygen'),[],0) for n in NAMES]))
jobs=[]
for name in NAMES:
 job,msg=default_job(name);n=len(job.secret)
 kg=bytes(int(w,16) for w in (out/'images'/name/'keygen/actual.mem').read_text().split())
 root=kg[3*n:4*n];assert root==kg[5*n:6*n]
 image=pack(name,job,msg,root,True)
 jobs.extend([(name+'/root_transfer',image,[],0),(name+'/swap',image,[],1),
              (name+'/replay',image,['+INTERRUPT=1','+REPLAYS=2'],0),
              (name+'/keygen_replay',pack(name,job,msg,root,False),['+INTERRUPT=1','+REPLAYS=2'],1),
              (name+'/fault_before',image,['+FAULT=1'],0),(name+'/fault_output',image,['+FAULT=2'],0)])
 for size in (8,31,64,87):
  message=bytes(range(size));case=pack(name,job,message,root,True)
  params=getattr(slh_dsa,f'SLH_DSA_SHAKE_{n*8}F')
  expected=slh_dsa.sign_internal(params,message,kg[:4*n])
  assert CompactMachine(case).run()==expected
  jobs.append((name+f'/message_{size}',case,[],0))
 # Three independent valid microcode mutations: sequence coordinate, template macro, hash recipe.
 kg_image=pack(name,job,msg,root,False)
 words=list(kg_image.program);words[0]-=64<<47
 jobs.append((name+'/program_mutation',replace(kg_image,program=tuple(words)),[],0))
 words=list(kg_image.templates);words[0]=(words[0]&~255)|2|(TO_PHYSICAL[17]<<3)
 jobs.append((name+'/template_mutation',replace(kg_image,templates=tuple(words)),[],0))
 words=list(kg_image.descriptors);words[TO_PHYSICAL[10]]^=1<<48
 jobs.append((name+'/descriptor_mutation',replace(kg_image,descriptors=tuple(words)),[],0))
with concurrent.futures.ThreadPoolExecutor(3) as pool:records.update(pool.map(one,jobs))
write(out/'results.json',dict(passed=True,rtl_sha256=inp['rtl_sha256'],bench_sha256=sha(bench),driver_sha256=sha(Path(__file__)),cases=records))
print('V42_EXTENDED_GATE_PASS',len(records),flush=True)
