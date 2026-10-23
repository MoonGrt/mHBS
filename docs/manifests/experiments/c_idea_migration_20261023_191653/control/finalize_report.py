#!/usr/bin/env python3
"""Render the completed, source-bound migration comparison without rerunning tools."""
from pathlib import Path
import hashlib
import importlib.util
import json
import re
import shutil

ARCHIVE = Path(__file__).resolve().parents[1]
META = json.loads((ARCHIVE / 'SOURCE.json').read_text())
RUN = Path(META['run'])
BASELINE = Path(META['baseline_route'])
FOCUS = ('slh_128f', 'xmss_h10', 'lms_h10')


def read(path):
    return json.loads(path.read_text())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    state = read(RUN / 'STATE.json')
    assert state['complete'] and state['deployment']['status'] == 'kept_baseline'
    assert state['cleanup']['status'] == 'removed'
    assert not Path(META['temporary_worktree']).exists()
    module = importlib.util.spec_from_file_location('route_resources', ARCHIVE / 'control/run_ablation_route.py')
    helper = importlib.util.module_from_spec(module)
    module.loader.exec_module(helper)
    resources = helper.resources
    validations = {key: read(RUN / 'validation' / key / 'SUMMARY.json') for key in state['validation']}
    assert all(summary['passed'] and summary['source_unchanged'] for summary in validations.values())
    comparisons = []
    for key, entry in sorted(state['routes'].items()):
        label, backend = key.split('/')
        design = entry['design']
        base = BASELINE / 'jobs' / backend / design
        old_route = read(base / 'result.json')
        old_synth = resources(base / 'synth/utilization.rpt')
        old_area = resources(base / 'route/utilization.rpt')
        old_sample = validations['baseline_' + design + '/' + backend]
        new_sample = validations[key]
        all_cycles_equal = all(old_sample['cases'][case]['cycles'] == row['cycles']
                               for case, row in new_sample['cases'].items())
        assert all_cycles_equal
        assert all(old_sample['cases'][case]['hashes'] == row['hashes'] and
                   old_sample['cases'][case]['physical_blocks'] == row['physical_blocks']
                   for case, row in new_sample['cases'].items())
        for p in base.rglob('*'):
            if p.is_file() and p.suffix in ('.rpt', '.json', '.txt', '.log', '.xdc'):
                target = ARCHIVE / 'baseline' / backend / design / p.relative_to(base)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(p, target)
        paths = (RUN / 'routes' / key / 'route/critical_paths.rpt').read_text()
        critical = {name: re.search(pattern, paths)[1].strip() for name, pattern in (
            ('source', r'Source:\s+([^\n]+)'), ('destination', r'Destination:\s+([^\n]+)'),
            ('logic_levels', r'Logic Levels:\s+([^\n]+)'))}
        comparisons.append(dict(candidate=label, design=design, backend=backend,
            baseline_synthesis_area=old_synth, candidate_synthesis_area=entry['synth_area'],
            baseline_routed_area=old_area, candidate_routed_area=entry['route_area'],
            baseline_route=old_route, candidate_route=entry['result'], all_normal_cycles_identical=True,
            area_change_pct=100 * (entry['route_area']['equivalent_slice'] / old_area['equivalent_slice'] - 1),
            sign={profile: dict(cycles=old_sample['cases'][profile + '/sign']['cycles'],
                baseline_atp100_assumed=old_area['equivalent_slice'] * old_sample['cases'][profile + '/sign']['cycles'] / 100000,
                candidate_atp100_assumed=entry['route_area']['equivalent_slice'] * new_sample['cases'][profile + '/sign']['cycles'] / 100000)
                for profile in FOCUS}, critical_path=critical))
    counts = dict(full_operations=sum(len(v['cases']) for v in validations.values()),
                  recipe_groups=sum(1 for v in validations.values() for t in v['tests'].values() if 'recipe_mask' in t),
                  recipe_vectors=sum(t.get('cases', 0) for v in validations.values() for t in v['tests'].values()),
                  synthesis_view_sign=sum(1 for v in validations.values() for name in v['tests'] if name == 'synthesis_slh_128f_sign'))
    assert counts == dict(full_operations=188, recipe_groups=24, recipe_vectors=5662, synthesis_view_sign=10)
    summary = dict(schema='mhbs.idea_migration.final_comparison.v1', complete=True,
                   decision='No candidate adopted; production RTL remains exactly baseline',
                   temporary_worktree_removed=True, validation_counts=counts, comparisons=comparisons,
                   scope='P1U1 common OOC, xc7a200tffg1156-3, Vivado2025.2, 100MHz target, two threads, SYNTHESIS',
                   cycle_sample='Existing deterministic project vectors, one-byte message; not the separate33-byte SLOTH KAT',
                   atp_scope='Routed area times measured cycles at assumed100MHz; physical frequency closure reported independently',
                   measurement_state=state)
    stem = ARCHIVE / 'reports' / ('Idea_Migration_' + META['stamp'])
    stem.with_suffix('.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n')
    (ARCHIVE / 'MEASUREMENT_STATE.json').write_text(json.dumps(state, ensure_ascii=False, indent=2) + '\n')
    lines = ['# 临时优化思路迁移：面积、周期与时序实测', '',
             '结论：所有功能检查通过，但没有候选同时满足两后端的面积／周期和时序取舍条件；**未采用，当前RTL保留原设计**。临时工作区已在完整保全和校验后删除。', '',
             '范围：P1U1、common、单Hash通道、Vivado2025.2、xc7a200tffg1156-3、OOC、SYNTHESIS裁剪统计、每Vivado2线程；100MHz目标，默认时序驱动，通用Keccak。未新增时序例外，未搜索频率。', '',
             '## 面积与布线时序', '',
             '面积均为等效Slice；BRAM/DSP全部为0。综合面积与布线面积分别比较，不交叉借用。', '',
             '| 候选 | 后端 | 综合面积：基线→候选 | 布线面积：基线→候选 | 布线面积变化 | WNS：基线→候选/ns | 候选100MHz |',
             '|---|---|---:|---:|---:|---:|---|']
    for c in comparisons:
        lines.append('| ' + ' | '.join([c['candidate'], c['backend'],
            f'{c["baseline_synthesis_area"]["equivalent_slice"]:,.3f} → {c["candidate_synthesis_area"]["equivalent_slice"]:,.3f}',
            f'{c["baseline_routed_area"]["equivalent_slice"]:,.3f} → {c["candidate_routed_area"]["equivalent_slice"]:,.3f}',
            f'{c["area_change_pct"]:+.3f}%',
            f'{c["baseline_route"]["wns_ns"]:.3f} → {c["candidate_route"]["wns_ns"]:.3f}',
            '通过' if c['candidate_route']['accepted_frequency'] else '未通过']) + ' |')
    lines += ['', '六项候选均完整合法布线，hold≥0、路由错误为0、DRC Error/Critical Warning为0。只有t_shared的SHAKE通过100MHz；其余是setup违例，不能当作100MHz可运行结果。', '',
              '## Sign周期', '', '候选的全部正常操作周期、Hash及实际压缩／置换数均与对应基线一致。三个目标Sign周期如下，使用原项目的确定性1字节消息向量；不是另一个SLOTH比较中的33字节KAT。', '',
              '| 实现／后端 | SLH128f Sign | XMSS h10 Sign | LMS h10 Sign |', '|---|---:|---:|---:|']
    seen = set()
    for c in comparisons:
        key = (c['design'], c['backend'])
        if key not in seen:
            lines.append('| ' + ' | '.join([key[0] + '/' + key[1]] + [f'{c["sign"][p]["cycles"]:,}' for p in FOCUS]) + ' |')
            seen.add(key)
    for profile, title in zip(FOCUS, ('SLH-DSA128f', 'XMSS h10', 'LMS h10')):
        lines += ['', f'## {title}：同频ATP对照', '',
                  '**频率假定100MHz，单位Slice·ms。未闭合的配置仅作同频面积×周期对照，不能解释为已实现的硬件时间／ATP。**', '',
                  '| 候选／后端 | 基线ATP₁₀₀ | 候选ATP₁₀₀ | 变化 |', '|---|---:|---:|---:|']
        for c in comparisons:
            sign = c['sign'][profile]
            lines.append(f'| {c["candidate"]}/{c["backend"]} | {sign["baseline_atp100_assumed"]:,.3f} | {sign["candidate_atp100_assumed"]:,.3f} | {c["area_change_pct"]:+.3f}% |')
    lines += ['', '## 为什么不采用', '',
              '- c_control：SHAKE面积和setup均改善，但SHA2综合面积的下降没有转化为布线面积下降；SHA2布线面积增加0.418%，WNS从−2.776退化到−3.178ns。因此不能将其作为两后端共同改进。',
              '- c_shared：SHAKE综合面积减少4.811%、布线面积减少5.805%，但WNS从−2.997退化到−3.736ns；SHA2也有上述回退。',
              '- i_shared：布线面积只减少0.127%，WNS从−2.949退化到−3.210ns。',
              '- t_shared：100MHz通过、setup裕量增加，但布线面积增加2.141%，周期不变，固定100MHz ATP回退。', '',
              'i/c候选的关键路径仍由group_index经过24～26级逻辑到执行控制／地址寄存器；本轮局部数据通路优化没有打断它。t_shared的关键路径在SHAKE seed_phase到sponge_state，为8级逻辑。详细起终点及路径见JSON与各route/critical_paths.rpt。', '',
              '## 验证与清理', '',
              '188项完整操作实例全部通过；另有24组配方检查，共5,662条向量，及10项SYNTHESIS视图Sign检查。逐字节核对输出和签名缓存，并核对64位Hash及实际压缩／置换计数。h20只做Verify，未执行完整Keygen/Sign。', '',
              '临时目录的24个修改文件、225个未跟踪文件、历史实验及崩溃日志均已保全；10,238份运行文件和210份原始日志保留在本仓库build/retired_worktrees/对应目录。归档省略新仿真明细，只保留验证摘要；原日志仍在build。',
              '临时工作区已通过git worktree remove移除；当前i/c/t生产RTL与本次基线校验完全一致。测量与刷新进程均已退出。', '',
              '[候选源码与设置](../PLAN.json) · [取舍](../SELECTION.json) · [当前RTL校验](../SELECTED_SOURCE.json) · [清理记录](../CLEANUP.json) · [历史保全](../legacy_worktree/PRESERVATION_SUMMARY.json) · [证据清单](../ARTIFACTS.json)', '']
    stem.with_suffix('.md').write_text('\n'.join(lines))
    for name in ('SOURCE.json', 'frozen_rtl.tar.gz'):
        shutil.copyfile(Path(read(BASELINE / 'SOURCE.json')['archive']) / name, ARCHIVE / ('baseline_route_' + name))
    print(stem.with_suffix('.md'))
    print(counts)


if __name__ == '__main__':
    main()
