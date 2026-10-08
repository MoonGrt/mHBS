#!/usr/bin/env python3
"""Detached, resumable XMSS/LMS omega4 Keygen P/U cycle and synthesis matrix."""
import argparse
import concurrent.futures
import csv
import fcntl
import hashlib
import json
import os
import re
import signal
import subprocess
import tarfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from v42_common_partition import partition

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT / 'manifests/experiments/stateful_keygen_pu13_20261012_v1'
POINTS = [(p, 1) for p in (1, 2, 3, 4, 6, 8, 12)] + [(p, 2) for p in (1, 2, 3, 4, 6, 12)]
PROFILES = ('xmss_omega4', 'lms_omega4')
PART = 'xc7a200tffg1156-3'
WORKERS = 6
VIVADO_THREADS = 4
LOCK = threading.Lock()


def now():
    return datetime.now(timezone.utc).isoformat()


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f'.{os.getpid()}.{threading.get_ident()}.tmp')
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + '\n')
    temporary.replace(path)


def source_names(root):
    names = set((root / 'manifests/v42_sources.txt').read_text().split())
    names.update(('manifests/v42_sources.txt', 'scripts/v42_common_partition.py',
                  'scripts/run_stateful_keygen_pu13.py', 'tb/integration/tb_mhbs_stateful.sv'))
    for profile in PROFILES:
        folder = root / 'manifests/experiments/stateful_20261008/vectors' / profile / 'q0_m1' / '0'
        assert folder.is_dir(), folder
        names.update(str(p.relative_to(root)) for p in folder.iterdir() if p.is_file())
    return sorted(names)


def prepare(out):
    if (out / 'config.json').exists():
        config = json.loads((out / 'config.json').read_text())
        assert config['points'] == [[p, u] for p, u in POINTS]
        assert config['profiles'] == list(PROFILES) and config['operations'] == ['Keygen']
        assert config['max_parallel_vivado'] == WORKERS and config['vivado_threads'] == VIVADO_THREADS
        assert sha(out / 'source_snapshot.tar.gz') == config['snapshot_sha256']
        return config
    out.mkdir(parents=True, exist_ok=True)
    (out / '.gitignore').write_text('/source/\n/work/\n/run.lock\n')
    names = source_names(ROOT)
    hashes = {name: sha(ROOT / name) for name in names}
    archive = out / 'source_snapshot.tar.gz'
    with tarfile.open(archive, 'w:gz') as tar:
        for name in names:
            tar.add(ROOT / name, arcname=name)
    config = dict(schema='mhbs.stateful_keygen_pu13.v1', created_at=now(),
                  scope='XMSS/LMS omega4 Keygen; common core OOC synthesis and RTL cycles',
                  points=POINTS, profiles=PROFILES, operations=['Keygen'],
                  device=PART, clock_period_ns=6.666667, routed=False,
                  profile_enable_synthesis=0, max_parallel_vivado=WORKERS,
                  vivado_threads=VIVADO_THREADS, compile_threads=2,
                  source_sha256=hashes, snapshot_sha256=sha(archive),
                  git_head=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
                  vivado=subprocess.check_output(['vivado', '-version'], text=True).splitlines()[0],
                  verilator=subprocess.check_output(['verilator', '--version'], text=True).splitlines()[0])
    write(out / 'config.json', config)
    write(out / 'status.json', dict(state='prepared', pid=None, started_at=None,
                                    updated_at=now(), total_points=len(POINTS),
                                    total_cases=len(POINTS) * len(PROFILES),
                                    completed_points=0, completed_cases=0,
                                    points={f'P{p}U{u}': 'pending' for p, u in POINTS},
                                    config_sha256=sha(out / 'config.json')))
    return config


def status_update(out, point=None, state=None, **fields):
    with LOCK:
        path = out / 'status.json'
        data = json.loads(path.read_text())
        if point is not None:
            data['points'][point] = state
        elif state is not None:
            data['state'] = state
        data.update(fields)
        data['completed_points'] = sum(x == 'complete' for x in data['points'].values())
        data['failed_points'] = sum(x == 'failed' for x in data['points'].values())
        data['active_vivado'] = sum(x == 'synthesizing' for x in data['points'].values())
        data['completed_cases'] = sum((out / point / profile / 'simulation.json').exists()
                                      for point in data['points'] for profile in PROFILES)
        data['updated_at'] = now()
        write(path, data)


def run_tool(command, log, cwd, timeout=172800):
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open('w') as output:
        process = subprocess.Popen(list(map(str, command)), cwd=cwd, stdout=output,
                                   stderr=subprocess.STDOUT, start_new_session=True)
        try:
            code = process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
            raise RuntimeError(f'timeout after {timeout} seconds: {log}')
    if code:
        raise RuntimeError(f'exit {code}: {log}; {log.read_text(errors="replace")[-800:]}')


def area(path):
    text = path.read_text()
    values = {}
    for label, key in (('Slice LUTs', 'lut'), ('Slice Registers', 'ff'),
                       ('LUT as Memory', 'lutram'), ('Block RAM Tile', 'bram36'), ('DSPs', 'dsp')):
        hit = re.search(r'\|\s*' + re.escape(label) + r'\*?\s*\|\s*([\d,.]+)', text)
        if not hit:
            raise ValueError(f'missing {label} in {path}')
        values[key] = float(hit[1].replace(',', ''))
    values['equivalent_slice'] = (values['lut'] / 4 + values['ff'] / 8 +
                                  232.4 * values['bram36'] + 102.4 * values['dsp'])
    return values


def synth(out, source, point, p, u):
    folder = out / point
    result = folder / 'synthesis.json'
    if result.exists():
        return json.loads(result.read_text())['area']
    common, _ = partition((source / 'rtl/top/mhbs_top.sv').read_text(), stub=True)
    (folder / 'mhbs_common.sv').write_text(common)
    (folder / 'clock.xdc').write_text('create_clock -name clk -period 6.666667 [get_ports clk]\n')
    names = (source / 'manifests/v42_sources.txt').read_text().split()
    script = [f'set_param general.maxThreads {VIVADO_THREADS}',
              f'create_project -in_memory -part {PART}']
    script += [f'read_verilog -sv {{{source / name}}}' for name in names
               if name != 'rtl/top/mhbs_top.sv']
    script += [f'read_verilog -sv {{{folder / "mhbs_common.sv"}}}',
               f'read_xdc {{{folder / "clock.xdc"}}}',
               f'synth_design -top mhbs_common -part {PART} -mode out_of_context '
               f'-flatten_hierarchy rebuilt -max_dsp 0 -generic PIPELINE={p} '
               f'-generic UNROLL={u} -generic PROFILE_ENABLE=0',
               f'report_utilization -file {{{folder / "core_utilization.rpt"}}}',
               f'report_utilization -hierarchical -file {{{folder / "core_hierarchical.rpt"}}}',
               f'report_timing_summary -file {{{folder / "core_timing.rpt"}}}',
               'set bad {}',
               'foreach c [get_cells -hier -filter {IS_PRIMITIVE == 1}] {'
               'if {[string match FD* [get_property REF_NAME $c]] && '
               '[regexp {(cycles|hash_count|permutation_count|hash_base|permutation_base)_reg} $c]} '
               '{lappend bad $c}}',
               'if {[llength $bad]} {error "Statistics registers remain: $bad"}',
               f'puts "STATEFUL_PU_SYNTH_PASS {point}"', 'exit']
    (folder / 'synth.tcl').write_text('\n'.join(script) + '\n')
    work = out / 'work' / point
    work.mkdir(parents=True, exist_ok=True)
    start = time.monotonic()
    run_tool(['vivado', '-mode', 'batch', '-nolog', '-nojournal', '-source', folder / 'synth.tcl'],
             folder / 'vivado.log', work, timeout=14400)
    assert f'STATEFUL_PU_SYNTH_PASS {point}' in (folder / 'vivado.log').read_text()
    measured = area(folder / 'core_utilization.rpt')
    files = ('mhbs_common.sv', 'clock.xdc', 'synth.tcl', 'vivado.log',
             'core_utilization.rpt', 'core_hierarchical.rpt', 'core_timing.rpt')
    write(result, dict(area=measured, elapsed_seconds=time.monotonic() - start,
                       evidence_sha256={name: sha(folder / name) for name in files}))
    return measured


def simulate(out, source, point, p, u, profile):
    folder = out / point / profile
    folder.mkdir(parents=True, exist_ok=True)
    result = folder / 'simulation.json'
    if result.exists():
        return json.loads(result.read_text())
    binary_dir = out / 'work' / point / 'obj'
    binary = binary_dir / 'Vtb_mhbs_stateful'
    if not binary.exists():
        names = (source / 'manifests/v42_sources.txt').read_text().split()
        files = [source / name for name in names if name != 'rtl/top/mhbs_top.sv']
        files += [out / point / 'mhbs_common.sv', source / 'tb/integration/tb_mhbs_stateful.sv']
        run_tool(['verilator', '--binary', '--timing', '-O3', '-j', '2', '-Wno-fatal',
                  '-Wno-WIDTH', '-Wno-UNOPTFLAT', '--top-module', 'tb_mhbs_stateful',
                  f'-GPIPELINE={p}', f'-GUNROLL={u}', '-GPROFILE_ENABLE=1',
                  '--Mdir', binary_dir, *files], out / point / 'compile.log', source,
                 timeout=14400)
    vector = (source / 'manifests/experiments/stateful_20261008/vectors' /
              profile / 'q0_m1' / '0')
    start = time.monotonic()
    run_tool([binary, f'+VECTOR={vector}'], folder / 'run.log', source)
    text = (folder / 'run.log').read_text()
    match = re.search(r'STATEFUL_PASS P(\d+)U(\d+) op=(\d+) cycles=(\d+) '
                      r'total=(\d+) hashes=(\d+) permutations=(\d+)', text)
    if not match or (int(match[1]), int(match[2]), int(match[3])) != (p, u, 0):
        raise RuntimeError(f'missing or wrong Keygen pass marker: {folder / "run.log"}')
    expected = [int(line, 16) for line in (vector / 'meta.mem').read_text().splitlines()]
    if (int(match[6]), int(match[7])) != (expected[1], expected[2]):
        raise RuntimeError(f'wrong Hash/permutation count: {folder / "run.log"}')
    data = dict(profile=profile, operation='Keygen', point=point,
                compute_cycles=int(match[4]), total_cycles=int(match[5]),
                hashes=int(match[6]), permutations=int(match[7]),
                output_bytes=expected[0], elapsed_seconds=time.monotonic() - start,
                vector_sha256={name: sha(vector / name) for name in
                               ('program.mem', 'template.mem', 'descriptor.mem', 'job.mem',
                                'meta.mem', 'message.mem', 'expected.mem', 'nodes.mem')},
                run_log_sha256=sha(folder / 'run.log'))
    write(result, data)
    return data


def point_job(out, source, p, u):
    point = f'P{p}U{u}'
    folder = out / point
    folder.mkdir(parents=True, exist_ok=True)
    if (folder / 'result.json').exists():
        status_update(out, point, 'complete')
        return
    try:
        status_update(out, point, 'synthesizing')
        measured = synth(out, source, point, p, u)
        if measured['lut'] > 134600 or measured['ff'] > 269200 or measured['bram36'] > 365:
            raise RuntimeError('device resource capacity exceeded')
        rows = {}
        for profile in PROFILES:
            status_update(out, point, 'simulating_' + profile)
            rows[profile] = simulate(out, source, point, p, u, profile)
        write(folder / 'result.json', dict(point=point, p=p, u=u, area=measured,
                                           keygen=rows))
        status_update(out, point, 'complete')
        print('POINT_PASS', point, flush=True)
    except Exception as error:
        write(folder / 'failure.json', dict(error=repr(error), at=now()))
        status_update(out, point, 'failed')
        print('POINT_FAIL', point, repr(error), flush=True)


def finish(out):
    rows = []
    for p, u in POINTS:
        name = f'P{p}U{u}'
        folder = out / name
        measured = json.loads((folder / 'synthesis.json').read_text())['area'] if (folder / 'synthesis.json').exists() else {}
        for profile in PROFILES:
            sim = folder / profile / 'simulation.json'
            row = dict(point=name, p=p, u=u, profile=profile, operation='Keygen',
                       **measured)
            if sim.exists():
                row.update(json.loads(sim.read_text()))
                row['status'] = 'pass'
            else:
                row['status'] = 'failed' if (folder / 'failure.json').exists() else 'incomplete'
                if (folder / 'failure.json').exists():
                    row['error'] = json.loads((folder / 'failure.json').read_text())['error']
            rows.append(row)
    write(out / 'results.json', dict(scope='XMSS/LMS omega4 Keygen', rows=rows,
                                     actual_frequency='not measured; synthesis only'))
    columns = ('point', 'profile', 'operation', 'status', 'compute_cycles', 'total_cycles',
               'hashes', 'permutations', 'output_bytes', 'lut', 'ff', 'lutram', 'bram36',
               'dsp', 'equivalent_slice', 'error')
    with (out / 'results.csv').open('w') as file:
        writer = csv.DictWriter(file, fieldnames=columns, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(rows)
    lines = ['# XMSS/LMS w=4 Keygen：13 个 P/U 配置', '',
             '器件 xc7a200tffg1156-3，Vivado 2025.2，6.666667 ns 共同核 OOC 综合约束，统计关闭。',
             '每轮最多 6 个 Vivado，各 4 线程。仅综合，频率未经布局布线测定；共同核面积不含外部 ROM/签名缓存。', '',
             '| P/U | 参数集 | 计算周期 | 总周期 | Hash | 置换 | LUT | FF | LUTRAM | BRAM36 | DSP | 等效 Slice | 状态 |',
             '|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|']
    for row in rows:
        show = lambda key: str(row.get(key, '-'))
        lines.append('| ' + ' | '.join(show(key) for key in
                     ('point', 'profile', 'compute_cycles', 'total_cycles', 'hashes',
                      'permutations', 'lut', 'ff', 'lutram', 'bram36', 'dsp',
                      'equivalent_slice', 'status')) + ' |')
    (out / 'report.md').write_text('\n'.join(lines) + '\n')
    complete = all(row['status'] == 'pass' for row in rows)
    status_update(out, state='complete' if complete else 'complete_with_failures',
                  ended_at=now())
    (out / 'DONE').write_text('complete\n' if complete else 'complete_with_failures\n')
    write(out / 'evidence_sha256.json',
          {str(path.relative_to(out)): sha(path) for path in out.rglob('*')
           if path.is_file() and not {'source', 'work'}.intersection(path.relative_to(out).parts)
           and path.name not in ('status.json', 'service.log', 'evidence_sha256.json', 'run.lock')})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('prepare', 'run'))
    parser.add_argument('--directory', type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    out = args.directory.resolve()
    if args.action == 'prepare':
        prepare(out)
        print('PREPARED', out / 'status.json')
        return
    source = out / 'source'
    assert Path(__file__).resolve() == source / 'scripts/run_stateful_keygen_pu13.py', 'run frozen copy'
    with (out / 'run.lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            config = prepare(out)
            assert sha(out / 'config.json') == json.loads((out / 'status.json').read_text())['config_sha256']
            if not source.exists():
                with tarfile.open(out / 'source_snapshot.tar.gz') as tar:
                    tar.extractall(source, filter='data')
            for name, digest in config['source_sha256'].items():
                assert sha(source / name) == digest, name
            status_update(out, state='running', pid=os.getpid(), started_at=now())
            with concurrent.futures.ThreadPoolExecutor(max_workers=WORKERS) as pool:
                list(pool.map(lambda pair: point_job(out, source, *pair), POINTS))
            finish(out)
        except Exception as error:
            write(out / 'service_failure.json', dict(error=repr(error), at=now()))
            status_update(out, state='failed', error=repr(error))
            raise


if __name__ == '__main__':
    main()
