#!/usr/bin/env python3
"""Refresh the selected-result report once after remaining measurements finish."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time


def read(path):
    return json.loads(path.read_text())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, required=True)
    args = parser.parse_args()
    run = args.run.resolve()
    meta = read(run / 'SOURCE.json')
    archive = Path(meta['archive'])
    while not read(run / 'STATE.json').get('complete'):
        time.sleep(60)
    selected = read(run / 'DECISION.json')['selected']
    command = [sys.executable, str(run / 'control/finalize_report.py'), '--run', str(run),
               '--selected-i', selected['i'], '--selected-c', selected['c'], '--adopted', 'true']
    subprocess.run(command, check=True)
    # The controller has exited its publishing loop before setting complete;
    # retain every late validation summary, then make a final content manifest.
    for source in (run / 'baseline_validation').rglob('SUMMARY.json'):
        target = archive / 'baseline_validation' / source.relative_to(run / 'baseline_validation')
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source.read_bytes())
    manifest = dict(complete=True, sha256={
        str(path.relative_to(archive)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in archive.rglob('*') if path.is_file()
        and path.name != 'ARTIFACTS.json' and not path.name.endswith('.tmp')})
    tmp = archive / 'ARTIFACTS.json.tmp'
    tmp.write_text(json.dumps(manifest, indent=2) + '\n')
    tmp.replace(archive / 'ARTIFACTS.json')
    print('Final report and artifact manifest complete; 60-second watcher exits.', flush=True)


if __name__ == '__main__':
    main()
