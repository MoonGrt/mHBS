#!/usr/bin/env python3
"""Synthesize an immutable captured candidate while the worktree evolves."""
import argparse
import json
import shutil
import subprocess
import tarfile
from autonomous_flow import BUILD, sha

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('tag')
    args = parser.parse_args()
    folder = BUILD/args.tag
    inputs = json.loads((folder/'inputs.json').read_text())
    snapshot = folder/'source_snapshot.tar.gz'
    assert sha(snapshot) == inputs['snapshot_sha256']
    workspace = BUILD/(args.tag+'_workspace')
    workspace.mkdir(exist_ok=False)
    with tarfile.open(snapshot) as tar:
        tar.extractall(workspace, filter='data')
    for name, digest in inputs['source_sha256'].items():
        assert sha(workspace/name) == digest, name
    command = ['vivado', '-mode', 'batch', '-nolog', '-nojournal', '-source',
        'experiments/v4.1/synth.tcl', '-tclargs', args.tag,
        str(inputs['lanes']), str(inputs['unroll']), 'Default', 'rebuilt']
    with (folder/'driver.log').open('w') as log:
        subprocess.run(command, cwd=workspace, stdout=log, stderr=subprocess.STDOUT, check=True)
    for path in (workspace/'build/v4.1'/args.tag).iterdir():
        if path.is_file():
            destination = folder/path.name
            if destination.exists():
                assert sha(destination) == sha(path), 'refuse overwrite '+path.name
            else:
                shutil.copy2(path, destination)
    print('SNAPSHOT_SYNTH_PASS', args.tag)

if __name__ == '__main__': main()
