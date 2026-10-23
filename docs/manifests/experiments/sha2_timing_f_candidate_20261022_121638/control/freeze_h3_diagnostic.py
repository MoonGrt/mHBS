#!/usr/bin/env python3
"""Freeze I's exact snapshot plus H3 core; measurements launch separately."""
from pathlib import Path
import json,sys
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'scripts'))
import run_sha2_timing_f as f
I_RUN=ROOT/'build/sha2_timing_g/candidate_20261022_120553'
I_SHA='4350a4db61a8b68e2428733ad05e85eb17a6818d41f9e8a6998a235834f34da9'
BASELINE=ROOT/'build/sha2_timing_f/baseline_20261022_100516'
PRIVATE=Path(__file__).resolve().parent
H3=PRIVATE/'fixture/rtl/hash/sha256.sv'
H3_SHA='ef6c9c04105b3eab91b24634ca2fd115611bd7d2eae95c44e7e439890622c13f'
CORE='rtl/hash/sha256.sv'
f.require(f.sha(I_RUN/'SOURCE.json')==I_SHA,'I source identity differs')
i=f.read(I_RUN/'SOURCE.json');f.require(f.shared.unchanged(i),'I frozen source changed')
f.require(f.sha(H3)==H3_SHA,'H3 component changed')
f.require(all(f.sha(ROOT/'scripts'/name)==i['sha256']['scripts/'+name] for name in f.CONTROLS),'F execution controls differ from I snapshot')
original_snapshot=f.dual.frozen_snapshot

def snapshot(source,destination):
    f.require(Path(source).resolve()==ROOT,'Only explicit candidate snapshot supported')
    checks=original_snapshot(Path(i['source_root']),destination)
    f.require(checks==i['sha256'],'Copy did not preserve full I snapshot')
    f.archive.copy_changed(H3,destination/CORE)
    checks[CORE]=f.sha(destination/CORE)
    f.require(checks[CORE]==H3_SHA,'Wrong replacement core')
    f.require([name for name,wanted in checks.items() if wanted!=i['sha256'][name]]==[CORE], 'More than core changed')
    return checks
f.dual.frozen_snapshot=snapshot
original_controls=f.controls

def controls(run,out,folder='control'):
    original_controls(run,out,folder)
    for base in (run,out):
        f.archive.copy_changed(__file__,base/folder/Path(__file__).name)
        proof=f.read(base/(folder.upper()+'_SOURCE.json'))
        proof[Path(__file__).name]=f.sha(base/folder/Path(__file__).name)
        f.write(base/(folder.upper()+'_SOURCE.json'),proof)
f.controls=controls
f.FAMILY=ROOT/'build/sha2_h3_diagnostic'
result=f.freeze('candidate','H3_I_snapshot_16x16_carry_select_P12U2_diagnostic_only',['sha2/P12U2'],BASELINE)
run=Path(result['run_root']);meta=f.read(run/'SOURCE.json');out=Path(meta['archive_directory'])
proof=dict(schema='mhbs.sha256.h3.one_point.provenance.v1',candidate_source_manifest_sha256=f.sha(run/'SOURCE.json'),
    base_run=str(I_RUN),base_source_manifest_sha256=I_SHA,base_inputs_verified=True,
    inherited_inputs_count=len(meta['sha256'])-1,changed_inputs={CORE:dict(before=i['sha256'][CORE],after=H3_SHA)},
    frozen_source_created_before_measurement=True,production_source_writes=0,route_authorized=False,route_launched=False,
    measurement_scope=['sha2/P12U2'],diagnostic_mhz=100,own_complete_sign_tests=3,same_source_functional_groups=36,
    no_14_point_acceptance_claim=True,baseline_run=str(BASELINE),helper_sha256=f.sha(__file__))
for base in (run,out):f.write(base/'H3_PROVENANCE.json',proof)
for relative in ['from_H2.patch','SOURCE.json','VALIDATION_SUMMARY.json','HANDOFF.json','NOTES.md','TOOLS.json','H3_frozen_component.tar.gz']:
    f.archive.copy_changed(PRIVATE/relative,out/'supplementary_evidence/H3_component'/relative)
f.inventory(run);f.archive.index()
(PRIVATE/'DIAGNOSTIC_FREEZE.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result,indent=2))
