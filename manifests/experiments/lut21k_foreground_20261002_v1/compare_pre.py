import json,sys
from pathlib import Path
root=Path(__file__).resolve().parents[3];r=Path(__file__).resolve().parent;label=sys.argv[1];c=next(x for x in json.loads((r/'config.json').read_text())['candidates'] if x['label']==label)
f=Path(c['workspace'])/'build/v4.2/external_job_message'/c['tag'];b=root/'manifests/experiments/unified_hbs_v4.2/external_job_message/candidates/lut21k_20261002_v1_bank'
a=json.loads((f/'simulation.json').read_text());z=json.loads((b/'simulation.json').read_text());assert a['passed'];assert a['cases'].keys()==z['cases'].keys()
for k,v in a['cases'].items():
 for x in ['output_sha256','boot_cycles','keygen_cycles','sign_cycles','hashes','permutations','total_cycles']:assert v.get(x)==z['cases'][k].get(x),(k,x)
a=json.loads((f/'verify/results.json').read_text());z=json.loads((b/'verify/results.json').read_text());assert a['passed']
for k,v in a['profiles'].items():
 for x,y in v['normal'].items():
  if x!='log_sha256':assert y==z['profiles'][k]['normal'][x],(k,x)
(r/(label+'_precomparison.json')).write_text(json.dumps(dict(passed=True,baseline=b.name,normal_cases=12,verify_profiles=6),indent=2)+'\n');print('COMPARISON_PASS',label)
