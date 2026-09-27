#!/usr/bin/env python3
"""Measure core-only Fmax from saved routes, retaining the separate I/O timing evidence."""
import concurrent.futures
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
from v42_external_flow import ROOT, BASE, BUILD, NAMES, sha, write, tool_version
from v42_external_route import audit_timing, audit_rom, resources

folder = BUILD / sys.argv[1]
inputs = json.loads((folder / 'inputs.json').read_text())
sim = json.loads((folder / 'simulation.json').read_text())
out = folder / 'route'
for name in ('finalize_core.tcl', 'rom_mapping.tcl'):
    src = ROOT / 'experiments/v4.2/external_job_message' / name
    dst = out / name
    if dst.exists():
        assert sha(src) == sha(dst)
    else:
        shutil.copy2(src, dst)
version = tool_version('vivado', '-version')
SCOPE = 'out_of_context internal register-to-register timing; external input/output paths excluded; I/O not signed off'


def one(name):
    case = out / name
    deadline = time.monotonic() + 7200
    source = case / 'post_route.dcp'
    while not (source.exists() and re.search(r'^INFO: \[Common 17-206\] Exiting Vivado', (case / 'route.log').read_text(errors='replace'), re.M)):
        if time.monotonic() > deadline:
            raise RuntimeError('Waiting for original route timed out: ' + name)
        time.sleep(15)
    target = case / 'core_timing'
    target.mkdir(exist_ok=True)
    command = ['vivado', '-mode', 'batch', '-nolog', '-nojournal', '-source', str(out / 'finalize_core.tcl'), '-tclargs', str(source), str(target)]
    invocation = dict(command=command, source_checkpoint_sha256=sha(source), script_sha256=sha(out / 'finalize_core.tcl'),
                      timing_scope=SCOPE, io_timing_qualified=False, tool_versions={'vivado': version}, started=time.time())
    if not (target / 'finalize.log').exists() or not re.search(r'^EXTERNAL_ROUTE_PASS ', (target / 'finalize.log').read_text(), re.M):
        write(target / 'invocation.json', invocation)
        with (target / 'finalize.log').open('w') as log:
            subprocess.run(command, cwd=target, stdout=log, stderr=subprocess.STDOUT, check=True)
    else:
        old = json.loads((target / 'invocation.json').read_text())
        for key in ('source_checkpoint_sha256', 'script_sha256', 'timing_scope'):
            assert old[key] == invocation[key]
    clock = json.loads((target / 'final_clock.json').read_text())
    assert clock['wns_ns'] >= .0999 and clock['whs_ns'] >= 0 and not clock['io_timing_qualified']
    audit_timing(target)
    profile, operation = name.rsplit('_', 1)
    rom = audit_rom(target / 'initialized_rom.tsv', folder / 'synth_source' / BASE.relative_to(ROOT) / 'images' / profile)
    for filename in ('utilization.rpt', 'hierarchical.rpt', 'timing_summary.rpt', 'route_status.rpt', 'drc.rpt',
                     'check_timing.rpt', 'constraints.xdc', 'post_route_final_clock.dcp', 'initialized_rom.tsv', 'final_clock.json'):
        shutil.copy2(target / filename, case / filename)
    cycles = sim['cases'][name][operation + '_cycles']
    row = dict(passed=True, core_timing_pass=True, timing_scope=SCOPE, **resources(target / 'utilization.rpt'), **clock,
               frequency_mhz=1000/clock['period_ns'], operation_cycles=cycles, rom_audit=rom)
    row['latency_ms'] = cycles * clock['period_ns'] / 1e6
    row['area_time_product'] = row['equivalent_slice'] * row['latency_ms']
    row['evidence_sha256'] = {str(p.relative_to(case)): sha(p) for p in case.rglob('*') if p.is_file() and p.name != 'result.json'}
    write(case / 'result.json', row)
    print('EXTERNAL_CORE_TIMING_PASS', name, row['equivalent_slice'], row['frequency_mhz'], 'io_hold=', row['io_zero_delay_whs_ns'], flush=True)
    return name, row


names = [n + '_' + op for n in NAMES for op in ('keygen', 'sign')]
with concurrent.futures.ThreadPoolExecutor(3) as pool:
    results = dict(pool.map(one, names))
write(out / 'result.json', dict(passed=True, core_timing_pass=True, io_timing_qualified=False, stage='post_route', tag=folder.name,
      timing_scope=SCOPE, rtl_sha256=inputs['rtl_sha256'], source_snapshot_sha256=inputs['snapshot_sha256'],
      common_frequency_mhz=min(r['frequency_mhz'] for r in results.values()), tops=results))
print('EXTERNAL_CORE_ALL_PASS', folder.name, flush=True)
