#!/usr/bin/env python3
"""Resynthesize only P2U2 with eight threads using the original frozen source."""
import argparse
import csv
import fcntl
import importlib.util
import json
from pathlib import Path
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', type=Path, required=True)
    args = parser.parse_args()
    directory = args.directory.resolve()
    source = directory / 'source'
    sys.path.insert(0, str(source / 'scripts'))
    spec = importlib.util.spec_from_file_location('frozen_matrix', source / 'scripts/run_single_lane_13.py')
    flow = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(flow)
    flow.OUT = directory
    flow.SOURCE = source
    flow.BUILD = directory / 'work/threads8'
    flow.BUILD.mkdir(parents=True, exist_ok=True)
    with (directory / 'run.lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            flow.bind_snapshot()
            config = json.loads((directory / 'config.json').read_text())
            metadata = dict(point='P2U2', vivado_threads=8, max_parallel_points=1,
                            snapshot_sha256=config['snapshot_sha256'],
                            change='Only general.maxThreads changed from 2 to 8; original RTL and constraints retained',
                            script_sha256=flow.sha(Path(__file__)), started_at=flow.now())
            flow.write(directory / 'P2U2/resynthesis_8threads.json', metadata)
            original_run = flow.tool_run

            def run_with_threads(cmd, log, cwd=None):
                if str(cmd[0]) == 'vivado':
                    tcl = Path(cmd[cmd.index('-source') + 1])
                    text = tcl.read_text()
                    if 'set_param general.maxThreads 2' in text:
                        assert text.count('set_param general.maxThreads 2') == 1
                        tcl.write_text(text.replace('set_param general.maxThreads 2',
                                                   'set_param general.maxThreads 8\nputs "VIVADO_THREADS [get_param general.maxThreads]"'))
                    else:
                        assert text.count('set_param general.maxThreads 8') == 1
                    assert tcl.parent == directory / 'P2U2'
                return original_run(cmd, log, cwd or source)

            flow.tool_run = run_with_threads
            flow.update(state='resynthesizing', active_point='P2U2', active_vivado_threads=8)
            flow.point(2, 2)
            for name in ('synthesis.json', 'result.json'):
                path = directory / 'P2U2' / name
                if path.exists():
                    result = json.loads(path.read_text())
                    result['vivado_threads'] = 8
                    flow.write(path, result)
            flow.finish()
            # Thread count is part of the evidence, including in the final table.
            report = directory / 'report.md'
            report.write_text(report.read_text() + '\nP2U2 was restarted with one Vivado process and 8 threads at user request; all other points used 2 threads. RTL and synthesis clock constraint were unchanged. The stopped attempt is retained in P2U2/attempt_threads2/.\n')
            path = directory / 'results.json'
            results = json.loads(path.read_text())
            results['vivado_threads_by_point'] = {row['point']: 8 if row['point'] == 'P2U2' else 2 for row in results['rows']}
            flow.write(path, results)
            path = directory / 'results.csv'
            with path.open(newline='') as stream:
                reader = csv.DictReader(stream)
                fields = list(reader.fieldnames) + ['vivado_threads']
                rows = list(reader)
            with path.open('w', newline='') as stream:
                writer = csv.DictWriter(stream, fields, lineterminator='\n')
                writer.writeheader()
                for row in rows:
                    row['vivado_threads'] = 8 if row['point'] == 'P2U2' else 2
                    writer.writerow(row)
            metadata['ended_at'] = flow.now()
            metadata['state'] = json.loads((directory / 'status.json').read_text())['points']['P2U2']
            flow.write(directory / 'P2U2/resynthesis_8threads.json', metadata)
            hashes = json.loads((directory / 'evidence_sha256.json').read_text())
            for name in ('report.md', 'results.json', 'results.csv', 'P2U2/resynthesis_8threads.json'):
                hashes[name] = flow.sha(directory / name)
            flow.write(directory / 'evidence_sha256.json', hashes)
        except Exception as exc:
            flow.write(directory / 'P2U2/resynthesis_service_failure.json', dict(error=str(exc), at=flow.now()))
            flow.update(state='failed', error=str(exc))
            raise


if __name__ == '__main__':
    main()
