#!/usr/bin/env python3
"""Exercise all P SHA2 contexts against independent hashlib vectors from frozen E1 RTL."""
from pathlib import Path
from hashlib import sha256
import argparse,json,re,subprocess,os
HERE=Path(__file__).resolve().parent

def digest_file(path):return sha256(path.read_bytes()).hexdigest()
def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--pipeline',type=int,choices=(12,24),required=True);p.add_argument('--synthesis',action='store_true');p.add_argument('--q',type=int,default=1024);args=p.parse_args()
 P=args.pipeline;U=1;binding=json.loads((HERE/'SOURCE_BINDING.json').read_text());work=HERE/'runs'/(f'P{P}U{U}'+('_synthesis' if args.synthesis else ''));work.mkdir(parents=True,exist_ok=True)
 for path,expected in binding['compiled_rtl_sha256'].items():assert digest_file(HERE/'core'/path)==expected,path
 for path,expected in binding['all_core_rtl_sha256'].items():assert digest_file(Path(binding['source_root'])/path)==expected,path
 assert digest_file(HERE/'tb_fullslots.sv')==binding['new_harness_sha256']
 obj=work/'obj';sources=[HERE/'core'/path for path in binding['compiled_rtl_sha256']]
 command=[os.environ.get('VERILATOR','verilator'),'--binary','--timing','-O3','-j','2','-Wno-fatal','--top-module','tb_fullslots','--Mdir',str(obj),'-DMHBS_SHA2',f'-GPIPELINE={P}',f'-GUNROLL={U}']
 if args.synthesis:command.append('-DSYNTHESIS')
 command += [str(path) for path in sources]+[str(HERE/'tb_fullslots.sv')]
 (work/'COMMAND.json').write_text(json.dumps(command,indent=2)+'\n')
 with (work/'compile.log').open('w') as log:subprocess.run(command,cwd=HERE,stdout=log,stderr=subprocess.STDOUT,check=True)
 sk,pub,ident=bytes(range(1,33)),bytes(range(65,97)),bytes(range(225,241));be=lambda x,n=4:x.to_bytes(n,'big')
 pattern=((0,0,1),(15,3,0),(1,1,1),(7,0,0),(2,0,0),(0,0,1),(3,3,1),(1,0,0))
 summaries=[]
 for family in range(3):
  rows=[];hashes=0;permutations=0;n=16 if family==0 else 32
  def h(value):
   nonlocal hashes,permutations
   hashes+=1;permutations+=(len(value)+9+63)//64;return sha256(value).digest()[:n]
  def slh_frame(address,value):return pub[:n]+bytes(64-n)+address[3:4]+address[8:16]+address[19:20]+address[20:32]+value[:n]
  for row in range(2*P):
   steps,cap,no_seed=pattern[row%len(pattern)];a=row+1;leaf=args.q
   address=b''.join(map(be,(3,0,0x01234567,0x89abcdef,0x83,leaf,a,0)))
   def masked(step,compound):return bytes(12)+b''.join(map(be,(0x83,leaf,a,step,compound)))
   initial=bytes((19*row+k)&255 for k in range(n));value=initial
   if not no_seed:
    if family==0:value=h(slh_frame(address,sk))
    elif family==1:value=h(be(4,32)+sk+pub+masked(0,0))
    else:value=h(ident+be(leaf)+be(a,2)+b'\xff'+sk)
   captured=value if cap==0 else None
   for step in range(steps):
    if family==0:value=h(slh_frame(address[:-4]+be(step),value))
    elif family==1:
     key,mask=h(be(3,32)+pub+masked(step,0)),h(be(3,32)+pub+masked(step,1))
     value=h(bytes(32)+key+bytes(x^y for x,y in zip(value,mask)))
    else:value=h(ident+be(leaf)+be(a,2)+bytes([step])+value)
    if cap==step+1:captured=value
   assert captured is not None
   packed=int.from_bytes(captured,'little')|int.from_bytes(value,'little')<<256|int.from_bytes(initial,'little')<<512|steps<<768|cap<<773|no_seed<<778
   rows.append(f'{packed:0195x}\n')
  vector=work/f'family{family}_q{leaf}.mem';vector.write_text(''.join(rows))
  result=subprocess.run([str(obj/'Vtb_fullslots'),f'+VECTOR={vector}',f'+FAMILY={family}',f'+LEAF={leaf}',f'+HASHES={hashes}',f'+PERMUTATIONS={permutations}'],cwd=HERE,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
  (work/f'family{family}_q{leaf}.log').write_text(result.stdout);print(result.stdout,end='',flush=True);result.check_returncode()
  match=re.search(r'^FULLSLOTS_PASS (.+)$',result.stdout,re.M);assert match,'missing successful coverage marker'
  values=dict(re.findall(r'(\w+)=(\w+)',match[1]));coverage={key:int(value,16 if key in ('accepted_tags','retired_tags') else 10) for key,value in values.items()}
  assert coverage['max_active']==P and coverage['accepted_tags']==(1<<P)-1 and coverage['retired_tags']==(1<<P)-1 and coverage['full_context_cycles']>0 and coverage['all_complete_cycles']>0 and coverage['retention_checks']>=8*P
  assert coverage['hashes']==hashes and coverage['permutations']==permutations
  summaries.append(dict(family=family,q=leaf,vector_sha256=digest_file(vector),passed=True,coverage=coverage,active_tags=list(range(P)),full_context_occupancy=True))
  (work/'partial_coverage.json').write_text(json.dumps(summaries,indent=2)+'\n')
 summary=dict(passed=True,hash_backend='sha2',pipeline=P,unroll=U,synthesis=args.synthesis,requests_per_family=2*P,groups=3,active_tags=list(range(P)),full_context_occupancy=True,coverage=summaries,source_binding=binding,tool_sha256=digest_file(Path(__file__)),new_harness_sha256=digest_file(HERE/'tb_fullslots.sv'),scope='Actual all-P busy and all-P complete observed before any result consumed; all captures checked while retained; same-edge reuse/out-of-order completions/request poisoning; standalone frozen-RTL submodule test')
 (work/'coverage.json').write_text(json.dumps(summary,indent=2)+'\n');print(f'ALL_FULLSLOTS_PASS P={P} synthesis={int(args.synthesis)} groups=3 tags={P}',flush=True)
if __name__=='__main__':main()
