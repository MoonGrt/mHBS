#!/usr/bin/env python3
"""Route the six source-bound layout-3 shells and audit timing and ROM contents."""
import argparse
import concurrent.futures
import json
from pathlib import Path
import re
import shutil
import subprocess
import time

from v42_external_flow import ROOT, BASE, BUILD, NAMES, sha, write, tool_version


def resources(path):
    text = path.read_text()
    result = {}
    for label, key in [('Slice LUTs', 'lut'), ('Slice Registers', 'ff'),
                       ('LUT as Memory', 'lutram'), ('Block RAM Tile', 'bram36'), ('DSPs', 'dsp')]:
        match = re.search(r'\|\s*' + re.escape(label) + r'\*?\s*\|\s*([\d,.]+)', text)
        if not match:
            raise ValueError(f'Missing {label}: {path}')
        result[key] = float(match[1].replace(',', ''))
    result['equivalent_slice'] = result['lut']/4 + result['ff']/8 + result['bram36']*232.4 + result['dsp']*102.4
    return result


def audit_rom(path, image_folder):
    words = {kind: [int(x, 16) for x in (image_folder / (kind + '.mem')).read_text().split()]
             for kind in ('program', 'template', 'descriptor')}
    seen = set()
    for line in path.read_text().splitlines():
        kind, port, bit, cell, bits, pins, init = line.split('\t')
        pins = list(map(int, pins.split(',')))
        bits, bit, port = int(bits), int(bit), int(port)
        assert sorted(pins) == list(range(bits)), cell
        expected = sum(((words[kind][sum(((i >> p) & 1) << a for p, a in enumerate(pins))] >> bit) & 1) << i
                       for i in range(1 << bits))
        assert int(init.split("'h")[1], 16) == expected, cell
        assert (kind, port, bit) not in seen
        seen.add((kind, port, bit))
    expected_bits = {(kind, port, bit) for kind in words
                     for port in range(2 if kind == 'descriptor' else 1) for bit in range(64)}
    assert seen == expected_bits
    return dict(passed=True, cells=len(seen), mapping_sha256=sha(path))


def audit_timing(folder):
    timing = (folder / 'timing_summary.rpt').read_text()
    assert 'All user specified timing constraints are met.' in timing, 'Timing summary did not pass'
    # The summary covers setup, hold and pulse-width checks for the full OOC top.
    checks = (folder / 'check_timing.rpt').read_text()
    for category in ('no_clock', 'unconstrained_internal_endpoints', 'no_input_delay', 'no_output_delay', 'partial_input_delay', 'partial_output_delay'):
        match = re.search(r'checking\s+' + category + r'\s*\((\d+)\)', checks, re.I)
        assert match and int(match[1]) == 0, (category, checks)
    route = (folder / 'route_status.rpt').read_text()
    counts = {}
    for label in ('routable nets', 'fully routed nets', 'nets with routing errors'):
        match = re.search(r'# of\s+' + label + r'\.*\s*:\s*(\d+)', route, re.I)
        assert match, label
        counts[label] = int(match[1])
    assert counts['routable nets'] == counts['fully routed nets'] > 0, counts
    assert counts['nets with routing errors'] == 0, counts
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('tag')
    parser.add_argument('--jobs', type=int, default=3)
    parser.add_argument('--only', nargs='+', help='route selected shells; do not publish full acceptance')
    parser.add_argument('--wait-for-synthesis', action='store_true',
                        help='start each route as its independently synthesized shell completes')
    args = parser.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.-]*', args.tag) or args.jobs < 1:
        parser.error('invalid tag or jobs')
    folder = BUILD / args.tag
    inputs = json.loads((folder / 'inputs.json').read_text())
    assert sha(folder / 'source_snapshot.tar.gz') == inputs['snapshot_sha256']
    for path, digest in inputs['rtl_sha256'].items():
        assert sha(ROOT / path) == digest, path
    sim = json.loads((folder / 'simulation.json').read_text())
    assert sim['passed'] and sim['rtl_sha256'] == inputs['rtl_sha256']
    names = [n + '_' + op for n in NAMES for op in ('keygen', 'sign')]
    assert set(sim['cases']) == set(names)
    if args.only:
        if len(set(args.only)) != len(args.only) or not set(args.only) <= set(names):
            parser.error('invalid or duplicate shell names')
        names = args.only
    out = folder / 'route'
    out.mkdir(exist_ok=True)
    flow = ROOT / 'experiments/v4.2/external_job_message'
    for name in ('route.tcl', 'rom_mapping.tcl', 'finalize_core.tcl'):
        dest = out / name
        if dest.exists():
            assert sha(dest) == sha(flow / name), 'route flow changed; use a new run directory'
        else:
            shutil.copy2(flow / name, dest)
    version = tool_version('vivado', '-version')

    def one(name):
        target = out / name
        target.mkdir(exist_ok=True)
        source = folder / 'synthesis' / name / 'post_synth.dcp'
        if args.wait_for_synthesis:
            deadline = time.monotonic() + 7200
            staged = folder / 'synth_source/build/v4.2/external_job_message' / args.tag / 'synthesis' / name / 'post_synth.dcp'
            while not source.exists():
                log = (folder / 'synth.log').read_text(errors='replace')
                if staged.exists() and re.search(r'^EXTERNAL_TOP_SYNTH_PASS ' + name + r' ', log, re.M):
                    source = staged
                    break
                if re.search(r'^ERROR:', log, re.M) or time.monotonic() > deadline:
                    raise RuntimeError('Synthesis failed or timed out; inspect synth.log')
                time.sleep(20)
        command = ['vivado', '-mode', 'batch', '-nolog', '-nojournal', '-source', str(out / 'route.tcl'),
                   '-tclargs', str(source), str(target)]
        invocation = dict(command=command, started=time.time(), source_dcp_sha256=sha(source),
                          route_script_sha256=sha(out / 'route.tcl'), rom_script_sha256=sha(out / 'rom_mapping.tcl'), finalize_script_sha256=sha(out / 'finalize_core.tcl'),
                          tool_versions={'vivado': version}, source_snapshot_sha256=inputs['snapshot_sha256'])
        completed = ((target / 'final_clock.json').exists()
                     and (target / 'post_route_final_clock.dcp').exists()
                     and (target / 'route.log').exists()
                     and re.search(r'^EXTERNAL_ROUTE_PASS ', (target / 'route.log').read_text(), re.M))
        if not completed:
            write(target / 'invocation.json', invocation)
            with (target / 'route.log').open('w') as log:
                subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True)
        else:
            previous = json.loads((target / 'invocation.json').read_text())
            for key in ('source_dcp_sha256', 'route_script_sha256', 'rom_script_sha256', 'finalize_script_sha256', 'source_snapshot_sha256'):
                assert previous[key] == invocation[key], key
        clock = json.loads((target / 'final_clock.json').read_text())
        assert clock['wns_ns'] >= .0999 and clock['whs_ns'] >= 0
        audit_timing(target)
        profile, operation = name.rsplit('_', 1)
        rom = audit_rom(target / 'initialized_rom.tsv', folder / 'synth_source' / BASE.relative_to(ROOT) / 'images' / profile)
        cycles = sim['cases'][name][operation + '_cycles']
        result = dict(passed=True, core_timing_pass=True, **resources(target / 'utilization.rpt'), **clock,
                      frequency_mhz=1000/clock['period_ns'], operation_cycles=cycles, rom_audit=rom)
        result['latency_ms'] = cycles * clock['period_ns'] / 1e6
        result['area_time_product'] = result['equivalent_slice'] * result['latency_ms']
        result['evidence_sha256'] = {p.name: sha(p) for p in target.iterdir() if p.is_file() and p.name != 'result.json'}
        write(target / 'result.json', result)
        print('EXTERNAL_ROUTED_TOP_PASS', name, result['equivalent_slice'], result['frequency_mhz'], flush=True)
        return name, result

    with concurrent.futures.ThreadPoolExecutor(args.jobs) as pool:
        results = dict(pool.map(one, names))
    write(out / ('partial_result.json' if args.only else 'result.json'), dict(passed=True, core_timing_pass=True, io_timing_qualified=False, stage='post_route', tag=args.tag,
          timing_scope='out_of_context internal register-to-register timing; external input/output paths excluded; I/O not signed off',
          rtl_sha256=inputs['rtl_sha256'], source_snapshot_sha256=inputs['snapshot_sha256'],
          common_frequency_mhz=min(row['frequency_mhz'] for row in results.values()), tops=results))
    print('EXTERNAL_ROUTE_PARTIAL_PASS' if args.only else 'EXTERNAL_ROUTE_ALL_PASS', args.tag, flush=True)


if __name__ == '__main__':
    main()
