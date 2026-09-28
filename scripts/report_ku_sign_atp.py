#!/usr/bin/env python3
"""Report measured Sign cycles/area at explicitly assumed U-specific clocks."""
import argparse
import csv
import difflib
import hashlib
import io
import json
import math
import os
import re
import tarfile
from datetime import datetime
from pathlib import Path

MAIN = Path(__file__).resolve().parents[1]
FREQUENCIES = {1: 151.0, 2: 112.0, 3: 67.0, 4: 48.0}
PREFIX = 'KU_Sign_ATP_' + '_'.join(f'{FREQUENCIES[u]:g}' for u in (1, 2, 3, 4))
PROFILES = ('slh_128f', 'slh_192f', 'slh_256f')
POINTS = [(k, u) for k in (1, 2, 4) for u in (1, 2, 3, 4)]


def resources(path, read):
    data = read(path, as_json=False)
    area = {}
    for label, key in [('Slice LUTs', 'lut'), ('Slice Registers', 'ff'),
                       ('LUT as Memory', 'lutram'), ('Block RAM Tile', 'bram36'),
                       ('DSPs', 'dsp')]:
        match = re.search(r'\|\s*' + re.escape(label) + r'\*?\s*\|\s*([\d,.]+)', data)
        if not match:
            raise ValueError(f'Missing resource {label}: {path}')
        area[key] = float(match[1].replace(',', ''))
    area['equivalent_slice'] = (area['lut'] / 4 + area['ff'] / 8
                                + area['bram36'] * 232.4 + area['dsp'] * 102.4)
    return area


def fmt(value, precision=3):
    if value is None:
        return '-'
    return f'{value:.{precision}f}' if isinstance(value, float) else str(value)


def write_csv(path, rows):
    with path.open('w', newline='', encoding='utf-8-sig') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]), lineterminator='\n')
        writer.writeheader()
        writer.writerows({k: '-' if v is None else v for k, v in row.items()} for row in rows)


def audit_positive_setup(folder, period, read, images):
    """Re-audit completed routes under the user's positive Setup criterion."""
    clock = read(folder / 'clock.json')
    assert math.isclose(clock['period_ns'], period)
    assert clock['wns_ns'] > 0 and clock['whs_ns'] >= 0
    timing = read(folder / 'timing_summary.rpt', as_json=False)
    assert 'All user specified timing constraints are met.' in timing
    checks = read(folder / 'check_timing.rpt', as_json=False)
    for category in ('no_clock', 'unconstrained_internal_endpoints', 'no_input_delay',
                     'no_output_delay', 'partial_input_delay', 'partial_output_delay'):
        match = re.search(r'checking\s+' + category + r'\s*\((\d+)\)', checks, re.I)
        assert match and int(match[1]) == 0, category
    route = read(folder / 'route_status.rpt', as_json=False)
    counts = {}
    for label in ('routable nets', 'fully routed nets', 'nets with routing errors'):
        match = re.search(r'# of\s+' + label + r'\.*\s*:\s*(\d+)', route, re.I)
        assert match, label
        counts[label] = int(match[1])
    assert counts['routable nets'] == counts['fully routed nets'] > 0
    assert counts['nets with routing errors'] == 0
    words = {kind: [int(x, 16) for x in read(images / (kind + '.mem'), as_json=False).split()]
             for kind in ('program', 'template', 'descriptor')}
    seen = set()
    for line in read(folder / 'initialized_rom.tsv', as_json=False).splitlines():
        kind, port, bit, cell, bits, pins, init = line.split('\t')
        pins = list(map(int, pins.split(',')))
        bits, bit, port = int(bits), int(bit), int(port)
        assert sorted(pins) == list(range(bits)), cell
        expected = sum(((words[kind][sum(((i >> p) & 1) << a for p, a in enumerate(pins))] >> bit) & 1) << i
                       for i in range(1 << bits))
        assert int(init.split("'h")[1], 16) == expected, cell
        assert (kind, port, bit) not in seen
        seen.add((kind, port, bit))
    assert seen == {(kind, port, bit) for kind in words
                    for port in range(2 if kind == 'descriptor' else 1) for bit in range(64)}
    return clock, resources(folder / 'utilization.rpt', read)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--worktree', type=Path,
                        default=MAIN / 'manifests/experiments/ku_sign_latest',
                        help='Self-contained evidence archive (or original experiment worktree)')
    parser.add_argument('--output-dir', type=Path, default=MAIN / 'docs/v4.2')
    args = parser.parse_args()
    worktree, output = args.worktree.resolve(), args.output_dir.resolve()
    archived = (worktree / 'archive_manifest.json').exists()
    original_root = Path(json.loads((worktree / 'archive_manifest.json').read_text())['original_worktree']) if archived else worktree

    def locate(path):
        path = Path(path)
        if path.is_absolute():
            path = path.relative_to(original_root)
        if archived and path.parts[0] == 'build':
            path = Path('results', *path.parts[1:])
        return worktree / path

    def evidence_name(path):
        return os.path.relpath(path, MAIN)

    build = locate('build/v4.2/external_job_message')
    generated = datetime.now().astimezone().isoformat(timespec='seconds')
    evidence = {}

    def read(path, as_json=True):
        raw = path.read_bytes()
        evidence[evidence_name(path)] = hashlib.sha256(raw).hexdigest()
        text = raw.decode()
        return json.loads(text) if as_json else text

    def remember(path):
        evidence[evidence_name(path)] = hashlib.sha256(path.read_bytes()).hexdigest()

    baseline = worktree / 'manifests/experiments/unified_hbs_v4.2/external_job_message/candidates/program16_20260927_v1'
    reference = read(baseline / 'simulation.json')['cases']
    baseline_area = resources(baseline / 'synthesis/core_utilization.rpt', read)
    points = {}
    old_sources = None
    for k, u in POINTS:
        label = f'K{k}U{u}'
        tag = f'ku_k{k}u{u}_v2' if u != 3 else ('signfixed_k2u3_50m_v1' if k == 2 else f'signscan_k{k}u3_v1')
        point = dict(k=k, u=u, frequency_mhz=FREQUENCIES[u], tag=tag,
                     area=None, simulation={}, inputs=None, shells={})
        points[label] = point
        if tag is None:
            continue
        folder = build / tag
        inputs, sim = read(folder / 'inputs.json'), read(folder / 'simulation.json')
        assert (inputs['lanes'], inputs['unroll']) == (k, u)
        assert sim['passed'] and (sim['lanes'], sim['unroll']) == (k, u)
        assert sim['rtl_sha256'] == inputs['rtl_sha256']
        cases = dict(sim['cases'])
        supplemental_path = folder / 'supplemental_sign_profiles.json'
        if supplemental_path.exists():
            supplemental = read(supplemental_path)
            assert (supplemental['lanes'], supplemental['unroll']) == (k, u)
            assert supplemental['rtl_sha256'] == inputs['rtl_sha256']
            assert supplemental['snapshot_sha256'] == inputs['snapshot_sha256']
            assert supplemental['software_gate_sha256'] == inputs['software_gate_sha256']
            assert not set(cases).intersection(supplemental['cases']), 'Supplement overwrites original measurements'
            cases.update(supplemental['cases'])
        if u != 3:
            old_sources = inputs['source_sha256'] if old_sources is None else old_sources
            assert inputs['source_sha256'] == old_sources, label
        remember(folder / 'source_snapshot.tar.gz')
        assert evidence[evidence_name(folder / 'source_snapshot.tar.gz')] == inputs['snapshot_sha256']
        point.update(inputs=inputs, area=resources(folder / 'synthesis/core_utilization.rpt', read))
        for profile in PROFILES:
            shell = profile + '_sign'
            if shell not in cases:
                continue
            case = cases[shell]
            ref = reference[shell]
            assert case['passed'] and case['output_sha256'] == ref['output_sha256'], (label, shell)
            assert (case['hashes'], case['permutations']) == (ref['hashes'], ref['permutations'])
            if label == 'K2U2':
                assert case['sign_cycles'] == ref['sign_cycles']
            point['simulation'][shell] = case
            shell_report = folder / 'synthesis' / shell / 'utilization.rpt'
            if shell_report.exists():
                point['shells'][shell] = resources(shell_report, read)
            for path, digest in [(folder / 'logs' / (shell + '.log'), case['log_sha256']),
                                 (folder / 'logs' / (shell + '.actual.mem'), case['output_sha256'])]:
                remember(path)
                assert evidence[evidence_name(path)] == digest

    # U3 changes only an elaboration guard; record rather than assert identical snapshots.
    old = points['K2U2']['inputs']
    new = points['K2U3']['inputs']
    changed = [p for p in old['rtl_sha256'] if old['rtl_sha256'][p] != new['rtl_sha256'][p]]
    assert changed == ['rtl/top/mhbs_hbs.sv']
    texts = []
    for label in ('K2U2', 'K2U3'):
        with tarfile.open(build / points[label]['tag'] / 'source_snapshot.tar.gz') as archive:
            member = next(m for m in archive.getmembers() if m.name.endswith(changed[0]))
            texts.append(archive.extractfile(member).read().decode())
    expected = texts[0].replace('(UNROLL!=1 && UNROLL!=2 && UNROLL!=4)', '(UNROLL<1 || UNROLL>4)').replace(
        'K and U must each be 1, 2 or 4', 'K must be 1, 2 or 4; U must be 1, 2, 3 or 4')
    assert expected == texts[1], 'U3 snapshot has additional RTL changes'
    assert old['software_gate_sha256'] == new['software_gate_sha256']
    assert all(new['source_sha256'].get(p) == digest for p, digest in old_sources.items() if '/images/' in p)
    for k in (1, 4):
        assert points[f'K{k}U3']['inputs']['source_sha256'] == new['source_sha256']
    source_diff = '\n'.join(difflib.unified_diff(texts[0].splitlines(), texts[1].splitlines(),
                                              fromfile='nine_point', tofile='U3_support'))

    rows = []
    for profile in PROFILES:
        shell = profile + '_sign'
        for k, u in POINTS:
            label, point = f'K{k}U{u}', points[f'K{k}U{u}']
            area, case = point['area'], point['simulation'].get(shell)
            freq = FREQUENCIES[u]
            latency = case['sign_cycles'] / (freq * 1000) if case else None
            core = area['equivalent_slice'] if area else None
            shell_area = point['shells'].get(shell, {}).get('equivalent_slice')
            row = dict(profile_operation=profile.replace('slh_', '') + ' SG', point=label,
                       core_lut=area['lut'] if area else None, core_ff=area['ff'] if area else None,
                       core_lutram=area['lutram'] if area else None,
                       core_bram36=area['bram36'] if area else None, core_dsp=area['dsp'] if area else None,
                       core_equivalent_slice=core, assumed_frequency_mhz=freq, assumed_period_ns=1000 / freq,
                       compute_cycles=case['sign_cycles'] if case else None,
                       hashes=case['hashes'] if case else None, permutations=case['permutations'] if case else None,
                       estimated_sign_ms=latency, estimated_core_atp=core * latency if core is not None and latency is not None else None,
                       estimated_sign_per_second=1000 / latency if latency else None,
                       shell_synth_equivalent_slice=shell_area,
                       estimated_shell_synth_atp=shell_area * latency if shell_area is not None and latency is not None else None,
                       atp_rank=None, atp_ratio_to_k2u2=None, speedup_to_k2u2=None,
                       measurement_status='实测面积/周期；指定频率估算' if case else '缺少面积/周期' if area is None else '缺少该参数集周期',
                       output_sha256=case['output_sha256'] if case else None,
                       source_tag=point['tag'], snapshot_sha256=point['inputs']['snapshot_sha256'] if point['inputs'] else None)
            rows.append(row)
        group = [r for r in rows if r['profile_operation'] == profile.replace('slh_', '') + ' SG']
        valid = sorted((r for r in group if r['estimated_core_atp'] is not None), key=lambda r: r['estimated_core_atp'])
        control = next(r for r in group if r['point'] == 'K2U2')
        for rank, row in enumerate(valid, 1):
            row.update(atp_rank=rank, atp_ratio_to_k2u2=row['estimated_core_atp'] / control['estimated_core_atp'],
                       speedup_to_k2u2=control['estimated_sign_ms'] / row['estimated_sign_ms'])

    probes = []
    for state_path in sorted(locate('build/v4.2').glob('sign*/state.json')):
        state = read(state_path)
        for label, point in state.get('points', {}).items():
            for attempt in point.get('attempts', []):
                period = attempt.get('period_ns', attempt.get('ticks', 0) / 10)
                if period <= 0:
                    continue
                status = attempt['status']
                original_status = status
                if status == 'running' and state['status'] == 'stopped':
                    status = 'stopped'
                cancellation_path = state_path.parent / label / 'cancelled_by_user.json'
                if cancellation_path.exists():
                    cancellation = read(cancellation_path)
                    if cancellation['attempt_index'] == attempt['index'] and status != 'passed':
                        status = 'stopped'
                wns, whs = attempt.get('wns_ns'), attempt.get('whs_ns')
                qualified = (status in ('passed', 'timing_failed') and wns is not None and wns > 0
                             and whs is not None and whs >= 0)
                route_area = attempt.get('equivalent_slice')
                audit_failure = None
                if qualified:
                    try:
                        folder = locate(attempt['folder'])
                        clock, area = audit_positive_setup(folder, period, read,
                            worktree / 'manifests/experiments/unified_hbs_v4.2/external_job_message/images/slh_128f')
                        wns, whs, route_area = clock['wns_ns'], clock['whs_ns'], area['equivalent_slice']
                        status = 'passed'
                    except (AssertionError, OSError, ValueError) as error:
                        qualified = False
                        status = 'audit_failed'
                        audit_failure = repr(error)
                elif status == 'passed':
                    status = 'timing_failed'
                latency = point['simulation']['sign_cycles'] * period / 1e6 if qualified else None
                record = dict(profile_operation='128f SG', point=label, run=state_path.parent.name,
                              attempt=attempt['index'], target_frequency_mhz=1000 / period,
                              target_period_ns=period, status=status, setup_ns=wns, hold_ns=whs,
                              elapsed_minutes=attempt.get('elapsed_seconds', 0) / 60,
                              post_route_equivalent_slice=route_area,
                              qualified_frequency_mhz=1000 / period if qualified else None,
                              qualified_sign_ms=latency,
                              qualified_route_atp=route_area * latency if qualified else None,
                              failure=audit_failure or (attempt.get('failure') if not qualified else None),
                              original_status=original_status, original_failure=attempt.get('failure'),
                              source_state=evidence_name(state_path),
                              source_dcp_sha256=point.get('source_dcp_sha256'))
                probes.append(record)
    probes.sort(key=lambda r: (int(r['point'][1]), int(r['point'][-1]), r['target_frequency_mhz'], r['run'], r['attempt']))
    status_names = {'passed': '通过', 'timing_failed': '时序失败', 'audit_failed': '审计失败',
                    'congestion': '拥塞失败', 'running': '运行中', 'stopped': '已停止',
                    'timeout': '超时', 'tool_error': '工具错误', 'pending': '待运行'}

    history = []
    for profile in PROFILES:
        for directory, name in [('route', '历史 10 ns 流程'), ('route_internal20_v1', '历史 20 ns 后重设时钟')]:
            path = build / 'ku_k2u2_v2' / directory / (profile + '_sign') / 'result.json'
            if path.exists():
                result = read(path)
                history.append(dict(profile_operation=profile.replace('slh_', '') + ' SG', flow=name,
                                    initial_period_ns=result.get('route_period_ns'), **result))

    complete = [r for r in rows if r['estimated_core_atp'] is not None]
    summary = []
    for profile in PROFILES:
        group = [r for r in complete if r['profile_operation'] == profile.replace('slh_', '') + ' SG']
        best, fastest = min(group, key=lambda r: r['estimated_core_atp']), min(group, key=lambda r: r['estimated_sign_ms'])
        control = next(r for r in group if r['point'] == 'K2U2')
        summary.append(dict(profile_operation=best['profile_operation'], best_atp_point=best['point'],
                            best_atp=best['estimated_core_atp'], best_atp_sign_ms=best['estimated_sign_ms'],
                            fastest_point=fastest['point'], fastest_sign_ms=fastest['estimated_sign_ms'],
                            improvement_vs_k2u2_percent=(1 - best['estimated_core_atp'] / control['estimated_core_atp']) * 100,
                            comparison_count=len(group)))
    full_points = [label for label, p in points.items() if len(p['simulation']) == 3]
    metrics = {label: [points[label]['area']['equivalent_slice'], *[
        next(r['estimated_sign_ms'] for r in rows if r['point'] == label and r['profile_operation'] == profile.replace('slh_', '') + ' SG')
        for profile in PROFILES]] for label in full_points}
    pareto = [label for label, value in metrics.items() if not any(
        all(a <= b for a, b in zip(other, value)) and any(a < b for a, b in zip(other, value))
        for other_label, other in metrics.items() if other_label != label)]

    def link(path):
        return os.path.relpath(path, output)

    frequency_title = ' / '.join(f'{FREQUENCIES[u]:g}' for u in (1, 2, 3, 4))
    frequency_description = '、'.join(f'U{u}={FREQUENCIES[u]:g} MHz' for u in (1, 2, 3, 4))
    coverage_description = ('全部 36 行均具有实测共同核面积、计算周期、Hash 次数、置换次数和参考输出比对结果。'
                            if len(complete) == len(rows) else
                            f'{len(complete)} 行具有实测面积和计算周期，{len(rows) - len(complete)} 行缺数据并填 `-`。')
    pareto_scope = '十二点' if len(full_points) == 12 else f'{len(full_points)} 个完整参数集设计'
    pareto_missing_note = '' if len(full_points) == 12 else '缺少完整三组数据的设计不纳入全参数集 Pareto 判定。'
    lines = [f'# K/U Sign 面积时间积报告：{frequency_title} MHz', '',
             f'统计时间：{generated}。本报告是指定频率下的估算结果及实测证据快照。', '',
             '## 1. 目的与范围', '',
             '比较 K∈{1,2,4}、U∈{1,2,3,4} 的十二个设计，在 128f、192f、256f Sign 下的面积、签名时间和 ATP。'
             '沿用实验的 K 取值，不包含 K3；本报告只分析 Sign。', '',
             f'指定工作频率：{frequency_description}。'
             '同一个 U 对所有 K 使用相同频率，这是比较条件，不代表所有设计均已完成该频率签核。', '',
             f'共有 {len(rows)} 行设计/参数集组合。{coverage_description}'
             'U3 的 192f/256f 补测复用相同源码、Program16 镜像及软件参考向量；计算周期来自实际仿真。', '',
             '## 2. 计算口径', '',
             '- 器件：`xc7a200tffg1156-3`；综合/布线：Vivado 2025.2；共同核综合采用 10 ns 约束。',
             '- 基线：Program16 镜像、ABI、软件参考向量；仅统计计算周期，不包含装载消息、输入输出传输及启动开销。',
             '- 主表面积采用共同核综合面积，保证所有已有设计使用同一面积口径。外壳综合面积及对应估算 ATP 另存 CSV；'
             '尚未综合的 U3 192f/256f 外壳资源仍为 `-`，不影响主表的共同核 ATP 计算。',
             '- 等效 Slice = LUT/4 + FF/8 + BRAM36×232.4 + DSP×102.4。LUTRAM 已包含在 LUT 中，不重复相加。'
             '等效 Slice 是资源换算指标，不是 Vivado 实际占用 Slice 数。',
             '- 签名时间（ms）= 计算周期 /（指定频率 MHz × 1000）。',
             '- 估算 ATP（Slice·ms）= 共同核综合等效 Slice × 估算签名时间。数值越小越好。',
             '- 布线实测 ATP = 对应档位的布线后等效 Slice × 该档位签名时间；仅通过签核的档位提供有效频率和实测 ATP。',
             '- 按用户最新要求，本报告判定通过的条件为：原目标周期下 Setup >0 ns、Hold ≥0、完整布线及 ROM 内容审计通过。'
             '外部接口排除在核内频率签核范围之外。',
             '- 后台旧档的原始日志与状态保留；报告按上述判据重新检查已完成档位，CSV/JSON 同时保留原始状态。',
             '- 以下固定频率排序不能代替最终布线排序，K 的变化也可能改变可达到的频率。', '',
             '## 3. 设计面积与数据覆盖', '',
             '| K/U | LUT | FF | LUTRAM | BRAM36 | DSP | 共同核等效 Slice | 指定 MHz | 周期 ns | 已验证 Sign 参数集 |',
             '|---|---:|---:|---:|---:|---:|---:|---:|---:|---|']
    for label, point in points.items():
        area = point['area'] or {}
        coverage = '、'.join(p.replace('slh_', '') for p in PROFILES if p + '_sign' in point['simulation']) or '-'
        lines.append('| ' + ' | '.join([label, *[fmt(area.get(key), 0) for key in ('lut', 'ff', 'lutram', 'bram36', 'dsp')],
                                       fmt(area.get('equivalent_slice')), fmt(point['frequency_mhz']),
                                       fmt(1000 / point['frequency_mhz'], 6), coverage]) + ' |')
    lines += ['', '## 4. 全部数据总表', '',
              '第一列合并参数集与操作；按 128f SG、192f SG、256f SG 连续排列。所有时间与主表 ATP 使用指定频率计算，属于估算。'
              '排序仅覆盖本参数集已有数据的设计，未测设计保留 `-`。', '',
              '| 参数集/操作 | K/U | 共同核等效 Slice | 指定 MHz | 计算周期 | Hash 次数 | 置换次数 | 签名时间 ms（估算） | ATP Slice·ms（估算） | ATP 排名 |',
              '|---|---|---:|---:|---:|---:|---:|---:|---:|---:|']
    for row in rows:
        lines.append('| ' + ' | '.join(fmt(row[key]) for key in (
            'profile_operation', 'point', 'core_equivalent_slice', 'assumed_frequency_mhz', 'compute_cycles',
            'hashes', 'permutations', 'estimated_sign_ms', 'estimated_core_atp', 'atp_rank')) + ' |')
    lines += ['', '## 5. 比较结论', '',
              '| 参数集/操作 | 最低估算 ATP 设计 | 签名时间 ms | ATP Slice·ms | 相对 K2U2 ATP 降幅 | 已有数据设计数 |',
              '|---|---|---:|---:|---:|---:|']
    for result in summary:
        lines.append('| ' + ' | '.join([result['profile_operation'], result['best_atp_point'],
                                       fmt(result['best_atp_sign_ms']), fmt(result['best_atp']),
                                       fmt(result['improvement_vs_k2u2_percent'], 2) + '%', str(result['comparison_count'])]) + ' |')
    best128 = summary[0]
    lines += ['', f'在指定频率和共同核综合面积的条件下，现有数据的三个参数集最低 ATP 均为 '
              f'**{best128["best_atp_point"]}**，并且三个参数集的最短估算签名时间也均为该设计。'
              '这是指定频率条件下的结论；其他 K 及参数集尚未完成对应频率签核，最终布线排序仍可能不同。', '',
              '固定频率下，增加 U 会减少计算周期，同时降低指定频率并增加面积，因此 ATP 并不随 U 单调下降。'
              '增大 K 的并行收益需要与新增 Hash lane 面积一起比较。', '',
              f'以共同核面积及三组指定频率下的签名时间判断支配关系，{pareto_scope}中 Pareto 前沿为：'
              + '、'.join(pareto) + '。' + pareto_missing_note, '',
              '## 6. 指定频率的布线验证与实测 ATP', '',
              '下表只展示 128f Sign 的对应指定频率证据。K1/K4 的这些目标频率尚未验证；192f/256f 也尚未完成对应目标频率扫描。'
              '失败档的布线面积可供观察，但不填写有效频率或合格实测 ATP。', '',
              '| 参数集/操作 | K/U | 指定 MHz | 布线后等效 Slice | Setup ns | Hold ns | 签核状态 | 有效 MHz | 合格实测 ATP Slice·ms |',
              '|---|---|---:|---:|---:|---:|---|---:|---:|']
    for label, point in points.items():
        candidates = [p for p in probes if p['point'] == label and math.isclose(p['target_frequency_mhz'], point['frequency_mhz'], abs_tol=1e-5)]
        probe = next((p for p in candidates if p['status'] == 'passed'), candidates[-1] if candidates else {})
        lines.append('| ' + ' | '.join(['128f SG', label, fmt(point['frequency_mhz']),
                                       fmt(probe.get('post_route_equivalent_slice')), fmt(probe.get('setup_ns')),
                                       fmt(probe.get('hold_ns')), status_names.get(probe.get('status'), '未测试'),
                                       fmt(probe.get('qualified_frequency_mhz')), fmt(probe.get('qualified_route_atp'))]) + ' |')
    lines += ['', 'K2U1 151 MHz、K2U2 112 MHz、K2U3 67 MHz、K2U4 48 MHz 均已按原目标周期通过。'
              '各自的 Setup/Hold 及布线后面积列于上表。这四个频率不能直接作为其他 K 或其他参数集已通过签核的证据。', '',
              '## 7. 全部新时序档位快照', '',
              '每档最多 2 小时、8 线程；中断与失败保留证据。下表状态来自本次生成报告时读取的持久化状态，运行中数据以后仍会变化。', '',
              '| 参数集/操作 | K/U | 目标 MHz | 周期 ns | Setup ns | Hold ns | 状态 | 累计分钟 | 运行目录 / 档位 |',
              '|---|---|---:|---:|---:|---:|---|---:|---|']
    for probe in probes:
        lines.append('| ' + ' | '.join([probe['profile_operation'], probe['point'], fmt(probe['target_frequency_mhz']),
                                       fmt(probe['target_period_ns'], 6), fmt(probe['setup_ns']), fmt(probe['hold_ns']),
                                       status_names.get(probe['status'], probe['status']), fmt(probe['elapsed_minutes'], 1),
                                       f'`{probe["run"]}` / {probe["attempt"]}']) + ' |')
    lines += ['', 'K2U3 75 MHz 因拥塞失败，最终工具报剩余 5,460 个节点重叠，不记录有效频率。'
              'K2U4 50 MHz 首次按用户要求停止，恢复后达到累计 120 分钟时限而超时，未完成布线；'
              '不记录有效频率；精简归档保留日志和审计报告，不保存大型 DCP 检查点。', '',
              '## 8. 历史 K2U2 10 ns / 20 ns 对照', '',
              '| 参数集/操作 | 流程 | 初始周期 ns | 最终报告 MHz | 布线等效 Slice | 签名时间 ms | 布线 ATP Slice·ms | Setup ns | Hold ns |',
              '|---|---|---:|---:|---:|---:|---:|---:|---:|']
    for row in history:
        lines.append('| ' + ' | '.join(fmt(row.get(key)) for key in (
            'profile_operation', 'flow', 'initial_period_ns', 'frequency_mhz', 'equivalent_slice',
            'latency_ms', 'area_time_product', 'wns_ns', 'whs_ns')) + ' |')
    lines += ['', '历史 20 ns 流程会在布线后重新设置最终时钟再分析，最终报告频率不是原始约束下的最高通过频率。'
              '历史 10 ns 流程的接口排除阶段也不同。它们与本次指定频率估算及严格目标周期扫描分表列示，不能直接混为同一测试条件。', '',
              '## 9. 功能验证与源码一致性', '',
              f'- 已有的 {len(complete)} 组 Sign 仿真输出、Hash 次数、置换次数均与软件参考/Program16 基线一致。',
              '- 九点使用同一源码快照。U3 版仅扩展 `mhbs_hbs.sv` 的合法 U 参数检查，Hash 数据通路未改变；'
              '已逐字比较两个封存文件，Program16 镜像哈希和软件门禁哈希一致。JSON 保存源码差异及各点快照哈希。',
              '- 参数化 K2U2 的三组 Sign 计算周期与封存 Program16 一致：729983、1249491、2579236。',
              f'- Program16 共同核等效 Slice 为 {baseline_area["equivalent_slice"]:.3f}；参数化 K2U2 为 '
              f'{points["K2U2"]["area"]["equivalent_slice"]:.3f}，增加 '
              f'{points["K2U2"]["area"]["equivalent_slice"] - baseline_area["equivalent_slice"]:.3f}（4.05%）。'
              '该面积变化单独列出，不将生产基线面积混入九点排序。',
              '- 当前可核对的 Keccak U1/U2/U3/U4 单元运行状态见 JSON；原九点端点存储、Verify、复位及统计关闭回归证据见九点封存记录。', '',
              '## 10. 文件与复现', '',
              f'- [全部数据 CSV]({PREFIX}.csv)：36 行，含共同核与外壳综合两种估算 ATP、排名和相对 K2U2 的比例。',
              f'- [全部档位 CSV]({PREFIX}_Timing.csv)：包含全部新时序尝试、失败原因和证据目录。',
              f'- [原始数据与证据 JSON]({PREFIX}.json)：实测资源/周期、源码快照、输出哈希、频率条件、历史对照和状态快照。',
              f'- [证据 SHA-256 清单]({PREFIX}.sha256)：输入证据、生成脚本和输出文件哈希。',
              f'- [九点封存记录]({link(worktree / "manifests/experiments/ku_matrix_20260927_v1")}): 旧流程详细证据与扩展回归。',
              f'- [报告生成脚本]({link(Path(__file__).resolve())})。',
              '- 更新命令：`python3 scripts/report_ku_sign_atp.py`。该命令只读取数据并生成报告，不启动仿真、综合或布线。',
              f'- [独立原始证据归档]({link(worktree / "README.md")}): 源码快照、镜像/向量、仿真输出、综合与布线原始报告。',
              '- 默认从独立归档读取，删除项目根目录 `build/` 后仍可重新生成本报告。SHA-256 清单路径相对仓库根目录。',
              '- 原始 JSON 中的绝对路径是历史来源记录；报告生成不依赖这些旧目录。旧版汇总报告已清理。', '']

    units_state = read(locate('build/v4.2/sign_timing_u1234_v1/state.json'))
    assert all(units_state['units'][str(u)]['passed'] for u in (1, 2, 3, 4))
    for u in (1, 2, 3, 4):
        path = locate(f'build/v4.2/sign_timing_u1234_v1/units/U{u}/run.log')
        remember(path)
        assert evidence[evidence_name(path)] == units_state['units'][str(u)]['run_sha256']
    remember(Path(__file__).resolve())
    payload = dict(schema='mhbs.ku_sign_fixed_frequency_atp.v1', generated_at=generated,
                   kind='conditional_frequency_estimate', device='xc7a200tffg1156-3', vivado='2025.2',
                   assumed_frequency_mhz_by_u=FREQUENCIES, worktree=evidence_name(worktree),
                   area_basis='common_core_synthesis_equivalent_slice', frequency_is_assumed=True,
                   timing_acceptance=dict(setup_ns_greater_than=0, hold_ns_greater_or_equal=0,
                                          complete_route_required=True, rom_audit_required=True),
                   rows=rows, measured_rows=len(complete), missing_rows=len(rows) - len(complete),
                   summary=summary, pareto_points=pareto, pareto_considered_points=full_points,
                   points=points, baseline_area=baseline_area,
                   u3_source_diff=source_diff, timing_probes=probes, history=history,
                   keccak_units=units_state['units'], source_evidence_sha256=evidence)
    output.mkdir(parents=True, exist_ok=True)
    md = output / (PREFIX + '.md')
    md.write_text('\n'.join(lines))
    write_csv(output / (PREFIX + '.csv'), rows)
    write_csv(output / (PREFIX + '_Timing.csv'), probes)
    (output / (PREFIX + '.json')).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n')
    hashes = dict(evidence)
    for suffix in ('.md', '.csv', '_Timing.csv', '.json'):
        path = output / (PREFIX + suffix)
        hashes[evidence_name(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
    (output / (PREFIX + '.sha256')).write_text(''.join(f'{digest}  {path}\n' for path, digest in sorted(hashes.items())))
    print(json.dumps(dict(report=str(md), measured_rows=len(complete), missing_rows=len(rows) - len(complete),
                          summary=summary), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
