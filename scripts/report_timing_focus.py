#!/usr/bin/env python3
"""Track frozen timing candidates and explicitly requested common-OOC routing."""
import argparse
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import time
from zoneinfo import ZoneInfo
import experiment_archive as archive_module
from experiment_archive import atomic, copy_changed, index, pack_rtl

ROOT = Path(os.environ.get('MHBS_TIMING_WORKSPACE', Path(__file__).resolve().parents[1])).resolve()
archive_module.ROOT = ROOT
archive_module.ARCHIVES = ROOT/'docs/manifests/experiments'
CONFIGS = ('P1U1', 'P4U1', 'P4U2', 'P12U1')
PROFILES = ('slh_128f', 'xmss_h10', 'lms_h10')


def read(path):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return {}


def stamp():
    return datetime.now(ZoneInfo('Asia/Singapore')).isoformat(timespec='seconds')


def timing(path):
    import re
    if not path.exists():
        return {}
    text = path.read_text()
    fields = {
        'wns_ns': r'Worst Slack\s+(-?[\d.]+)ns',
        'data_path_ns': r'Data Path Delay:\s+([\d.]+)ns',
        'logic_levels': r'Logic Levels:\s+(\d+)',
        'source': r'^  Source:\s+(.+)$',
        'destination': r'^  Destination:\s+(.+)$',
    }
    result = {}
    for key, expression in fields.items():
        match = re.search(expression, text, re.M)
        if match:
            result[key] = (match[1] if key in ('source', 'destination')
                           else int(match[1]) if key == 'logic_levels' else float(match[1]))
    return result


def fmt(value, precision=3):
    return '—' if value is None else f'{value:,.{precision}f}'


def change_pct(old, new):
    return None if old is None or new is None or old <= 0 else (new-old)/old*100


def compare_sign(meta, old, new, cfg, profile):
    comparable = old.get('status') == new.get('status') == 'passed'
    workload_equal = (all(new.get(k) is not None and new[k] == old.get(k)
                          for k in ('hashes', 'permutations')) if comparable else None)
    changes = {k: change_pct(old.get(k), new.get(k)) for k in ('cycles', 'total_cycles')}
    measured = comparable and all(value is not None for value in changes.values())
    cycle_equal = all(new[k] == old[k] for k in changes) if measured else None
    cycle_allowed = (all((new[k]-old[k])*100 <= old[k]*meta.get('max_cycle_increase_pct', 5.0)
                         for k in changes) if meta.get('allow_cycle_changes', False)
                     else cycle_equal) if measured else None
    return dict(configuration=cfg, profile=profile, status=new.get('status', 'pending'),
                workload_equal=workload_equal, cycle_equal=cycle_equal,
                cycle_budget_passed=cycle_allowed, cycle_change_pct=changes['cycles'],
                total_cycle_change_pct=changes['total_cycles'], baseline_cycles=old.get('cycles'),
                cycles=new.get('cycles'), hashes=new.get('hashes'), permutations=new.get('permutations'))


def publish(run):
    meta = read(run/'EXPERIMENT.json')
    out = ROOT/'docs/manifests/experiments'/meta['experiment']
    report_name = meta.get('report_name', 'Timing_Focus_P1_P4_P12_20261015')
    if Path(report_name).name != report_name:
        raise ValueError('report_name must be a filename stem within this experiment reports directory')
    prefix = out/'reports'/report_name
    baseline = Path(meta['baseline_run'])
    base = read(baseline/'status.json')
    base_route = read(Path(meta['baseline_route'])/'status.json') if meta.get('baseline_route') else {}
    result = dict(updated_at=stamp(), baseline_run=str(baseline), baseline_route=meta.get('baseline_route'),
                  scope='common OOC, xc7a200tffg1156-3, generic Keccak, two Vivado threads',
                  acceptance='Byte-identical outputs/signature cache; exact hashes/permutations; separate cycle/area budgets; routed setup/hold and ATP',
                  allow_cycle_changes=meta.get('allow_cycle_changes', False),
                  max_cycle_increase_pct=meta.get('max_cycle_increase_pct', 5.0) if meta.get('allow_cycle_changes', False) else 0.0,
                  max_area_increase_pct=meta.get('max_area_increase_pct'),
                  route_max_implementations=meta.get('route_max_implementations', 6),
                  candidate_rtl_is_provisional=True, h20_full_keygen_sign_run=False, stages=[])
    result['validation'] = {p.stem: read(p) for p in (run/'validation').glob('*.json')}
    for cfg in CONFIGS:
        for path in (baseline/'synth'/cfg/'common').glob('*'):
            if path.is_file() and path.suffix in ('.rpt', '.log', '.json', '.txt'):
                copy_changed(path, run/'baseline/synth'/cfg/'common'/path.name)
    for path in (run/'baseline').rglob('*'):
        if (path.is_file() and 'source' not in path.relative_to(run/'baseline').parts
                and path.suffix in ('.rpt', '.log', '.json', '.txt', '.tcl')):
            copy_changed(path, out/path.relative_to(run))
    atomic(out/'VALIDATION_SUMMARY.json', json.dumps(result['validation'], ensure_ascii=False, indent=2)+'\n')
    current = meta['stages'][-1]
    current_source = read(Path(current['run'])/'SOURCE.json')
    current_hashes = {name: value for name, value in current_source.get('sha256', {}).items()
                      if name.startswith('rtl/')}
    result['working_candidate'] = current['name']
    result['working_rtl_matches_candidate'] = bool(current_hashes) and all(
        (ROOT/name).exists() and hashlib.sha256((ROOT/name).read_bytes()).hexdigest() == value
        for name, value in current_hashes.items())
    cycle_policy = (f'周期与总周期增幅各不超过 {result["max_cycle_increase_pct"]:g}%，独立报告变化'
                    if result['allow_cycle_changes'] else '周期与总周期必须逐项相同')
    area_policy = (f'综合面积增幅警示线为 {result["max_area_increase_pct"]:g}%，超限单列并以实测时序/ATP取舍，不阻塞其他点布线'
                   if result['max_area_increase_pct'] is not None else '未指定综合面积增幅门限')
    lines = ['# P1U1 / P4U1 / P4U2 / P12U1 布线时序优化', '',
             f'更新时间：{result["updated_at"]}。本轮由用户明确授权布局布线；候选选择尚待实测。', '',
             f'工作区候选：`{current["name"]}`；与冻结 RTL 逐字节一致：`{result["working_rtl_matches_candidate"]}`。综合结果和布线结果分别报告。', '',
             '保持标准参数、单 Hash lane和模块接口。面积采用对应配置 common；使用通用 Keccak、同器件和默认时序驱动综合，不增加时序例外。综合约束沿用 6.666667 ns；布线起点 U1=150 MHz、U2=100 MHz。', '',
             f'验收预算：{cycle_policy}；{area_policy}。Hash/置换计数及逐字节输出必须一致；周期、面积超限属于性能预算问题，单独列出。', '',
             f'综合 WNS 只用于筛选，不能视为布线频率。本轮配置的基线及候选搜索预算均为最多 {result["route_max_implementations"]} 次独立实现，每轮做 0.1 ns STA 网格扫描并保留相邻失败证据；报告该搜索预算下实测闭合频率，不称全局最高频率。原长耗时综合继续后台，缺项保持空白，不借用其他配置。', '',
             '## 基线瓶颈', '',
             '| 配置 | 综合 WNS ns | 数据路径 ns | 逻辑级数 | 关键路径 |',
             '|---|---:|---:|---:|---|']
    baseline_rows = {}
    for cfg in CONFIGS:
        t = timing(baseline/'synth'/cfg/'common/timing.rpt')
        baseline_rows[cfg] = t
        label = ('`' + t.get('source', '—').replace('|', '\\|') + '` → `'
                 + t.get('destination', '—').replace('|', '\\|') + '`') if t else '尚无时序报告'
        lines.append(f'| {cfg} | {fmt(t.get("wns_ns"))} | {fmt(t.get("data_path_ns"))} | {fmt(t.get("logic_levels"),0)} | {label} |')
    lines += ['', '上述关键路径直接提取自本轮冻结基线的综合 timing.rpt；未完成项留空，不沿用其他候选的路径归因。', '',
              '## 候选与功能验证', '']
    for stage in meta['stages']:
        candidate = Path(stage['run'])
        state = read(candidate/'status.json')
        frozen_meta = read(candidate/'SOURCE.json')
        route = read(Path(stage['route'])/'status.json') if stage.get('route') else {}
        validation = []
        for cfg in CONFIGS:
            for profile in PROFILES:
                key = f'sim/{cfg}/{profile}'
                old, new = base.get('tasks', {}).get(key, {}), state.get('tasks', {}).get(key, {})
                validation.append(compare_sign(meta, old, new, cfg, profile))
        data = dict(name=stage['name'], run=str(candidate), route=stage.get('route'),
                    automatic_routing_status=stage.get('automatic_routing_status'),
                    description=stage['description'], counts=state.get('counts', {}), validation=validation,
                    functional_sign_cases=sum(v['workload_equal'] is True for v in validation),
                    exact_sign_cases=sum(v['workload_equal'] is True and v['cycle_equal'] is True for v in validation),
                    cycle_budget_cases=sum(v['cycle_budget_passed'] is True for v in validation),
                    functional_regression=any(v['status'] == 'failed' or v['workload_equal'] is False for v in validation),
                    cycle_budget_exceeded=any(v['cycle_budget_passed'] is False for v in validation),
                    synthesis={}, routing=route.get('tasks', {}), route_results=route.get('results', []))
        lines += [f'### {stage["name"]}', '', stage['description'], '',
                  f'逐字节输出、签名缓存及Hash/置换工作量核对：{data["functional_sign_cases"]}/12 项通过；周期完全相同 {data["exact_sign_cases"]}/12 项，满足周期预算 {data["cycle_budget_cases"]}/12 项。状态：`{data["counts"]}`。', '']
        if data['functional_regression']:
            lines += ['**功能或Hash/置换工作量检查失败，本候选不得用于最终验收。**', '']
        if data['cycle_budget_exceeded']:
            lines += ['**周期预算超限：自动布线门禁不通过；此项单独列为性能问题。**', '']
        stage_out = out/'candidates'/stage['name']
        if frozen_meta:
            pack_rtl(Path(frozen_meta['source_root']), stage_out/'rtl.tar.gz', frozen_meta['sha256'])
            copy_changed(candidate/'SOURCE.json', stage_out/'SOURCE.json')
            for path in (candidate/'synth').rglob('*'):
                if path.is_file() and path.suffix in ('.rpt', '.log', '.json', '.txt') and '.Xil' not in path.parts:
                    copy_changed(path, stage_out/path.relative_to(candidate))
        for cfg in CONFIGS:
            task = state.get('tasks', {}).get(f'synth/{cfg}/common', {})
            t = timing(candidate/'synth'/cfg/'common/timing.rpt')
            old_area = base.get('tasks', {}).get(f'synth/{cfg}/common', {}).get('area') or {}
            old_status = base.get('tasks', {}).get(f'synth/{cfg}/common', {}).get('status')
            old_slice = old_area.get('equivalent_slice') if old_status == 'passed' else None
            new_slice = (task.get('area') or {}).get('equivalent_slice') if task.get('status') == 'passed' else None
            area_change = change_pct(old_slice, new_slice)
            area_limit = result['max_area_increase_pct']
            area_allowed = ((new_slice-old_slice)*100 <= old_slice*area_limit
                            if area_change is not None and area_limit is not None else None)
            data['synthesis'][cfg] = dict(status=task.get('status', 'pending'),
                                           analysis_deferred=task.get('analysis_deferred', False),
                                           seconds=task.get('seconds'), area=task.get('area'), timing=t,
                                           area_change_pct=area_change, area_budget_passed=area_allowed)
        data['area_budget_exceeded'] = any(t['area_budget_passed'] is False for t in data['synthesis'].values())
        if data['area_budget_exceeded']:
            lines += ['**综合面积预算超限：此项单独警示，不阻塞布线；最终结合实测时序和ATP取舍。**', '']
        result['stages'].append(data)
    lines += ['## 综合对照', '',
              '| 候选 | 配置 | 等效 Slice | 面积变化 | WNS ns | WNS 改善 ns | 级数 | 综合耗时 s | 状态 |',
              '|---|---|---:|---:|---:|---:|---:|---:|---|']
    for stage in result['stages']:
        for cfg, task in stage['synthesis'].items():
            new = (task.get('area') or {}).get('equivalent_slice') if task['status'] == 'passed' else None
            delta = task['area_change_pct']
            t, bt = task['timing'], baseline_rows[cfg]
            gain = t['wns_ns']-bt['wns_ns'] if 'wns_ns' in t and 'wns_ns' in bt else None
            state = 'analysis_deferred（继续后台）' if task['analysis_deferred'] else task['status']
            if task['area_budget_passed'] is False:
                state += '；面积预算超限'
            lines.append('| ' + ' | '.join([stage['name'], cfg, fmt(new), fmt(delta)+'%' if delta is not None else '—',
                         fmt(t.get('wns_ns')), fmt(gain), fmt(t.get('logic_levels'),0), fmt(task.get('seconds'),1),state])+' |')
    lines += ['', '## 布线对照', '',
              '| 候选 | 配置 | 基线 MHz | 候选 MHz | 频率变化 | 候选布线 Slice | 搜索进度 |',
              '|---|---|---:|---:|---:|---:|---|']
    for stage in result['stages']:
        for cfg in CONFIGS:
            old = base_route.get('tasks', {}).get(cfg, {})
            new = stage['routing'].get(cfg, {})
            old_hz = old.get('result', {}).get('frequency_mhz') if old.get('status') == 'passed' else None
            new_hz = new.get('result', {}).get('frequency_mhz') if new.get('status') == 'passed' else None
            gain = None if old_hz is None or new_hz is None else (new_hz/old_hz-1)*100
            progress = new.get('status', '等待功能检查/尚未启动')
            if not new:
                progress = stage.get('automatic_routing_status') or progress
            if stage.get('route'):
                attempt = read(Path(stage['route'])/'route'/cfg/'attempts.json').get('attempts', [])
                if attempt and new.get('status') != 'passed':
                    progress += f'；完成{len(attempt)}轮，暂得{1000/min(a["closed_period_ns"] for a in attempt):.3f}MHz'
            lines.append('| ' + ' | '.join([stage['name'], cfg, fmt(old_hz), fmt(new_hz),
                         fmt(gain)+'%' if gain is not None else '—',fmt(new.get('routed_area', {}).get('equivalent_slice')),progress])+' |')
    for profile, title in zip(PROFILES, ('SLH-DSA 128f', 'XMSS h10', 'LMS h10')):
        lines += ['', f'## {title} Sign 实测布线 ATP', '',
                  '| 候选 | 配置 | 基线周期 | 候选周期 | 周期变化 | 周期预算 | 基线 ATP Slice·ms | 候选 ATP Slice·ms | ATP 变化 |',
                  '|---|---|---:|---:|---:|---|---:|---:|---:|']
        for stage in result['stages']:
            for cfg in CONFIGS:
                old = next((r for r in base_route.get('results', []) if r['configuration'] == cfg and r['profile'] == profile), {})
                new = next((r for r in stage['route_results'] if r['configuration'] == cfg and r['profile'] == profile), {})
                old_atp, new_atp = old.get('atp_slice_ms'), new.get('atp_slice_ms')
                delta = None if old_atp is None or new_atp is None else (new_atp/old_atp-1)*100
                case = next(v for v in stage['validation'] if v['configuration'] == cfg and v['profile'] == profile)
                budget = '通过' if case['cycle_budget_passed'] is True else '超限' if case['cycle_budget_passed'] is False else '待测'
                cycle_delta = case['cycle_change_pct']
                lines.append('| ' + ' | '.join([stage['name'],cfg,fmt(case['baseline_cycles'],0),fmt(case['cycles'],0),
                             fmt(cycle_delta)+'%' if cycle_delta is not None else '—',budget,fmt(old_atp),fmt(new_atp),
                             fmt(delta)+'%' if delta is not None else '—'])+' |')
    lines += ['', '## 附加验证摘要', '']
    for name, evidence in result['validation'].items():
        lines.append(f'- `{name}`：{evidence.get("status", evidence.get("passed", "见 JSON 摘要"))}；详见同目录 JSON 的 validation 字段。')
    lines += ['', '当前 RTL 为待验收候选。未结束的布线不报告最终频率或 ATP 收益；原始综合与仿真明细保留在各 build 目录。归档仅保留验证摘要、冻结源码及综合/布线证据，不保留 sim/validation 明细日志。', '',
              f'实验控制：`{run}`。', '']
    prefix.parent.mkdir(parents=True, exist_ok=True)
    atomic(prefix.with_suffix('.md'), '\n'.join(lines))
    atomic(prefix.with_suffix('.json'), json.dumps(result, ensure_ascii=False, indent=2)+'\n')
    atomic(out/'EXPERIMENT.json', json.dumps(meta, ensure_ascii=False, indent=2)+'\n')
    checksums = {str(p.relative_to(out)): hashlib.sha256(p.read_bytes()).hexdigest()
                 for p in out.rglob('*') if p.is_file() and p.name != 'ARTIFACTS.json'}
    atomic(out/'ARTIFACTS.json', json.dumps(dict(updated_at=stamp(), sha256=checksums), indent=2)+'\n')
    index()
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-root', type=Path, required=True)
    parser.add_argument('--watch', action='store_true')
    args = parser.parse_args()
    while True:
        result = publish(args.run_root.resolve())
        if not args.watch:
            return
        time.sleep(60)


if __name__ == '__main__':
    main()
