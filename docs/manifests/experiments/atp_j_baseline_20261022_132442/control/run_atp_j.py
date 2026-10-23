#!/usr/bin/env python3
"""J: source-bound SHA2 ATP and SHAKE P6U2 timing measurements.

Preparation and freezing start no hardware. Measurement and fixed-target route
commands are separate; old background jobs and their controllers are untouched.
"""
import argparse
from copy import deepcopy
from datetime import datetime
import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from zoneinfo import ZoneInfo

import run_sha2_timing_f as f

ROOT = Path(os.environ.get('MHBS_ATP_J_WORKSPACE', f.ROOT)).resolve()
FAMILY = ROOT / 'build/atp_j'
I_RUN = ROOT / 'build/sha2_timing_g/candidate_20261022_120553'
I_SHA = '4350a4db61a8b68e2428733ad05e85eb17a6818d41f9e8a6998a235834f34da9'
MATRIX = ROOT / 'build/dual_pu_route_matrix/20261022_093744'
MATRIX_SHA = '6361eeed6936b3714835aade83b7b8e04ce9140c679b455bf1893d25f30d9c7d'
CONFIGS = ('sha2/P1U1', 'sha2/P4U1', 'sha2/P12U1', 'sha2/P4U2', 'shake/P6U2')
CONTROLS = ('run_atp_j.py', 'route_sha2_hard_target.tcl', *f.CONTROLS)
read, write, sha, require, now = f.read, f.write, f.sha, f.require, f.now
original_gate = f.gate


def closed(job, config):
    target = 150 if f.parts(config)[2] == 1 else 100
    timing = job.get('result', {})
    return bool(job.get('status') == 'passed' and job.get('source_unchanged')
        and timing.get('setup_hold_met') and timing.get('drc_errors') == 0
        and job.get('route_status', {}).get('passed')
        and timing.get('actual_period_ns', float('inf')) <= 1000 / target)


def controls(run, out):
    for name in CONTROLS:
        for base in (run, out):
            f.archive.copy_changed(ROOT / 'scripts' / name, base / 'control' / name)
    for base in (run, out):
        f.archive.copy_changed(ROOT / 'scripts/route_common_target.tcl', base / 'control/upstream_route_common_target.tcl')
        f.archive.copy_changed(ROOT / 'scripts/route_sha2_hard_target.tcl', base / 'control/route_common_target.tcl')
        write(base / 'ALIAS_PROVENANCE.json', dict(selected_source='scripts/route_sha2_hard_target.tcl',
            selected_source_sha256=sha(ROOT / 'scripts/route_sha2_hard_target.tcl'),
            alias='control/route_common_target.tcl', reason='Strict U1 6.666ns, U2 10.000ns; no timing exceptions.'))
        write(base / 'CONTROL_SOURCE.json', {n: sha(run / 'control' / n)
            for n in (*CONTROLS, 'upstream_route_common_target.tcl')})


def native_reference():
    """Verify and preserve each native configuration's own measured evidence."""
    refs = {}
    for native, expected in ((I_RUN, I_SHA), (MATRIX, MATRIX_SHA)):
        require(sha(native / 'SOURCE.json') == expected, 'Native SOURCE changed')
        meta = read(native / 'SOURCE.json')
        require(f.shared.unchanged(meta), 'Native frozen input changed')
        refs[str(native)] = (meta, read(native / 'status.json'), expected)
    i_meta = refs[str(I_RUN)][0]
    m_meta = refs[str(MATRIX)][0]
    # The SHA2 files are inactive in SHAKE. All eight SHAKE RTL inputs, source
    # list and the complete Sign harness must match the native SHAKE baseline.
    shake_names = [n for n in i_meta['rtl_files'] if n not in
        ('rtl/hash/sha2-recipe.sv', 'rtl/hash/sha256.sv')]
    shake_names += ['sources.txt', 'tb/tb_fast.sv', 'tb/fast_main.cpp', 'scripts/simulate_fast.sh']
    require(all(i_meta['sha256'][n] == m_meta['sha256'][n] for n in shake_names),
        'I and native SHAKE active RTL/harness differ')
    result = dict(checked_at=now(), native_sources={str(I_RUN): I_SHA, str(MATRIX): MATRIX_SHA},
        tests={}, routing={}, diagnostics={}, configurations={},
        shake_active_input_equivalence={n: i_meta['sha256'][n] for n in shake_names},
        inactive_sha2_files_not_used_for_shake=True)
    for config in CONFIGS:
        native = MATRIX if config.startswith('shake/') else I_RUN
        meta, state, manifest = refs[str(native)]
        result['configurations'][config] = dict(native_run=str(native), source_manifest_sha256=manifest)
        for profile in f.dual.PROFILES:
            key = config + '/' + profile
            test = deepcopy(state['tests'][key])
            require(test['status'] == 'passed' and test['source_unchanged']
                and test['source_manifest_sha256'] == manifest
                and test['output_and_signature_cache_checked_bytewise'], 'Native Sign missing: ' + key)
            for field in ('log', 'raw_log'):
                require(sha(test[field]) == test[field + '_sha256'], 'Native Sign log changed: ' + key)
            require(all(meta['sha256'][n] == h == sha(Path(meta['source_root']) / n)
                for n, h in test['vectors_sha256'].items()), 'Native vector changed: ' + key)
            result['tests'][key] = test
        physical = read(native / 'PHYSICAL_STATUS.json')['routes'] if native == I_RUN else state['routes']
        route = deepcopy(physical[config])
        require(route['status'] in ('passed', 'target_not_met') and route['source_unchanged'],
            'Native physical result incomplete: ' + config)
        directory = native / 'jobs' / config
        require(route['synth_area'] == f.shared.resources(directory / 'synth/utilization.rpt')
            and route['routed_area'] == f.shared.resources(directory / 'route/utilization.rpt')
            and route['route_status'] == f.shared.route_status(directory / 'route/route_status.rpt'),
            'Native physical reports differ: ' + config)
        for name, field in (('synth/synthesized.dcp', 'synthesized_checkpoint_sha256'),
                            ('route/routed.dcp', 'routed_checkpoint_sha256')):
            require(sha(directory / name) == route[field], 'Native checkpoint changed: ' + config)
        require(read(directory / 'result.json')['actual_period_ns'] == route['result']['actual_period_ns'],
            'Native physical period differs')
        route.update(native_run=str(native), native_source_manifest_sha256=manifest,
            strict_frequency_closed=closed(route, config))
        result['routing'][config] = route
        if native == I_RUN:
            syn = deepcopy(state['synthesis'][config])
            require(syn['status'] == 'passed' and syn['source_unchanged']
                and syn['source_manifest_sha256'] == manifest, 'Native diagnostic not bound')
            for name, wanted in syn['reports_sha256'].items():
                require(sha(native / 'synth' / config / name) == wanted, 'Native diagnostic changed')
            require(sha(native / 'synth' / config / 'synthesized.dcp') == syn['checkpoint_sha256'],
                'Native diagnostic checkpoint changed')
            syn.update(native_run=str(native), native_source_manifest_sha256=manifest)
            result['diagnostics'][config] = syn
    return result


def copy_reference(run, out, reference):
    for config, provenance in reference['configurations'].items():
        native = Path(provenance['native_run'])
        for folder in ('jobs', 'synth'):
            directory = native / folder / config
            for path in directory.rglob('*') if directory.exists() else []:
                if path.is_file() and path.suffix in ('.rpt', '.log', '.json', '.txt', '.xdc'):
                    f.archive.copy_changed(path, out / 'baseline_evidence' / folder / config / path.relative_to(directory))
        f.archive.copy_changed(native / 'SOURCE.json', out / 'baseline_evidence' / native.name / 'SOURCE.json')
    for base in (run, out):
        write(base / 'REFERENCE_EVIDENCE.json', reference)


def freeze(kind, label, baseline=None):
    reference = native_reference()
    if baseline:
        old = read(baseline / 'SOURCE.json')
        require(old['kind'] == 'baseline' and old['experiment_family'] == 'atp_j'
            and tuple(old['configs']) == CONFIGS and f.shared.unchanged(old), 'Wrong or changed J baseline')
    stamp = datetime.now(ZoneInfo('Asia/Singapore')).strftime('%Y%m%d_%H%M%S')
    run = FAMILY / (kind + '_' + stamp)
    out = f.archive.ARCHIVES / ('atp_j_' + kind + '_' + stamp)
    source = Path(read(I_RUN / 'SOURCE.json')['source_root']) if kind == 'baseline' else ROOT
    checks = f.dual.frozen_snapshot(source, run / 'source')
    rtl = [n for n in (run / 'source/sources.txt').read_text().splitlines() if n.strip()]
    meta = dict(schema='mhbs.p1sha_atp.source.v1', experiment_family='atp_j', kind=kind, label=label,
        run_id=stamp, started_at=now(), source_root=str(run / 'source'), archive_directory=str(out),
        sha256=checks, rtl_files=rtl, configs=list(CONFIGS), reference_manifest_sha256=I_SHA,
        baseline_run=str(baseline.resolve()) if baseline else None)
    settings = dict(f.shared.tool_settings(), vivado_workers=3, configs=list(CONFIGS), operation='sign',
        cycle_changes_allowed=True, hard_target_period_ns={'1': 6.666, '2': 10.0})
    for base in (run, out):
        write(base / 'SOURCE.json', meta)
        write(base / 'EXPERIMENT.json', settings)
    controls(run, out)
    copy_reference(run, out, reference)
    f.archive.pack_rtl(run / 'source', out / 'rtl.tar.gz', checks)
    f.shared.pack_support(run / 'source', out, checks)
    state = dict(schema='mhbs.atp_j.results.v1', label=label, pid=None,
        complete=kind == 'baseline', measurement_started=False, source_manifest_sha256=sha(run / 'SOURCE.json'),
        tests=deepcopy(reference['tests']) if kind == 'baseline' else
            {c + '/' + p: dict(status='pending') for c in CONFIGS for p in f.dual.PROFILES},
        synthesis={c: dict(status='not_measured' if kind == 'baseline' else 'pending') for c in CONFIGS})
    if kind == 'baseline':
        for config, syn in reference['diagnostics'].items():
            imported = deepcopy(syn)
            imported.update(source_manifest_sha256=sha(run / 'SOURCE.json'),
                no_new_synthesis_run=True, evidence_kind='native_I_identical_RTL_and_diagnostic_Tcl',
                equivalent_diagnostic_inputs={n: checks[n] for n in rtl + ['sources.txt', 'scripts/diagnose_timing.tcl']})
            for name in syn['reports_sha256']:
                for base in (run, out):
                    f.archive.copy_changed(I_RUN / 'synth' / config / name, base / 'synth' / config / name)
            state['synthesis'][config] = imported
    else:
        delta = subprocess.run(['diff', '-ru', str(Path(read(I_RUN / 'SOURCE.json')['source_root']) / 'rtl'),
            str(run / 'source/rtl')], text=True, stdout=subprocess.PIPE)
        require(delta.returncode in (0, 1), 'Cannot create candidate lineage')
        f.archive.atomic(out / 'lineage/from_I.patch', delta.stdout)
    for base in (run, out):
        write(base / 'status.json', state)
    publish_report(run)
    inventory(run)
    f.archive.index()
    return dict(run_root=str(run), source_manifest_sha256=sha(run / 'SOURCE.json'),
        archive_directory=str(out), hardware_started=False)


def rows(run):
    meta, state, reference = read(run / 'SOURCE.json'), read(run / 'status.json'), read(run / 'REFERENCE_EVIDENCE.json')
    physical = read(run / 'PHYSICAL_STATUS.json') if (run / 'PHYSICAL_STATUS.json').exists() else {}
    result = []
    for config in CONFIGS:
        target = 150 if f.parts(config)[2] == 1 else 100
        syn, route = state['synthesis'][config], physical.get('routes', {}).get(config, {})
        old_route = reference['routing'][config]
        for profile in f.dual.PROFILES:
            key = config + '/' + profile
            test, old = state['tests'][key], reference['tests'][key]
            row = dict(config=config, backend=f.parts(config)[0], profile=profile, simulation_status=test['status'],
                diagnostic_status=syn['status'], physical_status=route.get('status', 'not_requested'),
                cycles=test.get('cycles'), baseline_cycles=old['cycles'], cycles_change_pct=None,
                target_mhz=target, target_time_ms=None, assumed_diagnostic_atp=None,
                baseline_diagnostic_atp_change_pct=None, actual_mhz=None, routed_time_ms=None,
                routed_atp_slice_ms=None, baseline_actual_mhz=None, baseline_routed_atp=None,
                routed_atp_change_pct=None, rank=None, workload_equal=None)
            if closed(old_route, config):
                period = old_route['result']['actual_period_ns']
                row.update(baseline_actual_mhz=1000 / period,
                    baseline_routed_atp=old_route['routed_area']['equivalent_slice'] * old['cycles'] * period / 1e6)
            if test['status'] == 'passed':
                equal = all(test[n] == old[n] for n in ('hashes', 'permutations', 'vectors_sha256'))
                row.update(cycles_change_pct=100 * (test['cycles'] / old['cycles'] - 1),
                    target_time_ms=test['cycles'] / (target * 1000), workload_equal=equal)
                if equal and syn['status'] == 'passed':
                    row['assumed_diagnostic_atp'] = syn['area']['equivalent_slice'] * row['target_time_ms']
                    old_syn = reference['diagnostics'].get(config)
                    if old_syn:
                        row['baseline_diagnostic_atp_change_pct'] = 100 * (syn['area']['equivalent_slice'] * test['cycles'] /
                            (old_syn['area']['equivalent_slice'] * old['cycles']) - 1)
                if equal and closed(route, config):
                    period = route['result']['actual_period_ns']
                    row.update(actual_mhz=1000 / period, routed_time_ms=test['cycles'] * period / 1e6,
                        routed_atp_slice_ms=route['routed_area']['equivalent_slice'] * test['cycles'] * period / 1e6)
                    if row['baseline_routed_atp'] is not None:
                        row['routed_atp_change_pct'] = 100 * (row['routed_atp_slice_ms'] / row['baseline_routed_atp'] - 1)
            result.append(row)
    for backend in ('shake', 'sha2'):
        for profile in f.dual.PROFILES:
            ranked = sorted((r for r in result if r['backend'] == backend and r['profile'] == profile
                and r['routed_atp_slice_ms'] is not None), key=lambda r: r['routed_atp_slice_ms'])
            for rank, row in enumerate(ranked, 1):
                row['rank'] = rank
    return result


def extra_validation(run):
    path = run / 'j_extra_validation/SUMMARY.json'
    return read(path) if path.exists() else None


def publish_report(run):
    run = Path(run)
    meta = read(run / 'SOURCE.json')
    out = Path(meta['archive_directory'])
    with (run / 'J_REPORT.lock').open('a+') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        state, reference = read(run / 'status.json'), read(run / 'REFERENCE_EVIDENCE.json')
        physical = read(run / 'PHYSICAL_STATUS.json') if (run / 'PHYSICAL_STATUS.json').exists() else {}
        value = dict(updated_at=now(), source=meta, results=state, rows=rows(run), physical=physical,
            baseline_physical=reference['routing'], functional=f.functional(run), extra_functional=extra_validation(run),
            strict_target_period_ns={'1': 6.666, '2': 10.0}, diagnostics_never_establish_fmax=True,
            frequency_search=False, automatic_frequency_fallback=False)
        prefix = out / 'reports' / ('ATP_J_' + meta['run_id'])
        write(prefix.with_suffix('.json'), value)
        fmt = lambda x: '—' if x is None else f'{x:,.3f}'
        lines = ['# J轮：SHA2 ATP与SHAKE P6U2时序', '',
            f'候选：{meta["label"]}；更新时间：{value["updated_at"]}。', '',
            'SHA2基线为冻结I设计4350a4db…，四重点配置已严格布线闭合；SHAKE P6U2基线为'
            '6361eeed…矩阵的同配置实测结果，其100MHz未闭合，基线布线ATP留空。'
            '各自完整Sign、原始日志、向量、综合/布线报告与checkpoint校验后复用，保留原始SOURCE身份；'
            'SHAKE八个活动RTL文件与I逐项相同，两个未编译SHA2文件不作为SHAKE等价条件。', '',
            '同候选冻结RTL执行15项完整Sign、5点100MHz common诊断、36组正常/综合视图验证，'
            '另加SHAKE P6U2四组配方/调度正常与综合视图验证。每点自己的三个Sign、诊断及同源验证'
            '通过后才允许指定频率布线。U1=150MHz采用6.666ns，U2=100MHz采用10.000ns，'
            '实际setup/hold、完整路由、零DRC均通过才填写布线ATP；无搜索、降频或新增例外。', '',
            '器件xc7a200tffg1156-3、Vivado2025.2、common OOC、默认时序驱动、通用Keccak、'
            'SYNTHESIS统计裁剪；全局最多12个顶层Vivado、每个2线程，旧任务继续后台。'
            '100MHz仅用于诊断，超过600秒只延后分析。等效Slice=LUT/4+FF/8+232.4×BRAM36+102.4×DSP。', '']
        for backend in ('shake', 'sha2'):
            lines += [f'## {backend.upper()} common面积与时序', '',
                '| 配置 | 诊断LUT | FF | BRAM36 | 诊断Slice | 基线诊断Slice | 路径ns | 布线Slice | WNS | WHS | 物理状态 |',
                '|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|']
            for config in CONFIGS:
                if not config.startswith(backend + '/'):
                    continue
                syn, route = state['synthesis'][config], physical.get('routes', {}).get(config, {})
                area, timing = syn.get('area', {}), route.get('result', {})
                old_syn = reference['diagnostics'].get(config, {})
                lines.append('| ' + ' | '.join([config, *[fmt(area.get(n)) for n in ('lut', 'ff', 'bram36', 'equivalent_slice')],
                    fmt(old_syn.get('area', {}).get('equivalent_slice')), fmt(syn.get('timing', {}).get('data_path_ns')),
                    fmt(route.get('routed_area', {}).get('equivalent_slice')), fmt(timing.get('wns_ns')), fmt(timing.get('whs_ns')),
                    route.get('status', 'not_requested') + ('；analysis_deferred' if route.get('analysis_deferred') else '')]) + ' |')
            lines.append('')
        for profile in f.dual.PROFILES:
            lines += [f'## {profile} 完整Sign', '',
                '| 后端 | P/U | 周期 | 基线周期 | 周期变化% | 目标时间ms | 假定诊断ATP | 诊断ATP变化% | 实际MHz | 布线ATP | 基线布线ATP | ATP变化% | 排名 | 状态 |',
                '|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|']
            for row in value['rows']:
                if row['profile'] == profile:
                    lines.append('| ' + ' | '.join([row['backend'], row['config'].split('/')[1],
                        *[fmt(row[n]) for n in ('cycles', 'baseline_cycles', 'cycles_change_pct', 'target_time_ms',
                            'assumed_diagnostic_atp', 'baseline_diagnostic_atp_change_pct', 'actual_mhz',
                            'routed_atp_slice_ms', 'baseline_routed_atp', 'routed_atp_change_pct', 'rank')],
                        row['simulation_status'] + '/' + row['physical_status']]) + ' |')
            lines.append('')
        lines += ['## 同源验证', '']
        for name, proof, total in [('配方、调度与Verify', value['functional'], 36),
                                   ('SHAKE P6U2补充', value['extra_functional'], 4)]:
            lines.append(f'{name}：{proof.get("passed", 0) if proof else 0}/{total}通过；'
                + ('已完成。' if proof and proof.get('complete') else '待完成，不作为通过。'))
        lines += ['', '冻结RTL/support、原生基线证据、源码校验、综合分层/时序和Vivado日志归档；'
            '详细sim/validation日志保留运行目录，归档只保留验证摘要。无CSV、无归档README；h20完整Keygen/Sign继续停止。', '']
        f.archive.atomic(prefix.with_suffix('.md'), '\n'.join(lines))


def inventory(run):
    f.inventory.__wrapped__(run) if hasattr(f.inventory, '__wrapped__') else original_inventory(run)
    meta = read(Path(run) / 'SOURCE.json')
    out = Path(meta['archive_directory'])
    proof = extra_validation(Path(run))
    if proof:
        write(out / 'supplementary_evidence/shake_P6U2/SUMMARY.json', proof)
    write(out / 'ARTIFACTS.json', dict(updated_at=now(), source_manifest_sha256=sha(Path(run) / 'SOURCE.json'),
        pending_is_not_pass=True, omitted_details=['sim', 'validation', 'j_extra_validation/logs'],
        sha256={str(p.relative_to(out)): sha(p) for p in out.rglob('*')
            if p.is_file() and p.name != 'ARTIFACTS.json' and not p.name.endswith('.tmp')}))


def gate(run, config, verify=False):
    status = original_gate(run, config, verify)
    if config.startswith('shake/'):
        proof = extra_validation(run)
        if not proof or not proof.get('complete'):
            status['pending'].append('shake_P6U2_extra4')
        elif proof['passed'] != 4 or proof['failed'] or not proof['source_unchanged']:
            status['failed'].append('shake_P6U2_extra4')
        elif verify:
            require(proof['source_manifest_sha256'] == sha(run / 'SOURCE.json'), 'Extra validator source differs')
            for test in proof['tests']:
                require(test['passed'] and sha(test['log']) == test['log_sha256'], 'Extra functional log changed')
    status['ready'] = not status['pending'] and not status['failed']
    return status


original_inventory = f.inventory
f.publish_report, f.inventory, f.gate = publish_report, inventory, gate


class Physical(f.Physical):
    def route(self, backend, p, u):
        super().route(backend, p, u)
        config = f.dual.route_key(backend, p, u)
        item = self.state['routes'][config]
        if 'result' in item:
            hard = bool(item['result']['setup_hold_met'] and item['result']['drc_errors'] == 0
                and item['route_status']['passed'] and item['result']['actual_period_ns'] <= 1000 / (150 if u == 1 else 100))
            timing = dict(item['result'], strict_frequency_target_met=hard, clock_quantization_tolerance_ns=0)
            self.update('routes', config, status='passed' if hard else 'target_not_met', meets_target=hard, result=timing)


def validate(run):
    """The shared 36-group validator plus four missing SHAKE P6U2 groups."""
    meta = read(run / 'SOURCE.json')
    source = Path(meta['source_root'])
    output = run / 'j_extra_validation'
    output.mkdir(parents=True, exist_ok=False)
    (output / 'logs').mkdir()
    cases = [(tool, synthesis) for tool in ('check_recipes.py', 'check_pipeline.py') for synthesis in (False, True)]
    tests = []
    for tool, synthesis in cases:
        command = [sys.executable, 'scripts/' + tool, '--hash', 'shake', '--pipeline', '6', '--unroll', '2']
        if synthesis:
            command += ['--synthesis']
        log = output / 'logs' / (tool.replace('.py', '') + '_syn' + str(int(synthesis)) + '.log')
        with log.open('w') as stream:
            result = subprocess.run(command, cwd=source, env=dict(os.environ, HASH_BACKEND='shake',
                SIM_SYNTHESIS=str(int(synthesis)), KECCAK_LUT6='0', SIM_VCD='0'),
                stdin=subprocess.DEVNULL, stdout=stream, stderr=subprocess.STDOUT)
        marker = 'RECIPE_PASS' if tool == 'check_recipes.py' else 'PIPELINE_PASS'
        tests.append(dict(name=log.stem, command=command, passed=result.returncode == 0 and marker in log.read_text(),
            returncode=result.returncode, log=str(log), log_sha256=sha(log)))
        write(output / 'SUMMARY.json', dict(complete=len(tests) == len(cases),
            passed=sum(t['passed'] for t in tests), failed=sum(not t['passed'] for t in tests),
            total_planned=4, source_manifest_sha256=sha(run / 'SOURCE.json'),
            source_unchanged=f.shared.unchanged(meta), tests=tests))
        publish_report(run)
        inventory(run)
    return int(any(not t['passed'] for t in tests))


def detach(run, mode, log):
    env = dict(os.environ, MHBS_ATP_J_WORKSPACE=str(ROOT), MHBS_SHA2_F_WORKSPACE=str(ROOT),
        MHBS_P1SHA_WORKSPACE=str(ROOT), MHBS_DUAL_MATRIX_WORKSPACE=str(ROOT))
    with (run / log).open('w') as stream:
        process = subprocess.Popen([sys.executable, str(run / 'control/run_atp_j.py'), mode, str(run)],
            cwd=ROOT, env=env, stdin=subprocess.DEVNULL, stdout=stream, stderr=subprocess.STDOUT, start_new_session=True)
    return process.pid


def launch_measure(run):
    run = run.resolve()
    meta = read(run / 'SOURCE.json')
    require(meta['experiment_family'] == 'atp_j' and meta['kind'] == 'candidate' and f.shared.unchanged(meta),
        'Only the unchanged frozen J candidate may run')
    require(not (run / 'MEASUREMENT_LAUNCH.json').exists(), 'Measurement already launched')
    value = dict(requested_at=now(), source_manifest_sha256=sha(run / 'SOURCE.json'),
        pid=detach(run, '--run-root', 'runner.log'))
    with (run / 'functional_validator.log').open('w') as stream:
        process = subprocess.Popen([sys.executable, str(Path(meta['source_root']) / 'scripts/validate_p1sha_candidate.py'),
            '--run-root', str(run)], cwd=ROOT, stdin=subprocess.DEVNULL, stdout=stream,
            stderr=subprocess.STDOUT, start_new_session=True)
    value['functional_pid'] = process.pid
    value['extra_functional_pid'] = detach(run, '--validate-extra', 'extra_validator.log')
    write(run / 'MEASUREMENT_LAUNCH.json', value)
    return value


def launch_physical(run):
    run = run.resolve()
    meta = read(run / 'SOURCE.json')
    require(meta['experiment_family'] == 'atp_j' and meta['kind'] == 'candidate' and f.shared.unchanged(meta),
        'Only the unchanged frozen J candidate may route')
    require(not (run / 'PHYSICAL_REQUEST.json').exists(), 'Physical phase already requested')
    existing = list(FAMILY.glob('candidate_*/PHYSICAL_REQUEST.json'))
    require(len(existing) < 2, 'J physical budget is limited to two frozen candidates')
    value = dict(requested_at=now(), source_manifest_sha256=sha(run / 'SOURCE.json'), configs=list(CONFIGS),
        explicit_user_authorization=True, root_explicit_final_freeze=True, per_configuration_gate=True,
        targets_mhz={'1': 150, '2': 100}, frequency_search=False, automatic_frequency_fallback=False)
    for base in (run, Path(meta['archive_directory'])):
        write(base / 'PHYSICAL_REQUEST.json', value)
    value['pid'] = detach(run, '--physical-run', 'physical_runner.log')
    for base in (run, Path(meta['archive_directory'])):
        write(base / 'PHYSICAL_LAUNCH.json', value)
    return value


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--prepare-baseline', action='store_true')
    mode.add_argument('--freeze-candidate', action='store_true')
    mode.add_argument('--launch-measure', type=Path)
    mode.add_argument('--route-existing', type=Path)
    mode.add_argument('--run-root', type=Path)
    mode.add_argument('--physical-run', type=Path)
    mode.add_argument('--validate-extra', type=Path)
    mode.add_argument('--report-existing', type=Path)
    parser.add_argument('--baseline', type=Path)
    parser.add_argument('--label', default='J1')
    args = parser.parse_args()
    if args.prepare_baseline:
        result = freeze('baseline', 'I_SHA2_and_native_SHAKE_P6U2')
    elif args.freeze_candidate:
        require(args.baseline is not None, '--baseline is required')
        result = freeze('candidate', args.label, args.baseline)
    elif args.launch_measure:
        result = launch_measure(args.launch_measure)
    elif args.route_existing:
        result = launch_physical(args.route_existing)
    elif args.run_root:
        raise SystemExit(f.Measurement(args.run_root).execute())
    elif args.physical_run:
        Physical(args.physical_run).execute()
        raise SystemExit()
    elif args.validate_extra:
        raise SystemExit(validate(args.validate_extra))
    else:
        publish_report(args.report_existing)
        inventory(args.report_existing)
        f.archive.index()
        result = dict(report_refreshed=str(args.report_existing))
    print(json.dumps(result, ensure_ascii=False, indent=2))
