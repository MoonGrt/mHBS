#!/usr/bin/env python3
"""Publish focused P1/SHA candidate comparisons without launching hardware jobs."""
import argparse
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import time
from zoneinfo import ZoneInfo

import experiment_archive as archive

ROOT = Path(os.environ.get('MHBS_P1SHA_WORKSPACE', Path(__file__).resolve().parents[1])).resolve()
FAMILY = ROOT / 'build/p1sha_atp_optimization'
BASELINE = FAMILY / 'baseline_20261021_202753'
OUT = ROOT / 'docs/manifests/experiments/p1sha_atp_baseline_20261021_202753'
PREFIX = OUT / 'reports/P1_SHA_ATP_Progress_20261021'


def read(path):
    return json.loads(Path(path).read_text())


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    archive.atomic(Path(path), json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def publish():
    baseline = read(BASELINE / 'status.json')
    candidates = []
    for source in sorted(FAMILY.glob('*/SOURCE.json')):
        run = source.parent
        if not (run / 'status.json').is_file():
            continue
        meta, state = read(source), read(run / 'status.json')
        physical_file = run / 'PHYSICAL_STATUS.json'
        if physical_file.is_file():
            physical = read(physical_file)
            if physical['source_manifest_sha256'] != sha(source):
                raise ValueError('Physical source binding differs: ' + str(run))
            state['routing'] = physical['routes']
            for row in state['rows']:
                route = physical['routes'].get(row['config'], {})
                if route.get('meets_target') and route.get('source_unchanged') and row['status'] == 'passed':
                    period = route['result']['actual_period_ns']
                    row.update(routed_frequency_mhz=1000/period, routed_time_ms=row['cycles']*period/1e6,
                        routed_atp=route['routed_area']['equivalent_slice']*row['cycles']*period/1e6)
        candidates.append(dict(run_root=str(run), source=meta, source_manifest_sha256=sha(source),
            results=state, report=str(Path(meta['archive_directory']) / 'reports' /
                ('P1_SHA_ATP_' + meta['run_id'] + '.md'))))
    candidates.sort(key=lambda c: c['source']['started_at'])
    actual = [c for c in candidates if c['source']['kind'] == 'candidate']
    counts = dict(candidates=len(actual), measured_sign_passed=sum(
        sum(t['status'] == 'passed' for t in c['results']['tests'].values()) for c in actual),
        measured_sign_total=sum(len(c['results']['tests']) for c in actual),
        reused_baseline_sign_passed=sum(t['status'] == 'passed' for t in baseline['tests'].values()),
        diagnostic_syntheses_passed=sum(sum(t['status'] == 'passed' for t in c['results']['synthesis'].values())
            for c in candidates), diagnostic_syntheses_total=sum(len(c['results']['synthesis']) for c in candidates),
        new_routes=sum(len(c['results']['routing']) for c in actual))
    coordination = read(FAMILY / 'COORDINATOR_STATUS.json') if (FAMILY / 'COORDINATOR_STATUS.json').is_file() else {}
    complete = (all(c['results'].get('complete') for c in candidates) and len(actual) >= 4
                and coordination.get('complete', False))
    changed = []
    newest = actual[-1] if actual else candidates[0]
    for name in newest['source']['rtl_files'] + ['sources.txt']:
        if sha(ROOT / name) != newest['source']['sha256'][name]:
            changed.append(name)
    result = dict(updated_at=datetime.now(ZoneInfo('Asia/Singapore')).isoformat(timespec='seconds'),
        complete=complete, candidates=candidates, counts=counts,
        workspace_matches_latest_candidate=not changed, workspace_changed_files=changed,
        final_frequency_mhz_by_unroll={'1': 150, '2': 100}, frequency_search=False,
        diagnostic_frequency_is_not_final_frequency=True,
        physical_baseline_target_not_met_is_not_closed_frequency_evidence=True, coordination=coordination,
        mixed_candidate_areas_and_cycles=False)
    fmt = lambda value: '—' if value is None else f'{value:,.3f}'
    lines = ['# P1／SHA 面积、延迟与 ATP 优化进展', '',
        f'更新时间：{result["updated_at"]}；状态：{"测量全部结束" if complete else "后台测量"}。', '',
        f'实测Sign：{counts["measured_sign_passed"]}/{counts["measured_sign_total"]}；'
        f'基线复用Sign：{counts["reused_baseline_sign_passed"]}；100MHz综合：'
        f'{counts["diagnostic_syntheses_passed"]}/{counts["diagnostic_syntheses_total"]}；'
        f'新增指定频率布线：{counts["new_routes"]}。', '',
        '基线B0为2026-10-21本轮开始时的完整冻结源码，RTL与193612双后端矩阵完全相同。'
        '其21项完整Sign和7点物理证据经过向量、RTL、日志与DCP散列核对后复用；'
        '7点100MHz诊断重新综合，不借用150MHz综合面积当同口径诊断基线。', '',
        'C1：SHA256轮内加法的进位保留重写；C2：在C1上加SHA2列表三字读取登记与SHAKE P1反馈/填充选择优化；'
        'C3：在C2上将SHA256轮常数表按实际循环遍历宽度切分；'
        'C4：保留小轮常数表、恢复普通加法并提前登记配方末块标记。候选结构通用，不恢复P/U特化。', '',
        '面积统一为相同后端、相同P/U的common OOC，器件xc7a200tffg1156-3，Vivado2025.2，'
        '默认时序驱动，每个Vivado2线程。等效Slice=LUT/4+FF/8+232.4×BRAM36+102.4×DSP。'
        '100MHz数据仅为面积和路径诊断；假设ATP使用U1=150MHz、U2=100MHz，不能作为闭合频率ATP。'
        '目标未通过的基线不推算Fmax，不借用其他候选频率；仅setup/hold、DRC与完整路由通过才给布线ATP。', '',
        '完整Sign核对输出、签名缓存和64位Hash/置换/压缩计数。新增C2列表读取拍可能增加周期，按完整Sign实测统计。'
        '未执行h20完整Keygen/Sign，异常长综合标analysis_deferred并留后台。', '']
    for backend in ('shake', 'sha2'):
        lines += [f'## {backend.upper()} 100MHz common诊断面积', '',
            '| 候选 | 配置 | LUT | FF | BRAM36 | 等效Slice | 面积变化% | 路径ns | 级数 | 状态 |',
            '|---|---|---:|---:|---:|---:|---:|---:|---:|---|']
        for candidate in candidates:
            for config, syn in candidate['results']['synthesis'].items():
                if not config.startswith(backend + '/'):
                    continue
                area, path = syn.get('area', {}), syn.get('timing', {})
                base_syn = baseline['synthesis'][config]
                delta = (100*(area['equivalent_slice']/base_syn['area']['equivalent_slice']-1)
                    if syn['status'] == base_syn['status'] == 'passed' else None)
                lines.append('| ' + ' | '.join([candidate['results']['label'], config.split('/')[1],
                    *[fmt(area.get(n)) for n in ('lut', 'ff', 'bram36', 'equivalent_slice')], fmt(delta),
                    fmt(path.get('data_path_ns')), fmt(path.get('logic_levels')), syn['status'] +
                    ('；分析延后，后台继续' if syn.get('analysis_deferred') else '')]) + ' |')
        lines.append('')
    for profile in ('slh_128f', 'xmss_h10', 'lms_h10'):
        lines += [f'## {profile} 完整Sign', '',
            '| 候选 | 后端／配置 | 周期 | 变化% | 假设时间ms | 假设ATP Slice·ms | ATP变化% | 闭合MHz | 布线ATP Slice·ms | 状态 |',
            '|---|---|---:|---:|---:|---:|---:|---:|---:|---|']
        for candidate in candidates:
            for row in candidate['results']['rows']:
                if row['profile'] != profile:
                    continue
                config, syn = row['config'], candidate['results']['synthesis'][row['config']]
                old_syn = baseline['synthesis'][config]
                delta = None
                if row['cycles'] is not None and syn['status'] == old_syn['status'] == 'passed':
                    delta = 100*(syn['area']['equivalent_slice']*row['cycles']/(
                        old_syn['area']['equivalent_slice']*row['baseline_cycles'])-1)
                lines.append('| ' + ' | '.join([candidate['results']['label'], row['config'], fmt(row['cycles']),
                    fmt(row.get('cycles_change_pct')), fmt(row.get('assumed_target_time_ms')), fmt(row['diagnostic_atp']),
                    fmt(delta), fmt(row['routed_frequency_mhz']), fmt(row['routed_atp']), row['status']]) + ' |')
        lines.append('')
    lines += ['## 指定频率物理证据', '',
        '| 候选 | 后端／配置 | 目标MHz | 布线Slice | WNS ns | WHS ns | 状态 |',
        '|---|---|---:|---:|---:|---:|---|']
    for candidate in candidates:
        for config, route in candidate['results']['routing'].items():
            data = route.get('result', {})
            lines.append('| ' + ' | '.join([candidate['results']['label'], config,
                fmt(route.get('target_frequency_mhz')), fmt(route.get('routed_area', {}).get('equivalent_slice')),
                fmt(data.get('wns_ns')), fmt(data.get('whs_ns')), route['status']]) + ' |')
    lines += ['', '## 源码与归档', '',
        f'当前工作区与最新冻结候选RTL{"一致" if not changed else "不一致（" + ", ".join(changed) + "）"}。', '']
    for candidate in candidates:
        path = Path(candidate['report']).relative_to(ROOT)
        lines += [f'- [{candidate["results"]["label"]}]({path})：'
            f'`{candidate["source_manifest_sha256"]}`。']
    correction = FAMILY / 'CAPACITY_CORRECTION.json'
    if correction.is_file():
        lines += ['', '初版两个控制器在进程启动窗口曾同时占用最后一槽，短暂出现13个Vivado；'
            '随后只暂停了新增候选诊断，并在容量释放后恢复；旧矩阵未修改。'
            'C2起采用跨进程预约锁及物理阶段顺序调度，限制全机12个、每个2线程。'
            '该调度修正及自动恢复记录保留运行目录，未终止任何旧任务。']
    lines += ['', 'RTL/support压缩包、源码/控制器SHA、分层面积、时序与Vivado日志随各候选归档。'
        '原始仿真和验证详细日志在运行目录；归档只保留验证摘要与原始日志路径/散列。', '']
    write(PREFIX.with_suffix('.json'), result)
    archive.atomic(PREFIX.with_suffix('.md'), '\n'.join(lines))
    controller = OUT / 'analysis_control' / Path(__file__).name
    archive.copy_changed(Path(__file__), controller)
    write(controller.with_suffix('.json'), dict(sha256=sha(controller),
        launches_hardware_jobs=False, source=str(Path(__file__).resolve())))
    artifact_path = OUT / 'ARTIFACTS.json'
    if artifact_path.is_file():
        data = read(artifact_path)
        for path in (PREFIX.with_suffix('.json'), PREFIX.with_suffix('.md'), controller, controller.with_suffix('.json')):
            data.setdefault('sha256', {})[str(path.relative_to(OUT))] = sha(path)
        write(artifact_path, data)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--watch', action='store_true')
    args = parser.parse_args()
    while True:
        result = publish()
        if not args.watch or result['complete']:
            break
        time.sleep(15)
