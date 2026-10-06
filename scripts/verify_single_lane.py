#!/usr/bin/env python3
"""Cycle-exact comparison with the frozen pre-specialization single-lane core."""
from pathlib import Path
import sys,json,subprocess,re,hashlib,shutil,concurrent.futures,argparse,tarfile
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from v42_common_partition import partition
OUT=ROOT/'manifests/experiments/single_lane_20261008';BUILD=ROOT/'build/single_lane_20261008'
BASE=ROOT/'manifests/experiments/unified_hbs_v4.2/external_job_message'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def mem(p,words,width):p.write_text(''.join(f'{w:0{width}x}\n' for w in words))
def prepare_vectors():
 oldver=json.loads((BASE/'candidates/lut21k_20261002_v1_route_alias/verify/results.json').read_text())['profiles']
 for name in ('slh_128f','slh_192f','slh_256f','slh_128s','slh_192s','slh_256s'):
  for op in (0,1,2):
   src=BASE/'vectors'/name/('keygen' if op==0 else 'sign');d=OUT/'vectors'/name/str(op);d.mkdir(parents=True,exist_ok=True)
   cfg=json.loads((src/'job.json').read_text());meta=[int(x,16) for x in (src/'metadata.mem').read_text().split()]
   data=bytes(int(x,16) for x in (src/'expected.mem').read_text().split());n=len(bytes.fromhex(cfg['public_seed']))
   message=bytes(int(x,16) for x in (src/'message.mem').read_text().split()) if (src/'message.mem').exists() else b''
   for f in ('program','template','descriptor'):shutil.copy2(BASE/'images'/name/(f+'.mem'),d/(f+'.mem'))
   mem(d/'expected.mem',data if op!=2 else b'\0',2);mem(d/'message.mem',message+bytes(87-len(message)),2)
   nodes=[int.from_bytes(data[i:i+n],'little') for i in range(0,len(data),n)] if op==2 else [0]
   mem(d/'nodes.mem',nodes,64)
   job=[int.from_bytes(bytes.fromhex(cfg[k]),'little') for k in ('secret_seed','secret_prf','public_seed','randomizer','public_root')]+[0,0,op,cfg['message_bytes']]
   mem(d/'job.mem',job,64)
   if op==2:meta=[0,oldver[name]['normal']['hashes'],oldver[name]['normal']['permutations'],len(nodes),1]
   else:meta=[len(data),meta[1],meta[2],1,0]
   mem(d/'meta.mem',meta,8)

def build(p=1,u=1,stats=1):
 name=f'P{p}U{u}_stats{stats}';d=BUILD/name;d.mkdir(parents=True,exist_ok=True)
 frozen=BUILD/'baseline'
 if not (frozen/'rtl/top/mhbs_top.sv').exists():
  with tarfile.open(OUT/'baseline/source_snapshot.tar.gz') as archive:archive.extractall(frozen,filter='data')
 original=(frozen/'rtl/top/mhbs_top.sv').read_text()
 # Load the frozen extraction function without importing the current version.
 ns={};exec((frozen/'scripts/v42_common_partition.py').read_text(),ns);old,_=ns['partition'](original)
 paths=(ROOT/'manifests/v42_sources.txt').read_text().split();modules=[Path(x).stem for x in paths]+['mhbs_common']
 def rename(s):return re.sub(r'\b('+'|'.join(modules)+r')\b',lambda m:'frozen_'+m[0],s)
 oldfiles=[]
 for path in paths:
  if path.endswith('mhbs_top.sv'):continue
  dest=d/('frozen_'+Path(path).name);dest.write_text(rename((frozen/path).read_text()));oldfiles.append(dest)
 (d/'frozen_common.sv').write_text(rename(old));oldfiles.append(d/'frozen_common.sv')
 live,_=partition((ROOT/'rtl/top/mhbs_top.sv').read_text());(d/'common.sv').write_text(live)
 sources=[ROOT/x for x in paths if not x.endswith('mhbs_top.sv')]+[d/'common.sv',*oldfiles,ROOT/'tb/integration/tb_mhbs_stateful.sv']
 identity={str(f):sha(f) for f in sources+[ROOT/'tb/integration/mhbs_single_lane_equiv.svh']};exe=d/'obj/Vtb_mhbs_stateful'
 if not exe.exists() or not (d/'inputs.json').exists() or json.loads((d/'inputs.json').read_text())!=identity:
  cmd=['verilator','--binary','--timing','-O3','-j','8','-Wno-fatal','-DSINGLE_LANE_EQUIV','--top-module','tb_mhbs_stateful',f'-GPIPELINE={p}',f'-GUNROLL={u}',f'-GPROFILE_ENABLE={stats}','--Mdir',str(exe.parent),*map(str,sources)]
  with (d/'compile.log').open('w') as f:subprocess.run(cmd,cwd=ROOT,stdout=f,stderr=subprocess.STDOUT,check=True)
  (d/'inputs.json').write_text(json.dumps(identity,indent=2)+'\n');print('BUILD_PASS',name,flush=True)
 return exe

def run(exe,vector,label,options=()):
 logs=OUT/'logs';logs.mkdir(exist_ok=True);log=logs/(label+'.log')
 with log.open('w') as f:subprocess.run([str(exe),f'+VECTOR={vector}',*options],cwd=ROOT,stdout=f,stderr=subprocess.STDOUT,check=True)
 text=log.read_text();m=re.findall(r'STATEFUL_PASS (P\d+U\d+) op=(\d+) cycles=(\d+) total=(\d+) hashes=(\d+) permutations=(\d+)',text)
 if m:
  x=m[-1];r=dict(point=x[0],operation=int(x[1]),compute_cycles=int(x[2]),total_cycles=int(x[3]),hashes=int(x[4]),permutations=int(x[5]),passed=True)
 else:assert 'STATEFUL_FAULT_PASS' in text or 'INDEX_REJECT_PASS' in text;text='';r=dict(passed=True)
 r.update(log=str(log.relative_to(ROOT)),log_sha256=sha(log),binary_sha256=sha(exe),build_inputs_sha256=sha(exe.parents[1]/'inputs.json'));print('EQUIV_PASS',label,r.get('compute_cycles'),flush=True);return r

def main():
 ap=argparse.ArgumentParser();ap.add_argument('--p',type=int,default=1);ap.add_argument('--u',type=int,default=1);ap.add_argument('--stats',type=int,default=1);ap.add_argument('--profile');ap.add_argument('--operation',type=int);a=ap.parse_args()
 prepare_vectors();exe=build(a.p,a.u,a.stats);cases=[]
 for name in ('slh_128f','slh_192f','slh_256f','slh_128s','slh_192s','slh_256s','xmss_omega2','xmss_omega4','lms_omega2','lms_omega4'):
  if a.profile and name!=a.profile:continue
  for op in (0,1,2):
   if a.operation is not None and op!=a.operation:continue
   vector=OUT/'vectors'/name/str(op) if name.startswith('slh') else ROOT/'manifests/experiments/stateful_20261008/vectors'/name/'q0_m1'/str(op)
   cases.append((name,op,vector))
 def one(case):
  n,op,v=case;label=f'{n}_{op}_P{a.p}U{a.u}_stats{a.stats}';return label,run(exe,v,label)
 with concurrent.futures.ThreadPoolExecutor(3) as pool:rows=dict(pool.map(one,cases))
 (OUT/f'equivalence_P{a.p}U{a.u}_stats{a.stats}.json').write_text(json.dumps(rows,indent=2)+'\n')
if __name__=='__main__':main()
