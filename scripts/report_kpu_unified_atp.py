#!/usr/bin/env python3
"""Report source-bound unified Keccak ATP candidates without rewriting history."""
import csv,json,hashlib,tarfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
EXP=ROOT/'manifests/experiments/kpu_atp_unified_20261007'
NAMES={'c0_unified':'统一 compact lane 内的 P×U 轮结构（必须保留）','c1_one_formatter':'合并链哈希块构造','c2_capture_valid':'capture 有效位代替清零写入','c3_batch_control':'压缩 WOTS 批次及输出控制','c4_round_decode':'U1 遍次计数与固定级轮常量译码'}
def read(p):return json.loads(p.read_text())
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
 baseline=read(EXP/'baseline/results.json');candidates=[];selected=None
 for name,title in NAMES.items():
  d=EXP/name;decision=read(d/'decision.json');rows=read(d/'results.json')
  candidates.append(dict(name=name,description=title,decision=decision,points=rows))
  if decision['accepted']:selected=name
 assert selected is not None
 final=read(EXP/selected/'results.json');unified=candidates[0]['points'];identity=read(EXP/selected/'inputs.json')['source_sha256']
 audit={p:dict(measured=identity[p],current=sha(ROOT/p)) for p in (ROOT/'manifests/v42_sources.txt').read_text().splitlines()}
 assert all(x['measured']==x['current'] for x in audit.values())
 assert not (ROOT/'rtl/hash_lane/mhbs_keccak_pipeline.sv').exists()
 for c in candidates:
  for p in range(1,5):assert read(EXP/c['name']/f'K1P{p}U1/pruning_audit.json')['passed']
 best=lambda rows:min(rows,key=lambda r:r['atp_slice_ms'])
 b,u,f=map(best,(baseline,unified,final));gain=(1-f['atp_slice_ms']/b['atp_slice_ms'])*100
 obj=dict(baseline=baseline,unified=unified,candidates=candidates,selected=selected,final=final,assumed_mhz=150,clock_ns=6.666667,routed=False,rtl_source_audit=audit)
 lines=['# K1P1U1～K1P4U1：统一 Keccak 与第二轮 ATP 优化','',
 '范围：128f sign，共同核，xc7a200tffg1156-3，6.666667 ns 综合约束，统计关闭。**150 MHz 为假定值，未经布局布线验证。**',
 '', '原始基线为 `9e412986`，其 RTL 与上一轮最终测量快照一致。结构统一按用户要求必须保留；其余候选仅在四组最低 ATP 严格下降且回归通过时保留。','',
 '| 候选 | 改动 | 最低 ATP Slice·ms | 最优点 | 决策 |','|---|---|---:|---|---|',
 f"| 原始基线 | 上一轮最终实现 | {b['atp_slice_ms']:.3f} | {b['point']} | 对照 |"]
 for c in candidates:
  z=best(c['points']);lines.append(f"| {c['name']} | {c['description']} | {z['atp_slice_ms']:.3f} | {z['point']} | {'保留' if c['decision']['accepted'] else '撤回'} |")
 lines+=['',f"最终保留 `{selected}`；最低 ATP **{f['atp_slice_ms']:.3f}**，相对原始基线变化 **{-gain:+.3f}%**，相对统一后基线变化 **{(f['atp_slice_ms']/u['atp_slice_ms']-1)*100:+.3f}%**。",'',
 '| 配置 | LUT | FF | LUTRAM | BRAM36 | DSP | 等效 Slice | 计算周期 | 总周期 | Hash | 置换 | 时间 ms | ATP Slice·ms | 有效轮利用率 |',
 '|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|']
 for r in final:
  lines.append(f"| {r['point']} | {r['lut']:.0f} | {r['ff']:.0f} | {r['lutram']:.0f} | {r['bram36']:g} | {r['dsp']:g} | {r['equivalent_slice']:.3f} | {r['compute_cycles']} | {r['total_cycles']} | {r['hashes']} | {r['permutations']} | {r['time_ms']:.6f} | {r['atp_slice_ms']:.3f} | {r['keccak_utilization']*100:.2f}% |")
 lines+=['','| 配置 | 原始 ATP | 统一后 ATP | 最终 ATP | 最终 ΔLUT | 最终 ΔFF | 最终 Δ周期 | 最终 ΔATP |','|---|---:|---:|---:|---:|---:|---:|---:|']
 for x,y,z in zip(baseline,unified,final):
  lines.append(f"| {z['point']} | {x['atp_slice_ms']:.3f} | {y['atp_slice_ms']:.3f} | {z['atp_slice_ms']:.3f} | {z['lut']-x['lut']:+.0f} | {z['ff']-x['ff']:+.0f} | {z['compute_cycles']-x['compute_cycles']:+d} | {z['atp_slice_ms']-x['atp_slice_ms']:+.3f} |")
 lines+=['','等效 Slice = LUT/4 + FF/8 + BRAM36×232.4 + DSP×102.4；LUT 已含 LUTRAM，不重复计数。时间(ms)=计算周期/150000；ATP=等效 Slice×时间。有效轮利用率=置换次数×24/(K×P×U×计算周期)，是有效轮吞吐比例，不是每个流水级的实测占用率。面积不含外部 ROM 和签名存储。','',
 '统一结构只保留 compact lane 内一套 P×U 轮实例，`mhbs_keccak` 是唯一组合轮实现。删除独立 pipeline 模块和重复轮函数；P1 不增加启动/返回周期，P>1 保留反馈和共享末级状态。测试适配器仅存在于 testbench，不进入综合。','',
 '验证：四组签名逐字节对照软件参考，Hash/置换次数保持 104937/105641；结构统一的四组周期与原始基线一致。保留候选通过统计关闭、停顿/复位重放、共同核等价、异常退出和默认 K2P1U2/K2P4U1 检查。候选特定测试覆盖块构造、capture 禁用/未命中/复用、轮号等价、交错返回、多块填充。详细通过记录以各候选 validation.json、unit_evidence 及定向测试目录为准。','',
 '最终选择源码另通过 17 项基础单元测试、14 项 Python 流程测试及 P4 签名复跑；RTL 哈希与所选综合快照逐文件一致，20 组综合网表均确认统计寄存器为零。', '',
 '第四项通过轮译码、随机置换、四组正常签名及基础单元检查，但最低 ATP 高于第三项，未进入完整 ATP 收益候选回归，已撤回。最终仍保留原轮号译码；不能将第四项 P3 的面积作为当前 P3 面积。', '',
 '独立证据目录：`manifests/experiments/kpu_atp_unified_20261007/`。所有候选保留源码快照、补丁、配置、完整日志和分层报告；撤回的测量不代表当前 RTL。',
 f'当前分层面积报告：`manifests/experiments/kpu_atp_unified_20261007/{selected}/K1P<n>U1/core_hierarchical.rpt`。','',
 '本轮未布线、未提交、未推送；历史频率和旧四核结果未作为本轮实测对照。']
 doc='\n'.join(lines)+'\n';(EXP/'report.md').write_text(doc);(EXP/'report.json').write_text(json.dumps(obj,indent=2)+'\n')
 rows=[]
 for name,accepted,points in [('baseline',True,baseline)]+[(c['name'],c['decision']['accepted'],c['points']) for c in candidates]:
  for r,original in zip(points,baseline):
   rows.append(dict(candidate=name,accepted=accepted,**r,delta_lut=r['lut']-original['lut'],delta_ff=r['ff']-original['ff'],delta_cycles=r['compute_cycles']-original['compute_cycles'],delta_atp=r['atp_slice_ms']-original['atp_slice_ms'],relative_atp_vs_original=r['atp_slice_ms']/original['atp_slice_ms'],relative_atp_vs_own_p1=r['atp_slice_ms']/points[0]['atp_slice_ms']))
 with (EXP/'report.csv').open('w') as o:w=csv.DictWriter(o,fieldnames=rows[0]);w.writeheader();w.writerows(rows)
 for suffix in ('md','json','csv'):(ROOT/f'docs/v4.2/KPU_ATP_Unified_Optimization.{suffix}').write_bytes((EXP/f'report.{suffix}').read_bytes())
 (EXP/'final_source_audit.json').write_text(json.dumps(audit,indent=2)+'\n')
 print('REPORT_COMPLETE',selected,f['point'],round(f['atp_slice_ms'],3),flush=True)
if __name__=='__main__':main()
