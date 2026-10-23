#!/usr/bin/env python3
"""Audit E-round immutable inputs and available evidence without launching tools."""
import argparse
import hashlib
import json
from pathlib import Path
import tarfile

import audit_p1sha_timing_refine as prior
import experiment_archive as archive
import run_p1sha_atp_e as e


def audit(run):
    run=Path(run).resolve();meta=e.read(run/'SOURCE.json');out=Path(meta['archive_directory'])
    if meta['kind']=='candidate' and not (run/'DISPOSITION.json').exists():
        result=prior.audit(run)
    else:
        manifest=e.sha(run/'SOURCE.json');errors=[];checks=0
        def check(ok,message):
            nonlocal checks
            checks+=1
            if not ok:errors.append(message)
        check(e.sha(out/'SOURCE.json')==manifest,'Archived manifest differs')
        for name,wanted in meta['sha256'].items():
            check(e.sha(Path(meta['source_root'])/name)==wanted,'Frozen input: '+name)
        for name,wanted in e.read(run/'CONTROL_SOURCE.json').items():
            check(e.sha(run/'control'/name)==e.sha(out/'control'/name)==wanted,'Control: '+name)
        for tarname,index in (('rtl.tar.gz','RTL_SOURCE.json'),('support.tar.gz','SUPPORT_SOURCE.json')):
            members=e.read(out/index)
            if index=='RTL_SOURCE.json':members=members['files']
            with tarfile.open(out/tarname,'r:gz') as tar:
                check(set(tar.getnames())==set(members),'Tar members: '+tarname)
                for name,wanted in members.items():
                    check(hashlib.sha256(tar.extractfile(name).read()).hexdigest()==wanted==meta['sha256'][name],
                        'Archived input: '+name)
        withdrawn=(run/'DISPOSITION.json').exists()
        if withdrawn:
            disposition=e.read(run/'DISPOSITION.json');state=e.read(run/'status.json')
            check(disposition['status']=='withdrawn_before_synthesis' and not disposition['vivado_started']
                and not disposition['route_requested'] and disposition['source_manifest_sha256']==manifest,
                'Withdrawal disposition')
            check(all(job['status'] in ('pending','waiting_for_capacity') for job in state['synthesis'].values()),
                'Withdrawn supervisor started synthesis')
            check(not (run/'PHYSICAL_LAUNCH.json').exists(),'Withdrawn precursor has physical phase')
            complete=False
        else:
            refs=e.read(run/'REFERENCES.json');complete=True
            check(manifest==e.BASELINE_SHA,'Baseline identity')
            for label,ref in refs.items():
                original=Path(ref['reference_run']);stored=out/'reference_sources'/label
                check(ref['source_inputs_checked'] and ref['actual_logs_and_reports_checked'],label+' reference proof')
                check(e.sha(original/'SOURCE.json')==e.sha(stored/'SOURCE.json')==ref['source_manifest_sha256'],
                    label+' archived original manifest')
                original_meta=e.read(original/'SOURCE.json')
                for name,wanted in original_meta['sha256'].items():
                    check(e.sha(Path(original_meta['source_root'])/name)==wanted,label+' original input: '+name)
                for key,syn in ref['synthesis'].items():
                    for name,wanted in syn['reports_sha256'].items():
                        check(e.sha(original/'synth'/key/name)==e.sha(stored/'synth'/key/name)==wanted,
                            label+' diagnostic: '+key+'/'+name)
                for key,test in ref['tests'].items():
                    for field in ('log','raw_log'):
                        check(e.sha(test[field])==test[field+'_sha256'],label+' actual Sign log: '+key+'/'+field)
        check(not list(out.rglob('README.md')) and not list(out.rglob('*.csv')),'Archive format')
        check(not (out/'sim').exists() and not (out/'validation').exists(),'Detailed logs omitted')
        result=dict(run_root=str(run),source_manifest_sha256=manifest,passed=not errors,errors=errors,
            checks=checks,measurements_complete=complete,pending_measurements_are_not_a_pass=True,
            withdrawn_before_synthesis=withdrawn)
        e.write(out/'AUDIT_SUMMARY.json',result)
    archive.copy_changed(Path(__file__),out/'audit_control'/Path(__file__).name)
    old=e.read(out/'ARTIFACTS.json') if (out/'ARTIFACTS.json').exists() else {}
    old.update(updated_at=e.now(),complete=result['measurements_complete'],omitted_details=['sim','validation'],
        sha256={str(p.relative_to(out)):e.sha(p) for p in out.rglob('*')
            if p.is_file() and p.name!='ARTIFACTS.json' and not p.name.endswith('.tmp')})
    e.write(out/'ARTIFACTS.json',old)
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('runs',nargs='*',type=Path);args=parser.parse_args()
    result=[audit(r) for r in (args.runs or [p.parent for p in sorted(e.FAMILY.glob('*/SOURCE.json'))])]
    archive.index();print(json.dumps(result,ensure_ascii=False,indent=2))
    raise SystemExit(int(any(not item['passed'] for item in result)))
