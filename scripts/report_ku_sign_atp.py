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
FREQUENCIES = {1: 150.0, 2: 110.0, 3: 67.0, 4: 48.0}
PREFIX = 'KU_Sign_ATP_' + '_'.join(f'{FREQUENCIES[u]:g}' for u in (1, 2, 3, 4))
PROFILES = ('slh_128f', 'slh_192f', 'slh_256f')
POINTS = [(k, u) for k in (1, 2, 3, 4) for u in (1, 2, 3, 4)]


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
    parser.add_argument('--current-area', type=Path,
                        default=MAIN / 'manifests/experiments/ku_sixteen_area_20261006_v1/results.json',
                        help='Optional current-RTL common-core synthesis results')
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
        tag = None if k == 3 else (f'ku_k{k}u{u}_v2' if u != 3 else ('signfixed_k2u3_50m_v1' if k == 2 else f'signscan_k{k}u3_v1'))
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

    full_top_dir = MAIN / 'manifests/experiments/ku_full_top_route_20261006_v1'
    full_top = {}
    full_top_status_path = full_top_dir / 'status.json'
    full_top_status = read(full_top_status_path) if full_top_status_path.exists() else {}
    if full_top_status:
        remember(full_top_status_path)
    for label in points:
        folder = full_top_dir / label
        result_path = folder / 'result.json'
        synth_path = folder / 'synth_result.json'
        if result_path.exists():
            full_top[label] = read(result_path)
            for name in ('synth_utilization.rpt', 'route_utilization.rpt',
                         'synth_hierarchical.rpt', 'route_hierarchical.rpt',
                         'timing_summary.rpt', 'check_timing.rpt', 'route_status.rpt'):
                report_path = folder / name
                if report_path.exists(): remember(report_path)
        elif synth_path.exists():
            full_top[label] = dict(area_synth=read(synth_path)['area'],
                                   area_route=None, final_frequency_mhz=None,
                                   timing_passed=False, status='synthesis_only')
            if (folder / 'synth_utilization.rpt').exists(): remember(folder / 'synth_utilization.rpt')

    current_area = None
    if args.current_area.exists():
        current_area = read(args.current_area.resolve())
        assert current_area['schema'] == 'mhbs.ku16_area.v1'
        assert set(current_area['points']) == set(points)
        area_dir = args.current_area.resolve().parent
        config = read(area_dir / 'config.json')
        assert hashlib.sha256((area_dir / 'config.json').read_bytes()).hexdigest() == current_area['config_sha256']
        for label, point in points.items():
            item = current_area['points'][label]
            assert (item['k'], item['u']) == (point['k'], point['u'])
            assert item['source_sha256'] == config['source_sha256']
            report_path = area_dir / label / 'core_utilization.rpt'
            assert hashlib.sha256(report_path.read_bytes()).hexdigest() == item['evidence_sha256']['core_utilization.rpt']
            assert resources(report_path, read) == item['area']
            point['historical_area'] = point['area']
            point['area'] = item['area']
            point['area_source'] = evidence_name(report_path)
            for name, expected_hash in item['evidence_sha256'].items():
                evidence_path = area_dir / label / name
                remember(evidence_path)
                assert evidence[evidence_name(evidence_path)] == expected_hash
        for path in (area_dir / 'snapshot').rglob('*'):
            if path.is_file():
                remember(path)

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
                       measurement_status=('当前源码实测面积/历史周期；指定频率估算' if current_area else '实测面积/周期；指定频率估算') if case else '缺少面积/周期' if area is None else '缺少该参数集周期',
                       output_sha256=case['output_sha256'] if case else None,
                       source_tag=point['tag'], snapshot_sha256=point['inputs']['snapshot_sha256'] if point['inputs'] else None,
                       area_source=point.get('area_source'))
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
    coverage_description = (f'全部 {len(rows)} 行均有共同核综合面积；其中 {len(complete)} 行沿用原 K/U 仿真的周期、'
                            f'Hash 次数、置换次数和输出比对，K3 的 {len(rows)-len(complete)} 行没有功能或周期测量，ATP 填 `-`。'
                            if current_area else
                            f'{len(complete)} 行具有实测面积和计算周期，{len(rows)-len(complete)} 行缺数据并填 `-`。')
    pareto_scope = '十六点' if len(full_points) == 16 else f'{len(full_points)} 个具有周期的设计'
    pareto_missing_note = '' if len(full_points) == len(points) else 'K3 缺少完整三组周期数据，不纳入 Pareto 判定。'
    lines = [f'# K/U Sign 面积时间积报告：{frequency_title} MHz', '',
             f'统计时间：{generated}。本报告是指定频率下的估算结果及实测证据快照。', '',
             '## 1. 目的与范围', '',
             '比较 K∈{1,2,3,4}、U∈{1,2,3,4} 的十六个综合配置，在 128f、192f、256f Sign 下的面积。'
             '有历史周期的配置继续计算签名时间和 ATP；K3 仅有面积。本报告只分析 Sign。', '',
             f'指定工作频率：{frequency_description}。'
             '同一个 U 对所有 K 使用相同频率，这是比较条件，不代表所有设计均已完成该频率签核。', '',
             f'共有 {len(rows)} 行设计/参数集组合。{coverage_description}'
             '历史 U3 的 192f/256f 补测复用原实验源码、Program16 镜像及软件参考向量；计算周期来自当时仿真。', '',
             '## 2. 计算口径', '',
             '- 器件：`xc7a200tffg1156-3`；综合/布线：Vivado 2025.2；共同核综合采用 10 ns 约束。',
             '- 基线：Program16 镜像、ABI、软件参考向量；仅统计计算周期，不包含装载消息、输入输出传输及启动开销。',
             '- 主表面积采用共同核综合面积，保证所有已有设计使用同一面积口径。外壳综合面积及对应估算 ATP 另存 CSV；'
             '尚未综合的 U3 192f/256f 外壳资源仍为 `-`，不影响主表的共同核 ATP 计算。',
             '- 共同核面积不包含 `mhbs_signature_store`。其独立综合为 11 RAMB36E1 + 1 RAMB18E1，'
             '即 11.5 BRAM36 等效（见 [签名缓存报告](../report/Signature_Storage.md)）；完整顶层还需计入 ROM 和外壳逻辑。'
             '下文指定 MHz 只是估算条件，不是本次十六点完整顶层的布线最终频率。',
             *(['- 本次按 U1→U4 四批、每批 K1～K4 并行，重新综合十六个共同核。'
                'K2 控制器取自当前 RTL；K1/K3/K4 控制器取自历史 K 参数化版本并连接当前数据通路，K3 增加三路端点存储。'
                'K1/K3/K4 不是当前生产 RTL 的直接实例，且未重新做功能验证。',
                '- 签名周期沿用原 K1/K2/K4 实验；K3 周期与 ATP 无有效数据。'
                '完整顶层的 128f Sign 布线结果单列于下表；指定频率估算不构成所有配置的时序签核。'
                'CSV 的外壳综合面积仍为历史数值。'] if current_area else []),
             '- 等效 Slice = LUT/4 + FF/8 + BRAM36×232.4 + DSP×102.4。LUTRAM 已包含在 LUT 中，不重复相加。'
             '等效 Slice 是资源换算指标，不是 Vivado 实际占用 Slice 数。',
             '- 签名时间（ms）= 计算周期 /（指定频率 MHz × 1000）。',
             '- 估算 ATP（Slice·ms）= 共同核综合等效 Slice × 估算签名时间。数值越小越好。',
             '- 布线实测 ATP = 对应档位的布线后等效 Slice × 该档位签名时间；仅通过签核的档位提供有效频率和实测 ATP。',
             '- 按用户最新要求，本报告判定通过的条件为：原目标周期下 Setup >0 ns、Hold ≥0、完整布线及 ROM 内容审计通过。'
             '外部接口排除在核内频率签核范围之外。',
             '- 后台旧档的原始日志与状态保留；报告按上述判据重新检查已完成档位，CSV/JSON 同时保留原始状态。',
             '- 以下固定频率排序不能代替最终布线排序，K 的变化也可能改变可达到的频率。', '',
             '## 3. 共同核面积与数据覆盖', '',
             '| K/U | LUT | FF | LUTRAM | BRAM36 | DSP | 共同核等效 Slice | 指定 MHz | 周期 ns | 已验证 Sign 参数集 |',
             '|---|---:|---:|---:|---:|---:|---:|---:|---:|---|']
    for label, point in points.items():
        area = point['area'] or {}
        coverage = '、'.join(p.replace('slh_', '') for p in PROFILES if p + '_sign' in point['simulation']) or '-'
        lines.append('| ' + ' | '.join([label, *[fmt(area.get(key), 0) for key in ('lut', 'ff', 'lutram', 'bram36', 'dsp')],
                                       fmt(area.get('equivalent_slice')), fmt(point['frequency_mhz']),
                                       fmt(1000 / point['frequency_mhz'], 6), coverage]) + ' |')
    lines += ['', '### 完整顶层：128f Sign（含签名缓存）', '',
              '下表面积包含共同核、Program/Template/Descriptor ROM、外壳及 `mhbs_signature_store`。'
              '原目标达标按目标周期下 Setup >0 ns 判断；布线最终 MHz 是同一已布线设计重新约束到约 0.05 ns Setup 余量的结果，并非在该周期重新布线。'
              '最终 MHz 仅在新布线完整、Setup >0、Hold ≥0、DRC 无错误及核内约束检查通过时填写。'
              '该频率只覆盖 128f Sign 核内路径，外部接口未签核；K3 的功能尚未验证。', '',
              f'当前后台状态：{full_top_status.get("status", "-")}；已完成 '
              f'{sum(v == "complete" for v in full_top_status.get("points", {}).values())}/16 点。', '',
              '| K/U | 综合 LUT | FF | LUTRAM | BRAM36 等效 | DSP | 综合等效 Slice | 布线等效 Slice | 原目标 Setup ns | 原目标达标 | 布线最终 MHz | Setup ns | Hold ns | 128f 布线 ATP Slice·ms | 状态 |',
              '|---|---:|---:|---:|---:|---:|---:|---:|---:|---|---:|---:|---:|---:|---|']
    for label in points:
        item = full_top.get(label, {})
        synth = item.get('area_synth') or {}
        route = item.get('area_route') or {}
        timing = item.get('timing') or {}
        freq = item.get('final_frequency_mhz') if item.get('timing_passed') else None
        target_wns = timing.get('initial_wns_ns')
        target_pass = '是' if freq and target_wns is not None and target_wns > 0 else '否' if target_wns is not None else '-'
        cycles = points[label]['simulation'].get('slh_128f_sign', {}).get('sign_cycles')
        atp = route.get('equivalent_slice') * cycles / (freq * 1000) if freq and cycles else None
        status = ('通过' if freq else '布线未通过' if item.get('area_route') else
                  '仅综合' if synth else '待完成')
        if full_top_status.get('points', {}).get(label) == 'stopped':
            status = '已停止（仅综合）' if synth else '已停止'
        elif full_top_status.get('status') == 'stopped' and status == '待完成':
            status = '未启动（已停止）'
        lines.append('| ' + ' | '.join([label, *[fmt(synth.get(key), 0) for key in ('lut','ff','lutram')],
                                        fmt(synth.get('bram36'), 1), fmt(synth.get('dsp'), 0),
                                        fmt(synth.get('equivalent_slice')), fmt(route.get('equivalent_slice')),
                                        fmt(target_wns), target_pass, fmt(freq), fmt(timing.get('final_wns_ns')),
                                        fmt(timing.get('final_whs_ns')), fmt(atp), status]) + ' |')
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
    lines += ['', '在指定频率和共同核综合面积条件下，仅对有历史周期的 K1/K2/K4 设计，三个参数集的最低估算 ATP 分别为：'
              + '、'.join(f'{r["profile_operation"]} {r["best_atp_point"]}' for r in summary) + '。'
              '这些是指定频率下的估算，其他 K 及参数集尚未完成对应频率签核。', '',
              '固定频率下，增加 U 会减少计算周期，同时降低指定频率并增加面积，因此 ATP 并不随 U 单调下降。'
              '增大 K 的并行收益需要与新增 Hash lane 面积一起比较。', '',
              f'以共同核面积及三组指定频率下的签名时间判断支配关系，{pareto_scope}中 Pareto 前沿为：'
              + '、'.join(pareto) + '。' + pareto_missing_note, '',
              '## 6. 指定频率的布线验证与实测 ATP', '',
              '下表只展示历史 128f Sign 的对应指定频率证据。K1/K3/K4 的这些目标频率尚未验证；'
              'K2 的历史通过记录也不能签核本次重新综合的 RTL。192f/256f 未完成对应目标频率扫描。'
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
    lines += ['', '历史 K2U1 150 MHz、K2U2 110 MHz、K2U3 67 MHz、K2U4 48 MHz 已按原目标周期通过。'
              '各自的 Setup/Hold 及布线后面积列于上表，不能作为本次新综合源码的频率签核。', '',
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
              f'- 原实验已有的 {len(complete)} 组 Sign 仿真输出、Hash 次数、置换次数均与软件参考/Program16 基线一致。'
              + ('本次当前 RTL 仅重综合，尚未重新验证这些周期与输出。' if current_area else ''),
              '- 原 K1/K2/K4 实验使用同一源码快照。U3 版仅扩展 `mhbs_hbs.sv` 的合法 U 参数检查，Hash 数据通路未改变；'
              '已逐字比较两个封存文件，Program16 镜像哈希和软件门禁哈希一致。JSON 保存历史源码差异及各点快照哈希。',
              '- 参数化 K2U2 的三组 Sign 计算周期与封存 Program16 一致：729983、1249491、2579236。',
              f'- 历史 Program16 共同核等效 Slice 为 {baseline_area["equivalent_slice"]:.3f}；本次 K2U2 为 '
              f'{points["K2U2"]["area"]["equivalent_slice"]:.3f}，变化 '
              f'{points["K2U2"]["area"]["equivalent_slice"] - baseline_area["equivalent_slice"]:.3f}'
              f'（{(points["K2U2"]["area"]["equivalent_slice"] / baseline_area["equivalent_slice"] - 1)*100:.2f}%）。'
              '该面积变化单独列出，不将历史基线面积混入 K/U 排序。',
              '- 当前可核对的 Keccak U1/U2/U3/U4 单元运行状态见 JSON；原九点端点存储、Verify、复位及统计关闭回归证据见九点封存记录。', '',
              *(['- 当前共同核综合源码及各点原始资源报告见 '
                 f'[新面积归档]({link(args.current_area.resolve().parent)})。历史面积也保存在 JSON 的 `historical_area` 中。', '']
                if current_area else []),
              '## 10. 文件与复现', '',
              f'- [全部数据 CSV]({PREFIX}.csv)：{len(rows)} 行；K3 缺少周期与 ATP，外壳综合面积是历史数据。',
              f'- [全部档位 CSV]({PREFIX}_Timing.csv)：包含全部新时序尝试、失败原因和证据目录。',
              f'- [原始数据与证据 JSON]({PREFIX}.json)：实测资源/周期、源码快照、输出哈希、频率条件、历史对照和状态快照。',
              f'- [完整顶层综合与布线归档]({link(full_top_dir)}): 128f Sign 各点的签名缓存、布线面积与最终核内频率证据。',
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
                   current_area_source=evidence_name(args.current_area.resolve()) if current_area else None,
                   summary=summary, pareto_points=pareto, pareto_considered_points=full_points,
                   points=points, baseline_area=baseline_area,
                   u3_source_diff=source_diff, timing_probes=probes, history=history,
                   keccak_units=units_state['units'], full_top_128f=full_top,
                   full_top_status=full_top_status,
                   source_evidence_sha256=evidence)
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
