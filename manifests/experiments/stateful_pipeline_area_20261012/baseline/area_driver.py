#!/usr/bin/env python3
"""Independent, frozen area candidates against 5d53fa6e. No place/route."""
import concurrent.futures
import csv
import json
import sys
from pathlib import Path
import stateful_pipeline_experiment as e

e.OUT=e.ROOT/'manifests/experiments/stateful_pipeline_area_20261012'
e.BUILD=e.ROOT/'build/stateful_pipeline_area_20261012'
MEASURE=[(1,1),(1,2),(4,1),(4,2),(12,1)]
ALL=[(p,1) for p in (1,2,3,4,6,8,12)]+[(p,2) for p in (1,2,3,4,6,12)]

def equivalent(label,p,u):
    # Exercise candidate and frozen original under identical actual Keccak
    # responses, including every issued permutation and its handshake cycle.
    s=e.source(label); b=e.source('baseline')
    d=e.OUT/label/f'equivalence_P{p}U{u}'; d.mkdir(parents=True,exist_ok=True)
    work=e.BUILD/label/d.name;work.mkdir(parents=True,exist_ok=True)
    for name in ('mhbs_recipe_lane','mhbs_chain_pipeline_lane'):
        text=(b/f'rtl/hash_lane/{name}.sv').read_text()
        for module in ('mhbs_recipe_lane','mhbs_chain_pipeline_lane'):
            text=text.replace(module,module+'_area_ref')
        (d/(name+'_ref.sv')).write_text(text)
    bench=(s/'tb/unit/tb_mhbs_stateful_pipeline.sv').read_text()
    start=bench.index(' mhbs_recipe_lane #'); end=bench.index(';',start)+1
    instance=bench[start:end].replace('mhbs_recipe_lane #','mhbs_recipe_lane_area_ref #').replace(' dut(',' ref_dut(')
    signals={'ready':1,'done':1,'done_tag':max(1,(p-1).bit_length()),'result':256,'capture':256,'read_result':256,'read_capture':256,'hashes':32,'perms':32}
    import re
    for signal in signals:
        instance=re.sub(r'\('+signal+r'\)', '('+signal+'_ref)',instance)
    extra='\n'+''.join(f'wire [{w-1}:0] {name}_ref;\n' for name,w in signals.items())+instance
    extra+='''
 reg [PIPELINE-1:0] readable=0;
 integer concurrent_accept_return=0, initial_transfers=0;
 always @(posedge clk)begin
  if(rst)readable=0;
  else begin
   if(valid&&ready)readable[tag]=req[2];
   if(dut.batch_perm_done && dut.chain_pipeline.engine.node_done)
    readable[dut.batch_perm_result_tag]=1;
   if(valid&&ready&&dut.batch_perm_done)concurrent_accept_return++;
  end
 end
 always @(negedge clk)if(!rst)begin
  if({ready,done,hashes,perms}!=={ready_ref,done_ref,hashes_ref,perms_ref})$fatal(1,"cycle control equivalence");
  if(done && {done_tag,result,capture}!=={done_tag_ref,result_ref,capture_ref})$fatal(1,"cycle result equivalence");
  if(read_capture!==read_capture_ref)$fatal(1,"cycle capture equivalence");
  if(readable[read_tag] && read_result!==read_result_ref)$fatal(1,"cycle digest equivalence");
  if({dut.batch_perm_valid,dut.batch_perm_ready,dut.batch_perm_done}!=={ref_dut.batch_perm_valid,ref_dut.batch_perm_ready,ref_dut.batch_perm_done})$fatal(1,"cycle permutation handshake");
  if(dut.batch_perm_valid && {dut.batch_perm_tag,dut.batch_perm_state}!=={ref_dut.batch_perm_tag,ref_dut.batch_perm_state})$fatal(1,"cycle block equivalence");
 end
'''
    bench=bench.replace('endmodule',extra+'endmodule')
    (d/'tb.sv').write_text(bench)
    files=[s/n for n in (s/'manifests/v42_sources.txt').read_text().split() if n.startswith('rtl/hash_lane/')]
    binary=work/'obj/Vtb_mhbs_stateful_pipeline'
    if not binary.exists():
        e.tool(['verilator','--binary','--timing','-O3','-j','2','-Wno-fatal','--top-module','tb_mhbs_stateful_pipeline',f'-GPIPELINE={p}',f'-GUNROLL={u}','--Mdir',work/'obj',*files,*d.glob('*_ref.sv'),d/'tb.sv'],d/'compile.log',s)
    e.tool([binary,f'+VECTORS={e.unit_vectors()}'],d/'run.log',s)
    assert 'STATEFUL_PIPE_UNIT_PASS' in (d/'run.log').read_text()
    print('EQUIVALENCE_PASS',label,p,u,flush=True)
    return dict(p=p,u=u,passed=True,log_sha256=e.sha(d/'run.log'))

def equivalences(label):
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        rows=list(pool.map(lambda pu:equivalent(label,*pu),[pu for pu in ALL if pu[0]>1]))
    # P1 does not instantiate the chain adapter. The complete operations and
    # ordinary sponge equivalence exercise P1U1 and P1U2 separately.
    e.write(e.OUT/label/'equivalence.json',dict(points=rows,p1='normal matrix and ordinary sponge reference'))

def synth(label):
    saved=e.POINTS
    try:e.POINTS=MEASURE;e.synthesis(label)
    finally:e.POINTS=saved

def regression(label):
    rows=[]
    for ref in json.loads((e.OUT/'baseline/slh_regression.json').read_text()):
        row=e.run(label,ref['p'],ref['u'],ref['profile'],ref['operation'])
        for k in ('compute_cycles','total_cycles','hashes','permutations'):
            assert row[k]==ref[k],(ref['profile'],ref['operation'],k)
        rows.append(row)
    e.write(e.OUT/label/'slh_regression.json',rows)

def validate(label):
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        jobs=[pool.submit(f,label) for f in (e.edges,regression,e.partition_checks,e.legacy_checks)]
        for job in jobs:job.result()
    e.write(e.OUT/label/'validation.json',dict(passed=True,
        checks=['edges','slh_regression','partition','legacy_units','equivalence']))

def report():
    baseline=json.loads((e.OUT/'baseline/area.json').read_text())
    base_area={(r['p'],r['u']):r for r in baseline}
    matrix=json.loads((e.OUT/'baseline/matrix.json').read_text())
    verdicts=[];rows=[]
    for label in ('single_write','shared_format'):
        d=e.OUT/label
        if not (d/'measurement.json').exists():continue
        decision=json.loads((d/'measurement.json').read_text())
        decision['label']=label
        decision['accepted']=decision['area_passed'] and (d/'validation.json').exists()
        verdicts.append(decision)
        am={(r['p'],r['u']):r for r in decision['areas']}
        for r in json.loads((d/'matrix.json').read_text()):
            pu=r['p'],r['u'];a=am.get(pu);base=base_area[pu]
            row={k:r[k] for k in ('profile','operation','p','u','compute_cycles','total_cycles','hashes','permutations')}
            mhz=150 if r['u']==1 else 110
            row.update(candidate=label,accepted=decision['accepted'],assumed_mhz=mhz,
                time_ms=r['compute_cycles']/(mhz*1000),utilization=r['permutations']*24/(r['p']*r['u']*r['compute_cycles']),
                **{k:a[k] if a else None for k in ('lut','ff','lutram','bram36','dsp','equivalent_slice')})
            row['atp']=row['time_ms']*a['equivalent_slice'] if a else None
            row['baseline_atp']=row['time_ms']*base['equivalent_slice']
            rows.append(row)
    out=e.ROOT/'docs/report/Stateful_Pipeline_Area_Optimization'
    e.write(out.with_suffix('.json'),dict(baseline_commit='5d53fa6e',routed=False,decisions=verdicts,rows=rows))
    if rows:
        with out.with_suffix('.csv').open('w') as f:
            w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    md=['# XMSS/LMS 流水面积优化','',
        '基线 `5d53fa6e`。单 lane，P/U、十参数及三操作保留；只综合，不布线。U1/U2 分别按 **150/110 MHz 假定频率**估算，未经布线验证。',
        '', '器件 xc7a200tffg1156-3，约束 6.666667 ns，统计关闭；最多六个 Vivado、每个四线程。P12U2 只回归功能，不新增综合。',
        '', '旧 P12U2 已在原快照完成综合；本轮仅修复其遗漏的汇总，不纳入本轮五点面积门禁。',
        '', '等效 Slice = LUT/4 + FF/8 + 232.4×BRAM36 + 102.4×DSP；LUT 已包含 LUTRAM。时间(ms)=计算周期/(MHz×1000)，ATP=Slice×时间；有效轮利用率=24×置换数/(P×U×计算周期)。',
        '', '| 候选 | 配置 | LUT | FF | LUTRAM | 等效 Slice | 对原基线 Slice | 决定 |', '|---|---|---:|---:|---:|---:|---:|---|']
    for pu in MEASURE:
        a=base_area[pu];md.append(f"| 原基线 | P{pu[0]}U{pu[1]} | {a['lut']:,.0f} | {a['ff']:,.0f} | {a['lutram']:,.0f} | {a['equivalent_slice']:,.3f} | — | 基线 |")
    for v in verdicts:
        for a in v['areas']:
            b=base_area[a['p'],a['u']]
            md.append(f"| {v['label']} | P{a['p']}U{a['u']} | {a['lut']:,.0f} | {a['ff']:,.0f} | {a['lutram']:,.0f} | {a['equivalent_slice']:,.3f} | {(a['equivalent_slice']/b['equivalent_slice']-1)*100:+.2f}% | {'保留' if v['accepted'] else '撤回' if not v['area_passed'] else '待回归'} |")
    md+=['', '## 改动与验证','',
        '- single_write：初值复用 key_value；首次 XMSS key 返回时转存初值。digest/captured 的写入均来自返回端，避免独立请求写口；零步与起始 capture 保留旁路。',
        '- shared_format：先选择普通或批量字段，再共用 recipe lane 固定块排列与填充；没有新增 Keccak 或流水级。',
        '- 每项 72 组四参数三操作检查输出、计算/总周期与 Hash/置换次数；11 个 P>1 配置逐周期比较块、握手和有效读数据，P1 由普通 sponge 对照及完整操作覆盖。',
        '- 面积门禁：五点 LUT 与等效 Slice 均不增加，且至少一个 P>1 点等效 Slice 下降。通过面积门禁后追加 SLH、统计关闭、停顿、异常、共同核和填充边界回归。',
        '', '## 独立证据','']
    for v in verdicts:
        d=e.OUT/v['label'];md.append(f"- `{v['label']}`：基于 `{v['parent']}`，周期一致；完整验证{'通过' if v['accepted'] else '未作为保留版本验收'}。")
        for a in v['areas']:
            name=f"P{a['p']}U{a['u']}"
            md.append(f"  - [{name} 分层报告](../../manifests/experiments/stateful_pipeline_area_20261012/{v['label']}/{name}/core_hierarchical.rpt)")
    md+=['', '源码快照、补丁、配置及日志位于 `manifests/experiments/stateful_pipeline_area_20261012/`；逐操作周期、利用率和 ATP 见同名 CSV/JSON。不提交、不推送。','']
    out.with_suffix('.md').write_text('\n'.join(md))

def compare(label,parent='baseline'):
    old=json.loads((e.OUT/parent/'matrix.json').read_text())
    new=json.loads((e.OUT/label/'matrix.json').read_text())
    key=lambda r:(r['p'],r['u'],r['profile'],r['operation'])
    refs={key(r):r for r in old}
    assert len(new)==len(old)==72
    for r in new:
        b=refs[key(r)]
        for field in ('compute_cycles','total_cycles','hashes','permutations'):
            assert r[field]==b[field],(key(r),field,r[field],b[field])
    oldarea={(r['p'],r['u']):r for r in json.loads((e.OUT/parent/'area.json').read_text())}
    areas=json.loads((e.OUT/label/'area.json').read_text())
    ok=all(a[k]<=oldarea[(a['p'],a['u'])][k] for a in areas for k in ('lut','equivalent_slice'))
    gain=any(a['p']>1 and a['equivalent_slice']<oldarea[(a['p'],a['u'])]['equivalent_slice'] for a in areas)
    verdict=dict(parent=parent,cycle_equal=True,area_passed=ok and gain,areas=areas)
    e.write(e.OUT/label/'measurement.json',verdict)
    print('MEASUREMENT',label,verdict,flush=True)

if __name__=='__main__':
    action,label=sys.argv[1:3]
    if action=='freeze':e.freeze(label)
    elif action=='equivalence':equivalences(label)
    elif action=='synth':synth(label)
    elif action=='compare':compare(label,sys.argv[3] if len(sys.argv)>3 else 'baseline')
    elif action=='validate':validate(label)
    elif action=='report':report()
    else:{'matrix':e.matrix,'edges':e.edges,'regression':e.regression,'partition':e.partition_checks,'legacy':e.legacy_checks,'units':e.units}[action](label)
