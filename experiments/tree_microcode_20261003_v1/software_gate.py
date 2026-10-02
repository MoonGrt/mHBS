#!/usr/bin/env python3
"""Software-only gate; no RTL is generated or modified by this stage."""
import concurrent.futures,hashlib,json,sys,time,copy,traceback
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from microcode import *
from model.unified_hbs import Machine,Job,compile_image
from model.profiles import SLH_NAMES
from model.reference import slh_dsa as ref
from tests.slh_fixtures import default_job
OUT=ROOT/'manifests/experiments/tree_microcode_20261003_v1/software'
OUT.mkdir(parents=True,exist_ok=True)
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def write(p,x):
 p=Path(p);p.parent.mkdir(parents=True,exist_ok=True);q=p.with_suffix('.tmp');q.write_text(json.dumps(x,indent=2)+'\n');q.replace(p)
class Trace:
 def __init__(self):self.count=0;self.perm=0;self.sum=0;self.square=0
 def __call__(self,kind,data,value):
  h=int.from_bytes(hashlib.sha256(len(data).to_bytes(4,'little')+data+value).digest(),'big')
  self.count+=1;self.perm+=len(data)//136+1;self.sum=(self.sum+h)%(1<<256);self.square=(self.square+h*h)%(1<<256)
 def record(self):return dict(count=self.count,permutations=self.perm,multiset_sum=f'{self.sum:064x}',multiset_square=f'{self.square:064x}')
def compare(vm,expected,trace=None):
 actual=vm.run();assert actual==expected, 'output mismatch'
 if trace is not None:assert vm.backend.observe.record()==trace.record(), 'Hash input/output multiset mismatch'
 return actual

def profile(name):
 p=get_profile(name);img=compile_program(name);img.write(OUT/'images'/name)
 params=getattr(ref,f'SLH_DSA_SHAKE_{p.n*8}{name[-1].upper()}');j,msg=default_job(name)
 rows={}
 for case,length in enumerate((1,8,9,87)):
  job=j if case==0 else Job(*(hashlib.shake_256(f'{name}:{case}:{k}'.encode()).digest(p.n) for k in range(4)))
  message=msg if case==0 else bytes((i*17+case)&255 for i in range(length))
  # Independent algorithm reference. The old model is used only as the baseline oracle.
  sk,pk=ref.keygen_internal(params,job.secret,job.prf,job.public)
  baseline=Machine(compile_image(name),job,Trace());kg=baseline.run(False,b'')
  vm=VM(img,job,bytes(p.n),b'',0,observe=Trace());compare(vm,sk+pk,baseline.observe);assert kg==sk+pk
  kg_stats=vm.stats()
  baseline=Machine(compile_image(name),job,Trace());baseline.values[3]=pk[p.n:]
  sig=baseline.run(True,message)
  # Reference signer defaults to PK.seed as optrand; pass explicit job randomizer.
  reference_sig=ref.sign_internal(params,message,sk,job.random)
  assert sig==reference_sig
  vm=VM(img,job,pk[p.n:],message,1,observe=Trace());compare(vm,sig,baseline.observe)
  sg_stats=vm.stats()
  independent=Trace();assert ref.verify_internal(params,message,sig,pk,independent)
  vm=VM(img,job,pk[p.n:],message,2,sig,Trace());compare(vm,True,independent)
  verify_stats=vm.stats()
  if case==0:
   legacy=json.loads((OUT.parent/'baseline/verify.json').read_text())['profiles'][name]['normal']
   assert (verify_stats['hashes'],verify_stats['permutations'])==(legacy['hashes'],legacy['permutations'])
   metadata=json.loads((OUT.parent/'baseline/sign.json').read_text())['cases'][name+'_sign']
   assert (sg_stats['hashes'],sg_stats['permutations'])==(metadata['hashes'],metadata['permutations'])
  faults=[]
  for label,node_index in [('R',0),('fors_secret',1),('fors_auth',2),('wots',1+p.k*(p.a+1)),('xmss_auth',1+p.k*(p.a+1)+p.chains),('last_auth',len(sig)//p.n-1)]:
   changed=bytearray(sig);changed[node_index*p.n]^=1
   expect=ref.verify_internal(params,message,bytes(changed),pk)
   vm=VM(img,job,pk[p.n:],message,2,bytes(changed));assert vm.run()==expect==False
   faults.append(label)
  changed=bytes([message[0]^1])+message[1:]
  assert not ref.verify_internal(params,changed,sig,pk)
  assert not VM(img,job,pk[p.n:],changed,2,sig).run()
  rows[str(length)]=dict(passed=True,keygen=kg_stats,sign=sg_stats,verify=verify_stats,signature_sha256=hashlib.sha256(sig).hexdigest(),faults=faults+['message'])
  write(OUT/name/'results.json',rows)
  print('SOFTWARE_PROFILE_CASE_PASS',name,length,flush=True)
 return name,rows

def tree_boundaries():
 # Invoke ROM subroutine with controlled targets, using the old tree solely as oracle.
 rows=[]
 for name in SLH_NAMES:
  p=get_profile(name);img=compile_program(name);job,_=default_job(name)
  for fors in (0,1):
   h=p.a if fors else p.hp
   for target in (0,1,(1<<h)-2,(1<<h)-1):
    for external in ((0,) if fors else (0,8)):
     group=p.k-1 if fors else 0;flags=3|external
     old=Machine(compile_image(name),job,Trace());old.message=b'x';old.active_q=0;old.scalar_tree=123;old.scalar_leaf=target if not fors else 3
     old.digits=[i%16 for i in range(p.chains)];old.values[3]=bytes([77])*p.n
     if fors:
      fb=(p.k*p.a+7)//8;bits=target<<(8*fb-p.a*(group+1));old.values[1]=bits.to_bytes(fb,'big')
     expected=old.tree(20 if fors else 21,flags,(2<<19)|(group<<13))
     vm=VM(img,job,bytes([77])*p.n,b'x',1,observe=Trace())
     vm.backend.scalar_tree=123;vm.backend.scalar_leaf=old.scalar_leaf;vm.backend.digits=list(old.digits);vm.backend.values[1]=old.values[1]
     vm.reg[R.LAYER]=2;vm.reg[R.GROUP]=group;vm.reg[R.TARGET]=target;vm.reg[R.HEIGHT]=h
     vm.reg[R.CID]=16 if fors else 17;vm.reg[R.PID]=6 if fors else 10;vm.reg[R.FLAGS]=flags;vm.reg[R.MODE]=fors
     # A separate HALT appended after return permits subroutine-only validation.
     image=copy.deepcopy(img);image.program.append(encode(Op.HALT));vm.image=image
     vm.pc=img.labels['tree'];vm.link=len(img.program)
     # run() validates full signature length; bypass only that final length for this subroutine test.
     try:vm.run()
     except ValueError as ex:assert str(ex)=='output length'
     assert vm.node[0]==expected and bytes(vm.backend.output)==bytes(old.output)
     assert vm.backend.observe.record()==old.observe.record()
     assert vm.peak_stack<=h and vm.peak_auth<=h
     rows.append(dict(profile=name,fors=fors,target=target,external=bool(external),passed=True,stats=vm.stats()))
  print('SOFTWARE_BOUNDARIES_PASS',name,flush=True)
 return rows

def negative_tests():
 img=compile_program('slh_128f');job,_=default_job('slh_128f');cases=[]
 def rejected(label,fn):
  try:fn()
  except (ValueError,KeyError,IndexError):cases.append(label)
  else:raise AssertionError('accepted '+label)
 bad=copy.deepcopy(img);bad.format='slh64_v4.2';rejected('legacy',bad.validate)
 bad=copy.deepcopy(img);bad.program=[encode(Op.JMP,imm=255)];rejected('jump',bad.validate)
 bad=copy.deepcopy(img);bad.program=[encode(Op.JMP,imm=0)]
 rejected('loop',lambda:VM(bad,job,bytes(16),b'',0,max_steps=50).run())
 bad=copy.deepcopy(img);bad.program=[encode(Op.SET,R.LEVEL,imm=16),encode(Op.STORE,Mem.STACK,N.NODE,R.LEVEL)]
 rejected('memory',lambda:VM(bad,job,bytes(16),b'',0).run())
 rejected('signature_length',lambda:VM(img,job,bytes(16),b'x',2,b'x'))
 return cases

def main():
 start=time.time();state=dict(status='running',phase='software',rtl_modified=False);write(OUT/'status.json',state)
 try:
  with concurrent.futures.ProcessPoolExecutor(3) as pool:results=dict(pool.map(profile,SLH_NAMES))
  boundaries=tree_boundaries();negative=negative_tests()
  frozen=json.loads((OUT.parent/'baseline/inputs.json').read_text())['rtl_sha256']
  assert all(sha(ROOT/p)==h for p,h in frozen.items()),'RTL changed during software gate'
  result=dict(passed=True,profiles=results,boundaries=boundaries,rejected=negative,seconds=time.time()-start,
      rtl_unchanged=True,source_sha256={p.name:sha(p) for p in Path(__file__).parent.glob('*.py')})
  write(OUT/'gate.json',result);write(OUT/'status.json',dict(status='passed',seconds=time.time()-start))
  print('TREE_FREE_SOFTWARE_GATE_PASS',flush=True)
 except Exception as ex:
  write(OUT/'status.json',dict(status='failed',error=repr(ex),seconds=time.time()-start));traceback.print_exc();raise
if __name__=='__main__':main()
