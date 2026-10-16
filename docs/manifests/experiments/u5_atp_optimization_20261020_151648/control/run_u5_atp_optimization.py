#!/usr/bin/env python3
"""Freeze a U5-based SHAKE candidate; measure six Sign and two common syntheses.

Launch returns after initial publication. Synthesis uses 100 MHz for diagnosis;
this controller cannot launch routing, infer a physical frequency, or stop jobs.
"""
import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import time
from zoneinfo import ZoneInfo

import run_c2_timing_optimization as core

ROOT = core.ROOT
SCHEMA = 'u5_shake_atp_optimization_v1'
BASELINE_RUN = ROOT / 'build/t2_atp_optimization/candidate_20261020_140547'
BASELINE_SHA = '40f3a70f7a61255747d3acc4ff0b8d836290e2fd04245a2eb58c7caa3cc06df5'
CONFIGS, PROFILES = core.CONFIGS, core.PROFILES
CONTROLS = ('run_u5_atp_optimization.py', 'report_u5_atp_optimization.py',
    'report_t2_atp_optimization.py', 'run_t2_atp_optimization.py',
    'validate_t2_atp_candidate.py', 'audit_t2_atp_archive.py', *core.CONTROLS)
read, write, require, sha, now = core.read, core.write, core.require, core.sha, core.now


def checked_baseline():
    require(sha(BASELINE_RUN / 'SOURCE.json') == BASELINE_SHA, 'Only frozen U5 is accepted')
    evidence = core.checked_evidence(BASELINE_RUN)
    require(not evidence['results']['routing'], 'U5 baseline must not borrow routed evidence')
    proof_path = BASELINE_RUN / 'functional_validation/VALIDATION.json'
    proof = read(proof_path)
    require(proof.get('complete') is True and proof.get('passed') == 76
        and proof.get('failed') == 0 and proof.get('source_unchanged') is True
        and proof.get('source_manifest_sha256') == BASELINE_SHA
        and proof.get('rtl_sha256') == {k: v for k, v in evidence['source']['sha256'].items()
                                       if k.startswith('rtl/')}, 'U5 validation is incomplete or unbound')
    for test in proof['tests']:
        require(test.get('passed') is True and sha(Path(test['log'])) == test['log_sha256'],
                f'Changed U5 validation evidence: {test["name"]}')
    archived = Path(evidence['source']['archive_directory']) / 'validation_summary/VALIDATION.json'
    require(sha(archived) == sha(proof_path), 'U5 archived validation differs')
    require(all(item.get('output_and_signature_cache_checked_bytewise') is True
        for item in evidence['results']['tests'].values()), 'U5 bytewise checks missing')
    evidence.update(label='U5', comparison_parent_baselines_ignored=True,
        supplemental_validation_sha256=sha(proof_path), supplemental_validation_passed=76,
        measured_physical_frequency_mhz=None, routed_atp_slice_ms=None,
        physical_frequency_status='unknown; U5 has no routed evidence')
    return evidence


class Runner(core.Runner):
    """Reuse the measured-job engine without adding a routing entry point."""
    def __init__(self, run):
        self.run = Path(run).resolve()
        self.meta = read(self.run / 'SOURCE.json')
        require(self.meta.get('schema') == SCHEMA and self.meta.get('hash_backend') == 'shake',
                'Not a U5 ATP experiment')
        self.source, self.out = Path(self.meta['source_root']), Path(self.meta['archive_directory'])
        self.baseline = read(self.run / 'U5_BASELINE_EVIDENCE.json')
        require(self.baseline['manifest_sha256'] == BASELINE_SHA
            and sha(self.run / 'U5_BASELINE_EVIDENCE.json') == self.meta['baseline_evidence_sha256'],
            'Frozen U5 baseline evidence changed')
        require(self.meta.get('route_requested') is False and not self.meta.get('route_frequencies_mhz'),
                'This experiment is synthesis-only')
        self.lock, self.capacity_lock, self.reserved = threading.RLock(), threading.Lock(), 0
        self.routes_only, self.targets = False, []
        self.state = dict(schema=SCHEMA, label=self.meta['label'], hash_backend='shake',
            baseline_label='U5', baseline_manifest_sha256=BASELINE_SHA, pid=os.getpid(),
            started_at=now(), complete=False, source_unchanged=None,
            tests={f'P{p}U1/{profile}': dict(status='pending') for p in CONFIGS for profile in PROFILES},
            synthesis={f'P{p}U1': dict(status='pending') for p in CONFIGS}, routing={},
            measured_candidate_frequency_mhz=None, measured_candidate_routed_atp=None)

    def comparisons(self):
        rows = super().comparisons()
        for row in rows:
            row.update(baseline_label='U5', baseline_cycles=row.pop('c2_cycles'))
            if 'c2_equivalent_slice' in row:
                row['baseline_equivalent_slice'] = row.pop('c2_equivalent_slice')
        return rows

    def publish(self):
        self.state.update(updated_at=now(), comparisons=self.comparisons(), validation_passed=self.validated())
        self.state['counts'] = {s: sum(t['status'] == s for t in self.state['tests'].values())
                                for s in ('pending', 'running', 'passed', 'failed')}
        write(self.run / 'status.json', self.state)
        write(self.out / 'VALIDATION_SUMMARY.json', self.state)
        prefix = self.out / 'reports' / ('U5_ATP_Optimization_' + self.meta['run_id'])
        write(prefix.with_suffix('.json'), dict(source=self.meta, results=self.state))
        fmt = lambda value: '—' if value is None else f'{value:,.3f}'
        row = lambda values: '| ' + ' | '.join(map(str, values)) + ' |'
        lines = ['# U5 基础 SHAKE 面积与延迟优化', '',
            f'候选：{self.meta["label"]}；更新时间：{self.state["updated_at"]}；'
            f'状态：{"完成" if self.state["complete"] else "后台运行"}。', '',
            '唯一比较基线是冻结 U5（20261020_140547），核对六项完整 Sign、两项100 MHz综合和'
            '76组源绑定补充验证。U5及本轮候选均无布线证据，实际频率和布线ATP未知。', '',
            '面积取对应P/U的common OOC，xc7a200tffg1156-3、通用Keccak、默认时序驱动。'
            '以下ATP仅假设100 MHz；综合路径仅用于诊断。每个Vivado两线程，最多十二个；'
            '异常综合仅延后分析，进程继续。未执行h20完整Keygen/Sign。', '',
            '| 配置 | LUT | FF | BRAM36 | 等效 Slice | 对U5面积% | 诊断路径ns | 级数 | 状态 |',
            '|---|---:|---:|---:|---:|---:|---:|---:|---|']
        for config, item in self.state['synthesis'].items():
            area, path = item.get('area', {}), item.get('timing', {})
            old = self.baseline['results']['synthesis'][config]['area']['equivalent_slice']
            delta = 100 * (area['equivalent_slice'] / old - 1) if area else None
            status = item['status'] + ('／分析延后，后台继续' if item.get('analysis_deferred') else '')
            lines.append(row([config, *[fmt(area.get(k)) for k in ('lut', 'ff', 'bram36', 'equivalent_slice')],
                fmt(delta), fmt(path.get('data_path_ns')), fmt(path.get('logic_levels')), status]))
        for profile in PROFILES:
            lines += ['', f'## {profile} 完整 Sign', '',
                '| 配置 | 周期 | U5周期 | 周期变化% | 假设100MHz时间ms | 假设ATP Slice·ms | ATP变化% | 工作量相同 | 状态 |',
                '|---|---:|---:|---:|---:|---:|---:|---|---|']
            for item in self.state['comparisons']:
                if item['profile'] == profile:
                    keys = ('cycles', 'baseline_cycles', 'cycles_change_pct', 'diagnostic_time_ms_at_100mhz',
                            'diagnostic_atp_slice_ms_at_100mhz', 'diagnostic_atp_change_pct')
                    equal = '—' if 'workload_equal' not in item else ('是' if item['workload_equal'] else '否')
                    lines.append(row([item['configuration'], *[fmt(item.get(k)) for k in keys], equal, item['status']]))
        lines += ['', f'运行目录：`{self.run}`。详细仿真日志仅保留运行目录；归档包含冻结RTL、SHA、'
            '源绑定摘要、综合分层／时序报告及日志。', '']
        core.archive.atomic(prefix.with_suffix('.md'), '\n'.join(lines))
        missing = {}
        for config in self.state['synthesis']:
            folder = self.run / 'synth' / config
            for path in folder.rglob('*') if folder.exists() else []:
                if path.is_file() and path.suffix in ('.rpt', '.log', '.txt', '.xdc', '.json'):
                    core.archive.copy_changed(path, self.out / 'synth' / config / path.relative_to(folder))
            missing[f'synth/{config}'] = [name for name in ('hierarchical.rpt', 'timing.rpt')
                if not (self.out / 'synth' / config / name).is_file()]
        write(self.out / 'ARTIFACTS.json', dict(complete=self.state['complete'], missing=missing,
            omitted_details=['sim', 'validation'], sha256={str(p.relative_to(self.out)): sha(p)
                for p in self.out.rglob('*') if p.is_file() and p.name != 'ARTIFACTS.json'
                and not p.name.endswith('.tmp')}))


def launch(args):
    baseline = checked_baseline()
    require(all((ROOT / 'scripts' / name).is_file() for name in CONTROLS),
            'All measurement/report/validation controls must exist before freezing')
    source = (args.source_root or ROOT).resolve()
    tools = {name: shutil.which(os.environ.get(name.upper(), name)) for name in ('vivado', 'verilator')}
    require(all(tools.values()), 'Vivado and Verilator are required')
    versions = {name: subprocess.check_output([path, '-version' if name == 'vivado' else '--version'],
        text=True, timeout=30).strip() for name, path in tools.items()}
    require(versions == baseline['source']['tool_versions'], 'Tool versions differ from U5')
    for profile in PROFILES:
        require(core.previous.vectors(source, profile) == core.previous.vectors(
            Path(baseline['source']['source_root']), profile), f'Vectors differ from U5: {profile}')
    require(sha(source / 'scripts/diagnose_timing.tcl') == baseline['source']['sha256']['scripts/diagnose_timing.tcl'],
            'Diagnostic tool settings differ from U5')
    stamp = datetime.now(ZoneInfo('Asia/Singapore')).strftime('%Y%m%d_%H%M%S')
    run, out = ROOT / 'build/u5_atp_optimization' / f'candidate_{stamp}', core.archive.ARCHIVES / f'u5_atp_optimization_{stamp}'
    require(not run.exists() and not out.exists(), 'Run exists; retry next second')
    spec = core.snapshot(source, run / 'source')
    for base in (run, out):
        write(base / 'U5_BASELINE_EVIDENCE.json', baseline)
    meta = dict(spec, schema=SCHEMA, run_id=stamp, label=args.label, phase='candidate', hash_backend='shake',
        **tools, tool_versions=versions, started_at=now(), archive_directory=str(out), configurations=CONFIGS,
        profiles=PROFILES, top='common', part='xc7a200tffg1156-3', synthesis_period_ns=10.0,
        threads_per_vivado=2, max_total_vivado=12, route_requested=False, route_frequencies_mhz=[],
        frequency_search=False, new_timing_exceptions=False, h20_full_keygen_sign_run=False,
        baseline_label='U5', baseline_run=str(BASELINE_RUN), baseline_manifest_sha256=BASELINE_SHA,
        baseline_evidence_sha256=sha(run / 'U5_BASELINE_EVIDENCE.json'), reuse_evidence=False,
        measured_physical_frequency_mhz=None, physical_frequency_status='unknown; no routing requested')
    for base in (run, out):
        write(base / 'SOURCE.json', meta)
        for name in CONTROLS:
            core.archive.copy_changed(ROOT / 'scripts' / name, base / 'control' / name)
        write(base / 'CONTROL_SOURCE.json', {name: sha(base / 'control' / name) for name in CONTROLS})
    core.previous.archive_source(meta, out)
    patch = subprocess.run(['diff', '-ru', str(Path(baseline['source']['source_root']) / 'rtl'),
        str(run / 'source/rtl')], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    require(patch.returncode in (0, 1), patch.stderr)
    core.archive.atomic(out / 'lineage/from_U5.patch', patch.stdout)
    write(out / 'lineage/LINEAGE.json', dict(candidate_manifest_sha256=sha(run / 'SOURCE.json'),
        baseline_manifest_sha256=BASELINE_SHA, patch_sha256=sha(out / 'lineage/from_U5.patch')))
    marker = run / 'INITIAL_PUBLICATION.json'
    with (run / 'runner.log').open('w') as stream:
        process = subprocess.Popen([sys.executable, str(run / 'control/run_u5_atp_optimization.py'),
            '--run-root', str(run)], cwd=ROOT,
            env=dict(os.environ, MHBS_C2_TIMING_WORKSPACE=str(ROOT), MHBS_SHAKE_TIMING_WORKSPACE=str(ROOT),
                MHBS_BACKEND_WORKSPACE=str(ROOT)), stdin=subprocess.DEVNULL, stdout=stream,
            stderr=subprocess.STDOUT, start_new_session=True)
    deadline = time.monotonic() + 30
    while not marker.exists():
        require(process.poll() is None and time.monotonic() <= deadline, f'Initial publication failed: {run}')
        time.sleep(.1)
    index = core.archive.ARCHIVES / 'INDEX.md'
    text = index.read_text()
    entry = f'| {out.name} | [U5_ATP_Optimization_{stamp}]({out.name}/reports/U5_ATP_Optimization_{stamp}.md) | [证据]({out.name}/ARTIFACTS.json) |\n'
    require(out.name not in text, 'Duplicate experiment index entry')
    text = text.replace('\n后台补齐：', '\n' + entry + '\n后台补齐：')
    core.archive.atomic(index, text)
    result = dict(pid=process.pid, root=str(run), report=str(out / 'reports' / f'U5_ATP_Optimization_{stamp}.md'),
                  baseline='U5', simulation_cases=6, diagnostic_syntheses=2, route_jobs=0)
    write(run / 'LAUNCH.json', result)
    print(json.dumps(result, ensure_ascii=False, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--launch-candidate', action='store_true')
    group.add_argument('--inspect-baseline', action='store_true')
    group.add_argument('--run-root', type=Path, help=argparse.SUPPRESS)
    group.add_argument('--refresh-run', type=Path)
    parser.add_argument('--source-root', type=Path)
    parser.add_argument('--label', default='V1_U5_based_candidate')
    args = parser.parse_args()
    if args.inspect_baseline:
        evidence = checked_baseline()
        print(json.dumps(dict(baseline='U5', validated=True, manifest_sha256=BASELINE_SHA,
            measured_sign_cases=6, diagnostic_syntheses=2, supplemental_validation_passed=76,
            measured_physical_frequency_mhz=None, routed_atp_slice_ms=None), indent=2))
    elif args.refresh_run:
        runner = Runner(args.refresh_run)
        runner.state = read(runner.run / 'status.json')
        require(runner.state.get('complete') and core.previous.unchanged(runner.meta),
                'Only completed unchanged-source runs can be refreshed')
        runner.publish()
    elif args.run_root:
        return Runner(args.run_root).execute()
    else:
        launch(args)
    return 0


if __name__ == '__main__':
    sys.exit(main())
