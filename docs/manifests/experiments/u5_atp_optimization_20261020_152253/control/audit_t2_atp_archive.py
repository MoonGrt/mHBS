#!/usr/bin/env python3
"""Verify completed frozen T2 candidates and refresh only archive evidence hashes."""
import argparse
import hashlib
from pathlib import Path
import tarfile

import run_t2_atp_optimization as measure

read, write, sha, require = measure.read, measure.write, measure.sha, measure.require


def check_tar(path, files):
    with tarfile.open(path, 'r:gz') as tar:
        for name, digest in files.items():
            stream = tar.extractfile(name)
            require(stream is not None and hashlib.sha256(stream.read()).hexdigest() == digest,
                    f'Changed frozen archive member: {path}/{name}')


def audit(run):
    global measure
    run = run.resolve()
    if read(run / 'SOURCE.json').get('schema') == 'u5_shake_atp_optimization_v1':
        import run_u5_atp_optimization
        measure = run_u5_atp_optimization
    else:
        import run_t2_atp_optimization
        measure = run_t2_atp_optimization
    evidence = measure.core.checked_evidence(run)
    meta, state = evidence['source'], evidence['results']
    require(meta.get('schema') == measure.SCHEMA
        and meta.get('baseline_manifest_sha256') == measure.BASELINE_SHA,
        f'Wrong T2 candidate identity: {run}')
    out = Path(meta['archive_directory'])
    require(sha(out / 'SOURCE.json') == evidence['manifest_sha256'], 'Archive SOURCE differs')
    rtl = {k: v for k, v in meta['sha256'].items() if k.startswith('rtl/')}
    rtl_package = dict(rtl)
    for name in ('sources.txt', 'scripts/clock.xdc'):
        if name in meta['sha256']:
            rtl_package[name] = meta['sha256'][name]
    check_tar(out / 'rtl.tar.gz', rtl_package)
    support = read(out / 'SUPPORT_SOURCE.json')
    require(sha(out / 'support_source.tar.gz') == support['archive_sha256'], 'Changed support archive')
    check_tar(out / 'support_source.tar.gz', support['files'])
    for config, item in state['synthesis'].items():
        for name, digest in item['reports_sha256'].items():
            require(sha(out / 'synth' / config / name) == digest,
                    f'Changed archived synthesis proof: {config}/{name}')
    validation = read(out / 'validation_summary/VALIDATION.json')
    require(validation.get('complete') is True and validation.get('passed') == 76
        and validation.get('failed') == 0 and validation.get('source_unchanged') is True
        and validation.get('source_manifest_sha256') == evidence['manifest_sha256']
        and validation.get('rtl_sha256') == rtl, 'Supplemental validation failed or unbound')
    for test in validation['tests']:
        require(sha(Path(test['log'])) == test['log_sha256'], f'Changed validation log: {test["name"]}')
    nested = 0
    for path in out.rglob('*SHA256.json'):
        values = read(path)
        if not values or not all(isinstance(v, str) and len(v) == 64 for v in values.values()):
            continue
        for name, digest in values.items():
            require(sha(path.parent / name) == digest, f'Changed nested archive proof: {path}/{name}')
        nested += 1
    baseline_label = meta.get('baseline_label', 'T2')
    lineage = read(out / 'lineage/LINEAGE.json')
    require(lineage.get('candidate_manifest_sha256') == evidence['manifest_sha256']
        and lineage.get('baseline_manifest_sha256') == measure.BASELINE_SHA
        and lineage.get('patch_sha256') == sha(out / f'lineage/from_{baseline_label}.patch'),
        'Source lineage or patch changed')
    require(not list(out.rglob('*.csv')) and not list(out.rglob('README.md')),
            'Report CSV or archive README is forbidden')
    require(not (out / 'sim').exists() and not (out / 'validation').exists(),
            'Detailed simulation/validation logs must stay in the build directory')
    tools = out / 'analysis_tools'
    measure.core.archive.copy_changed(Path(__file__), tools / Path(__file__).name)
    controls = read(out / 'CONTROL_SOURCE.json')
    for name, digest in controls.items():
        require(sha(out / 'control' / name) == digest
            and sha(run / 'control' / name) == digest, f'Changed frozen measurement tool: {name}')
    data = dict(schema=f'mhbs.{baseline_label.lower()}_atp.archive_audit.v1', candidate_run=str(run),
        source_manifest_sha256=evidence['manifest_sha256'], checked_at=measure.now(),
        frozen_files_unchanged=True, rtl_tar_checked_files=len(rtl),
        rtl_package_auxiliary_inputs_checked=len(rtl_package) - len(rtl),
        support_tar_checked_files=len(support['files']), support_tar_sha256_verified=True,
        hierarchical_timing_tool_logs_present=True, measured_sign_cases=6,
        supplemental_validation_passed=76, nested_checksum_manifests_checked=nested,
        lineage_present=True, workspace_validation_summary_present=(out / 'workspace_validation_summary').exists(),
        detailed_sim_validation_logs_archived=False,
        new_routing_started=bool(state['routing']), audit_tool_sha256=sha(Path(__file__)),
        frozen_measurement_tool_checksums_validated=True)
    write(out / 'analysis_evidence/ARCHIVE_AUDIT.json', data)
    artifacts = read(out / 'ARTIFACTS.json')
    require(not any(artifacts['missing'].values()), 'Archived synthesis reports are missing')
    artifacts['sha256'] = {str(p.relative_to(out)): sha(p) for p in out.rglob('*')
        if p.is_file() and p.name != 'ARTIFACTS.json' and not p.name.endswith('.tmp')}
    write(out / 'ARTIFACTS.json', artifacts)
    print(f'{run.name}: archive proof PASS, {len(artifacts["sha256"])} files', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run', nargs='+', type=Path)
    args = parser.parse_args()
    for run in args.run:
        audit(run)


if __name__ == '__main__':
    main()
