#!/usr/bin/env python3
"""Bind the independent all-slot stress harness to one immutable F candidate."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
import json
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / 'tmp/sha2_fullslots_E2_20261021'


def sha(path):
    return sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-root', type=Path, required=True)
    args = parser.parse_args()
    run = args.run_root.resolve()
    manifest = run / 'SOURCE.json'
    meta = json.loads(manifest.read_text())
    source = Path(meta['source_root'])
    work = Path(__file__).resolve().parent / run.name / 'fullslots'
    work.mkdir(parents=True, exist_ok=False)
    old = json.loads((BASE / 'SOURCE_BINDING.json').read_text())
    for name in ('tb_fullslots.sv', 'check_fullslots.py'):
        shutil.copyfile(BASE / name, work / name)
    rtl = {name: digest for name, digest in meta['sha256'].items() if name.startswith('rtl/')}
    assert all(sha(source / name) == digest for name, digest in rtl.items())
    compiled = {name: rtl[name] for name in old['compiled_rtl_sha256']}
    for name in compiled:
        target = work / 'core' / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source / name, target)
    binding = dict(source_manifest=str(manifest), source_manifest_sha256=sha(manifest),
        source_root=str(source), all_core_rtl_sha256=rtl, compiled_rtl_sha256=compiled,
        base_harness_sha256=old['base_harness_sha256'], new_harness_sha256=sha(work / 'tb_fullslots.sv'),
        tool_sha256=sha(work / 'check_fullslots.py'),
        scope='Unmodified independent E2 all-slot harness/tool against frozen F RTL; no historical source substituted')
    (work / 'SOURCE_BINDING.json').write_text(json.dumps(binding, indent=2) + '\n')

    def execute(case):
        p, synthesis = case
        command = [sys.executable, str(work / 'check_fullslots.py'), '--pipeline', str(p)]
        if synthesis:
            command.append('--synthesis')
        log = work / f'P{p}U1_syn{int(synthesis)}_driver.log'
        with log.open('w') as stream:
            code = subprocess.run(command, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT).returncode
        print(f'P{p}U1 synthesis={int(synthesis)} exit={code}', flush=True)
        return dict(pipeline=p, synthesis=synthesis, returncode=code, log=str(log), log_sha256=sha(log))

    with ThreadPoolExecutor(max_workers=4) as pool:
        jobs = list(pool.map(execute, [(p, syn) for p in (12, 24) for syn in (False, True)]))
    passed = all(job['returncode'] == 0 for job in jobs)
    rows = []
    for job in jobs:
        folder = work / 'runs' / (f'P{job["pipeline"]}U1' + ('_synthesis' if job['synthesis'] else ''))
        coverage = folder / 'coverage.json'
        if not coverage.exists():
            passed = False
            continue
        data = json.loads(coverage.read_text())
        passed = passed and data['passed'] and data['full_context_occupancy']
        for family in data['coverage']:
            rows.append(dict(family['coverage'], pipeline=job['pipeline'], synthesis=job['synthesis'],
                passed=family['passed'], vector_sha256=family['vector_sha256']))
    for p in (12, 24):
        for family in range(3):
            pair = [row for row in rows if row['pipeline'] == p and row['family'] == family]
            passed = passed and len(pair) == 2
            if len(pair) == 2:
                passed = passed and all(pair[0][key] == pair[1][key]
                    for key in ('hashes', 'permutations', 'requests', 'returns', 'total_cycles'))
    passed = passed and all(sha(source / name) == digest for name, digest in rtl.items())
    summary = dict(passed=passed, source_binding=binding, groups=len(rows), expected_groups=12,
        total_requests=sum(row['requests'] for row in rows), total_returns=sum(row['returns'] for row in rows),
        all_context_occupancy=True if passed else None, normal_synthesis_metric_equality=passed,
        test_commands=jobs, rows=rows)
    (work / 'SUMMARY.json').write_text(json.dumps(summary, indent=2) + '\n')
    out = Path(meta['archive_directory']) / 'supplementary_evidence/fullslots'
    out.mkdir(parents=True, exist_ok=True)
    for name in ('SUMMARY.json', 'SOURCE_BINDING.json', 'check_fullslots.py', 'tb_fullslots.sv'):
        shutil.copyfile(work / name, out / name)
    shutil.copyfile(__file__, out / Path(__file__).name)
    print(json.dumps({key: summary[key] for key in ('passed', 'groups', 'total_requests', 'total_returns')}), flush=True)
    return 0 if passed else 1


if __name__ == '__main__':
    raise SystemExit(main())
