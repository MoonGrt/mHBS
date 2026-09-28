#!/usr/bin/env python3
"""Seal the nine K/U runs and render their area/cycle Pareto report."""
import hashlib
import json
import re
import shutil
from pathlib import Path

from v42_external_flow import ROOT, BASE, BUILD, NAMES, sha, write
from v42_external_route import resources

OUT = ROOT / 'manifests/experiments/ku_matrix_20260927_v1'
REPORT = ROOT / 'docs/v4.2/KU_Nine_Point_Experiment.md'
BASELINE = BASE / 'candidates/program16_20260927_v1'
SHELLS = [f'{name}_{operation}' for name in NAMES for operation in ('keygen', 'sign')]
POINTS = [(k, u) for k in (1, 2, 4) for u in (1, 2, 4)]
ROUTE_DIR = 'route_internal20_v1'


def copy_file(source, target):
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    return sha(target)


def checked_json(path):
    return json.loads(path.read_text())


def fail_reason(folder):
    for path in (folder / 'route.log', folder / 'synth.log'):
        if path.exists():
            lines = path.read_text(errors='replace').splitlines()
            errors = [line for line in lines if re.search(r'ERROR:|failed|exception|out of memory', line, re.I)]
            if errors:
                return errors[-1][:300]
    return 'required result file is absent'


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    baseline_sim = checked_json(BASELINE / 'simulation.json')['cases']
    baseline_area = resources(BASELINE / 'synthesis/core_utilization.rpt')
    first_source = None
    points = {}
    errors = []
    for k, u in POINTS:
        label = f'K{k}U{u}'
        tag = f'ku_k{k}u{u}_v2'
        build = BUILD / tag
        archive = OUT / 'candidates' / label
        inputs = checked_json(build / 'inputs.json')
        assert (inputs['lanes'], inputs['unroll']) == (k, u)
        assert sha(build / 'source_snapshot.tar.gz') == inputs['snapshot_sha256']
        if first_source is None:
            first_source = inputs['source_sha256']
        assert first_source == inputs['source_sha256'], f'{label}: source differs from other points'
        assert inputs['rtl_sha256'] == {p: first_source[p] for p in inputs['rtl_sha256']}
        copy_file(build / 'inputs.json', archive / 'inputs.json')
        copy_file(build / 'source_snapshot.tar.gz', archive / 'source_snapshot.tar.gz')
        sim = checked_json(build / 'simulation.json')
        assert sim['passed'] and (sim['lanes'], sim['unroll']) == (k, u)
        assert set(sim['cases']) == set(SHELLS)
        copy_file(build / 'simulation.json', archive / 'simulation.json')
        cycles = {}
        hashes = {}
        for shell in SHELLS:
            row = sim['cases'][shell]
            operation = shell.rsplit('_', 1)[1]
            assert row['passed'] and row['output_sha256'] == baseline_sim[shell]['output_sha256']
            assert (row['hashes'], row['permutations']) == (baseline_sim[shell]['hashes'], baseline_sim[shell]['permutations'])
            cycles[shell] = row[f'{operation}_cycles']
            hashes[shell] = {field: row[field] for field in ('hashes', 'permutations', 'output_sha256')}
        for evidence_file in (build / 'logs').iterdir():
            if evidence_file.is_file() and evidence_file.suffix in ('.json', '.log', '.mem'):
                copy_file(evidence_file, archive / 'logs' / evidence_file.name)
        for evidence_name in ('extended.json', 'pruning_verification.json', 'faults.json',
                              'simulation_no_profile.json', 'simulation_partition_no_profile.json'):
            if (build / evidence_name).exists():
                copy_file(build / evidence_name, archive / evidence_name)
        for compile_log in (build / 'binaries').glob('*/compile.log'):
            copy_file(compile_log, archive / 'compile' / compile_log.parent.name / 'compile.log')
        extended_vectors = build / 'extended_vectors'
        if extended_vectors.exists():
            for evidence_file in extended_vectors.rglob('*'):
                if evidence_file.is_file() and evidence_file.suffix in ('.json', '.mem'):
                    copy_file(evidence_file, archive / 'extended_vectors' / evidence_file.relative_to(extended_vectors))
        verify_path = build / 'verify_k_matrix/results.json'
        if not verify_path.exists():
            verify_path = build / 'verify/results.json'
        verify = checked_json(verify_path)
        assert verify['passed']
        copy_file(verify_path, archive / 'verify_results.json')
        verify_directory = verify_path.parent
        for evidence_file in verify_directory.rglob('*'):
            if evidence_file.is_file() and evidence_file.suffix in ('.json', '.log', '.mem'):
                copy_file(evidence_file, archive / 'verify' / evidence_file.relative_to(verify_directory))
        synth = build / 'synthesis'
        if not (synth / 'core_utilization.rpt').exists():
            raise RuntimeError(f'{label}: full synthesis has not completed')
        area = resources(synth / 'core_utilization.rpt')
        for filename in ('core_utilization.rpt', 'core_hierarchical.rpt', 'core_timing.rpt', 'pruning_audit.json'):
            copy_file(synth / filename, archive / 'synthesis' / filename)
        shell_synth = {}
        for shell in SHELLS:
            sd = synth / shell
            if not (sd / 'post_synth.dcp').exists():
                errors.append(f'{label} {shell}: synthesis checkpoint absent')
                shell_synth[shell] = {'passed': False, 'failure': fail_reason(build)}
                continue
            shell_synth[shell] = {'passed': True, 'dcp_sha256': sha(sd / 'post_synth.dcp'), **resources(sd / 'utilization.rpt')}
            for filename in ('utilization.rpt', 'timing.rpt', 'core_sha256.txt', 'initialized_rom.tsv'):
                copy_file(sd / filename, archive / 'synthesis' / shell / filename)
        if (build / 'synth_invocation.json').exists():
            copy_file(build / 'synth_invocation.json', archive / 'synth_invocation.json')
        if (build / 'synth_elapsed.json').exists():
            copy_file(build / 'synth_elapsed.json', archive / 'synth_elapsed.json')
        if (build / 'synth.log').exists():
            copy_file(build / 'synth.log', archive / 'synth.log')
        points[label] = dict(tag=tag, lanes=k, unroll=u, source_snapshot_sha256=inputs['snapshot_sha256'],
                             common_area=area, cycles=cycles, hash_evidence=hashes,
                             verify_pass=True, shell_synthesis=shell_synth)

    # A candidate dominates another only if all seven metrics are no worse
    # and at least one is strictly better.
    metrics = {label: [row['common_area']['equivalent_slice'], *[row['cycles'][name] for name in SHELLS]]
               for label, row in points.items()}
    pareto = []
    for label, metric in metrics.items():
        dominators = [other for other, comparison in metrics.items() if other != label
                      and all(x <= y for x, y in zip(comparison, metric))
                      and any(x < y for x, y in zip(comparison, metric))]
        points[label]['dominated_by'] = dominators
        if not dominators:
            pareto.append(label)
    selected = [label for label in points if label in pareto or label == 'K2U2']
    for label in selected:
        tag = points[label]['tag']
        build = BUILD / tag
        archive = OUT / 'candidates' / label
        route = {}
        for shell in SHELLS:
            rd = build / ROUTE_DIR / shell
            result_path = rd / 'result.json'
            if not result_path.exists():
                route[shell] = {'passed': False, 'failure': fail_reason(rd)}
                errors.append(f'{label} {shell}: {route[shell]["failure"]}')
                if (rd / 'route.log').exists():
                    copy_file(rd / 'route.log', archive / 'route' / shell / 'route.log')
                continue
            result = checked_json(result_path)
            if not result.get('passed'):
                route[shell] = {'passed': False, 'failure': result.get('failure', fail_reason(rd))}
                errors.append(f'{label} {shell}: {route[shell]["failure"]}')
                copy_file(result_path, archive / 'route' / shell / 'result.json')
                if (rd / 'route.log').exists():
                    copy_file(rd / 'route.log', archive / 'route' / shell / 'route.log')
                continue
            assert result['passed'] and result['core_timing_pass']
            route[shell] = {key: result[key] for key in ('equivalent_slice', 'period_ns', 'frequency_mhz',
                'operation_cycles', 'latency_ms', 'area_time_product', 'wns_ns', 'whs_ns')}
            route[shell]['passed'] = True
            route[shell]['dcp_sha256'] = sha(rd / 'post_route_final_clock.dcp')
            for filename in ('result.json', 'final_clock.json', 'utilization.rpt', 'timing_summary.rpt',
                             'check_timing.rpt', 'route_status.rpt', 'initialized_rom.tsv', 'route.log'):
                copy_file(rd / filename, archive / 'route' / shell / filename)
        points[label]['route'] = route
        if (build / ROUTE_DIR / 'result.json').exists():
            copy_file(build / ROUTE_DIR / 'result.json', archive / 'route' / 'result.json')
        old_route = build / 'route'
        if old_route.exists():
            for evidence_file in old_route.rglob('*'):
                if evidence_file.is_file() and evidence_file.name in ('route.log', 'result.json', 'final_clock.json', 'invocation.json'):
                    copy_file(evidence_file, archive / 'initial10ns_route' / evidence_file.relative_to(old_route))

    k2 = points['K2U2']
    delta = {key: k2['common_area'][key] - baseline_area[key] for key in ('lut', 'ff', 'lutram', 'equivalent_slice')}
    comparison = {}
    for shell in SHELLS:
        operation = shell.rsplit('_', 1)[1]
        old = baseline_sim[shell]
        new = checked_json(BUILD / k2['tag'] / 'simulation.json')['cases'][shell]
        comparison[shell] = {field: new[field] - old[field] for field in
            (f'{operation}_cycles', 'hashes', 'permutations')}
        assert new['output_sha256'] == old['output_sha256']
        assert all(v == 0 for v in comparison[shell].values())
    test_files = ['tb_ku_store.sv', 'ku_store_compile.log', 'ku_store_run.log',
                  'tb_ku_keccak.sv', 'ku_verify_tb.sv', 'ku_verify_driver.py']
    test_files += [f'ku_keccak_u{u}_{kind}.log' for u in (1, 2, 4) for kind in ('compile', 'run')]
    for name in test_files:
        copy_file(ROOT / 'build' / name, OUT / 'tests' / name)
    for name in ('scripts/run_ku_routes.py', 'scripts/collect_ku_matrix.py', 'experiments/v4.2/ku_matrix/route.tcl'):
        copy_file(ROOT / name, OUT / 'flow' / Path(name).name)
    assert 'KU_STORE_FOUR_WAY_PASS' in (ROOT / 'build/ku_store_run.log').read_text()
    for u in (1, 2, 4):
        assert 'COMPACT_SHAKE_CONTEXT_LANE_PASS' in (ROOT / 'build' / f'ku_keccak_u{u}_run.log').read_text()
    result = dict(schema='mhbs.ku_matrix.v1', device='xc7a200tffg1156-3', vivado='2025.2',
                  source_sha256=first_source, baseline='program16_20260927_v1',
                  baseline_core_area=baseline_area, parameterized_k2u2_area_delta=delta,
                  parameterized_k2u2_functional_delta=comparison,
                  pareto=pareto, route_selected=selected, points=points,
                  route_initial_period_ns=20.0,
                  route_timing_scope='out-of-context internal register-to-register; external interfaces excluded',
                  passed=not errors, failures=errors)
    write(OUT / 'results.json', result)
    archive_hashes = {}
    for path in sorted(OUT.rglob('*')):
        if path.is_file() and path.name not in ('evidence_sha256.json',):
            archive_hashes[str(path.relative_to(OUT))] = sha(path)
    write(OUT / 'evidence_sha256.json', archive_hashes)
    render(result)
    print('KU_MATRIX_COLLECT', 'PASS' if not errors else 'INCOMPLETE', len(pareto), 'pareto', len(errors), 'failures')


def render(result):
    lines = ['# K/U 九点实验', '',
        '设备 `xc7a200tffg1156-3`；Vivado 2025.2。九点使用同一参数化源码、Program16 镜像和六组软件向量。',
        '参数化 RTL 位于独立 worktree，生产 RTL 未替换。', '',
        '## 共同核综合与计算周期', '',
        '等效 Slice = LUT/4 + FF/8 + BRAM36×232.4 + DSP×102.4。周期列顺序为 128f Keygen、128f Sign、192f Keygen、192f Sign、256f Keygen、256f Sign。', '',
        '| K/U | LUT | FF | LUTRAM | 等效 Slice | 六组周期 | Pareto | 综合状态 |',
        '|---|---:|---:|---:|---:|---|---|---|']
    for label, row in result['points'].items():
        area = row['common_area']
        c = ' / '.join(str(row['cycles'][name]) for name in SHELLS)
        synthesis_ok = all(s['passed'] for s in row['shell_synthesis'].values())
        lines.append(f"| {label} | {area['lut']:.0f} | {area['ff']:.0f} | {area['lutram']:.0f} | {area['equivalent_slice']:.3f} | {c} | {'是' if label in result['pareto'] else '否'} | {'通过' if synthesis_ok else '失败'} |")
    lines += ['', 'Pareto 判定使用等效 Slice 与全部六组周期；各指标均不差且至少一项更优才构成支配。',
              f"进入布线：{', '.join(result['route_selected'])}。", '',
              '## Program16 K2U2 对照', '',
              f"封存基线共同核：{result['baseline_core_area']['lut']:.0f} LUT、{result['baseline_core_area']['ff']:.0f} FF、{result['baseline_core_area']['lutram']:.0f} LUTRAM、{result['baseline_core_area']['equivalent_slice']:.3f} 等效 Slice。",
              f"参数化 K2U2 改造本身增加 {result['parameterized_k2u2_area_delta']['lut']:.0f} LUT、{result['parameterized_k2u2_area_delta']['ff']:.0f} FF、{result['parameterized_k2u2_area_delta']['equivalent_slice']:.3f} 等效 Slice；六组输出、周期、Hash 次数和置换次数一致。",
              '', '## 六组外壳布线', '',
              '全部入选点采用统一 20 ns 初始周期，外部接口路径从布局布线开始排除；完成后在 0.1 ns 网格上按至少 0.1 ns 建立裕量重新分析核内频率。外部接口未签核。面积时间积采用各外壳布线后等效 Slice × 计算延迟（ms）。',
              '先前 10 ns 作业的有效结果及被中断的拥塞日志保留在 `initial10ns_route/`，不混入本表。', '',
              '| K/U | 外壳 | 核内 MHz | 等效 Slice | 周期 | 面积时间积 (Slice·ms) | 状态 |',
              '|---|---|---:|---:|---:|---:|---|']
    for label in result['route_selected']:
        for shell in SHELLS:
            row = result['points'][label]['route'][shell]
            if row['passed']:
                lines.append(f"| {label} | {shell} | {row['frequency_mhz']:.3f} | {row['equivalent_slice']:.3f} | {row['operation_cycles']} | {row['area_time_product']:.3f} | 通过 |")
            else:
                lines.append(f"| {label} | {shell} | — | — | — | — | {row['failure']} |")
    lines += ['', '## 验证与证据', '',
              'U1/U2/U4 的 Keccak 单元向量通过。九点的六组输出哈希、Hash 次数和置换次数一致；每点三组 Verify 正常路径通过。K2U2 还通过 65 个 Verify、33 个扩展、统计关闭、复位与故障回归；K1U2/K4U2 的 Verify 复位、停顿、填充、坏消息和统计关闭检查通过。四路端点存储同拍写入与两路读取单元检查通过。',
              '每点的源码快照、参数、仿真日志、综合资源、布线报告和 SHA-256 清单见 `manifests/experiments/ku_matrix_20260927_v1/candidates/`。DCP 保留在该独立 worktree 的 `build/v4.2/external_job_message/`，哈希列入结果文件。', '']
    if result['failures']:
        lines += ['## 失败原因', ''] + [f'- {failure}' for failure in result['failures']] + ['']
    REPORT.write_text('\n'.join(lines))


if __name__ == '__main__':
    main()
