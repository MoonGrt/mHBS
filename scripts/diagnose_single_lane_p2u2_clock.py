#!/usr/bin/env python3
"""Run the separately prepared 110 MHz P2U2 synthesis diagnostic."""
import argparse
import fcntl
import importlib.util
import json
from pathlib import Path
import sys
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', type=Path, required=True)
    args = parser.parse_args()
    root = args.directory.resolve()
    source = root / 'source'
    diagnostic = root / 'P2U2/relaxed_110mhz'
    sys.path.insert(0, str(source / 'scripts'))
    spec = importlib.util.spec_from_file_location('frozen_flow', source / 'scripts/run_single_lane_13.py')
    flow = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(flow)
    flow.OUT, flow.SOURCE = root, source
    with (root / 'run.lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        config = json.loads((diagnostic / 'config.json').read_text())
        started = time.monotonic()
        try:
            flow.bind_snapshot()
            for name, expected in config['input_sha256'].items():
                assert flow.sha(diagnostic / name) == expected, name
            flow.write(diagnostic / 'status.json', dict(state='synthesizing', started_at=flow.now(),
                                                       vivado_threads=8, clock_period_ns=9.090909))
            flow.update(state='diagnostic_synthesis', active_point='P2U2', active_vivado_threads=8,
                        active_clock_period_ns=9.090909)
            work = root / 'work/P2U2_relaxed_110mhz'
            work.mkdir(parents=True, exist_ok=True)
            flow.tool_run(['vivado', '-mode', 'batch', '-nolog', '-nojournal', '-source', diagnostic / 'synth.tcl'],
                          diagnostic / 'vivado.log', work)
            assert 'PU_SYNTH_PASS P2U2' in (diagnostic / 'vivado.log').read_text()
            area = flow.support.area(diagnostic / 'core_utilization.rpt')
            simulation = json.loads((root / 'P2U2/simulation.json').read_text())
            result = dict(point='P2U2', diagnostic=True, clock_period_ns=9.090909,
                          original_clock_period_ns=6.666667, vivado_threads=8,
                          elapsed_seconds=time.monotonic() - started,
                          snapshot_sha256=config['snapshot_sha256'],
                          compute_cycles=simulation['sign_cycles'], total_cycles=simulation['total_cycles'],
                          hashes=simulation['hashes'], permutations=simulation['permutations'],
                          output_sha256=simulation['output_sha256'],
                          assumed_mhz=110, time_ms=simulation['sign_cycles']/110000,
                          atp_slice_ms=area['equivalent_slice']*simulation['sign_cycles']/110000,
                          routed=False, **area)
            flow.write(diagnostic / 'result.json', result)
            flow.write(diagnostic / 'evidence_sha256.json', {
                name: flow.sha(diagnostic / name) for name in
                ('config.json', 'synth.tcl', 'clock.xdc', 'mhbs_common.sv', 'vivado.log',
                 'core_utilization.rpt', 'core_hierarchical.rpt', 'core_timing.rpt', 'result.json')})
            (diagnostic / 'report.md').write_text(
                '# P2U2 relaxed-clock synthesis diagnostic\n\n'
                'Same frozen RTL as the 13-point matrix. Only the clock constraint changed from 6.666667 ns to '
                '9.090909 ns relative to the stopped 8-thread attempt. Vivado uses 8 threads. No placement/routing.\n\n'
                'This result is kept separately because its synthesis constraint differs from the other matrix points. '
                'Simulation cycles and outputs are reused from the identical frozen RTL.\n\n'
                '| LUT | FF | LUTRAM | BRAM36 | DSP | Eq. Slice | Cycles | Assumed MHz | ATP Slice·ms |\n'
                '|---:|---:|---:|---:|---:|---:|---:|---:|---:|\n'
                f'| {area["lut"]} | {area["ff"]} | {area["lutram"]} | {area["bram36"]} | {area["dsp"]} | '
                f'{area["equivalent_slice"]} | {simulation["sign_cycles"]} | 110 | {result["atp_slice_ms"]:.3f} |\n')
            flow.write(diagnostic / 'status.json', dict(state='complete', ended_at=flow.now(),
                                                       elapsed_seconds=result['elapsed_seconds']))
            flow.update(state='diagnostic_complete', diagnostic_result=str(diagnostic / 'result.json'))
            print('RELAXED_SYNTH_PASS P2U2', area['lut'], result['elapsed_seconds'], flush=True)
        except Exception as exc:
            flow.write(diagnostic / 'failure.json', dict(error=str(exc), at=flow.now()))
            flow.write(diagnostic / 'status.json', dict(state='failed', error=str(exc), updated_at=flow.now()))
            flow.update(state='diagnostic_failed', diagnostic_error=str(exc))
            raise


if __name__ == '__main__':
    main()
