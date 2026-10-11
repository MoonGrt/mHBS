#!/usr/bin/env python3
"""Collect the frozen debug/sharing candidate without interrupting long synthesis."""
import argparse
import csv
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from run_pu_sign_matrix import utilization

NAME = 'RTL_Debug_Sharing_Cleanup_20261013'


def collect(base):
    selection_file = base / 'FINAL.json'
    selection = json.loads(selection_file.read_text()) if selection_file.exists() else None
    frozen = Path(selection['source_root']) if selection else base / 'candidate'
    source_manifest = Path(selection['source_manifest']) if selection else base / 'SOURCE.json'
    source = json.loads(source_manifest.read_text())
    validation = Path(selection['validation_root']) if selection else base / 'validation'
    unchanged = all(hashlib.sha256((frozen / f).read_bytes()).hexdigest() == h
                    for f, h in source['files'].items())
    old = json.loads((ROOT / 'docs/report/PU_Sign_Matrix_20261013_203826.json').read_text())
    areas = []
    tasks_file = Path(selection['tasks_file']) if selection else base / 'synthesis_tasks.json'
    tasks = json.loads(tasks_file.read_text())
    for task in tasks['tasks'] if isinstance(tasks, dict) else tasks:
        top = task['name'].startswith('top/')
        signature = int(task['name'][-1]) if top else None
        work = frozen / 'build/synth/top_P4U1_generic' if top else Path(task['out'])
        if top:
            work /= 'slh_128f' + ('_no_signature_store' if not signature else '')
        report = work / ('top_utilization.rpt' if top else 'utilization.rpt')
        text = Path(task['log']).read_text() if Path(task['log']).exists() else ''
        passed = ('MHBS_TOP_SYNTH_PASS' if top else 'MHBS_MATRIX_SYNTH_PASS') in text
        record = dict(name=task['name'], status='passed' if passed else
                      'failed' if 'ERROR:' in text else 'running',
                      pid=task.get('pid'), log=task['log'], signature_store=signature,
                      area=utilization(report) if passed else None)
        if passed:
            record['debug_audit'] = json.loads((work / 'debug_audit.json').read_text())
        if not top:
            config = task['name'].split('/')[1]
            record['previous_area'] = old['tasks'][f'synth/{config}/common']['area']
            if passed:
                record['area_change_percent'] = 100 * (
                    record['area']['equivalent_slice'] /
                    record['previous_area']['equivalent_slice'] - 1)
        areas.append(record)
    simulations = []
    for log in sorted(validation.rglob('*_sign.log')):
        parts = re.fullmatch(r'(P\d+U\d+)_synthesis([01])_(.*)_sign', log.stem)
        if not parts:
            parts = re.fullmatch(r'(P\d+U\d+)_(.*)_sign', log.stem)
            if parts:
                config, profile = parts.groups()
                parts = (config, '0', profile)
        match = re.search(r'STATEFUL_PASS .*cycles=(\d+) total=(\d+) hashes=(\d+) '
                          r'permutations=(\d+).*seconds=([\d.e+]+)', log.read_text())
        if not parts or not match:
            continue
        config, synthesis, profile = parts.groups() if hasattr(parts, 'groups') else parts
        values = match.groups()
        baseline = old['tasks'][f'sim/{config}/{profile}']
        area = next((a['area'] for a in areas if a['name'] == 'common/' + config), None)
        frequency = 150 if config.endswith('U1') else 110
        cycles, total, hashes, permutations = map(int, values[:4])
        simulations.append(dict(config=config, synthesis=int(synthesis), profile=profile,
                                cycles=cycles, total_cycles=total, hashes=hashes,
                                permutations=permutations, wall_seconds=float(values[4]),
                                log=str(log), frequency_mhz=frequency,
                                fpga_ms=cycles / (frequency * 1000),
                                atp_slice_ms=area['equivalent_slice'] * cycles /
                                (frequency * 1000) if area else None,
                                matches_previous=all((cycles == baseline['cycles'],
                                                      hashes == baseline['hashes'],
                                                      permutations == baseline['permutations']))))
    for profile in ('slh_128f', 'xmss_h10', 'lms_h10'):
        ranked = sorted((s for s in simulations if s['profile'] == profile and
                         s['synthesis'] == 0 and s['atp_slice_ms'] is not None),
                        key=lambda s: s['atp_slice_ms'])
        for rank, item in enumerate(ranked, 1):
            item['rank_measured'] = rank
    best_comparison = []
    for profile in ('slh_128f', 'xmss_h10', 'lms_h10'):
        previous = []
        for key, task in old['tasks'].items():
            if not key.startswith('sim/') or not key.endswith('/' + profile) or task['status'] != 'passed':
                continue
            config = key.split('/')[1]
            area_task = old['tasks'].get(f'synth/{config}/common', {})
            if area_task.get('status') != 'passed':
                continue
            frequency = 150 if config.endswith('U1') else 110
            previous.append((area_task['area']['equivalent_slice'] * task['cycles'] /
                             (frequency * 1000), config))
        candidate = [(s['atp_slice_ms'], s['config']) for s in simulations
                     if s['profile'] == profile and s['synthesis'] == 0 and s['atp_slice_ms'] is not None]
        if previous and candidate:
            old_atp, old_config = min(previous)
            new_atp, new_config = min(candidate)
            best_comparison.append(dict(profile=profile, previous_config=old_config,
                                        previous_atp_slice_ms=old_atp, candidate_config=new_config,
                                        candidate_atp_slice_ms=new_atp,
                                        change_percent=100 * (new_atp / old_atp - 1)))
    verify_file = validation / 'verify24.json'
    verify = json.loads(verify_file.read_text()) if verify_file.exists() else []
    supplemental_file = Path(selection['supplemental_file']) if selection else ROOT / 'build/debug_cleanup/VALIDATION.json'
    supplemental = json.loads(supplemental_file.read_text()) if supplemental_file.exists() else {}
    if not verify:
        verify = [r for r in supplemental.get('results', [])
                  if re.fullmatch(r'verify_synthesis[01]_.+', r['name'])]
    experiments = []
    for out in sorted((base / 'variants').glob('*/synth/P*/')):
        log = out / 'vivado.log'
        text = log.read_text() if log.exists() else ''
        passed = 'MHBS_MATRIX_SYNTH_PASS' in text
        experiments.append(dict(variant=out.parent.parent.name, config=out.name,
                                status='passed' if passed else 'failed' if 'ERROR:' in text else 'running',
                                area=utilization(out / 'utilization.rpt') if passed else None,
                                log=str(log)))
    return dict(updated_at=datetime.now().astimezone().isoformat(),
                source_unchanged=unchanged, baseline_head=source['head'],
                selection=selection, source_manifest=str(source_manifest), source_root=str(frozen),
                validation_root=str(validation), supplemental_file=str(supplemental_file),
                areas=areas, simulations=simulations, verify=verify,
                supplemental_validation=supplemental,
                experiments=experiments,
                best_comparison=best_comparison,
                fixed_frequency_atp_pass=len(best_comparison) == 3 and
                    all(s['change_percent'] <= 0 for s in best_comparison) and
                    any(s['change_percent'] < 0 for s in best_comparison),
                area_complete=all(a['status'] == 'passed' for a in areas),
                h20_full_keygen_sign_enabled=False)


def write_report(data, base):
    report = ROOT / 'docs/report' / NAME
    report.with_suffix('.json').write_text(json.dumps(data, indent=2) + '\n')
    fields = ['kind', 'name', 'synthesis', 'lut', 'ff', 'bram36', 'equivalent_slice',
              'cycles', 'hashes', 'permutations', 'frequency_mhz', 'fpga_ms',
              'atp_slice_ms', 'rank_measured', 'status']
    with report.with_suffix('.csv').open('w', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for item in data['areas']:
            writer.writerow(dict(kind='area', name=item['name'], status=item['status'],
                                 **{k: v for k, v in (item['area'] or {}).items() if k in fields}))
        for item in data['simulations']:
            writer.writerow(dict(kind='sign', name=item['profile'] + '/' + item['config'],
                                 status='passed' if item['matches_previous'] else 'changed',
                                 **{k: v for k, v in item.items() if k in fields}))
    lines = [
        '# RTL 调试裁剪、签名缓存宏与互斥资源复用（2026-10-13）', '',
        f"更新时间：{data['updated_at']}。冻结源码校验：{data['source_unchanged']}。", '',
        '本轮基线是提交 `' + data['baseline_head'][:8] +
        '` 的标准算法通用实现，对照上一矩阵 20261013_203826；历史报告保持原口径。', '',
        '定义 `MHBS_SIGNATURE_STORE` 才实例化 top 的 Sign 缓存，未定义时缓存读回接口返回零，'
        '签名输出流继续有效。宏按是否定义判断，`-DMHBS_SIGNATURE_STORE=0` 仍表示开启。'
        '`synth_top.tcl <profile> 0/1` 负责转换为宏不存在/存在；脚本默认1，延续之前含缓存的面积口径。', '',
        '`SYNTHESIS` 下 error_code、cycles、boot/keygen/sign_cycles、hash_count、permutation_count '
        '及内部统计接口、寄存器、更新逻辑一起删除。调试更新和断言使用独立 always 块，'
        '功能 always 中没有 SYNTHESIS 条件。功能性 error/abort、存储读回长度、有效标记和'
        '错误中止保留，它们参与协议和数据正确性。', '',
        '| 共用项 | 实现及存活期约束 |',
        '|---|---|',
        '| 控制标记 | ' + ('归约寄存器、滚动active/批次done标记的合并均已撤回；'
        '实测新增选择逻辑抵消FF收益。原有互斥调度继续共用一套状态机。' if data['selection'] else
        '初次尝试将 L-tree/FORS 归约 count/cursor/level 合并；隔离面积比较后决定是否保留。') + ' |',
        '| 宽度与策略 | ' + ('缩窄计数器的候选比保留原宽度的候选面积更大，故撤回；'
        'endpoint_count保留8位，非法ROM计数检测继续有效。公共计数策略复用尝试同样撤回。'
        if data['selection'] else '初次尝试将计数保持策略改为批次一位；正在隔离评估实际面积。') + ' |',
        '| 现有宽存储 | 三算法共用单 Hash lane、136×256工作区和可选签名缓存；本轮容量不变。 |',
        '| 保留的同时存活数据 | 树栈与认证路径、XMSS key/digest/captured、Verify二元输入、'
        'Sign缓存与树工作区分别同时存活，继续占不同位置。 |', '',
        '所有 sources.txt 中 RTL 使用统一4空格缩进、100列目标宽度和长表达式换行。'
        '`scripts/format_rtl.sh` 可复现格式；工具为 '
        '[Verible](https://github.com/chipsalliance/verible) v0.0-4296-g0f262651。'
        '清理退休 omega2 分支及未使用配方信号，保留 FSM 编号和测试观察层级。', '',
        '源码和四种宏组合 lint/预处理审计通过：综合视图没有诊断标识符，'
        '任一 always 内均没有 SYNTHESIS 开关。Vivado 对实际综合网表继续核对诊断端口和寄存器。', '',
        '## 面积', '',
        '器件 xc7a200tffg1156-3，Vivado 2025.2，OOC，通用 Keccak，6.666667ns，'
        '默认时序驱动，每个 Vivado 2线程；没有新增时序例外。'
        '等效 Slice=LUT/4+FF/8+232.4×BRAM36+102.4×DSP。'
        'common 排除ROM、签名缓存和板级I/O；top 包含固定128f Sign ROM及按宏选择的缓存。', '',
        '| 口径 | LUT | FF | BRAM36 | 等效Slice | 相同P/U上轮Slice | 变化 | 状态 |',
        '|---|---:|---:|---:|---:|---:|---:|---|']
    for item in data['areas']:
        area = item['area'] or {}
        previous = item.get('previous_area', {}).get('equivalent_slice', '')
        delta = item.get('area_change_percent')
        cells = [item['name'], *[str(area.get(k, '')) for k in
                 ['lut', 'ff', 'bram36', 'equivalent_slice']], str(previous),
                 f'{delta:+.3f}%' if delta is not None else '', item['status']]
        lines.append('| ' + ' | '.join(cells) + ' |')
    lines += ['', '排名仅覆盖本轮已测 common 的配置；未测/未完成面积不借用上一轮值。'
              'U1=150MHz、U2=110MHz 是比较用假定频率；本轮尚无布线 STA，因此不作布线 ATP 结论。']
    lines += ['', '| 算法 | 修改前已测最佳 | 最终候选已测最佳 | ATP变化 |',
              '|---|---|---|---:|']
    for item in data['best_comparison']:
        lines.append(f"| {item['profile']} | {item['previous_config']} | "
                     f"{item['candidate_config']} | {item['change_percent']:+.3f}% |")
    lines += ['', '## 复用取舍', '',
              '相同P/U、相同工具设置的隔离实验保留在独立冻结目录。减少声明位数会增加选择逻辑，'
              '按实际综合面积决定是否保留；最终候选的三个目标最佳ATP须与本轮之前标准矩阵比较。', '',
              '| 变体 | P/U | LUT | FF | 等效Slice | 状态 |',
              '|---|---|---:|---:|---:|---|']
    for experiment in data['experiments']:
        area = experiment['area'] or {}
        lines.append('| ' + ' | '.join([experiment['variant'], experiment['config'],
                     *[str(area.get(k, '')) for k in ['lut', 'ff', 'equivalent_slice']],
                     experiment['status']]) + ' |')
    if data['selection']:
        lines += ['', '最终选定 `separate_both`：保留签名宏、完整诊断裁剪、独立调试块、'
                  '无用逻辑清理与格式整理；新增存储/状态合并和缩窄尝试按实测撤回。'
                  '此前已有的单lane、上下文、工作区复用保持有效。']
    for profile in ('slh_128f', 'xmss_h10', 'lms_h10'):
        lines += ['', '## ' + profile + ' Sign', '',
                  '| P/U | 周期 | 时间ms | ATP Slice·ms | 已测排名 | 与上轮周期/工作量 |',
                  '|---|---:|---:|---:|---:|---|']
        for item in data['simulations']:
            if item['profile'] != profile or item['synthesis']:
                continue
            atp = item['atp_slice_ms']
            lines.append('| ' + ' | '.join([item['config'], str(item['cycles']),
                         f"{item['fpga_ms']:.6f}", f'{atp:.6f}' if atp is not None else '',
                         str(item.get('rank_measured', '')),
                         '一致' if item['matches_previous'] else '变化']) + ' |')
    lines += ['', '## 验证与证据', '',
              f"本轮完整 Sign 已完成 {len(data['simulations'])} 项，包括普通与综合宏视图；"
              f"六组 SLH 与六组 XMSS/LMS 的两种宏视图 Verify 已完成 {len(data['verify'])} 项。",
              '补充验证包括：四种 top 宏组合的完整128f Sign及缓存逐字节读回；'
              '459项配方、12项流水 family/地址检查；64位计数进位；两种宏视图下'
              '非法状态、q越界、非法配置和在途故障的功能中止。', '',
              f'- 冻结源码及校验：[SOURCE.json]({data["source_manifest"]})。',
              f'- 完整 Sign/Verify 日志：[validation]({data["validation_root"]})。',
              f'- 源码裁剪审计：[source_audit.json]({base / "source_audit.json"})。',
              f'- 补充验证：[VALIDATION.json]({data["supplemental_file"]})。',
              f'- 综合任务和日志：[synthesis_tasks.json]({base / "synthesis_tasks.json"})。', '',
              'XMSS/LMS h20 完整 Keygen/Sign 保持停止。上一轮异常 P3U2 和旧赢家布线继续后台运行，'
              '其结果属于归档源码，不混入本轮候选面积。综合耗时异常时仅暂缓分析，不终止进程。', '']
    report.with_suffix('.md').write_text('\n'.join(lines))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base', type=Path, default=ROOT / 'build/rtl_cleanup_20261013')
    parser.add_argument('--watch', action='store_true')
    args = parser.parse_args()
    while True:
        data = collect(args.base.resolve())
        write_report(data, args.base.resolve())
        if not args.watch or data['area_complete']:
            break
        time.sleep(30)


if __name__ == '__main__':
    main()
