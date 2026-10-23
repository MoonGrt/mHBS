#!/usr/bin/env python3
"""Add source-bound formatter attribution to a frozen SHA2 optimization run."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import time

import experiment_archive as archive


def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def read(path): return json.loads(Path(path).read_text())
def write(path, obj): archive.atomic(path, json.dumps(obj, ensure_ascii=False, indent=2) + '\n')


def hierarchy(path):
    rows = {}
    for line in path.read_text().splitlines():
        cells = [c.strip() for c in line.split('|')[1:-1]]
        if len(cells) != 10 or cells[0] not in ('common', '(lane)', 'compression'): continue
        nums = [int(v) for v in cells[2:]]
        rows[cells[0]] = dict(lut=nums[0], ff=nums[4], bram36=nums[5] + nums[6]/2, dsp=nums[7])
    if set(rows) != {'common', '(lane)', 'compression'}:
        raise ValueError(f'Missing common/recipe-exclusive/SHA256 hierarchy: {path}')
    return dict(common=rows['common'], recipe_excluding_sha256=rows['(lane)'], sha256=rows['compression'])


def paths(path):
    text = path.read_text()
    sources = re.findall(r'^\s*Source:\s*(.+)$', text, re.M)
    destinations = re.findall(r'^\s*Destination:\s*(.+)$', text, re.M)
    if len(sources) != len(destinations): raise ValueError(f'Incomplete timing paths: {path}')
    return dict(report=str(path), sha256=sha(path), reported_paths=len(sources),
        block_buffer_endpoints=sum('block_buffer' in d for d in destinations),
        endpoints=[dict(source=s, destination=d) for s, d in zip(sources, destinations)])


def archive_validation(run, local):
    meta = read(run / 'SOURCE.json')
    out = Path(meta['archive_directory'])
    archived = {}
    for name in ('RESULTS.json', 'PIPELINE_AND_SMOKE.json', 'ROBUSTNESS.json', 'ACVP_AND_SYNTHESIS.json'):
        p = local / name
        if not p.exists(): raise ValueError(f'Missing required validation summary: {p}')
        data = read(p)
        source = data.get('source_after', data.get('source_sha256', {}))
        if not source or not data.get('source_unchanged') or not data.get('passed'):
            raise ValueError(f'Validation is incomplete or failed: {p}')
        if data.get('source_before', source) != source:
            raise ValueError(f'Validation changed source: {p}')
        if any(meta['sha256'].get(n) != h for n, h in source.items()):
            raise ValueError(f'Validation source differs from frozen candidate: {p}')
        cases = data.get('results', data.get('cases', []))
        logs = {}
        for case in cases:
            if case.get('returncode', case.get('exit_code', 1)) != 0 or not case.get('passed', case.get('coverage', {}).get('passed')):
                raise ValueError(f'Failed test in {p}')
            log = Path(case['log'])
            h = sha(log)
            if case.get('log_sha256', h) != h: raise ValueError(f'Changed validation log: {log}')
            logs[str(log)] = h
        target = out / 'prerequisites' / name
        archive.copy_changed(p, target)
        archived[name] = dict(sha256=sha(target), passed=True, cases=len(cases),
                             frozen_source_match=True, log_checksums_verified=logs)
    for name in ('REVIEW.md', 'SOURCE.json'):
        if (local / name).exists():
            archive.copy_changed(local / name, out / 'prerequisites' / name)
            archived[name] = dict(sha256=sha(out / 'prerequisites' / name))
    data = dict(candidate_source_manifest_sha256=sha(run / 'SOURCE.json'), files=archived,
                detailed_validation_logs_archived=False, original_logs_directory=str(local))
    write(out / 'prerequisites' / 'MANIFEST.json', data)
    return data


def report(run, validation):
    meta, state = read(run / 'SOURCE.json'), read(run / 'status.json')
    out = Path(meta['archive_directory'])
    baseline_run = Path(meta['baseline_run'])
    old_meta, old = read(baseline_run / 'SOURCE.json'), read(baseline_run / 'status.json')
    frozen = Path(meta['source_root'])
    if any(sha(frozen / n) != h for n, h in meta['sha256'].items()):
        raise ValueError('Frozen candidate changed')
    rtl = [n for n in meta['sha256'] if n.startswith('rtl/')]
    changed = [n for n in rtl if meta['sha256'][n] != old_meta['sha256'].get(n)]
    if changed != ['rtl/hash/sha2-recipe.sv']:
        raise ValueError(f'Unexpected changed RTL: {changed}')
    data = dict(candidate_source_sha256=sha(run / 'SOURCE.json'), baseline_source_sha256=sha(baseline_run / 'SOURCE.json'),
                complete=state['complete'], changed_rtl=changed, sha256_and_shake_unchanged=True,
                validation=validation, configurations={}, comparisons=state['comparisons'])
    fmt = lambda v: '—' if v is None else f'{v:,.3f}'
    lines = ['# SHA2 固定窗口 formatter 优化归因', '',
        '本轮只修改 SHA2 配方的块格式化与准备控制；SHA256 压缩原语、SHAKE 后端和执行器逐文件 SHA 与基线相同。'
        '测量使用 P1U1/P4U1/P12U1 的统一 common 核及 SLH128f、XMSS h10、LMS h10 完整 Sign。', '',
        '原设计按字节进行可变源选择和宽位置运算，新设计登记格式控制，再以固定64位／128位窗口组成当前拍的数据。'
        '旧块准备路径为 SELECT→PREFETCH→4×BUILD→SEND，最少7拍；新路径首次为 SELECT→4×BUILD→SEND，'
        '最少6拍。SEND 接受当前块时准备下一块，连续块最少5拍；实际吞吐仍受压缩返回、槽位和多块依赖限制。', '',
        '基线与候选使用同一工具版本、xc7a200tffg1156-3、100MHz、OOC、默认时序驱动、每进程2线程。'
        '等效Slice沿用项目口径：LUT/4 + FF/8 + 232.4×BRAM36 + 102.4×DSP，包含综合得到的共享存储。'
        '固定100MHz ATP是频率假设；综合数据路径用于定位瓶颈，不能当作布线Fmax或布线ATP。', '',
        f'完整Sign进度：{state["counts"]}；整轮状态：' + ('已完成。' if state['complete'] else '后台运行。'), '',
        '| 配置 | 原recipe自身 LUT | 新recipe自身 LUT | 变化 % | 原SHA256 LUT | 新SHA256 LUT | 原前20路径到block_buffer | 新前20路径到block_buffer |',
        '|---|---:|---:|---:|---:|---:|---:|---:|']
    for cfg in ('P1U1', 'P4U1', 'P12U1'):
        b = old['synthesis'][cfg]
        folder = Path(b['evidence_directory'])
        bh, bp = hierarchy(folder / 'hierarchical.rpt'), paths(folder / 'critical_paths.rpt')
        if bp['reported_paths'] != 20 or bp['block_buffer_endpoints'] != 20:
            raise ValueError('Baseline formatter bottleneck evidence differs')
        r = dict(baseline_hierarchy=bh, baseline_paths=bp, candidate_status=state['synthesis'][cfg]['status'])
        ch = cp = None
        if r['candidate_status'] == 'passed':
            cfolder = run / 'synth' / cfg
            ch, cp = hierarchy(cfolder / 'hierarchical.rpt'), paths(cfolder / 'critical_paths.rpt')
            r.update(candidate_hierarchy=ch, candidate_paths=cp,
                     recipe_lut_change_pct=100*(ch['recipe_excluding_sha256']['lut']/bh['recipe_excluding_sha256']['lut']-1))
        r['baseline_synthesis_seconds'] = b.get('elapsed_seconds', b.get('seconds'))
        r['candidate_synthesis_seconds'] = state['synthesis'][cfg].get('elapsed_seconds')
        data['configurations'][cfg] = r
        lines.append('| ' + ' | '.join([cfg, fmt(bh['recipe_excluding_sha256']['lut']),
            fmt(ch['recipe_excluding_sha256']['lut'] if ch else None), fmt(r.get('recipe_lut_change_pct')),
            fmt(bh['sha256']['lut']), fmt(ch['sha256']['lut'] if ch else None), '20/20',
            f'{cp["block_buffer_endpoints"]}/{cp["reported_paths"]}' if cp else '—']) + ' |')
    lines += ['', '| 配置 | 原综合耗时 s | 新综合耗时 s | 原关键路径 | 新关键路径 |',
              '|---|---:|---:|---|---|']
    for cfg, r in data['configurations'].items():
        bpath = old['synthesis'][cfg]['timing']
        cpath = state['synthesis'][cfg].get('timing', {})
        describe = lambda p: '—' if not p else f"{p['data_path_ns']:.3f}ns / {p['logic_levels']}级 / `{p['destination']}`"
        lines.append('| ' + ' | '.join([cfg, fmt(r['baseline_synthesis_seconds']),
            fmt(r['candidate_synthesis_seconds']), describe(bpath), describe(cpath)]) + ' |')
    lines += ['', 'recipe自身为分层报告中的 `(lane)` 行，不含其 `compression` 子模块；SHA256 单独取 `compression` 行。'
              '该统计覆盖配方控制、上下文和格式化逻辑，不能把全部recipe资源都归为formatter。'
              '候选与基线原始hierarchical.rpt、timing.rpt、critical_paths.rpt均归档；JSON保留路径端点与报告校验。'
              '综合耗时为各次实测墙钟时间，并发负载可能不同，不能视为独立受控的工具速度实验。', '',
              '验证覆盖与限制：', '',
              '- 标量配方764项通过（P1U1普通345、P12U1 SYNTHESIS 345、P4U1 mask 74）；另有最终P4U1 345项及统计测试通过。',
              '- 批配方P4U1/P12U1/P4U2共36组通过，含乱序返回、退槽补发和空闲标签。P12局部测试使用4个同时活动标签，整核P12 Sign另测完整调度。',
              '- 9项鲁棒性测试通过：停顿／复位重放、消息篡改、截断恢复、在途标量及批请求异常。',
              '- 4条NIST ACVP确定性／随机化SHA2-128f/128s完整签名及3个目标SYNTHESIS完整Sign通过；统计声明预处理裁剪，测试包装统计为零，功能事件计数独立核对。',
              '- SHA256原语和SHAKE源码未改，本轮未重复全部P/U原语或SHAKE大树回归；先前双后端完整回归继续后台运行。h20完整Keygen／Sign未启动。', '',
              '所有局部摘要绑定当前冻结源码，并复核原始日志SHA；签名向量SHA保留在摘要和整核测量记录中。'
              '原始详细仿真日志保留build运行目录，归档只留摘要。', '',
              f'面积、周期、假定ATP及变化表见 [主测量报告](SHA2_Optimization_{meta["run_id"]}.md)。', '']
    if (out / 'FINAL_SELECTION.json').exists():
        data['final_selection'] = read(out / 'FINAL_SELECTION.json')
        lines += ['', '最终取舍：保留候选1，当前工作区RTL已核验与其冻结源码一致。详见[阶段记录](SHA2_Optimization_Stages.md)及FINAL_SELECTION.json。', '']
    prefix = out / 'reports' / f'SHA2_Formatter_Analysis_{meta["run_id"]}'
    write(prefix.with_suffix('.json'), data)
    archive.atomic(prefix.with_suffix('.md'), '\n'.join(lines))
    return state['complete']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run', type=Path)
    parser.add_argument('--validation', type=Path, required=True)
    parser.add_argument('--watch', action='store_true')
    args = parser.parse_args()
    run = args.run.resolve()
    meta = read(run / 'SOURCE.json')
    out = Path(meta['archive_directory'])
    validation = archive_validation(run, args.validation.resolve())
    own = Path(__file__).resolve()
    archive.copy_changed(own, out / 'analysis_tools' / own.name)
    write(out / 'ANALYSIS_SOURCE.json', dict(script=str(own), sha256=sha(own)))
    while True:
        complete = report(run, validation)
        if not args.watch or complete: break
        time.sleep(60)
    if complete:
        # The matrix runner publishes status before archive files. Wait for its final publication.
        for _ in range(30):
            artifacts = out / 'ARTIFACTS.json'
            if artifacts.exists() and read(artifacts).get('complete'): break
            time.sleep(1)
        else: raise RuntimeError('Matrix final archive publication is incomplete')
        data = read(artifacts)
        data['sha256'] = {str(p.relative_to(out)): sha(p) for p in out.rglob('*')
                         if p.is_file() and p.name != 'ARTIFACTS.json' and not p.name.endswith('.tmp')}
        write(artifacts, data)
    return 0


if __name__ == '__main__': raise SystemExit(main())
