#!/usr/bin/env python3
"""Start the frozen single-lane matrix in a detached user service."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', type=Path, required=True)
    parser.add_argument('--unit', default='mhbs-single-13-20261009-v2')
    args = parser.parse_args()
    if not all(c.isalnum() or c in '-_' for c in args.unit):
        parser.error('invalid service name')
    directory = args.directory.resolve()
    config = json.loads((directory / 'config.json').read_text())
    expected = [[p, 1] for p in (1, 2, 3, 4, 6, 8, 12)] + [[p, 2] for p in (1, 2, 3, 4, 6, 12)]
    assert config['points'] == expected
    assert (config['max_parallel_points'], config['vivado_threads_per_point'], config['compile_threads_per_point']) == (13, 2, 2)
    digest = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
    assert digest(directory / 'source_snapshot.tar.gz') == config['snapshot_sha256']
    source = directory / 'source'
    for name, expected_hash in config['source_sha256'].items():
        assert digest(source / name) == expected_hash, name
    log = directory / 'service.log'
    subprocess.run([
        'systemd-run', '--user', f'--unit={args.unit}', '--collect',
        f'--working-directory={source}',
        f'--property=StandardOutput=append:{log}',
        f'--property=StandardError=append:{log}',
        '--property=KillMode=control-group', '--property=Restart=no',
        f'--setenv=PATH={os.environ["PATH"]}',
        sys.executable, str(source / 'scripts/run_single_lane_13.py'),
        'run', '--directory', str(directory),
    ], check=True)
    metadata = dict(task=args.unit + '.service', log=str(log),
                    status=str(directory / 'status.json'),
                    snapshot_sha256=config['snapshot_sha256'])
    (directory / 'service.json').write_text(json.dumps(metadata, indent=2) + '\n')
    print(json.dumps(metadata))


if __name__ == '__main__':
    main()
