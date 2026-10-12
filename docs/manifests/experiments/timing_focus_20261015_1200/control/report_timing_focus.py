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


def publish(run):
    meta = read(run/'EXPERIMENT.json')
    out = ROOT/'docs/manifests/experiments'/meta['experiment']
    prefix = out/'reports/Timing_Focus_P1_P4_P12_20261015'
    baseline = Path(meta['baseline_run'])
    base = read(baseline/'status.json')
    base_route = read(Path(meta['baseline_route'])/'status.json') if meta.get('baseline_route') else {}
    result = dict(updated_at=stamp(), baseline_run=str(baseline), baseline_route=meta.get('baseline_route'),
                  scope='common OOC, xc7a200tffg1156-3, generic Keccak, two Vivado threads',
                  acceptance='Byte-identical outputs/signature cache; exact cycles/hashes/permutations; routed setup/hold and ATP',
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
    lines = ['# P1U1 / P4U1 / P4U2 / P12U1 布线时序优化', '',
             f'更新时间：{result["updated_at"]}。本轮由用户明确授权布局布线；候选选择尚待实测。', '',
             f'工作区候选：`{current["name"]}`；与冻结 RTL 逐字节一致：`{result["working_rtl_matches_candidate"]}`。候选01/02/03是逐步试验记录，未将其综合改善直接当作布线收益。', '',
             '保持标准参数、单 Hash lane、模块接口和执行周期。面积采用对应配置 common；使用通用 Keccak、同器件和默认时序驱动综合，不增加时序例外。综合约束沿用 6.666667 ns；布线起点 U1=150 MHz、U2=100 MHz。', '',
             '综合 WNS 只用于筛选，不能视为布线频率。布线搜索使用 0.1 ns 周期网格及相邻失败证据；报告实际 STA 频率。原长耗时综合继续后台，缺项保持空白，不借用其他配置。', '',
             '## 基线瓶颈', '',
             '| 配置 | 综合 WNS ns | 数据路径 ns | 逻辑级数 | 关键路径 |',
             '|---|---:|---:|---:|---|']
    baseline_rows = {}
    for cfg in CONFIGS:
        t = timing(baseline/'synth'/cfg/'common/timing.rpt')
        baseline_rows[cfg] = t
        label = ('FORS 索引算术与动态摘要选择' if cfg == 'P1U1' else
                 '端点读址、RAM 与首轮 Keccak' if cfg == 'P4U1' else
                 '链索引、步数选择与首轮 Keccak' if cfg == 'P12U1' else
                 '原综合未完成' if not t else t.get('source', ''))
        lines.append(f'| {cfg} | {fmt(t.get("wns_ns"))} | {fmt(t.get("data_path_ns"))} | {fmt(t.get("logic_levels"),0)} | {label} |')
    lines += ['', '前三个已完成基线的前100条setup路径显示：P1U1有51条起于FORS组索引，P4U1有87条起于端点读址，P12U1有96条起于链游标。基线DCP只读扫描及源码/检查点校验见 baseline/paths；未更改约束。', '',
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
                passed = new.get('status') == 'passed'
                equal = passed and old.get('status') == 'passed' and all(
                    new.get(k) == old.get(k) for k in ('cycles', 'total_cycles', 'hashes', 'permutations'))
                validation.append(dict(configuration=cfg, profile=profile, status=new.get('status', 'pending'),
                                       workload_equal=equal if passed else None,
                                       cycles=new.get('cycles'), hashes=new.get('hashes'), permutations=new.get('permutations')))
        data = dict(name=stage['name'], run=str(candidate), route=stage.get('route'),
                    automatic_routing_status=stage.get('automatic_routing_status'),
                    description=stage['description'], counts=state.get('counts', {}), validation=validation,
                    exact_sign_cases=sum(v['workload_equal'] is True for v in validation),
                    functional_regression=any(v['status'] == 'failed' or v['workload_equal'] is False for v in validation),
                    synthesis={}, routing=route.get('tasks', {}), route_results=route.get('results', []))
        lines += [f'### {stage["name"]}', '', stage['description'], '',
                  f'逐字节输出、签名缓存及工作量核对：{data["exact_sign_cases"]}/12 项完成且与基线周期、Hash、置换计数完全一致。状态：`{data["counts"]}`。', '']
        if data['functional_regression']:
            lines += ['**功能或周期检查失败，本候选不得用于最终验收。**', '']
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
            data['synthesis'][cfg] = dict(status=task.get('status', 'pending'),
                                           analysis_deferred=task.get('analysis_deferred', False),
                                           seconds=task.get('seconds'), area=task.get('area'), timing=t)
        result['stages'].append(data)
    lines += ['## 综合对照', '',
              '| 候选 | 配置 | 等效 Slice | 面积变化 | WNS ns | WNS 改善 ns | 级数 | 综合耗时 s | 状态 |',
              '|---|---|---:|---:|---:|---:|---:|---:|---|']
    for stage in result['stages']:
        for cfg, task in stage['synthesis'].items():
            old = base.get('tasks', {}).get(f'synth/{cfg}/common', {}).get('area', {}).get('equivalent_slice')
            new = (task.get('area') or {}).get('equivalent_slice')
            delta = None if old is None or new is None else (new/old-1)*100
            t, bt = task['timing'], baseline_rows[cfg]
            gain = t['wns_ns']-bt['wns_ns'] if 'wns_ns' in t and 'wns_ns' in bt else None
            state = 'analysis_deferred（继续后台）' if task['analysis_deferred'] else task['status']
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
                progress = stage.get('automatic_routing_status') or ('归因测量；不启动布线' if stage['name'].startswith('01_') else progress)
            if stage.get('route'):
                attempt = read(Path(stage['route'])/'route'/cfg/'attempts.json').get('attempts', [])
                if attempt and new.get('status') != 'passed':
                    progress += f'；完成{len(attempt)}轮，暂得{1000/min(a["closed_period_ns"] for a in attempt):.3f}MHz'
            lines.append('| ' + ' | '.join([stage['name'], cfg, fmt(old_hz), fmt(new_hz),
                         fmt(gain)+'%' if gain is not None else '—',fmt(new.get('routed_area', {}).get('equivalent_slice')),progress])+' |')
    for profile, title in zip(PROFILES, ('SLH-DSA 128f', 'XMSS h10', 'LMS h10')):
        lines += ['', f'## {title} Sign 实测布线 ATP', '',
                  '| 候选 | 配置 | 周期 | 基线 ATP Slice·ms | 候选 ATP Slice·ms | ATP 变化 |',
                  '|---|---|---:|---:|---:|---:|']
        for stage in result['stages']:
            for cfg in CONFIGS:
                old = next((r for r in base_route.get('results', []) if r['configuration'] == cfg and r['profile'] == profile), {})
                new = next((r for r in stage['route_results'] if r['configuration'] == cfg and r['profile'] == profile), {})
                old_atp, new_atp = old.get('atp_slice_ms'), new.get('atp_slice_ms')
                delta = None if old_atp is None or new_atp is None else (new_atp/old_atp-1)*100
                case = next(v for v in stage['validation'] if v['configuration'] == cfg and v['profile'] == profile)
                lines.append('| ' + ' | '.join([stage['name'],cfg,fmt(case['cycles'],0),fmt(old_atp),fmt(new_atp),
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
        time.sleep(30)


if __name__ == '__main__':
    main()
