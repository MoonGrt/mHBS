#!/usr/bin/env python3
"""Audit frozen C3-reference and timing-refine evidence; launch no hardware."""
import argparse
import hashlib
import json
from pathlib import Path
import tarfile

import experiment_archive as archive
from run_p1sha_timing_refine import ROOT, FAMILY, REFERENCE_SHA, sha, read, write


def audit(run):
    run=Path(run).resolve();meta=read(run/'SOURCE.json');out=Path(meta['archive_directory'])
    source=Path(meta['source_root']);manifest=sha(run/'SOURCE.json');errors=[];checks=0
    def check(condition,message):
        nonlocal checks
        checks+=1
        if not condition:errors.append(message)
    check(sha(out/'SOURCE.json')==manifest,'Archived manifest')
    for name,wanted in meta['sha256'].items():check(sha(source/name)==wanted,'Frozen input: '+name)
    for name,wanted in read(run/'CONTROL_SOURCE.json').items():
        check(sha(run/'control'/name)==sha(out/'control'/name)==wanted,'Control: '+name)
    for tarname,index in [('rtl.tar.gz','RTL_SOURCE.json'),('support.tar.gz','SUPPORT_SOURCE.json')]:
        members=read(out/index)
        if index=='RTL_SOURCE.json':members=members['files']
        with tarfile.open(out/tarname,'r:gz') as tar:
            check(set(tar.getnames())==set(members),'Tar members: '+tarname)
            for name,wanted in members.items():
                check(hashlib.sha256(tar.extractfile(name).read()).hexdigest()==wanted==meta['sha256'][name],
                      'Archived input: '+name)
    base=read(run/'C3_EVIDENCE.json')
    check(base['source_manifest_sha256']==REFERENCE_SHA and base['source_inputs_checked'],'Reference C3 identity')
    complete=True
    if meta['kind']=='candidate':
        state=read(run/'status.json');complete=state['complete']
        check(state['source_manifest_sha256']==manifest,'Candidate status binding')
        for key,test in state['tests'].items():
            if test['status']!='passed':continue
            check(test['source_manifest_sha256']==manifest and test['source_unchanged']
                and test['output_and_signature_cache_checked_bytewise'],'Sign source/bytes: '+key)
            for field in ('log','raw_log'):check(sha(test[field])==test[field+'_sha256'],'Sign log: '+key+'/'+field)
            check(all(test[n]==base['tests'][key][n] for n in ('hashes','permutations','vectors_sha256')),
                  'Sign workload: '+key)
        for key,syn in state['synthesis'].items():
            if syn['status']!='passed':continue
            check(syn['source_manifest_sha256']==manifest and syn['source_unchanged'],'Diagnostic source: '+key)
            for name,wanted in syn['reports_sha256'].items():
                check(sha(run/'synth'/key/name)==wanted,'Diagnostic report: '+key+'/'+name)
                check((out/'synth'/key/name).is_file() and sha(out/'synth'/key/name)==wanted,'Archived report: '+key+'/'+name)
        functional=run/'functional_validation/VALIDATION.json'
        if functional.is_file() and read(functional).get('complete'):
            summary=read(functional)
            check(summary['source_manifest_sha256']==manifest and summary['passed']==36
                and summary['failed']==0 and summary['source_unchanged'],'Functional summary')
            for test in summary['tests']:check(test['passed'] and sha(test['log'])==test['log_sha256'],'Functional log: '+test['name'])
            archive.copy_changed(functional,out/'supplementary_evidence/functional/SUMMARY.json')
            archive.copy_changed(run/'functional_validation/validator.py',out/'supplementary_evidence/functional/validator.py')
    else:
        for key,test in base['tests'].items():
            for field in ('log','raw_log'):check(sha(test[field])==test[field+'_sha256'],'C3 measured Sign: '+key+'/'+field)
        for key,syn in base['synthesis'].items():
            for name,wanted in syn['reports_sha256'].items():
                check(sha(out/'reference_synth'/key/name)==wanted,'C3 diagnostic: '+key+'/'+name)
    physical=out/'PHYSICAL_ARTIFACTS.json'
    if physical.is_file():
        proof=read(physical)
        check(proof['source_manifest_sha256']==manifest,'Physical artifact source')
        for name,wanted in proof['sha256'].items():check(sha(out/name)==wanted,'Physical artifact: '+name)
        if proof['complete']:check(all(not m for m in proof['missing'].values()),'Physical missing artifacts')
    check(not list(out.rglob('README.md')) and not list(out.rglob('*.csv')),'Archive format')
    check(not (out/'sim').exists() and not (out/'validation').exists(),'Detailed logs omitted')
    value=dict(run_root=str(run),source_manifest_sha256=manifest,passed=not errors,errors=errors,
        checks=checks,measurements_complete=complete,pending_measurements_are_not_a_pass=True)
    write(out/'AUDIT_SUMMARY.json',value)
    old=read(out/'ARTIFACTS.json') if (out/'ARTIFACTS.json').is_file() else {}
    old.update(complete=complete,omitted_details=['sim','validation'],sha256={str(p.relative_to(out)):sha(p)
        for p in out.rglob('*') if p.is_file() and p.name!='ARTIFACTS.json' and not p.name.endswith('.tmp')})
    write(out/'ARTIFACTS.json',old)
    return value


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('runs',nargs='*',type=Path);args=parser.parse_args()
    result=[audit(r) for r in (args.runs or [p.parent for p in sorted(FAMILY.glob('*/SOURCE.json'))])]
    print(json.dumps(result,ensure_ascii=False,indent=2));raise SystemExit(int(any(not r['passed'] for r in result)))
