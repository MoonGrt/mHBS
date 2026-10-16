#!/usr/bin/env python3
"""Compare frozen SHAKE timing candidates without starting or stopping hardware jobs.

The optional watcher republishes the report every 30 seconds. It rebuilds the
latest archive's checksum index only after all measured runners finish their
final archive publication. Neither RTL nor the experiment INDEX is changed.
"""
import argparse
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import time
from zoneinfo import ZoneInfo

import experiment_archive as archive


ROOT = Path(os.environ.get('MHBS_SHAKE_TIMING_WORKSPACE',
                          Path(__file__).resolve().parents[1])).resolve()
RUNS = (
    ('baseline_20261019_211532', 'B0', '当前基线'),
    ('baseline_20261019_211543', 'B0r', '同源基线重复综合'),
    ('candidate_20261019_211536', 'C1', '统一输入寄存器；中间级取消 reset 数据使能'),
    ('candidate_20261019_211601', 'C2', 'C1＋末级前一拍预读上下文'),
    ('candidate_20261019_211718', 'C3', 'C2＋流式窗口与填充间寄存器'),
    ('candidate_20261019_211827', 'C4', '保留上下文预读及流式级；撤销统一输入级，按模式选择输入'),
    ('candidate_20261019_212211', 'C5', 'C4＋固定标量引擎由寄存的 FIXED_WAIT 所有权驱动'),
    ('candidate_20261019_212542', 'C6', 'C5＋FORS 目标相对索引提前登记，范围比较及父节点索引复用'),
    ('candidate_20261019_213301', 'C7', 'C6＋上下文控制预读、反馈预约和已保留槽位的直接 ready'),
)
CONFIGS = ('P12U1', 'P4U1')
PROFILES = ('slh_128f', 'xmss_h10', 'lms_h10')
OLD_REPORT = ('docs/manifests/experiments/single_lane_13_20261009_v4/reports/'
              'SLH_DSA_128f_sign_ATP_150_110.md')
OLD_ROUTE = ('docs/manifests/experiments/timing_targets_20261019_120529/jobs/'
             'P12U1_100MHz/route/timing.rpt')
LEGACY_REPORTS = (
    'docs/manifests/experiments/legacy_113648d7_pu_route_20261019_203925/'
    'reports/Legacy_PU_Route_20261019_203925.md',
    'docs/manifests/experiments/legacy_01486e3f_p12u1_route_20261019_200221/'
    'reports/Legacy_P12U1_Route_20261019_200221.md',
)


def now():
    return datetime.now(ZoneInfo('Asia/Singapore')).isoformat(timespec='seconds')


def read(path):
    path = Path(path)
    return json.loads(path.read_text()) if path.is_file() else {}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    archive.atomic(Path(path), json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def fmt(value, digits=3):
    return '—' if value is None else f'{value:,.{digits}f}'


def delta(old, new):
    return None if old is None or new is None or old <= 0 else 100 * (new / old - 1)


def evidence(path):
    path = Path(path)
    return dict(path=str(path), exists=path.is_file(),
                sha256=sha(path) if path.is_file() else None)


def historical_evidence():
    report, routed = ROOT / OLD_REPORT, ROOT / OLD_ROUTE
    original = report.read_text() if report.is_file() else ''
    text = routed.read_text() if routed.is_file() else ''
    critical = re.search(r'Data Path Delay:\s+([\d.]+)ns.*?route\s+([\d.]+)ns\s+'
                         r'\(([\d.]+)%\).*?Logic Levels:\s+(\d+)', text, re.S)
    sources = re.findall(r'^\s*Source:\s*(.+)$', text, re.M)
    destinations = re.findall(r'^\s*Destination:\s*(.+)$', text, re.M)
    return dict(
        original_slh_report=evidence(report),
        original_report_explicitly_assumed_frequency=(
            'U1 假定 150 MHz' in original and '频率未经布线验证' in original),
        original_report_routing_performed=False if '不布局布线' in original else None,
        original_p12_100mhz_routed_report=evidence(routed),
        original_routed_critical_path=dict(
            data_path_ns=float(critical[1]) if critical else None,
            route_ns=float(critical[2]) if critical else None,
            route_share_pct=float(critical[3]) if critical else None,
            logic_levels=int(critical[4]) if critical else None,
            source=sources[0] if sources else None,
            destination=destinations[0] if destinations else None),
        user_referenced_legacy_reports=[evidence(ROOT / p) for p in LEGACY_REPORTS],
        scope='Available frozen reports only; unavailable legacy reports cannot substantiate historical routing closure.')


def run_specs(run_root):
    """Keep curated labels while picking up subsequent frozen timing candidates."""
    specs = list(RUNS)
    names = {name for name, _, _ in specs}
    extra = []
    for path in run_root.glob('candidate_*/SOURCE.json'):
        if path.parent.name in names:
            continue
        meta = read(path)
        if meta.get('schema') == 'shake_timing_optimization_v1' and meta.get('hash_backend') == 'shake':
            extra.append((meta.get('run_id', ''), path.parent.name))
    for number, (_, name) in enumerate(sorted(extra), start=8):
        specs.append((name, f'C{number}', '后续冻结候选；具体改动见该轮源码及报告'))
    return specs


def load_runs(run_root):
    results = []
    for name, label, description in run_specs(run_root):
        run = run_root / name
        manifest = run / 'SOURCE.json'
        meta, state = read(manifest), read(run / 'status.json')
        if meta and (meta.get('hash_backend') != 'shake' or meta.get('top') != 'common'):
            raise ValueError(f'Unexpected measured backend/top: {manifest}')
        frozen = Path(meta['source_root']) if meta else None
        rtl = {p: digest for p, digest in meta.get('sha256', {}).items() if p.startswith('rtl/')}
        mismatches = [p for p, digest in rtl.items()
                      if not (frozen / p).is_file() or sha(frozen / p) != digest]
        results.append(dict(name=name, label=label, description=description, directory=str(run),
            archive_directory=meta.get('archive_directory'),
            source_manifest=evidence(manifest), frozen_rtl_sha256=rtl,
            frozen_rtl_unchanged=bool(rtl) and not mismatches, frozen_rtl_mismatches=mismatches,
            complete=state.get('complete', False), counts=state.get('counts', {}),
            source_unchanged=state.get('source_unchanged'),
            synthesis_period_ns=meta.get('synthesis_period_ns'),
            route_requested=meta.get('route_requested'),
            route_frequency_mhz=meta.get('route_frequency_mhz'),
            tools=meta.get('tool_versions', {}), part=meta.get('part'),
            tests=state.get('tests', {}), synthesis=state.get('synthesis', {}),
            routing=state.get('routing', {}), updated_at=state.get('updated_at')))
    return results


def external_timing(run):
    """Bind an explicitly launched target matrix to its measured candidate."""
    pointer = Path(run['directory']) / 'EXTERNAL_TIMING_RUN.json'
    if not pointer.is_file() and run['archive_directory']:
        pointer = Path(run['archive_directory']) / 'EXTERNAL_TIMING_RUN.json'
    expected = run['label'] == 'C7'
    if not pointer.is_file():
        return (dict(label=run['label'], pointer=evidence(pointer), complete=False,
                     archive_complete=False, expected=True, tasks={}, source_bound=False)
                if expected else None)
    spec = read(pointer)
    directory = spec.get('run_root', spec.get('root'))
    if not directory:
        return dict(label=run['label'], pointer=evidence(pointer), complete=False,
                    archive_complete=False, expected=expected, tasks={}, source_bound=False,
                    error='Pointer has no run_root/root')
    folder = Path(directory)
    if not folder.is_absolute():
        folder = ROOT / folder
    manifest = folder / 'SOURCE.json'
    meta, state = read(manifest), read(folder / 'status.json')
    candidate = read(Path(run['directory']) / 'SOURCE.json')
    wanted = {p: digest for p, digest in candidate.get('sha256', {}).items()
              if p.startswith('rtl/') or p == 'sources.txt'}
    mismatches = [p for p, digest in wanted.items() if meta.get('sha256', {}).get(p) != digest]
    frozen = Path(meta['source_root']) if meta.get('source_root') else None
    mismatches += [f'frozen:{p}' for p, digest in wanted.items()
                   if frozen is None or not (frozen / p).is_file() or sha(frozen / p) != digest]
    manifest_evidence = evidence(manifest)
    pointer_match = spec.get('source_manifest_sha256') == manifest_evidence['sha256']
    validation_match = (meta.get('validation_source_manifest_sha256') ==
                        run['source_manifest']['sha256'])
    bound = (len([p for p in wanted if p.startswith('rtl/')]) == 10 and not mismatches and
             pointer_match and validation_match and meta.get('hash_backend') == 'shake' and
             meta.get('top') == 'common' and meta.get('part') == run['part'])
    out = Path(meta.get('archive_directory', spec.get('archive_directory', folder)))
    return dict(label=run['label'], pointer=evidence(pointer), directory=str(folder),
        archive_directory=str(out), report=spec.get('report'), source_manifest=manifest_evidence,
        candidate_source_manifest_sha256=run['source_manifest']['sha256'],
        source_bound=bound, source_mismatches=mismatches, pointer_manifest_match=pointer_match,
        validation_manifest_match=validation_match, rtl_files_compared=10,
        sources_txt_compared='sources.txt' in wanted, complete=state.get('complete', False),
        archive_complete=read(out / 'ARTIFACTS.json').get('complete', False),
        expected=expected, targets=meta.get('targets', spec.get('targets', [])),
        tasks=state.get('tasks', {}), updated_at=state.get('updated_at'))


def external_closed_atp(matrices, rows):
    """Only publish times/ATP for verified, source-bound, fully closed targets."""
    closed = []
    for matrix in matrices:
        for name, task in matrix['tasks'].items():
            result = task.get('result', {})
            period = result.get('actual_period_ns')
            target = task.get('target_frequency_mhz')
            match = re.match(r'^(P\d+U\d+)', name)
            area = task.get('routed_area', {}).get('equivalent_slice')
            accepted = (matrix['source_bound'] and task.get('status') == 'passed' and
                        task.get('meets_target') is True and result.get('setup_hold_met') is True and
                        result.get('drc_errors') == 0 and task.get('route_status', {}).get('passed') is True and
                        period is not None and period > 0 and target is not None and
                        period <= 1000 / target + 1e-6 and area is not None and match is not None)
            if not accepted:
                continue
            for row in rows:
                if (row['label'] == matrix['label'] and row['configuration'] == match[1] and
                        row['status'] == 'passed' and row['workload_equal'] is True and
                        row['output_and_signature_cache_checked_bytewise'] is True):
                    closed.append(dict(label=row['label'], task=name, configuration=match[1],
                        profile=row['profile'], target_frequency_mhz=target,
                        closed_target_frequency_mhz=1000 / period, routed_equivalent_slice=area,
                        cycles=row['cycles'], routed_time_ms=row['cycles'] * period / 1e6,
                        routed_atp_slice_ms=area * row['cycles'] * period / 1e6))
    return closed


def summarize_validation(run_root, runs):
    summaries = []
    for path in sorted((run_root / 'final_validation').rglob('VALIDATION.json')):
        data = read(path)
        source = Path(data.get('source_manifest', ''))
        bound = next((r for r in runs if str(Path(r['directory']) / 'SOURCE.json') == str(source)), None)
        summaries.append(dict(summary=evidence(path), candidate_run=data.get('candidate_run'),
            run_label=bound['label'] if bound else None, complete=data.get('complete'),
            status=data.get('status'), passed=data.get('passed'), failed=data.get('failed'),
            planned=data.get('total_planned', len(data.get('tests', []))), scope=data.get('scope'),
            source_unchanged=data.get('source_unchanged'),
            source_manifest_match=(bool(bound) and data.get('source_manifest_sha256') ==
                                   bound['source_manifest']['sha256']),
            detailed_logs_archived=False))
    return summaries


def comparisons(runs):
    baseline = runs[0]
    rows = []
    for run in runs:
        for cfg in CONFIGS:
            syn = run['synthesis'].get(cfg, {})
            old_syn = baseline['synthesis'].get(cfg, {})
            area, old_area = syn.get('area', {}), old_syn.get('area', {})
            route = run['routing'].get(cfg, {})
            for profile in PROFILES:
                key = f'{cfg}/{profile}'
                test, old = run['tests'].get(key, {}), baseline['tests'].get(key, {})
                measured = test.get('status') == old.get('status') == 'passed'
                match = ({k: test.get(k) is not None and test[k] == old.get(k)
                          for k in ('hashes', 'permutations', 'vectors_sha256')} if measured else {})
                row = dict(run=run['name'], label=run['label'], configuration=cfg, profile=profile,
                    status=test.get('status', 'pending'), cycles=test.get('cycles'),
                    total_cycles=test.get('total_cycles'), baseline_cycles=old.get('cycles'),
                    cycles_change_pct=delta(old.get('cycles'), test.get('cycles')) if measured else None,
                    hashes=test.get('hashes'), permutations=test.get('permutations'),
                    workload_checks=match, workload_equal=all(match.values()) if match else None,
                    output_and_signature_cache_checked_bytewise=test.get('output_and_signature_cache_checked_bytewise'),
                    equivalent_slice=area.get('equivalent_slice'),
                    area_change_pct=delta(old_area.get('equivalent_slice'), area.get('equivalent_slice')),
                    vectors_sha256=test.get('vectors_sha256'),
                    simulation_seconds=test.get('simulation_seconds'))
                # These are explicitly named assumptions, never measured Fmax or acceptance ATP.
                if test.get('status') == syn.get('status') == 'passed':
                    row['assumed_100mhz_time_ms'] = test['cycles'] / 100000
                    row['diagnostic_assumed_100mhz_atp_slice_ms'] = (
                        area['equivalent_slice'] * test['cycles'] / 100000)
                if test.get('status') == route.get('status') == 'passed':
                    period = route.get('result', {}).get('actual_period_ns')
                    routed_area = route.get('area', {}).get('equivalent_slice')
                    if period and routed_area is not None:
                        row.update(closed_target_frequency_mhz=1000 / period,
                            routed_time_ms=test['cycles'] * period / 1e6,
                            routed_atp_slice_ms=routed_area * test['cycles'] * period / 1e6)
                rows.append(row)
    return rows


def render(run_root, prefix):
    runs = load_runs(run_root)
    rows = comparisons(runs)
    history = historical_evidence()
    matrices = [value for run in runs if (value := external_timing(run)) is not None]
    external_atp = external_closed_atp(matrices, rows)
    all_complete = all(r['complete'] for r in runs) and all(m['complete'] for m in matrices)
    current_rtl = {p: sha(ROOT / p) if (ROOT / p).is_file() else None
                   for p in runs[-1]['frozen_rtl_sha256']}
    workspace_matches = [run['label'] for run in runs if current_rtl == run['frozen_rtl_sha256']]
    c7 = next((run for run in runs if run['label'] == 'C7'), None)
    c7_route = next((m for m in matrices if m['label'] == 'C7'), {})
    selection = ('functional_candidate_pending_routed_results' if not c7_route.get('complete') else
                 'functional_candidate_routed_results_available_pending_review')
    data = dict(schema='mhbs.shake_timing.architecture_comparison.v1', updated_at=now(),
        all_runs_complete=all_complete, candidate_selection=selection,
        candidate_selection_note='No automatic RTL selection. Wait for routed setup/hold, complete routing and DRC evidence.',
        current_workspace_rtl_sha256=current_rtl, current_workspace_matches=workspace_matches,
        current_workspace_matches_c7='C7' in workspace_matches,
        current_candidate=read(Path(c7['directory']) / 'CURRENT_CANDIDATE.json') if c7 else {},
        measurement_scope='SHAKE common OOC, xc7a200tffg1156-3; generic Keccak; no new false/multicycle paths.',
        diagnostic_warning='100 MHz synthesis paths and assumed ATP are diagnostic, not routed Fmax or ATP acceptance.',
        history=history, runs=runs, comparisons=rows,
        external_timing_matrices=matrices, external_closed_target_atp=external_atp,
        validation_summaries=summarize_validation(run_root, runs), detailed_simulation_logs_archived=False)
    lines = ['# SHAKE P12U1／P4U1 时序架构对照', '',
        f'更新时间：{data["updated_at"]}；{len(runs)} 轮测量：' + ('全部结束。' if all_complete else '后台继续运行。'), '',
        'C7 保留为功能验证通过的当前候选，频率与最终 ATP 结论等待独立布线。'
        '当前工作区 10 个 RTL SHA 与 C7 ' + ('全部一致。' if 'C7' in workspace_matches else '未全部一致，需复核。'), '',
        '报告不自动替换 RTL。100 MHz 综合用于面积和路径诊断，'
        '不能证明实际最高频率或 ATP 改善。150／130 MHz 布线另列，完整布通、DRC、setup／hold '
        '均通过才记录该目标下时间与 ATP；失败目标不能推导成较低频率已闭合。', '',
        '共同口径：SHAKE、单 Hash lane、common OOC、xc7a200tffg1156-3、通用 Keccak、'
        '默认时序驱动、每个 Vivado 两线程；无新增 false-path／multicycle。'
        '算法执行互斥，未引入 P/U 专用优化。h20 完整 Keygen／Sign 保持停止。', '',
        '| 阶段 | 冻结版本 | 内容 | Sign 通过 | 完成 |',
        '|---|---|---|---:|---|']
    for run in runs:
        lines.append(f'| {run["label"]} | `{run["name"]}` | {run["description"]} | '
                     f'{run["counts"].get("passed", 0)}/6 | {"是" if run["complete"] else "后台运行"} |')
    lines += ['', '## 关键路径与改动依据', '',
        '原 P12U1 的 100 MHz 实际布线最差内部路径为末级 tag→captured 上下文 RAM→'
        '固定块格式化→首轮 Keccak→第一级状态寄存器，9.884 ns、8 级，连线占 88.699%。'
        '其 tag→RAM 地址网扇出 178、连线 3.042 ns；瓶颈包含上下文选择和宽数据布局，'
        '并非仅有 Keccak 轮逻辑。原始证据见 '
        f'[100 MHz 布线报告]({ROOT / OLD_ROUTE}:225)。', '',
        'C1 在格式化与首轮之间加入弹性输入寄存器，并去掉中间无效数据流水级的 reset 使能；'
        '有效位及末级共享 sponge 的功能控制保留。C2 用倒数第二级 tag 提前读取上下文，'
        '使 key／digest／captured、地址和格式控制与最后一级置换结果对齐。C3 在流式窗口选择与填充间'
        '加入数据／控制寄存器，减少端点 RAM→窗口选择→填充的串联级数。C4 保留后两项，'
        '撤销额外统一输入级，通过 engine_mode 选择固定与流式状态，避免 request-valid 串入宽 mux。'
        'C5 将 engine_mode 中的标量分支改为已登记的 FIXED_WAIT 所有权，'
        '使首次请求的组合配方译码不再串入引擎 ready；scalar_bridge 仍负责初次请求字段选择。'
        'C6 提前登记 FORS 目标相对索引，并共用范围比较与父节点索引。'
        'C7 在数据预读之外同步预读 phase／format／iteration／node 控制，提前登记反馈预约；'
        'pending 已保留槽位的下游 ready 直接使用物理流水容量，去掉重复模式判断。'
        'C7 相对 C6 保持三个 Sign 周期，同时 P12 的诊断面积与路径下降；'
        'P4 诊断路径略降、面积略增，实际收益仍由布线 ATP 判定。'
        '各阶段是否有效由下列实测决定；失败或未完成阶段同样保留。', '',
        '## 面积与低频综合诊断', '',
        '面积均取各自配置的 common；等效 Slice=LUT/4＋FF/8＋232.4×BRAM36＋102.4×DSP。'
        '综合路径含未布局连线估计，不转换为 Fmax。', '',
        '| 阶段 | 配置 | LUT | FF | BRAM36 | Slice | 面积变化 % | 综合路径 ns | 级数 | 耗时 s | 状态 |',
        '|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|']
    for run in runs:
        for cfg in CONFIGS:
            syn = run['synthesis'].get(cfg, {})
            area, path = syn.get('area', {}), syn.get('timing', {})
            old = runs[0]['synthesis'].get(cfg, {}).get('area', {}).get('equivalent_slice')
            status = syn.get('status', 'pending') + ('；分析延后，进程继续' if syn.get('analysis_deferred') else '')
            values = [run['label'], cfg, fmt(area.get('lut'), 0), fmt(area.get('ff'), 0),
                fmt(area.get('bram36')), fmt(area.get('equivalent_slice')),
                fmt(delta(old, area.get('equivalent_slice'))), fmt(path.get('data_path_ns')),
                fmt(path.get('logic_levels'), 0), fmt(syn.get('elapsed_seconds')), status]
            lines.append('| ' + ' | '.join(values) + ' |')
    lines += ['', '| 阶段 | 配置 | 综合路径起点 | 综合路径终点 |', '|---|---|---|---|']
    for run in runs:
        for cfg in CONFIGS:
            path = run['synthesis'].get(cfg, {}).get('timing', {})
            lines.append(f'| {run["label"]} | {cfg} | `{path.get("source", "—")}` | '
                         f'`{path.get("destination", "—")}` |')
    for profile in PROFILES:
        lines += ['', f'## {profile} 完整 Sign', '',
            '| 阶段 | 配置 | 周期 | 相对 B0 % | Hash | 置换 | 相同工作量 | 输出／缓存逐字节 | 状态 |',
            '|---|---|---:|---:|---:|---:|---|---|---|']
        for row in rows:
            if row['profile'] != profile:
                continue
            boolean = lambda v: '—' if v is None else ('是' if v else '否')
            lines.append('| ' + ' | '.join([row['label'], row['configuration'], fmt(row['cycles'], 0),
                fmt(row['cycles_change_pct'], 6), fmt(row['hashes'], 0), fmt(row['permutations'], 0),
                boolean(row['workload_equal']), boolean(row['output_and_signature_cache_checked_bytewise']),
                row['status']]) + ' |')
    lines += ['', '相同工作量逐项要求 Hash、置换及全部 Sign 向量文件 SHA 与 B0 一致。'
        'JSON 保留未舍入周期、面积、SHA、假定 100 MHz 的诊断时间／ATP；'
        '这些假定值不作为布线 ATP 验收。', '', '## 150 MHz 布线', '',
        '| 阶段 | 配置 | 目标 MHz | 布线 Slice | WNS ns | WHS ns | DRC 错误 | 完整布通 | 状态 |',
        '|---|---|---:|---:|---:|---:|---:|---|---|']
    for run in runs:
        for cfg in CONFIGS:
            route = run['routing'].get(cfg, {})
            result = route.get('result', {})
            complete_route = route.get('route_status', {}).get('passed')
            lines.append('| ' + ' | '.join([run['label'], cfg, fmt(route.get('target_frequency_mhz')),
                fmt(route.get('area', {}).get('equivalent_slice')), fmt(result.get('wns_ns')),
                fmt(result.get('whs_ns')), fmt(result.get('drc_errors'), 0),
                '—' if complete_route is None else ('是' if complete_route else '否'),
                route.get('status', 'pending')]) + ' |')
    closed = [row for row in rows if 'routed_atp_slice_ms' in row]
    lines += ['', '| 阶段 | 配置 | 算法 | 已闭合目标 MHz | Sign 时间 ms | 布线 ATP Slice·ms |',
        '|---|---|---|---:|---:|---:|']
    for row in closed:
        lines.append('| ' + ' | '.join([row['label'], row['configuration'], row['profile'],
            fmt(row['closed_target_frequency_mhz']), fmt(row['routed_time_ms'], 6),
            fmt(row['routed_atp_slice_ms'], 6)]) + ' |')
    if not closed:
        lines += ['| — | — | — | — | — | — |', '', '尚无本轮通过的完整布线结果，实际频率与 ATP 收益待验证。']
    lines += ['', '## C7 独立 150／130 MHz 四目标布线', '',
        '此矩阵由显式请求的独立 timing_targets 运行器执行，各目标重新综合并布局布线。'
        '报告逐文件复核其 10 个 RTL 及 sources.txt 与 C7 相同，并核对验证来源和冻结源码。'
        '只有对应目标完整布线、DRC、setup／hold 全部通过，才计算该目标下的实际时间与 ATP。', '',
        '| 阶段 | 目标 | 目标 MHz | 源码绑定 | 综合 Slice | 布线 Slice | WNS ns | WHS ns | DRC 错误 | 状态 |',
        '|---|---|---:|---|---:|---:|---:|---:|---:|---|']
    for matrix in matrices:
        if matrix.get('report'):
            lines += [f'| {matrix["label"]} | [独立矩阵报告]({matrix["report"]}) | — | '
                      f'{"匹配" if matrix["source_bound"] else "未确认"} | — | — | — | — | — | '
                      f'{"已结束" if matrix["complete"] else "后台运行"} |']
        for name, task in matrix['tasks'].items():
            result = task.get('result', {})
            lines.append('| ' + ' | '.join([matrix['label'], name,
                fmt(task.get('target_frequency_mhz')), '匹配' if matrix['source_bound'] else '未确认',
                fmt(task.get('synth_area', {}).get('equivalent_slice')),
                fmt(task.get('routed_area', {}).get('equivalent_slice')), fmt(result.get('wns_ns')),
                fmt(result.get('whs_ns')), fmt(result.get('drc_errors'), 0),
                task.get('status', 'pending')]) + ' |')
        if not matrix['tasks']:
            lines += [f'| {matrix["label"]} | 等待外部矩阵指针／状态 | — | 未确认 | — | — | — | — | — | pending |']
    lines += ['', '| 阶段 | 目标 | 算法 | 已闭合目标 MHz | Sign 时间 ms | 布线 ATP Slice·ms |',
        '|---|---|---|---:|---:|---:|']
    for row in external_atp:
        lines.append('| ' + ' | '.join([row['label'], row['task'], row['profile'],
            fmt(row['closed_target_frequency_mhz']), fmt(row['routed_time_ms'], 6),
            fmt(row['routed_atp_slice_ms'], 6)]) + ' |')
    if not external_atp:
        lines += ['| — | — | — | — | — | — |', '', 'C7 尚无已通过的四目标布线结果；不填实际频率或 ATP。']
    lines += ['', '## 验证与历史证据范围', '']
    for summary in data['validation_summaries']:
        label = summary['run_label'] or '未匹配冻结版本'
        lines.append(f'- {label}：额外验证 {summary["passed"]}/{summary["planned"]}，'
            f'状态 `{summary["status"]}`；冻结源码绑定 '
            f'{"匹配" if summary["source_manifest_match"] else "未确认"}。{summary["scope"] or ""}')
    lines += ['', '原始 SLH 13 点报告明确写明“不布局布线”和“U1 假定 150 MHz，频率未经布线验证”，'
        f'不能将其当作历史 150 MHz 布线通过证据。见 [原报告]({ROOT / OLD_REPORT}:5)。']
    for item in history['user_referenced_legacy_reports']:
        lines.append(f'- 用户引用的历史报告 `{Path(item["path"]).relative_to(ROOT)}`：'
            + ('当前可读取，内容与源码身份仍需独立复核。' if item['exists'] else
               '当前 checkout 中报告文件缺失；目录存在也不能代替布线证据。'))
    lines += ['', '本轮修改 SHAKE 执行路径及两后端共用的 FORS 控制；SHA2 配方保持原样，兼容性由对应冻结版本的新回归支持。'
        '各轮冻结 RTL、SOURCE.json、综合 hierarchical／timing／critical_paths 及布线日志留在各自实验目录。'
        '详细仿真日志保留 build，汇总归档不复制 sim／validation 日志。'
        '后台超过十分钟的综合只标记分析延后，报告程序不停止任何测量进程。', '']
    write(prefix.with_suffix('.json'), data)
    archive.atomic(prefix.with_suffix('.md'), '\n'.join(lines))
    return data


def archives_finished(data):
    runs_finished = all(r['complete'] and r['archive_directory'] and
        read(Path(r['archive_directory']) / 'ARTIFACTS.json').get('complete') for r in data['runs'])
    external_finished = all(m['complete'] and m['archive_complete']
                            for m in data['external_timing_matrices'])
    return runs_finished and external_finished


def finalize_artifacts(out):
    path = out / 'ARTIFACTS.json'
    value = read(path)
    if not value.get('complete'):
        raise RuntimeError('Latest runner has not completed final archive publication')
    value['sha256'] = {str(p.relative_to(out)): sha(p) for p in sorted(out.rglob('*'))
                      if p.is_file() and p.name != 'ARTIFACTS.json' and not p.name.endswith('.tmp')}
    value['comparison_report_finalized_at'] = now()
    value['comparison_report_status'] = 'finalized'
    value.pop('volatile_artifacts', None)
    write(path, value)


def refresh_immutable_artifacts(out, prefix):
    """Index completed measurement evidence while the comparison stays live."""
    path = out / 'ARTIFACTS.json'
    value = read(path)
    if not value.get('complete'):
        return
    volatile = {prefix.with_suffix('.md').resolve(), prefix.with_suffix('.json').resolve()}
    value['sha256'] = {str(p.relative_to(out)): sha(p) for p in sorted(out.rglob('*'))
                      if p.is_file() and p.name != 'ARTIFACTS.json' and not p.name.endswith('.tmp')
                      and p.resolve() not in volatile}
    value['volatile_artifacts'] = [str(p.relative_to(out)) for p in sorted(volatile)
                                   if p.is_relative_to(out)]
    value['comparison_report_status'] = 'live_external_routes_pending'
    value['immutable_evidence_index_updated_at'] = now()
    write(path, value)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-root', type=Path, default=ROOT / 'build/shake_timing_optimization')
    parser.add_argument('--output-prefix', type=Path)
    parser.add_argument('--watch', action='store_true')
    parser.add_argument('--interval', type=float, default=30,
                        help='Watcher refresh seconds, positive and no greater than 30')
    args = parser.parse_args()
    if not 0 < args.interval <= 30:
        parser.error('--interval must be positive and no greater than 30')
    root = args.run_root.resolve()
    latest = read(root / run_specs(root)[-1][0] / 'SOURCE.json')
    if not latest.get('archive_directory'):
        parser.error('Latest frozen run SOURCE.json is unavailable')
    out = Path(latest['archive_directory'])
    prefix = (args.output_prefix or out / 'reports/SHAKE_Timing_Architecture_20261019').resolve()
    own = Path(__file__).resolve()
    archive.copy_changed(own, out / 'analysis_tools' / own.name)
    indexed_immutable = False
    while True:
        data = render(root, prefix)
        if not indexed_immutable:
            refresh_immutable_artifacts(out, prefix)
            indexed_immutable = read(out / 'ARTIFACTS.json').get('complete', False)
        if archives_finished(data):
            # Runners atomically publish ARTIFACTS last. Confirm its final marker
            # before adding comparison-report checksums, without touching raw evidence.
            finalize_artifacts(out)
            print(json.dumps(dict(report=str(prefix.with_suffix('.md')), complete=True,
                                  candidate_selection=data['candidate_selection']), ensure_ascii=False))
            return 0
        if not args.watch:
            print(json.dumps(dict(report=str(prefix.with_suffix('.md')), complete=False,
                                  candidate_selection=data['candidate_selection']), ensure_ascii=False))
            return 0
        time.sleep(args.interval)


if __name__ == '__main__':
    raise SystemExit(main())
