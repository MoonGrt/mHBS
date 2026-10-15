#!/usr/bin/env python3
"""Archive actual-RTL arbiter equivalence and compare frozen SHA2 candidates."""
import argparse
from pathlib import Path
import json
import time

import experiment_archive as archive
from report_sha2_optimization import sha, read, write, hierarchy, paths


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run', type=Path)
    parser.add_argument('--validation', type=Path, required=True)
    args = parser.parse_args()
    run, local = args.run.resolve(), args.validation.resolve()
    meta, state = read(run/'SOURCE.json'), read(run/'status.json')
    previous_run = Path(meta['comparison_run'])
    previous_meta, previous = read(previous_run/'SOURCE.json'), read(previous_run/'status.json')
    out, previous_out = Path(meta['archive_directory']), Path(previous_meta['archive_directory'])
    root = Path(__file__).resolve().parents[1]
    files = {}
    for name in ('RESULTS.json', 'VALIDATION.json'):
        path = local/name
        data = read(path)
        assert data['source_unchanged'] and data['passed'] and data['source_before'] == data['source_after']
        sources = {}
        for n, h in data['source_after'].items():
            if n in meta['sha256']:
                assert meta['sha256'][n] == h
                assert sha(Path(meta['source_root'])/n) == h
            else:
                assert sha(root/n) == h
                target = out/'prerequisites/source'/n
                archive.copy_changed(root/n, target)
                sources[n] = h
        if name == 'RESULTS.json':
            assert data['compile_returncode'] == data['run_returncode'] == 0
            assert 'ARBITER_ALL_PASS' in data['markers']
            for n, h in data['log_sha256'].items(): assert sha(local/n) == h
            assert sha(local/'run.py') == data['runner_sha256']
            archive.copy_changed(local/'run.py', out/'prerequisites/source/run.py')
            sources['run.py'] = data['runner_sha256']
        else:
            assert data['complete'] and len(data['cases']) == 6
            for case in data['cases']:
                assert case['returncode'] == 0 and case['passed'] and case.get('cycle_equivalent', True)
                assert sha(root/case['log']) == case['log_sha256']
        archive.copy_changed(path, out/'prerequisites'/name)
        files[name] = dict(sha256=sha(path), frozen_source_match=True, log_checksums_verified=True,
                          supplemental_sources=sources)
    archive.copy_changed(local/'SUMMARY.md', out/'prerequisites/SUMMARY.md')
    for name in ('report_sha2_arbiter.py', 'report_sha2_optimization.py', 'experiment_archive.py'):
        archive.copy_changed(root/'scripts'/name, out/'analysis_tools'/name)
    write(out/'ANALYSIS_SOURCE.json', {p.name:sha(p) for p in (out/'analysis_tools').iterdir()})
    write(out/'prerequisites/MANIFEST.json', dict(candidate_source_manifest_sha256=sha(run/'SOURCE.json'),
          files=files, detailed_logs_archived=False,
          previous_candidate_evidence=dict(path=str(previous_out/'prerequisites'),
              source_manifest_sha256=sha(previous_run/'SOURCE.json'), rerun_on_candidate2=False)))
    rows = []
    for config in ('P1U1', 'P4U1', 'P12U1'):
        old, new = previous['synthesis'][config], state['synthesis'][config]
        old_folder = previous_run/'synth'/config
        row = dict(configuration=config, previous_area=old['area'], previous_timing=old['timing'],
                   previous_hierarchy=hierarchy(old_folder/'hierarchical.rpt'),
                   previous_paths=paths(old_folder/'critical_paths.rpt'), status=new['status'])
        if new['status'] == 'passed':
            folder = run/'synth'/config
            row.update(area=new['area'], timing=new['timing'], hierarchy=hierarchy(folder/'hierarchical.rpt'),
                       paths=paths(folder/'critical_paths.rpt'),
                       area_change_pct=100*(new['area']['equivalent_slice']/old['area']['equivalent_slice']-1),
                       path_change_pct=100*(new['timing']['data_path_ns']/old['timing']['data_path_ns']-1))
        rows.append(row)
    fmt = lambda x: '—' if x is None else f'{x:,.3f}'
    lines = ['# SHA2 轮询仲裁候选2', '',
        '候选1使用共享64位／128位固定窗口消除了大部分逐字节格式化逻辑。候选2继续处理P12U1的'
        '`need_block→标签选择→长度／掩码控制`路径：以游标后的资格掩码、最低有效位选择和one-hot编码替换'
        '动态环形索引扫描，保留原轮询顺序和寄存边界。只修改sha2-recipe.sv的仲裁与声明位置，不改变格式化数据路径。', '',
        f'候选2recipe SHA256：`{meta["sha256"]["rtl/hash/sha2-recipe.sv"]}`。', '',
        f'完整Sign：{state["counts"]}；逐点周期核对：{state.get("previous_candidate_equivalence")}。', '',
        '| 配置 | 候选1 Slice | 候选2 Slice | 面积变化 % | 候选1路径 ns | 候选2路径 ns | 候选2WNS ns | 状态 |',
        '|---|---:|---:|---:|---:|---:|---:|---|']
    for row in rows:
        lines.append('| ' + ' | '.join([row['configuration'], fmt(row['previous_area']['equivalent_slice']),
            fmt(row.get('area',{}).get('equivalent_slice')), fmt(row.get('area_change_pct')),
            fmt(row['previous_timing']['data_path_ns']), fmt(row.get('timing',{}).get('data_path_ns')),
            fmt(row.get('timing',{}).get('wns_ns')), row['status']]) + ' |')
    lines += ['', '面积均为同配置common，等效Slice = LUT/4 + FF/8 + 232.4×BRAM36 + 102.4×DSP。'
        '报告固定100MHz假定ATP；综合路径只是低频诊断，尚无本轮布局布线结论。', '',
        '本候选重新验证实际生产RTL仲裁：P1/2/3/4/6/8/12全部合法游标与请求掩码穷举，P24为边界和固定种子随机测试，'
        '共306,754组，检查valid、标签及one-hot选择。它是两态组合等价检查，未覆盖不可达游标或X传播。'
        '另有P4U1/P12U1/P4U2共36组批配方及P4U1三目标完整Sign通过；局部P12批测试使用4个同时活动标签，'
        '全核P12 Sign按真实上下文调度另外测量。', '',
        '候选1的764项配方、9项鲁棒性、4条ACVP签名及3个SYNTHESIS Sign证据仍归属候选1的源码，'
        '本轮未重跑这些集合，不把其结果改记到候选2。两候选的SHA256、SHAKE和executor源码相同；'
        '既有双后端长回归继续后台运行，h20完整Keygen／Sign未启动。', '',
        f'逐算法周期、原始基线ATP以及候选1的逐点对照见[测量报告](SHA2_Optimization_{meta["run_id"]}.md)。', '',
        f'候选1完整验证见[候选1分析](../../{previous_out.name}/reports/SHA2_Formatter_Analysis_{previous_meta["run_id"]}.md)。', '']
    selection = read(out/'FINAL_SELECTION.json') if (out/'FINAL_SELECTION.json').exists() else None
    if selection:
        lines += ['', '最终取舍：撤回候选2，保留全部冻结证据，工作区恢复候选1。详见[阶段记录](SHA2_Optimization_Stages.md)及FINAL_SELECTION.json。', '']
    prefix = out/'reports'/f'SHA2_Arbiter_Analysis_{meta["run_id"]}'
    archive.atomic(prefix.with_suffix('.md'), '\n'.join(lines))
    write(prefix.with_suffix('.json'), dict(candidate_manifest_sha256=sha(run/'SOURCE.json'),
        previous_manifest_sha256=sha(previous_run/'SOURCE.json'), complete=state['complete'],
        rows=rows, cycle_equivalence=state.get('previous_candidate_equivalence'),
        local_validation=files, prior_full_validation_rerun=False, final_selection=selection))
    if state['complete']:
        path = out/'ARTIFACTS.json'
        for _ in range(30):
            artifacts = read(path)
            if artifacts['complete']: break
            time.sleep(1)
        else: raise RuntimeError('Matrix final archive publication incomplete')
        artifacts['sha256'] = {str(p.relative_to(out)):sha(p) for p in out.rglob('*')
                              if p.is_file() and p.name!='ARTIFACTS.json' and not p.name.endswith('.tmp')}
        write(path,artifacts)
    archive.index()


if __name__ == '__main__': main()
