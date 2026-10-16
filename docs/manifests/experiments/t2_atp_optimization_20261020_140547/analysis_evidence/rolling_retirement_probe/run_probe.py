from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import hashlib,json,re,subprocess,time
RUN=Path(__file__).resolve().parent; SOURCE=RUN/'source';meta=json.loads((RUN/'SOURCE.json').read_text())
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def pu(p):
 rows=[]
 for profile in ('slh_128f','xmss_h10','lms_h10'):
  log=RUN/f'P{p}_{profile}_sign.log';t=time.time();cmd=['bash','scripts/simulate_fast.sh',profile,'sign',str(p),'1']
  with log.open('w') as f:r=subprocess.run(cmd,cwd=SOURCE,stdout=f,stderr=subprocess.STDOUT)
  match=re.search(r'STATEFUL_PASS P(\d+)U1 op=1 cycles=(\d+) total=(\d+) hashes=(\d+) permutations=(\d+).*?seconds=([\d.e+]+)',log.read_text())
  baseline=Path(meta['baseline_run'])/f'sim/P{p}U1/{profile}_sign.log';bm=re.search(r'cycles=(\d+).*hashes=(\d+) permutations=(\d+)',baseline.read_text()) if baseline.exists() else None
  row=dict(p=p,profile=profile,passed=r.returncode==0 and bool(match),elapsed_seconds=time.time()-t,log=str(log),log_sha256=sha(log))
  if match:row.update(cycles=int(match[2]),hashes=int(match[4]),permutations=int(match[5]))
  if bm and match:row.update(baseline_cycles=int(bm[1]),cycles_delta=int(match[2])-int(bm[1]),cycles_change_pct=100*(int(match[2])/int(bm[1])-1),counts_equal=int(match[4])==int(bm[2]) and int(match[5])==int(bm[3]))
  rows.append(row);print(json.dumps(row),flush=True)
 return rows
with ThreadPoolExecutor(max_workers=2) as ex:rows=[row for group in ex.map(pu,[4,12]) for row in group]
unchanged=all(sha(SOURCE/n)==h for n,h in meta['rtl_sha256'].items())
data=dict(schema='mhbs.t2_atp.rolling_retire_probe.v1',source_manifest_sha256=sha(RUN/'SOURCE.json'),source_unchanged=unchanged,passed=all(r['passed'] and r.get('counts_equal') for r in rows),tests=rows,no_vivado=True,scope=meta['hypothesis'])
(RUN/'RESULTS.json').write_text(json.dumps(data,indent=2)+'\n')
if not data['passed']:raise SystemExit(1)
