"""Archive a completed controlled experiment without changing active PPA."""
from pathlib import Path
import hashlib
import json
import shutil
import subprocess
import sys

root=Path(__file__).resolve().parents[2]
main=root.parents[2]
sys.path.insert(0,str(root/'scripts'))
from v42_external_route import resources

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def write(p,x):p.write_text(json.dumps(x,indent=2)+'\n')

tag='k2u2_lanes_only_20260927_v1'
base='prune_k2u2_20260927_v1'
build=root/'build/v4.2/external_job_message'/tag
manifest=main/'manifests/experiments/unified_hbs_v4.2/external_job_message'
verification=json.loads((build/'verification.json').read_text())
pruning=json.loads((build/'pruning_verification.json').read_text())
assert verification['passed'] and pruning['passed']
core=resources(build/'synthesis/core_utilization.rpt')
baseline=resources(manifest/'candidates'/base/'synthesis/core_utilization.rpt')
scope=json.loads((root/'build/lane_only/scope_audit.json').read_text())
assert scope['passed']
audit=json.loads((build/'synthesis/pruning_audit.json').read_text())
assert audit['passed'] and audit['profile_enable'] is False
inputs=json.loads((build/'inputs.json').read_text())
assert sha(build/'source_snapshot.tar.gz')==inputs['snapshot_sha256']
dest=manifest/'candidates'/tag
dest.mkdir(exist_ok=False)
for p in build.iterdir():
 if p.is_file():shutil.copy2(p,dest/p.name)
for name in ('synthesis','logs','extended_vectors'):
 shutil.copytree(build/name,dest/name)
external=root/'manifests/experiments/unified_hbs_v4.2/external_job_message'
for name in ('unit','images','vectors'):
 shutil.copytree(external/name,dest/name)
for name in ('software_gate.json','rtl_start.json'):
 if (external/name).exists():shutil.copy2(external/name,dest/name)
shutil.copytree(root/'build/lane_only',dest/'experiment')
patch=subprocess.check_output(['git','diff','--','rtl','tb','scripts','experiments'],cwd=root)
(dest/'implementation.patch').write_bytes(patch)
delta=core['equivalent_slice']-baseline['equivalent_slice']
result=dict(candidate=tag,baseline=base,stage='post_synth_core',
 experiment='lane_instantiation_only',functional_pass=True,
 cycle_equivalence_pass=pruning['cycle_equivalence_pass'],
 scope_audit_pass=True,profile_enable=False,
 core=core,baseline_core=baseline,
 equivalent_slice_delta=delta,equivalent_slice_increase_percent=delta/baseline['equivalent_slice']*100,
 core_area_eligible=delta<=0,production_selected=False,
 post_route_pass=False,frequency_mhz=None,route_skipped=True,
 route_skip_reason='controlled_synthesis_diagnostic_no_frequency_claim',
 rtl_sha256=inputs['rtl_sha256'],source_snapshot_sha256=inputs['snapshot_sha256'])
write(dest/'result.json',result)
write(dest/'evidence_sha256.json',{str(p.relative_to(dest)):sha(p) for p in sorted(dest.rglob('*')) if p.is_file() and p.name!='evidence_sha256.json'})
summary=json.loads((manifest/'k2u2_specialization.json').read_text())
summary.setdefault('controlled_experiments',{})['lanes_only']=result
write(manifest/'k2u2_specialization.json',summary)
print(json.dumps(result,indent=2))
