#!/usr/bin/env python3
"""Fresh functional smoke test of the slimmed production tree; no Vivado."""
import argparse
import hashlib
import json
import subprocess
import sys
import tarfile
import time
from pathlib import Path

from v42_external_flow import BASE, BUILD, ROOT, NAMES, capture, sha, write


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('tag')
    args = parser.parse_args()
    if not args.tag or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-' for c in args.tag):
        parser.error('tag must contain only letters, digits, underscores and hyphens')
    folder = BUILD / args.tag
    if folder.exists():
        parser.error('use a fresh tag: this check must rebuild its RTL binaries')
    status = ROOT / 'build' / ('smoke_' + args.tag + '.json')
    started = time.time()
    result = dict(tag=args.tag, passed=False, status='running', stages=[],
                  scope='12 software cases, current unit groups, 12 Keygen/Sign RTL cases, 6 normal Verify RTL cases',
                  full_extended_regression=False, vivado_run=False)

    def save():
        result['elapsed_seconds'] = time.time() - started
        temporary = status.with_suffix('.tmp')
        write(temporary, result)
        temporary.replace(status)

    try:
        for name, command in (
            ('test', ['make', 'test', 'TAG=' + args.tag]),
            ('verify_quick', [sys.executable, 'scripts/verify_v42_verify.py', args.tag, '--quick']),
            ('frozen_evidence', ['make', 'reproduce-v42', 'reproduce-ku']),
        ):
            result['current_stage'] = name
            save()
            subprocess.run(command, cwd=ROOT, check=True)
            result['stages'].append(name)
        # Re-capture rejects changed/missing inputs, including test drivers.
        assert capture(args.tag) == folder
        inputs = json.loads((folder / 'inputs.json').read_text())
        assert sha(folder / 'source_snapshot.tar.gz') == inputs['snapshot_sha256']
        with tarfile.open(folder / 'source_snapshot.tar.gz') as snapshot:
            for name, digest in inputs['source_sha256'].items():
                assert hashlib.sha256(snapshot.extractfile(name).read()).hexdigest() == digest, name
        normal = json.loads((folder / 'simulation.json').read_text())
        selected = json.loads((BASE / 'current_core.json').read_text())['candidate']
        baseline = json.loads((BASE / 'candidates' / selected / 'simulation.json').read_text())
        assert normal['passed']
        assert set(normal['cases']) == {name + '_' + op for name in NAMES for op in ('keygen', 'sign')}
        for name, row in normal['cases'].items():
            assert row['passed']
            for key in ('output_sha256', 'boot_cycles', 'keygen_cycles', 'sign_cycles', 'hashes', 'permutations', 'total_cycles'):
                if name in baseline['cases']:assert row[key] == baseline['cases'][name][key], (name, key)
            assert sha(folder / 'logs' / (name + '.actual.mem')) == row['output_sha256']
            assert sha(folder / 'logs' / (name + '.log')) == row['log_sha256']
        verify = json.loads((folder / 'verify/results.json').read_text())
        assert verify['passed'] and verify['quick'] and set(verify['profiles']) == set(NAMES)
        assert verify['source_snapshot_sha256'] == inputs['snapshot_sha256']
        for name, cases in verify['profiles'].items():
            row = cases['normal']
            assert row['passed'] and row['accepted'] == 1
            assert sha(folder / 'verify' / name / 'normal.log') == row['log_sha256']
        result.update(passed=True, status='completed', current_stage=None,
                      baseline_match=True, source_snapshot_sha256=inputs['snapshot_sha256'],
                      results=str(folder.relative_to(ROOT)))
    except Exception as error:
        result.update(status='failed', error=repr(error))
        raise
    finally:
        save()
    print('CURRENT_SMOKE_PASS', args.tag, flush=True)


if __name__ == '__main__':
    main()
