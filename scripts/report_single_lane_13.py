#!/usr/bin/env python3
"""Verify and publish the recovered single-lane 13-point experiment."""
import csv, json, math, shutil
from pathlib import Path
from experiment_support import area
from run_single_lane_13 import sha, write

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'manifests/experiments/single_lane_13_20261009_v4'
DOC = ROOT / 'docs/report/Single_Lane_13_ATP_150_110'
OVERVIEW = ROOT / 'docs/report/Single_Lane_13_20261009.md'

# Recorded in the conversation before the original v3 evidence was deleted.
PRIOR_V3 = [
    ('P12U1',47020,24673,342457,33878.415), ('P8U1',38199,18197,481501,37956.323),
    ('P6U1',34351,14961,554321,38646.798), ('P12U2',73161,24648,199009,38664.283),
    ('P6U2',52377,14948,305633,41573.729), ('P4U2',40035,11708,412170,42986.521),
    ('P4U1',29604,11716,766014,45273.981), ('P3U2',37539,10075,519606,50279.556),
    ('P3U1',26383,10095,979434,51306.834), ('P2U2',30679,8448,732492,58104.928),
    ('P2U1',24251,8456,1402428,66566.245), ('P1U2',21855,6764,1352027,77547.967),
    ('P1U1',18332,6772,2619719,94825.095)]

def read(path):
    return json.loads(path.read_text())

def main():
    config, status, raw = [read(OUT/f) for f in ['config.json','status.json','results.json']]
    assert status['state']=='complete' and status['completed']==13 and status['failed']==0
    assert sha(OUT/'config.json')==status['config_sha256']
    assert sha(OUT/'source_snapshot.tar.gz')==config['snapshot_sha256']
    assert raw['output_agreement'] and len(raw['rows'])==13
    assert config['clock_period_ns']==6.666667 and config['vivado_threads_per_point']==2
    history = OUT/'previous_report'
    if not history.exists():
        history.mkdir()
        for f in [DOC.with_suffix(e) for e in ['.md','.csv','.json']]+[OVERVIEW]:
            shutil.copy2(f,history/f.name)
    old = {r['point']:r for r in read(history/DOC.with_suffix('.json').name)['rows']}
    rows=[]
    for original, prior in zip(raw['rows'],PRIOR_V3):
        r=dict(original); name,lut,ff,cycles,atp=prior; d=OUT/r['point']
        assert (r['point'],r['lut'],r['ff'],r['sign_cycles'],r['total_cycles'])==(name,lut,ff,cycles,cycles+5)
        assert abs(r['atp_slice_ms']-atp)<=0.0005
        assert r['simulation']==r['synthesis']==r['reference_agreement']=='pass'
        assert (r['hashes'],r['permutations'])==(104937,105641)
        assert r['output_sha256']==sha(d/f'{name}.actual.mem')=='c012e24c6dbb7dbb5db0cd54871ca7a063a6ebbfcd65a25054b8b7602bf01c51'
        assert r['snapshot_sha256']==config['snapshot_sha256']
        for f,h in read(d/'synthesis.json')['evidence_sha256'].items():
            assert sha(d/f)==h,(name,f)
        for k,v in area(d/'core_utilization.rpt').items():
            assert r[k]==v,(name,k)
        assert '-no_timing_driven' not in (d/'synth.tcl').read_text()
        assert '6.666667' in (d/'clock.xdc').read_text()
        assert r['assumed_mhz']==(150 if r['u']==1 else 110)
        assert math.isclose(r['atp_slice_ms'],r['equivalent_slice']*r['sign_cycles']/(r['assumed_mhz']*1000))
        r['keccak_utilization']=r['permutations']*24/(r['p']*r['u']*r['sign_cycles'])
        assert 0<r['keccak_utilization']<=1
        r.update(area_source=str((d/'core_hierarchical.rpt').relative_to(ROOT)),synthesis_period_ns=6.666667,
                 synthesis_strategy='default_timing_driven',v3_conversation_match=True)
        b=old[name]
        r.update(lut_delta=r['lut']-b['lut'],ff_delta=r['ff']-b['ff'],cycles_delta=r['sign_cycles']-b['sign_cycles'],
                 atp_change_percent=(r['atp_slice_ms']/b['atp_slice_ms']-1)*100,comparison_same_synthesis_settings=name!='P2U2')
        rows.append(r)
    write(OUT/'v3_conversation_record.json',dict(provenance='Values recorded in the conversation; original v3 evidence was deleted. Not recovered raw measurements.',
          columns=['point','lut','ff','sign_cycles','atp_rounded_3dp'],rows=PRIOR_V3,all_13_match=True))
    payload=dict(scope='single-lane 128f Sign, U2 optimization recovered',rows=rows,output_agreement=True,
                 actual_frequency='assumed only; no placement or routing',snapshot_sha256=config['snapshot_sha256'],
                 experiment=str(OUT.relative_to(ROOT)),synthesis_exception=None,
                 keccak_utilization_formula='permutations*24/(p*u*sign_cycles); effective round throughput, not sampled stage occupancy',
                 prior_v3_source='conversation record; original experiment deleted',prior_v3_all_match=True)
    write(DOC.with_suffix('.json'),payload)
    fields=['rank','point','assumed_mhz','sign_cycles','total_cycles','hashes','permutations','keccak_utilization','lut','ff','lutram','bram36','dsp','equivalent_slice','time_ms','atp_slice_ms','synthesis_period_ns','synthesis_strategy','area_source','lut_delta','ff_delta','cycles_delta','atp_change_percent','comparison_same_synthesis_settings','v3_conversation_match']
    with DOC.with_suffix('.csv').open('w') as f:
        w=csv.DictWriter(f,fieldnames=fields,extrasaction='ignore',lineterminator='\n');w.writeheader();w.writerows(rows)
    lines=['# 单 lane：13 组 128f Sign ATP 排名（v4 重跑）','',
      '本报告使用 `single_lane_13_20261009_v4`：13/13 点全部通过。基于 `1fef998a` 恢复 U2 的末级状态复用与 WOTS 直接写回；源码按冻结快照绑定。','',
      '器件 `xc7a200tffg1156-3`，Vivado 2025.2，共同核 OOC、统计关闭。全部 13 点统一采用 **6.666667 ns、默认时序驱动综合、每任务 2 线程**，包括 P2U2。不布局布线。',
      'U1 假定 150 MHz，U2 假定 110 MHz，频率未经布线验证。等效 Slice=LUT/4+FF/8+232.4×BRAM36+102.4×DSP；LUT 含 LUTRAM。时间(ms)=计算周期/(MHz×1000)，ATP=等效 Slice×时间。',
      'Keccak 有效轮利用率=置换次数×24/(P×U×计算周期)，反映整个签名期间的有效轮吞吐比例，并非逐级实测忙碌率。CSV/JSON 保存 0～1 的原始比例。','',
      '全部签名字节匹配软件参考，Hash/置换次数均为 **104937/105641**；BRAM36/DSP 均为 0。','',
      '| 排名 | 配置 | MHz（假定） | LUT | FF | LUTRAM | 等效 Slice | 计算周期 | 总周期 | 时间 ms | ATP Slice·ms | Keccak 有效轮利用率 |',
      '|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|']
    for r in rows:
        lines.append(f"| {r['rank']} | {r['point']} | {r['assumed_mhz']} | {r['lut']:,.0f} | {r['ff']:,.0f} | {r['lutram']:,.0f} | {r['equivalent_slice']:,.3f} | {r['sign_cycles']:,} | {r['total_cycles']:,} | {r['time_ms']:.6f} | {r['atp_slice_ms']:,.3f} | {r['keccak_utilization']:.2%} |")
    lines+=['','最低 ATP：**P12U1，33,878.415 Slice·ms**；U2 最低：**P12U2，38,664.283 Slice·ms**。','',
      '## 与误删前 v3 对话记录比较','',
      '13 组 LUT、FF、周期及排名全部一致；相同口径下等效 Slice、ATP 和有效轮利用率也一致。v3 原始文件已误删，本项对照来源为先前对话记录，保存在实验目录 `v3_conversation_record.json`；本报告各项实测证据均来自 v4。','',
      '## 与优化前 v2 比较','',
      'U1 全部档位和 P1U2 保持原面积、周期。P>1 的 U2 均减少 25,058 个签名周期，FF 减少约 1,600；P3U2/P12U2 的 LUT 略增，等效 Slice 和 ATP 仍下降。','',
      '| 配置 | LUT 变化 | FF 变化 | 周期变化 | ATP 变化 | 比较条件 |','|---|---:|---:|---:|---:|---|']
    for r in sorted((r for r in rows if r['u']==2),key=lambda r:r['p']):
        note='同约束' if r['comparison_same_synthesis_settings'] else '旧综合策略不同'
        lines.append(f"| {r['point']} | {r['lut_delta']:+,.0f} | {r['ff_delta']:+,.0f} | {r['cycles_delta']:+,} | {r['atp_change_percent']:+.2f}% | {note} |")
    lines+=['','旧 P2U2 使用 9.090909 ns、8 线程、`-no_timing_driven` 诊断综合；本轮使用统一的默认综合。该点差值不能单独归因于 RTL 优化。旧发布报告保留在本轮目录 `previous_report/`。','',
      f"源码快照 SHA256：`{config['snapshot_sha256']}`。",'',
      '原始证据：[single_lane_13_20261009_v4](../../manifests/experiments/single_lane_13_20261009_v4/)。每点的 `core_hierarchical.rpt` 为分层面积报告，`vivado.log` 为完整综合日志。',
      '更新命令：`python3 scripts/report_single_lane_13.py`。同名 CSV/JSON 已同步。']
    DOC.with_suffix('.md').write_text('\n'.join(lines)+'\n')
    OVERVIEW.write_text('''# 固定单 lane：13 组 P/U 周期与共同核综合（v4）

基于 `1fef998a` 恢复两处 U2 优化：普通 sponge 复用流水末级状态；P>1 的 SLH Sign WOTS 使用完成直接写回。冻结当前源码后完成 13 组 128f Sign 仿真与共同核综合，13/13 通过，失败 0。

配置为 U1 的 P1/2/3/4/6/8/12，以及 U2 的 P1/2/3/4/6/12。每点 Verilator 签名字节匹配软件参考，Hash/置换次数均为 104937/105641。未运行 Icarus。最多 13 个任务并行，每个 Vivado 和仿真编译各 2 线程。

全部点采用 xc7a200tffg1156-3、共同核 OOC、6.666667 ns、默认时序驱动综合、统计关闭，检查统计寄存器裁剪；未布线。P2U2 本轮正常完成，不采用旧诊断面积。U1=150 MHz、U2=110 MHz 均为假定频率。

完整资源、周期、ATP、Keccak 有效轮利用率及历史对比见 [排名报告](Single_Lane_13_ATP_150_110.md) 和同名 CSV/JSON。有效轮利用率=置换次数×24/(P×U×计算周期)。13 组结果与误删前 v3 的对话记录一致；v3 原始证据已删除，本轮使用独立冻结快照和重新测量的数据。

实验目录：[single_lane_13_20261009_v4](../../manifests/experiments/single_lane_13_20261009_v4/)。包含源码快照、源码差异、配置、status.json、service.log、results.csv/json、report.md，以及每点仿真输出和分层面积。源码改变不会影响已冻结实验。

重新生成发布报告：`python3 scripts/report_single_lane_13.py`，只读取已有结果，不启动仿真或综合。新实验使用新的目录，保留已有原始证据。
''')
    write(OUT/'published_report_sha256.json',{str(f.relative_to(ROOT)):sha(f) for f in [DOC.with_suffix(e) for e in ['.md','.csv','.json']]+[OVERVIEW,Path(__file__).resolve()]})
    print('REPORT_PASS 13/13; v3 conversation match; P12U1 ATP=33878.415')

if __name__=='__main__':
    main()
