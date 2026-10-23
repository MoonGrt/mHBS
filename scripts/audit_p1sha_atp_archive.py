#!/usr/bin/env python3
"""Check frozen P1/SHA evidence without starting simulations or Vivado."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import tarfile

import experiment_archive as archive

ROOT = Path(os.environ.get('MHBS_P1SHA_WORKSPACE', Path(__file__).resolve().parents[1])).resolve()


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text())


def audit(run):
    run = Path(run).resolve()
    meta, state = read(run / 'SOURCE.json'), read(run / 'status.json')
    out, source = Path(meta['archive_directory']), Path(meta['source_root'])
    errors, checked = [], 0

    def check(condition, message):
        nonlocal checked
        checked += 1
        if not condition:
            errors.append(message)

    manifest_sha = sha(run / 'SOURCE.json')
    check(manifest_sha == sha(out / 'SOURCE.json') == state['source_manifest_sha256'], 'Source manifest binding')
    for name, wanted in meta['sha256'].items():
        check((source / name).is_file() and sha(source / name) == wanted, 'Frozen input: ' + name)
    for name, wanted in read(run / 'CONTROL_SOURCE.json').items():
        check(sha(run / 'control' / name) == sha(out / 'control' / name) == wanted, 'Control: ' + name)
    upgraded = run / 'DISPATCHER_UPGRADE.json'
    if upgraded.is_file():
        proof = read(upgraded)
        check(proof['source_manifest_sha256'] == manifest_sha and not proof['raw_jobs_terminated'],
              'Dispatcher upgrade source/job scope')
        for name, wanted in proof['new_controls_sha256'].items():
            check(sha(run / 'control_upgraded' / name) == sha(out / 'control_upgraded' / name) == wanted,
                  'Upgraded control: ' + name)
    rtl_names = read(out / 'RTL_SOURCE.json')['files']
    support_names = read(out / 'SUPPORT_SOURCE.json')
    for archive_name, members in [('rtl.tar.gz', rtl_names), ('support.tar.gz', support_names)]:
        with tarfile.open(out / archive_name, 'r:gz') as tar:
            check(set(tar.getnames()) == set(members), 'Archive member list: ' + archive_name)
            for name, wanted in members.items():
                actual = hashlib.sha256(tar.extractfile(name).read()).hexdigest()
                check(actual == wanted == meta['sha256'].get(name), 'Archived source: ' + name)
    for key, test in state['tests'].items():
        if test['status'] != 'passed':
            continue
        for field in ('log', 'raw_log'):
            path = Path(test[field])
            check(path.is_file() and sha(path) == test[field + '_sha256'], 'Sign log: ' + key + '/' + field)
        check(test.get('source_unchanged') and test.get('output_and_signature_cache_checked_bytewise'),
              'Sign bytewise/source proof: ' + key)
        if meta['kind'] == 'candidate':
            check(test.get('source_manifest_sha256') == manifest_sha, 'Sign manifest: ' + key)
        else:
            check(test.get('reused_source_manifest_sha256') == read(run / 'MATRIX_EVIDENCE.json')['source_manifest_sha256'],
                  'Reused Sign manifest: ' + key)
        for name, wanted in test['vectors_sha256'].items():
            check(meta['sha256'][name] == wanted, 'Sign vector binding: ' + key + '/' + name)
    for config, syn in state['synthesis'].items():
        if syn['status'] != 'passed':
            continue
        folder = run / 'synth' / config
        check(syn.get('source_manifest_sha256') == manifest_sha and syn.get('source_unchanged'),
              'Diagnostic source binding: ' + config)
        for name, wanted in syn['reports_sha256'].items():
            check(sha(folder / name) == wanted, 'Diagnostic report: ' + config + '/' + name)
            archived = out / 'synth' / config / name
            check(archived.is_file() and sha(archived) == wanted, 'Archived diagnostic: ' + config + '/' + name)
        check(sha(folder / 'synthesized.dcp') == syn['checkpoint_sha256'], 'Diagnostic DCP: ' + config)
        settings = (folder / 'settings.txt').read_text().splitlines()
        for value in ('diagnostic_only=1', 'top=common', 'period_ns=10.0', 'threads=2',
                      'mode=out_of_context', 'timing_driven=default', 'new_timing_exceptions=none'):
            check(value in settings, 'Diagnostic setting: ' + config + '/' + value)
    physical_file = run / 'PHYSICAL_STATUS.json'
    physical = read(physical_file) if physical_file.is_file() else None
    if physical:
        check(physical['source_manifest_sha256'] == manifest_sha, 'Physical phase source binding')
    for config, route in (physical['routes'] if physical else state['routing']).items():
        if route['status'] not in ('passed', 'target_not_met'):
            continue
        folder = Path(route.get('reused_from', run / 'jobs' / config))
        check(sha(folder / 'synth/synthesized.dcp') == route['synthesized_checkpoint_sha256'], 'Route synth DCP: ' + config)
        check(sha(folder / 'route/routed.dcp') == route['routed_checkpoint_sha256'], 'Route DCP: ' + config)
        check(route.get('source_unchanged'), 'Route frozen source: ' + config)
        if route.get('meets_target'):
            check(route['result']['setup_hold_met'] and route['result']['drc_errors'] == 0
                  and route['route_status']['passed'], 'Closed route proof: ' + config)
    physical_manifest = out / 'PHYSICAL_ARTIFACTS.json'
    if physical_manifest.is_file():
        proof = read(physical_manifest)
        check(proof['source_manifest_sha256'] == manifest_sha, 'Physical artifact source')
        for name, wanted in proof['sha256'].items():
            check((out / name).is_file() and sha(out / name) == wanted, 'Physical archive: ' + name)
        if proof['complete']:
            check(all(not missing for missing in proof['missing'].values()), 'Completed physical artifacts')
    functional = out / 'supplementary_evidence/functional/SUMMARY.json'
    if functional.is_file():
        summary = read(functional)
        check(summary['source_manifest_sha256'] == manifest_sha and summary['passed'] == 36
              and summary['failed'] == 0 and summary['source_unchanged'], 'Functional 36-group proof')
        check(sha(functional.with_name('validator.py')) == summary['validator_sha256'], 'Archived functional validator')
        for test in summary['tests']:
            check(test['passed'] and sha(test['log']) == test['log_sha256'], 'Functional log: ' + test['name'])
    for summary in (out / 'supplementary_evidence').rglob('BINDING.json'):
        data = read(summary)
        check(data['candidate_source_manifest_sha256'] == manifest_sha, 'Supplement source binding: ' + str(summary))
        for name, wanted in data.get('raw_logs_sha256', {}).items():
            check(Path(name).is_file() and sha(name) == wanted, 'Supplement raw log: ' + name)
    lineage = out / 'lineage/LINEAGE.json'
    if lineage.is_file():
        identity = read(lineage)
        check(identity['candidate_manifest_sha256'] == manifest_sha
              and sha(lineage.with_name('from_B0.patch')) == identity['patch_sha256'], 'Lineage patch/source binding')
    check(not list(out.rglob('*.csv')), 'No report CSV')
    check(not list(out.rglob('README.md')), 'No archive README')
    check(not (out / 'sim').exists() and not (out / 'validation').exists(), 'Detailed logs omitted from archive')
    result = dict(run_root=str(run), source_manifest_sha256=manifest_sha, checks=checked,
        errors=errors, passed=not errors, measurements_complete=state['complete'],
        validation_passed=state.get('validation_passed'), scope='Frozen inputs, controls, archives, completed measurements; pending jobs are not a pass')
    archive.atomic(out / 'AUDIT_SUMMARY.json', json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    artifact_file = out / 'ARTIFACTS.json'
    artifacts = read(artifact_file)
    artifacts['sha256'] = {str(path.relative_to(out)): sha(path) for path in out.rglob('*')
        if path.is_file() and path.name != 'ARTIFACTS.json' and not path.name.endswith('.tmp')}
    archive.atomic(artifact_file, json.dumps(artifacts, ensure_ascii=False, indent=2) + '\n')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('runs', nargs='*', type=Path)
    args = parser.parse_args()
    runs = args.runs or [p.parent for p in sorted((ROOT / 'build/p1sha_atp_optimization').glob('*/SOURCE.json'))]
    results = [audit(run) for run in runs]
    print(json.dumps([dict(run_root=r['run_root'], checks=r['checks'], passed=r['passed'],
                           errors=r['errors'], complete=r['measurements_complete']) for r in results], ensure_ascii=False, indent=2))
    raise SystemExit(int(any(not r['passed'] for r in results)))
