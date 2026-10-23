#!/usr/bin/env python3
"""Separate software-loop optimization from control-granularity measurements."""
from pathlib import Path
from datetime import datetime
import hashlib
import json

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
LATEST = ROOT / 'tmp/sloth_ict_cycle_comparison_latest'


def read(path):
    return json.loads(path.read_text())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    audit = read(HERE / 'DATA_AUDIT.json')
    assert audit['passed'], 'Independent controlled-input audit must pass'
    latest = read(LATEST / 'cycle_breakdown_data.json')
    rows, comparisons, workload = [], [], []
    for backend in ('shake', 'sha2'):
        existing = {r['design']:dict(r,source=str((LATEST/r['source']).relative_to(ROOT)),
                                    source_scope='repository-relative')
                    for r in latest['rows'] if r['backend'] == backend}
        path = HERE / 'profile/i_generic' / backend / 'result.json'
        generic = read(path)
        assert generic['status'] == 'passed' and generic['message_bytes'] == 33
        assert generic['total'] == generic['hash'] + generic['transfer'] + generic['remaining']
        assert generic['signature_cache_and_kat_match']
        assert all(generic[k] == existing['i'][k] for k in ('hash','hash_count','physical_blocks',
                                                          'logical_blocks','signature_sha256'))
        row = {k:generic[k] for k in ('backend','total','hash','transfer','remaining','rounds',
              'feedforward','hash_count','physical_blocks','logical_blocks','signature_sha256',
              'signature_cache_sha256','signature_cache_and_kat_match','message_bytes')}
        row.update(design='i-generic', status='passed', source=str(path.relative_to(HERE)),
                   source_scope='figure-relative',
                   source_sha256=sha(path), software_strategy='Original generic single-loop chain program',
                   not_best_software_baseline=True, no_added_wait=True)
        rows += [dict(existing['SLotH']), row,
                 dict(existing['i'],design='i-opt',software_strategy='Four-path loop-invariant dispatch'),
                 dict(existing['c']),dict(existing['t'])]
        c,t=existing['c']['total'],existing['t']['total']
        for label,metrics in [('i-generic',generic),('i-opt',existing['i'])]:
            i=metrics['total']
            comparisons.append(dict(backend=backend,software_baseline=label,i_cycles=i,c_cycles=c,t_cycles=t,
                i_to_c_saved=i-c,i_to_c_decrease_percent=100*(i-c)/i,
                c_to_t_saved=c-t,c_to_t_decrease_percent=100*(c-t)/c,
                chain_share_of_i_to_t_savings_percent=100*(i-c)/(i-t),
                hash_fixed_across_project_designs=True))
        workload.append(dict(backend=backend,software_optimization_saved_cycles=generic['total']-existing['i']['total'],
            generic_remaining=generic['remaining'],optimized_remaining=existing['i']['remaining'],
            sloth_remaining=existing['SLotH']['remaining'],
            generic_remaining_lower_than_sloth=generic['remaining']<existing['SLotH']['remaining'],
            optimized_remaining_lower_than_sloth=existing['i']['remaining']<existing['SLotH']['remaining']))
    assert len(rows)==10 and all(r['total']==r['hash']+r['transfer']+r['remaining'] for r in rows)
    report=dict(created_at=datetime.now().astimezone().isoformat(timespec='seconds'),
        configuration='P1U1',profile='slh_128f',operation='sign',message_bytes=33,rows=rows,
        comparisons=comparisons,software_strategy_effect=workload,definitions=latest['definitions'],
        caveats=latest['caveats']+[
            'i-generic is a controlled compiler-strategy baseline, not the best software implementation.',
            'All common RTL and Hash optimizations are retained; only the i software program/model strategy changes.',
            'The generic-vs-optimized i comparison controls RTL exactly; the existing i/c/t frontends have architectural differences beyond opcode counts.',
            'Identical i common RTL allows hash-verified reuse of its100MHz OOC evidence, not a ROM-containing top timing claim.',
            'The generic SHA2 Remaining is higher than SLotH; the prior dual-backend Remaining target holds only for i-opt.',
            'Production RTL/model/ROM and previous reports/plots remain unchanged.'],
        independent_audit='DATA_AUDIT.json',latest_evidence=str((LATEST/'cycle_breakdown_data.json').relative_to(ROOT)),
        latest_evidence_sha256=sha(LATEST/'cycle_breakdown_data.json'))
    (HERE/'cycle_breakdown_data.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    lines=['# 软件链优化与控制粒度分层对照','',
        'P1U1；SLH-DSA-128f Sign；同一组33字节KAT；全部为真实测量周期。', '',
        'i-generic 与 i-opt 使用完全相同的当前硬件，只改变软件链程序：前者使用原通用单循环，后者使用四路径条件外提。未增加等待，也未撤掉公共Hash优化。i-generic不能被称为最佳软件实现。', '',
        '| 后端 | i软件策略 | i周期 | c周期 | t周期 | i→c降幅 | c→t降幅 | 链占i→t省拍 |',
        '|---|---|---:|---:|---:|---:|---:|---:|']
    for x in comparisons:
        lines.append(f'| {x["backend"].upper()} | {x["software_baseline"]} | {x["i_cycles"]:,} | {x["c_cycles"]:,} | {x["t_cycles"]:,} | {x["i_to_c_decrease_percent"]:.2f}% | {x["c_to_t_decrease_percent"]:.2f}% | {x["chain_share_of_i_to_t_savings_percent"]:.2f}% |')
    lines += ['', '## 完整周期分解','',
        '| 后端 | 实现 | Hash | Transfer | Remaining | Total |', '|---|---|---:|---:|---:|---:|']
    for x in rows:
        lines.append('| '+' | '.join([x['backend'].upper(),x['design'],*[f'{x[k]:,}' for k in ('hash','transfer','remaining','total')]])+' |')
    lines += ['', '本对照拆开了两个因素：相同i硬件的软件链编译策略，以及既有i/c/t的控制粒度。通用循环可作为明确声明的软件策略基线，i-opt保留为优化软件对照；不能把受控基线的差距推广为相对最佳软件实现的收益。', '',
        '三种粒度的Hash工作量相同，链占Hash多数不意味着硬件化能消除链的Hash轮计算；减少的主要是控制与任务交接开销。跨阶段百分比的分母不同，绝对省拍及占i→t总收益的比例可作为补充。', '',
        'SHA2 i-generic的Remaining为2,324,134，高于SLotH的1,784,934；i-opt为1,640,672，仍低于SLotH。不能同时套用两种软件策略的结论。', '',
        '现有100MHz证据仅对应完全相同RTL的common OOC，未重做综合/布线，不覆盖包含ROM的top。未修改生产文件或旧实验。', '']
    (HERE/'comparison.md').write_text('\n'.join(lines))
    print('\n'.join(lines[:14]))


if __name__=='__main__':
    main()
