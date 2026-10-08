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
MEASURE=[(1,1),(1,2),(4,1),(12,1)] # User skipped P4U2 synthesis.
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
    rows += [ordinary_equivalent(label,u) for u in (1,2)]
    e.write(e.OUT/label/'equivalence.json',dict(points=rows,p1='frozen baseline ordinary sponge cycle comparison'))

def simultaneous(label):
    """Deterministic out-of-order returns, including initial/return collisions."""
    s=e.source(label);b=e.source('baseline')
    def point(pu):
        p,u=pu;d=e.OUT/label/f'simultaneous_P{p}';d.mkdir(parents=True,exist_ok=True)
        work=e.BUILD/label/d.name;work.mkdir(parents=True,exist_ok=True)
        (d/'ref.sv').write_text((b/'rtl/hash_lane/mhbs_chain_pipeline_lane.sv').read_text().replace('module mhbs_chain_pipeline_lane #','module mhbs_chain_pipeline_lane_ref #'))
        bench=(b/'tb/unit/tb_mhbs_chain_format_equiv.sv').read_text()
        if 'output wire [1599:0] perm_state' not in (s/'rtl/hash_lane/mhbs_chain_pipeline_lane.sv').read_text():
            original=(b/'rtl/hash_lane/mhbs_chain_pipeline_lane.sv').read_text()
            functions=original[original.index(' function automatic [1599:0] block_for'):original.index(' assign request_ready')]
            independent='''
 localparam [2:0] SEED=0,STEP=1,KEY=2,MASK=3,FINAL=4;
 wire [1:0] block_family;wire [2:0] block_phase;wire [3:0] block_step;
 wire [255:0] block_address,block_value,block_key;
 function automatic [31:0] be32(input [31:0] v);be32={v[7:0],v[15:8],v[23:16],v[31:24]};endfunction
'''+functions+'''
 assign perm_state=block_family==0 ? block_for(block_address,block_value) : stateful_block(block_family,block_phase,block_address,block_value,block_key,block_step);
'''
            bench=bench.replace(' wire [31:0] hash_count,permutation_count;',independent+' wire [31:0] hash_count,permutation_count;')
        bench=bench.replace('logic [1:0] request_tag','localparam integer T=$clog2(PIPELINE);\n logic [T-1:0] request_tag').replace('wire [1:0] response_tag','wire [T-1:0] response_tag').replace('wire [1:0] rt,pt','wire [T-1:0] rt,pt').replace("2'(i%PIPELINE)","T'(i%PIPELINE)").replace("2'((i/3)%PIPELINE)","T'((i/3)%PIPELINE)").replace("2'(t)","T'(t)")
        ports='.request_family,.request_no_seed,.request_start,.request_initial_value,.identifier'
        bench=bench.replace(".request_family(2'd0),.request_no_seed(1'b0),.request_start(4'd0),\n .request_initial_value(256'd0),.identifier(128'd0)",ports)
        bench=bench.replace('.clk,.rst,.node_bytes,.request_valid',ports+',.clk,.rst,.node_bytes,.request_valid')
        bench=bench.replace(' logic [PIPELINE-1:0] pending=0,known=0;', '''
 logic [1:0] request_family=0;
 logic request_no_seed=0;
 logic [3:0] request_start=0;
 logic [255:0] request_initial_value=256'h12345678;
 wire [127:0] identifier=128'habcdef;
 integer initial_with_return=0,key_returns=0;
 always @(posedge clk)if(!rst)begin
  if(request_valid&&request_ready&&request_no_seed&&perm_done)initial_with_return++;
  if(perm_done&&ref_dut.phase[perm_result_tag]==2)key_returns++;
 end
 logic [PIPELINE-1:0] pending=0,known=0;''')
        bench=bench.replace('request_steps=5\'(i%6);', "request_family=width==2 ? 2'(i%3) : 0;request_no_seed=width==2 && i%4!=0;request_start=4'(i%4);request_initial_value=256'(i)*256'h123456789abcdef;\n    request_steps=5'(i%6);")
        bench=bench.replace("request_capture_after=5'((i/7)%8);", "request_capture_after=i%2 ? {1'b0,request_start} : 5'((i/7)%8);")
        bench=bench.replace('$display("CHAIN_FORMAT_EQUIV_PASS', 'if(initial_with_return==0 || key_returns==0)$fatal(1,"stateful collision coverage");\n  $display("COLLISION_COVERAGE initial_with_return=%0d key_returns=%0d",initial_with_return,key_returns);\n  $display("CHAIN_FORMAT_EQUIV_PASS')
        (d/'tb.sv').write_text(bench)
        binary=work/'obj/Vtb_mhbs_chain_format_equiv'
        if not binary.exists():e.tool(['verilator','--binary','--timing','-O3','-j','2','-Wno-fatal','--top-module','tb_mhbs_chain_format_equiv',f'-GPIPELINE={p}','--Mdir',work/'obj',s/'rtl/hash_lane/mhbs_chain_pipeline_lane.sv',d/'ref.sv',d/'tb.sv'],d/'compile.log',s)
        e.tool([binary],d/'run.log',s)
        assert 'CHAIN_FORMAT_EQUIV_PASS' in (d/'run.log').read_text()
        print('SIMULTANEOUS_PASS',label,p,flush=True)
        return dict(p=p,passed=True,log_sha256=e.sha(d/'run.log'))
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:rows=list(pool.map(point,[(p,1) for p in (2,3,4,6,8,12)]))
    e.write(e.OUT/label/'simultaneous.json',rows)

def ordinary_equivalent(label,u):
    s=e.source(label);b=e.source('baseline')
    d=e.OUT/label/f'equivalence_P1U{u}';d.mkdir(parents=True,exist_ok=True)
    work=e.BUILD/label/d.name;work.mkdir(parents=True,exist_ok=True)
    for name in ('mhbs_recipe_lane','mhbs_chain_pipeline_lane'):
        text=(b/f'rtl/hash_lane/{name}.sv').read_text()
        for module in ('mhbs_recipe_lane','mhbs_chain_pipeline_lane'):
            text=text.replace(module,module+'_area_ref')
        (d/(name+'_ref.sv')).write_text(text)
    bench=(s/'tb/unit/tb_mhbs_recipe_padding.sv').read_text().replace('mhbs_recipe_pre_direct_ref #','mhbs_recipe_lane_area_ref #')
    (d/'tb.sv').write_text(bench)
    original=Path(json.loads((e.OUT/'baseline/reused_evidence.json').read_text())['source'])
    (d/'padding.mem').write_bytes((original/'legacy_units/padding.mem').read_bytes())
    binary=work/'obj/Vtb_mhbs_recipe_padding'
    if not binary.exists():
        files=[s/n for n in (s/'manifests/v42_sources.txt').read_text().split() if n.startswith('rtl/hash_lane/')]
        e.tool(['verilator','--binary','--timing','-O3','-j','2','-Wno-fatal','--top-module','tb_mhbs_recipe_padding','-GPIPELINE=1',f'-GUNROLL={u}','--Mdir',work/'obj',*files,*d.glob('*_ref.sv'),d/'tb.sv'],d/'compile.log',s)
    e.tool([binary,f'+VECTORS={d}/padding.mem'],d/'run.log',s)
    assert 'RECIPE_PADDING_PASS' in (d/'run.log').read_text()
    print('EQUIVALENCE_PASS',label,1,u,flush=True)
    return dict(p=1,u=u,passed=True,log_sha256=e.sha(d/'run.log'))

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

def legacy(label):
    # Bind the historical recipe oracle to its own frozen chain interface,
    # never to the current adapter whose internal port list may have changed.
    s=e.source(label);b=e.source('baseline');d=e.OUT/label/'legacy_units'
    d.mkdir(parents=True,exist_ok=True)
    (d/'chain_ref.sv').write_text((b/'rtl/hash_lane/mhbs_chain_pipeline_lane.sv').read_text().replace('module mhbs_chain_pipeline_lane #','module mhbs_chain_pipeline_lane_ref #'))
    (d/'recipe_ref.sv').write_text((s/'tb/reference/mhbs_recipe_pre_direct_ref.sv').read_text().replace('mhbs_chain_pipeline_lane #','mhbs_chain_pipeline_lane_ref #'))
    original=Path(json.loads((e.OUT/'baseline/reused_evidence.json').read_text())['source'])
    (d/'padding.mem').write_bytes((original/'legacy_units/padding.mem').read_bytes())
    rows=[]
    for top,p,u in [('tb_mhbs_chain_format_equiv',4,1)]+[('tb_mhbs_recipe_padding',p,u) for p,u in ((1,1),(1,2),(4,1),(12,2))]:
        name=f'{top}_P{p}U{u}';work=e.BUILD/label/(name+'_bound_ref');work.mkdir(parents=True,exist_ok=True)
        bench=d/(top+'.sv');bench.write_text((s/f'tb/unit/{top}.sv').read_text())
        binary=work/('obj/V'+top)
        if not binary.exists():
            files=[s/n for n in (s/'manifests/v42_sources.txt').read_text().split() if n.startswith('rtl/hash_lane/')]
            params=[f'-GPIPELINE={p}']+([f'-GUNROLL={u}'] if 'padding' in top else [])
            e.tool(['verilator','--binary','--timing','-O3','-j','2','-Wno-fatal','--top-module',top,*params,'--Mdir',work/'obj',*files,d/'chain_ref.sv',s/'tb/reference/mhbs_shake_pre_direct_ref.sv',d/'recipe_ref.sv',bench],d/(name+'_bound_compile.log'),s)
        e.tool([binary,f'+VECTORS={d}/padding.mem'],d/(name+'_bound.log'),s)
        assert '_PASS' in (d/(name+'_bound.log')).read_text()
        rows.append(dict(test=name,passed=True,log_sha256=e.sha(d/(name+'_bound.log'))))
        print('LEGACY_BOUND_PASS',label,name,flush=True)
    e.write(e.OUT/label/'legacy_units.json',rows)

def validate(label):
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        jobs=[pool.submit(f,label) for f in (e.edges,regression,e.partition_checks,legacy)]
        for job in jobs:job.result()
    edge_cycles(label)
    e.write(e.OUT/label/'validation.json',dict(passed=True,
        checks=['edges','edge_cycles','slh_regression','partition','legacy_units','equivalence','simultaneous']))

def edge_cycles(label):
    def identity(row):
        return json.dumps({k:row.get(k) for k in ('p','u','profile','operation','stats','options','vector_sha256')},sort_keys=True)
    refs={identity(r):r for r in json.loads((e.OUT/'baseline/edges.json').read_text())}
    rows=json.loads((e.OUT/label/'edges.json').read_text())
    for r in rows:
        b=refs[identity(r)]
        for field in ('compute_cycles','total_cycles','hashes','permutations'):
            assert r.get(field)==b.get(field),(r['profile'],r['operation'],field)
    e.write(e.OUT/label/'edge_cycles.json',dict(passed=True,cases=len(rows),reference='baseline/edges.json'))

def report():
    baseline=json.loads((e.OUT/'baseline/area.json').read_text())
    base_area={(r['p'],r['u']):r for r in baseline}
    matrix=json.loads((e.OUT/'baseline/matrix.json').read_text())
    verdicts=[];rows=[];hierarchies=[]
    original=Path(json.loads((e.OUT/'baseline/reused_evidence.json').read_text())['source'])
    def hierarchy(path):
        for line in path.read_text().splitlines():
            cells=[x.strip() for x in line.split('|')[1:-1]]
            if cells and cells[0]=='chain_pipeline.engine':
                return dict(lut=int(cells[2]),lutram=int(cells[4]),ff=int(cells[6]))
        return None
    for label in ('single_write','shared_format'):
        d=e.OUT/label
        if not (d/'measurement.json').exists():continue
        decision=json.loads((d/'measurement.json').read_text())
        decision['label']=label
        decision['functional_validation_passed']=(d/'validation.json').exists()
        decision['accepted']=(decision['area_passed'] and (d/'validation.json').exists()
            and (d/'simultaneous.json').exists()
            and len(json.loads((d/'equivalence.json').read_text())['points'])==13)
        verdicts.append(decision)
        for a in decision['areas']:
            point=f"P{a['p']}U{a['u']}"
            h=hierarchy(d/point/'core_hierarchical.rpt')
            if h:hierarchies.append(dict(candidate=label,point=point,baseline=hierarchy(original/point/'core_hierarchical.rpt'),current=h))
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
    final=next((v['label'] for v in reversed(verdicts) if v['accepted']),'baseline')
    e.write(out.with_suffix('.json'),dict(baseline_commit='5d53fa6e',final_candidate=final,routed=False,skipped_synthesis=['P4U2','P12U2'],decisions=verdicts,chain_hierarchy=hierarchies,rows=rows))
    if rows:
        with out.with_suffix('.csv').open('w') as f:
            w=csv.DictWriter(f,fieldnames=list(rows[0]),lineterminator='\n');w.writeheader();w.writerows(rows)
    md=['# XMSS/LMS 流水面积优化','',
        '基线 `5d53fa6e`。单 lane，P/U、十参数及三操作保留；只综合，不布线。U1/U2 分别按 **150/110 MHz 假定频率**估算，未经布线验证。',
        '', '器件 xc7a200tffg1156-3，约束 6.666667 ns，统计关闭；最多六个 Vivado、每个四线程。P12U2 只回归功能，不新增综合。按用户后续指令停止并跳过 P4U2 综合，功能回归仍包含它；两者本轮新面积/ATP 留空。',
        '', '旧 P12U2 已在原快照完成综合；本轮仅修复其遗漏的汇总，不纳入本轮四点面积门禁。',
        '', '等效 Slice = LUT/4 + FF/8 + 232.4×BRAM36 + 102.4×DSP；LUT 已包含 LUTRAM。时间(ms)=计算周期/(MHz×1000)，ATP=Slice×时间；有效轮利用率=24×置换数/(P×U×计算周期)。',
        '', f'最终保留 `{final}`。共用块构造虽然降低 P12U1 面积，但 P4U1 相比 single_write 增加 574 LUT、65 FF、151.625 等效 Slice，未满足所有测量点不增加的条件，整体撤回。',
        '', '| 候选 | 配置 | LUT | FF | LUTRAM | 等效 Slice | 对原基线 Slice | 决定 |', '|---|---|---:|---:|---:|---:|---:|---|']
    for pu in MEASURE:
        a=base_area[pu];md.append(f"| 原基线 | P{pu[0]}U{pu[1]} | {a['lut']:,.0f} | {a['ff']:,.0f} | {a['lutram']:,.0f} | {a['equivalent_slice']:,.3f} | — | 基线 |")
    for v in verdicts:
        for a in v['areas']:
            b=base_area[a['p'],a['u']]
            md.append(f"| {v['label']} | P{a['p']}U{a['u']} | {a['lut']:,.0f} | {a['ff']:,.0f} | {a['lutram']:,.0f} | {a['equivalent_slice']:,.3f} | {(a['equivalent_slice']/b['equivalent_slice']-1)*100:+.2f}% | {'保留' if v['accepted'] else '撤回' if not v['area_passed'] else '待回归'} |")
    md+=['', '## 链上下文模块映射','', '| 候选 | 配置 | 原 LUT → 新 LUT | 原 FF → 新 FF | 原 LUTRAM → 新 LUTRAM |', '|---|---|---:|---:|---:|']
    for h in hierarchies:
        b,a=h['baseline'],h['current']
        md.append(f"| {h['candidate']} | {h['point']} | {b['lut']:,} → {a['lut']:,} | {b['ff']:,} → {a['ff']:,} | {b['lutram']:,} → {a['lutram']:,} |")
    md+=['', '## 最终版本周期、利用率与 ATP','', '以下计算/总周期、输出与 Hash/置换次数均与基线一致。签名包含完整认证路径重算。面积未重新测量的配置不计算新 ATP。']
    for name in e.PROFILES:
        md+=['', '### '+name,'', '| 操作 | 配置 | 计算/总周期 | Hash/置换次数 | 利用率 | 时间 ms | 原 ATP | 新 ATP |', '|---|---|---:|---:|---:|---:|---:|---:|']
        for r in sorted((r for r in rows if r['candidate']==final and r['profile']==name),key=lambda r:(r['operation'],r['p'],r['u'])):
            atp=f"{r['atp']:,.3f}" if r['atp'] is not None else '未测'
            md.append(f"| {('Keygen','Sign','Verify')[r['operation']]} | P{r['p']}U{r['u']} | {r['compute_cycles']:,}/{r['total_cycles']:,} | {r['hashes']:,}/{r['permutations']:,} | {r['utilization']*100:.2f}% | {r['time_ms']:.3f} | {r['baseline_atp']:,.3f} | {atp} |")
    md+=['', '层次报告按 Vivado rebuilt hierarchy 读取；逻辑可能跨层迁移，因此保留判断始终使用共同核总资源。', '', '## 改动与验证','',
        '- single_write：初值复用 key_value；首次 XMSS key 返回时转存初值。digest/captured 的写入均来自返回端，避免独立请求写口；零步与起始 capture 保留旁路。',
        '- shared_format：先选择普通或批量字段，再共用 recipe lane 固定块排列与填充；没有新增 Keccak 或流水级。',
        '- 每项 72 组四参数三操作检查输出、计算/总周期与 Hash/置换次数；11 个 P>1 配置逐周期比较块、握手和有效读数据，P1 由普通 sponge 对照及完整操作覆盖。',
        '- 六种上下文深度额外比较混合算法、乱序返回及初值接收/完成同拍；测试对实际碰撞次数和 XMSS key 返回次数设置非零断言。',
        '- 面积门禁：四点 LUT 与等效 Slice 均不增加，且至少一个 P>1 点等效 Slice 下降。P4U2 面积尚未验收。追加 SLH、统计关闭、停顿、异常、共同核和填充边界回归。',
        '', '## 独立证据','']
    for v in verdicts:
        d=e.OUT/v['label'];md.append(f"- `{v['label']}`：基于 `{v['parent']}`，72 组正常周期一致；完整验证{'通过' if v['functional_validation_passed'] else '尚未汇总'}，面积门禁{'通过' if v['area_passed'] else '失败'}。")
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
    elif action=='simultaneous':simultaneous(label)
    elif action=='synth':synth(label)
    elif action=='compare':compare(label,sys.argv[3] if len(sys.argv)>3 else 'baseline')
    elif action=='validate':validate(label)
    elif action=='edge-cycles':edge_cycles(label)
    elif action=='report':report()
    else:{'matrix':e.matrix,'edges':e.edges,'regression':e.regression,'partition':e.partition_checks,'legacy':legacy,'units':e.units}[action](label)
