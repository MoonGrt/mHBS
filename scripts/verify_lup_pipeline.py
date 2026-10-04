#!/usr/bin/env python3
"""Independent SHAKE chain vectors and interleaved U/P unit checks."""
from pathlib import Path
import hashlib,json,subprocess,sys,random
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'build/lup_shared_units';OUT.mkdir(parents=True,exist_ok=True)
rng=random.Random(713)
requests=[];digests=[];captures=[]
for n in (16,24,32):
 for i in range(32):
  steps=(0,1,2,15)[i%4];cap=steps+1 if i%8==7 else (0,steps//2,steps)[i%3];enabled=i%8!=6;domain=3 if i%2 else 0
  a=rng.randrange(67);b=rng.randrange(1<<20);leaf=rng.randrange(512);tree=rng.getrandbits(64);layer=rng.randrange(22)
  req=n|(steps<<8)|(cap<<16)|(domain<<24)|(a<<32)|(b<<40)|(leaf<<72)|(tree<<88)|(layer<<152)|((not enabled)<<160)
  def address(dom,counter):return layer.to_bytes(4,'big')+bytes(4)+tree.to_bytes(8,'big')+dom.to_bytes(4,'big')+leaf.to_bytes(4,'big')+a.to_bytes(4,'big')+counter.to_bytes(4,'big')
  pk=bytes(range(32,64))[:n];val=hashlib.shake_256(pk+address(6 if domain==3 else 5,b)+bytes(range(32))[:n]).digest(n)
  captured=val if enabled and cap==0 else bytes(n)
  for j in range(steps):
   val=hashlib.shake_256(pk+address(domain,b if domain==3 else j)+val).digest(n)
   if enabled and j+1==cap:captured=val
  requests.append(f'{req:064x}');digests.append(f'{int.from_bytes(val,"little"):064x}');captures.append(f'{int.from_bytes(captured,"little"):064x}')
for name,values in [('chain_requests',requests),('chain_digest',digests),('chain_capture',captures)]:
 (OUT/(name+'.mem')).write_text('\n'.join(values)+'\n')
sources=(ROOT/'manifests/v42_sources.txt').read_text().splitlines()+['tb/unit/mhbs_batch_test_driver.sv']
records=[]
for top in ('tb_mhbs_keccak_pipeline','tb_mhbs_chain_overlap'):
 for u,p in ((1,2),(1,3),(1,4),(2,2)):
  name=f'{top}_U{u}P{p}';log=OUT/(name+'.log');binary=OUT/(name+'.vvp')
  with log.open('w') as f:
   for cmd in (['iverilog','-g2012','-s',top,f'-P{top}.UNROLL={u}',f'-P{top}.PIPELINE={p}','-o',str(binary),*sources,f'tb/unit/{top}.sv'],['vvp',str(binary),f'+VECTORS={OUT}']):
    r=subprocess.run(cmd,cwd=ROOT,stdout=f,stderr=subprocess.STDOUT)
    if r.returncode:print(log.read_text()[-2000:]);raise SystemExit(r.returncode)
  hits=[x for x in log.read_text().splitlines() if '_PASS ' in x];assert hits,name
  print(*hits,flush=True);records.append({'test':name,'passed':True,'log_sha256':hashlib.sha256(log.read_bytes()).hexdigest()})
padding=[]
for n,shape,m in [(16,4,87),(32,3,72),(24,4,65),(32,4,39),(24,4,64),
                  (32,3,73),(24,4,63),(32,4,41),(32,3,71),(32,4,40)]:
    prf=bytes(range(32,32+n));seed=bytes(range(64,64+n))
    randomizer=bytes(range(96,96+n));root=bytes(range(128,128+n))
    payload=(prf+randomizer if shape==3 else randomizer+seed+root)+bytes(range(m))
    digest=hashlib.shake_256(payload).digest(49)
    padding.append((n<<442)|(shape<<438)|(m<<431)|((len(payload)//136+1)<<423)|
                   int.from_bytes(digest,'little'))
padding_file=OUT/'recipe_padding.mem'
padding_file.write_text(''.join(f'{v:0112x}\n' for v in padding))

for top in ('tb_mhbs_compact_shake_context_lane','tb_mhbs_recipe_padding'):
 for p in (1,2,3,4):
  name=f'{top}_P{p}';log=OUT/(name+'.log');binary=OUT/(name+'.vvp')
  with log.open('w') as f:
   for cmd in (['iverilog','-g2012','-s',top,f'-P{top}.PIPELINE={p}','-o',str(binary),*sources,f'tb/unit/{top}.sv'],['vvp',str(binary),f'+VECTORS={padding_file}']):
    r=subprocess.run(cmd,cwd=ROOT,stdout=f,stderr=subprocess.STDOUT)
    if r.returncode:print(log.read_text()[-2000:]);raise SystemExit(r.returncode)
  assert '_PASS' in log.read_text(),name
  print('LUP_STREAM_PASS',top,p,flush=True)
  records.append({'test':name,'passed':True,'log_sha256':hashlib.sha256(log.read_bytes()).hexdigest()})
(OUT/'results.json').write_text(json.dumps(records,indent=2)+'\n')
