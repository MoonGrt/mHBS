import hashlib,json,os,pathlib,shutil,subprocess,time
root=pathlib.Path.cwd(); work=root/'build/sha2_optimization/scalar_validation'; logs=work/'robustness'; logs.mkdir(exist_ok=True)
names=[s for s in (root/'sources.txt').read_text().splitlines() if s]+['sources.txt','tb/tb.sv','scripts/simulate.sh']
def sha(p):return hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()
before={s:sha(root/s) for s in names}
assert before['rtl/hash/sha2-recipe.sv']=='2a1680cb59fff763a7007a01ca51294962cf3d44133670d7b2bd8e7acf54116e'
(logs/'SOURCE.json').write_text(json.dumps(before,indent=2)+'\n')
cases=[(f'{p}_verify_stall_replay',p,'verify',['+STALL=3','+REPLAYS=2']) for p in ('slh_128f','xmss_h10','lms_h10')]
cases += [('xmss_h10_tamper_message','xmss_h10','verify',['+TAMPER=1']),('xmss_h10_cut_restore','xmss_h10','verify',['+CUT=5','+STALL=1']),('slh_128f_sign_interrupt','slh_128f','sign',['+INTERRUPT=1','+STALL=1','+REPLAYS=2'])]
cases += [('lms_h10_tamper_auth','lms_h10','verify',['+TAMPER=3']),('slh_128f_fault_batch','slh_128f','sign',['+FAULT=2'])]
cases += [('slh_128f_fault_scalar','slh_128f','sign',['+FAULT=1'])]
rows=[]
def publish():
 d=dict(schema='mhbs.sha2.robustness.v1',passed=sum(r['passed'] for r in rows),completed=len(rows),total=len(cases),source_sha256=before,source_unchanged=all(sha(root/s)==v for s,v in before.items()),hash_backend='sha2',pipeline=4,unroll=1,h20_jobs=0,results=rows)
 (work/'ROBUSTNESS.json').write_text(json.dumps(d,indent=2)+'\n')
publish()
env=os.environ.copy();env.update(HASH_BACKEND='sha2',SIM_SYNTHESIS='0',SIM_VCD='0',VECTORS_DIR='tb/vectors/sha2')
for label,p,op,options in cases:
 cmd=['bash','scripts/simulate.sh',p,op,'4','1',*options,'+TIMEOUT=20000000']
 started=time.monotonic()
 with (logs/f'{label}.driver.log').open('w') as out:
  result=subprocess.run(cmd,cwd=root,env=env,stdout=out,stderr=subprocess.STDOUT)
 canonical=root/f'build/sim/P4U1_synthesis0_sha2/{p}_{op}.log'
 log=logs/f'{label}.log'
 if canonical.exists():shutil.copyfile(canonical,log)
 else:shutil.copyfile(logs/f'{label}.driver.log',log)
 text=log.read_text();marker='STATEFUL_FAULT_PASS' if any(o.startswith('+FAULT=') for o in options) else 'STATEFUL_PASS '
 vectors=root/'tb/vectors/sha2'/p/op
 row=dict(label=label,profile=p,operation=op,command=cmd,environment={k:env[k] for k in ('HASH_BACKEND','SIM_SYNTHESIS','SIM_VCD','VECTORS_DIR')},returncode=result.returncode,passed=result.returncode==0 and marker in text,elapsed_seconds=time.monotonic()-started,log=str(log),log_sha256=sha(log),vector_sha256={x.name:sha(x) for x in sorted(vectors.glob('*.mem'))},markers=[line for line in text.splitlines() if 'PASS' in line or 'P4_COVERAGE' in line or 'BATCH_OBSERVED' in line])
 rows.append(row);publish();print(json.dumps({k:row[k] for k in ('label','passed','elapsed_seconds','markers')}),flush=True)
print('ROBUSTNESS_COMPLETE',flush=True)
