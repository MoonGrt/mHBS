#!/usr/bin/env python3
"""Compare ordered primitive task fingerprints against an immutable C1 clone."""
import argparse,hashlib,json,os,re,shutil,subprocess,time
from pathlib import Path

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def command(cmd,cwd,log,env=None):
 log.parent.mkdir(parents=True,exist_ok=True)
 with log.open('w') as f:p=subprocess.run(cmd,cwd=cwd,env=dict(os.environ,**(env or {})),stdout=f,stderr=subprocess.STDOUT)
 if p.returncode:raise RuntimeError(f'Exit {p.returncode}: {log}')
 return log.read_text()
def main():
 p=argparse.ArgumentParser(description=__doc__)
 p.add_argument('--source',type=Path,required=True);p.add_argument('--baseline-source',type=Path,required=True)
 p.add_argument('--run',type=Path,required=True);p.add_argument('--summary',type=Path,required=True)
 a=p.parse_args();src=a.source.resolve();old=a.baseline_source.resolve();run=a.run.resolve();run.mkdir(parents=True,exist_ok=True)
 clone=run/'c1_source'
 if not clone.exists():
  clone.mkdir()
  for folder in ('rtl','tb','model','scripts'):shutil.copytree(old/folder,clone/folder,ignore=shutil.ignore_patterns('__pycache__'))
  shutil.copy2(old/'sources.txt',clone/'sources.txt')
  cpp=clone/'tb/fast_main.cpp';s=cpp.read_text()
  if 'HASH_TASK_TRACE ' not in s:
   s=s.replace('bool collect_trace=false;','bool collect_trace=false,collect_ordered=false;')
   s=s.replace('if(path.empty())throw','for(int i=1;i<argc;i++)if(std::string(argv[i])=="+HASH_ORDERED=1"){collect_ordered=true;collect_trace=true;}\n    if(path.empty())throw')
   s=s.replace('trace_hashes++;task_blocks=0;','if(collect_ordered)std::cout<<"HASH_TASK_TRACE "<<trace_hashes<<" "<<hex_bytes(item,32)<<std::endl;\n                        trace_hashes++;task_blocks=0;')
  cpp.write_text(s)
 inputs=[x.strip() for x in (old/'sources.txt').read_text().splitlines() if x.strip()]+['rtl/executor/instructions.svh','tb/tb_fast.sv']
 assert all(sha(old/n)==sha(clone/n) for n in inputs),'C1 production or monitor changed'
 state=dict(complete=False,passed=False,baseline_source=str(old),baseline_clone=str(clone),source=str(src),baseline_production_sha256={n:sha(old/n) for n in inputs},baseline_instrumented_cpp_sha256=sha(clone/'tb/fast_main.cpp'),tests={})
 def publish():a.summary.parent.mkdir(parents=True,exist_ok=True);a.summary.write_text(json.dumps(state,indent=2)+'\n')
 publish()
 vmcode='''import json,sys
import model.hash_trace as h
Original=h.HashTrace
records=[]
class Ordered(Original):
 def __call__(self,*args):
  before=self.sum256
  super().__call__(*args)
  records.append(f'{(self.sum256-before)%(1<<256):064x}')
h.HashTrace=Ordered
report=h.expected_trace(sys.argv[1],sys.argv[2],'verify',sys.argv[3])
print(json.dumps(dict(records=records,report=report)))
'''
 for b in ('shake','sha2'):
  env=dict(HASH_BACKEND=b,SIM_FAST_OPT_SLOW='-O1',SIM_COMPILE_ONLY='1')
  for tag,source in (('old',clone),('new',src)):
   command(['bash','scripts/simulate_fast.sh','slh_128f','verify','1','1'],source,run/f'{tag}_{b}_compile.log',env)
  for n in ('slh_128f','xmss_h10','lms_h10'):
   key=f'{b}/{n}/verify';started=time.monotonic()
   try:
    streams={}
    for tag,source in (('old',clone),('new',src)):
     v=source/'tb/vectors'/('sha2' if b=='sha2' else '')/n/'verify'
     folder=source/('build/sim/P1U1_fast_o3_synthesis0_slow_O1'+('_sha2' if b=='sha2' else ''))
     log=run/f'{tag}_{b}_{n}.log'
     text=command([str(folder/'obj/Vtb_fast'),'+VECTOR='+str(v),'+HASH_ORDERED=1'],source,log)
     records=re.findall(r'^HASH_TASK_TRACE (\d+) ([0-9a-f]{64})$',text,re.M)
     assert records and [int(x[0]) for x in records]==list(range(len(records))),'noncontiguous RTL trace'
     streams[tag]=[x[1] for x in records]
     vm_log=run/f'{tag}_{b}_{n}_vm.log'
     vm=json.loads(command(['python3','-c',vmcode,str(v),n,b],source,vm_log,dict(PYTHONPATH=str(source))))
     assert vm['records']==streams[tag],f'{tag} VM and RTL ordered primitive fingerprints differ'
    assert streams['old']==streams['new'],'C1 and candidate ordered primitive fingerprints differ'
    state['tests'][key]=dict(status='passed',primitive_hashes=len(streams['new']),ordered_sequence_sha256=hashlib.sha256(''.join(streams['new']).encode()).hexdigest(),vm_and_rtl_equal=True,seconds=time.monotonic()-started)
   except Exception as e:state['tests'][key]=dict(status='failed',error=str(e),seconds=time.monotonic()-started)
   publish()
 state['complete']=True;state['passed']=all(v['status']=='passed' for v in state['tests'].values()) and len(state['tests'])==6;publish()
 raise SystemExit(0 if state['passed'] else 1)
if __name__=='__main__':main()
