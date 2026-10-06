#!/usr/bin/env python3
"""Resynthesize the current K2 common core for U={1,2,3,4}.

The source snapshot and Vivado reports live outside build so a later build
cleanup does not erase the evidence.  Runs are deliberately sequential by U.
"""
from legacy_lane_guard import require_legacy_lanes
require_legacy_lanes()
import hashlib
import json
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from v42_common_partition import partition

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'manifests/experiments/ku_current_k2_area_20261006_v1'
POINTS = [(2, u) for u in (1, 2, 3, 4)]
PART = 'xc7a200tffg1156-3'


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def atomic_json(path, payload):
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + '\n')
    tmp.replace(path)


def parse_resources(path):
    content = path.read_text()
    found = {}
    for label, key in [('Slice LUTs', 'lut'), ('Slice Registers', 'ff'),
                       ('LUT as Memory', 'lutram'), ('Block RAM Tile', 'bram36'),
                       ('DSPs', 'dsp')]:
        match = re.search(r'\|\s*' + re.escape(label) + r'\*?\s*\|\s*([\d,.]+)', content)
        if not match:
            raise ValueError(f'{path}: missing {label}')
        found[key] = float(match[1].replace(',', ''))
    found['equivalent_slice'] = (found['lut']/4 + found['ff']/8 +
                                 found['bram36']*232.4 + found['dsp']*102.4)
    return found


def prepare():
    OUT.mkdir(parents=True, exist_ok=True)
    snapshot = OUT / 'snapshot'
    sources = (ROOT / 'manifests/v42_sources.txt').read_text().splitlines()
    sources += ['scripts/v42_common_partition.py', 'manifests/v42_sources.txt']
    if not snapshot.exists():
        snapshot.mkdir()
        for name in sources:
            target = snapshot / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / name, target)
        # Production RTL deliberately rejects all points except K2U2.  This
        # isolated elaboration-only patch permits the four K2 U variants; it
        # changes no hardware branch or synthesis behavior at K2U2.
        hbs = snapshot / 'rtl/top/mhbs_hbs.sv'
        original = hbs.read_text()
        guard = 'initial if(LANES!=2 || UNROLL!=2) $error("Production core requires K2U2");'
        assert original.count(guard) == 1
        hbs.write_text(original.replace(guard,
            'initial if(LANES!=2 || UNROLL<1 || UNROLL>4 || (24 % UNROLL)!=0) '
            '$error("Isolated K2 U1-U4 area sweep");'))
        sys.path.insert(0, str(snapshot / 'scripts'))
        from v42_common_partition import partition as frozen_partition
        common, _ = frozen_partition((snapshot / 'rtl/top/mhbs_top.sv').read_text(), stub=True)
        (snapshot / 'mhbs_common.sv').write_text(common)
    manifest = {name: digest(snapshot / name) for name in sources}
    manifest['mhbs_common.sv'] = digest(snapshot / 'mhbs_common.sv')
    config = OUT / 'config.json'
    if config.exists():
        old = json.loads(config.read_text())
        if old['snapshot_sha256'] != manifest:
            raise RuntimeError('Frozen source snapshot changed')
    else:
        atomic_json(config, dict(schema='mhbs.ku_current_area.v1',
                                 created_at=datetime.now(timezone.utc).isoformat(),
                                 git_head=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
                                 device=PART, clock_period_ns=10, profile_enable=0,
                                 threads=8, source_files=sources,
                                 scope='K2 U1-U4 only; production K1/K4 controller is not parameterized',
                                 snapshot_patch='Isolated elaboration guard accepts K2 U1-U4',
                                 snapshot_sha256=manifest,
                                 vivado=subprocess.check_output(['vivado', '-version'], text=True).splitlines()[0],
                                 run_order=[f'K{k}U{u}' for k, u in POINTS]))
    return snapshot


def write_tcl(snapshot, point_dir, k, u):
    sources = (snapshot / 'manifests/v42_sources.txt').read_text().splitlines()
    lines = ['set_param general.maxThreads 8', f'create_project -in_memory -part {PART}']
    for source in sources:
        if source != 'rtl/top/mhbs_top.sv':
            lines.append(f'read_verilog -sv {{{snapshot / source}}}')
    (point_dir / 'clock.xdc').write_text('create_clock -name clk -period 10.0 [get_ports clk]\n')
    lines += [f'read_verilog -sv {{{snapshot / "mhbs_common.sv"}}}',
              f'read_xdc {{{point_dir / "clock.xdc"}}}',
              f'synth_design -top mhbs_common -part {PART} -mode out_of_context '
              f'-flatten_hierarchy rebuilt -max_dsp 0 -generic LANES={k} '
              f'-generic UNROLL={u} -generic PROFILE_ENABLE=0',
              f'report_utilization -file {{{point_dir / "core_utilization.rpt"}}}',
              f'report_utilization -hierarchical -file {{{point_dir / "core_hierarchical.rpt"}}}',
              f'report_timing_summary -file {{{point_dir / "core_timing.rpt"}}}',
              'puts "KU_CURRENT_CORE_SYNTH_PASS"', 'close_project', 'exit']
    path = point_dir / 'synth.tcl'
    path.write_text('\n'.join(lines) + '\n')
    return path


def main():
    snapshot = prepare()
    status_file = OUT / 'status.json'
    state = json.loads(status_file.read_text()) if status_file.exists() else {'points': {}}
    for k, u in POINTS:
        label = f'K{k}U{u}'
        point_dir = OUT / label
        point_dir.mkdir(exist_ok=True)
        result_file = point_dir / 'result.json'
        if result_file.exists():
            result = json.loads(result_file.read_text())
            if (result['source_sha256'] == json.loads((OUT / 'config.json').read_text())['snapshot_sha256']
                    and digest(point_dir / 'core_utilization.rpt') == result['evidence_sha256']['core_utilization.rpt']):
                state['points'][label] = 'complete'
                continue
        tcl = write_tcl(snapshot, point_dir, k, u)
        state.update(current=label, status='running')
        state['points'][label] = 'running'
        atomic_json(status_file, state)
        with (point_dir / 'vivado.log').open('w') as log:
            run = subprocess.run(['vivado', '-mode', 'batch', '-nolog', '-nojournal',
                                  '-source', str(tcl)], cwd=point_dir, stdout=log, stderr=subprocess.STDOUT)
        if run.returncode or 'KU_CURRENT_CORE_SYNTH_PASS' not in (point_dir / 'vivado.log').read_text():
            state.update(current=label, status='failed')
            state['points'][label] = 'failed'
            atomic_json(status_file, state)
            raise RuntimeError(f'{label} Vivado failed; see {point_dir / "vivado.log"}')
        report_names = ['core_utilization.rpt', 'core_hierarchical.rpt', 'core_timing.rpt', 'clock.xdc', 'synth.tcl', 'vivado.log']
        atomic_json(result_file, dict(point=label, k=k, u=u,
                                      source_sha256=json.loads((OUT / 'config.json').read_text())['snapshot_sha256'],
                                      area=parse_resources(point_dir / 'core_utilization.rpt'),
                                      evidence_sha256={name: digest(point_dir / name) for name in report_names}))
        state['points'][label] = 'complete'
        atomic_json(status_file, state)
        print(label, json.loads(result_file.read_text())['area'], flush=True)
    results = {f'K{k}U{u}': json.loads((OUT / f'K{k}U{u}' / 'result.json').read_text()) for k, u in POINTS}
    atomic_json(OUT / 'results.json', dict(schema='mhbs.ku_current_area.v1',
                                          config_sha256=digest(OUT / 'config.json'),
                                          points=results))
    state.update(current=None, status='complete')
    atomic_json(status_file, state)


if __name__ == '__main__':
    main()
