import json
from pathlib import Path
b=Path('manifests/experiments/unified_hbs_v4.2/external_job_message/candidates/shared_list_store_20260927_v1')
f=Path('build/v4.2/external_job_message/program16_20260927_v1')
old=json.loads((b/'simulation.json').read_text())['cases'];new=json.loads((f/'simulation.json').read_text())['cases']
keys=('boot_cycles','keygen_cycles','sign_cycles','total_cycles','hashes','permutations','output_sha256')
for name,row in old.items():
 for key in keys:assert row[key]==new[name][key],(name,key,row[key],new[name][key])
oldv=json.loads((b/'verify/results.json').read_text())['profiles'];newv=json.loads((f/'verify/results.json').read_text())['profiles'];count=0
for name,cases in oldv.items():
 for label,row in cases.items():
  if label=='fault':continue
  updated=newv[name][label]
  for key in ('accepted','nodes','hashes','permutations','zero','full'):assert row[key]==updated[key],(name,label,key)
  assert row['cycles']-row['waits']==updated['cycles']-updated['waits'],(name,label,'cycles')
  count+=1
result=dict(passed=True,baseline=b.name,candidate=f.name,normal_cases=6,verify_cases=count,normal_compared=list(keys),verify_no_wait_cycles_equal=True)
(f/'program16_comparison.json').write_text(json.dumps(result,indent=2)+'\n')
print('PROGRAM16_BASELINE_EQUIVALENCE_PASS',6,count)
