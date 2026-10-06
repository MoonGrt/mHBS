#!/usr/bin/env python3
"""Audit and summarize the source-bound single-lane specialization experiment."""
import csv,hashlib,json,shutil
from pathlib import Path
from v42_external_flow import ROOT,identity,sha,write
OUT=ROOT/'manifests/experiments/single_lane_20261008'
BUILD=ROOT/'build/single_lane_20261008'
def load(p):return json.loads(p.read_text())
def main():
 normal=load(OUT/'equivalence_P1U1_stats1.json');assert len(normal)==30
 shell=load(OUT/'shell.json');assert shell['passed']
 shell_src=ROOT/'build/v4.2/external_job_message/single_lane_shell_final'
 shutil.copytree(shell_src/'logs',OUT/'shell_logs',dirs_exist_ok=True)
 for name,row in shell['cases'].items():
  assert sha(OUT/'shell_logs'/(name+'.log'))==row['log_sha256']
  assert sha(OUT/'shell_logs'/(name+'.actual.mem'))==row['output_sha256']
 edges=load(OUT/'edges.json');assert edges['passed']
 for row in list(normal.values())+list(edges['cases'].values()):
  assert row['passed'] and sha(ROOT/row['log'])==row['log_sha256']
 verify_src=ROOT/'build/v4.2/external_job_message/single_lane_verify'
 verify=load(verify_src/'verify/results.json');assert verify['passed'] and not verify['quick']
 verify_count=sum(len(x) for x in verify['profiles'].values());assert verify_count==118
 for profile,cases in verify['profiles'].items():
  for name,row in cases.items():assert sha(verify_src/'verify'/profile/(name+'.log'))==row['log_sha256']
 # Preserve logs/configuration, excluding rebuilt simulation executables.
 for src in verify_src.rglob('*'):
  if src.is_file() and ('binaries' not in src.parts and 'obj' not in src.parts) and (src.suffix in ('.log','.json') or src.name=='source_snapshot.tar.gz'):
   dest=OUT/'verify'/src.relative_to(verify_src);dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(src,dest)
 compiled={}
 for inp in BUILD.glob('P*U*_stats*/inputs.json'):
  d=OUT/'verification_inputs'/inp.parent.name;d.mkdir(parents=True,exist_ok=True)
  shutil.copy2(inp,d/'inputs.json');shutil.copy2(inp.parent/'compile.log',d/'compile.log');compiled[inp.parent.name]=load(inp)
 # Earlier executables predate only removal of whitespace at the end of four
 # blank RTL lines. Prove their production inputs match the final RTL.
 for point,files in compiled.items():
  for path in identity():
   if path.endswith('mhbs_top.sv'):continue # independently extracted common below
   oldhash=files[str(ROOT/path)]
   if oldhash!=sha(ROOT/path):
    previous=BUILD/'single_write_source'/path
    assert sha(previous)==oldhash
    assert [x.rstrip() for x in previous.read_text().splitlines()]==[x.rstrip() for x in (ROOT/path).read_text().splitlines()]
  common=BUILD/point/'common.sv'
  from v42_common_partition import partition
  assert sha(common)==files[str(common)]
  assert common.read_text()==partition((ROOT/'rtl/top/mhbs_top.sv').read_text())[0]
 rows=[]
 for point in ('P1U1','P1U2','P4U1'):
  old=load(OUT/'baseline'/point/'result.json');new=load(OUT/'final'/point/'result.json')
  assert new['rtl_sha256']==identity() and new['statistics_pruned'] and old['statistics_pruned']
  a,b=old['area'],new['area'];assert b['lut']<a['lut']
  if point=='P1U1':sim=normal['slh_128f_1_P1U1_stats1']
  else:sim=edges['cases'][point+'_stats1_slh128f_1']
  rows.append(dict(point=point,baseline_lut=int(a['lut']),lut=int(b['lut']),lut_change=int(b['lut']-a['lut']),lut_change_percent=100*(b['lut']/a['lut']-1),baseline_ff=int(a['ff']),ff=int(b['ff']),lutram=int(b['lutram']),bram36=b['bram36'],dsp=b['dsp'],baseline_equivalent_slice=a['equivalent_slice'],equivalent_slice=b['equivalent_slice'],sign_cycles=sim['compute_cycles'],total_cycles=sim['total_cycles'],hashes=sim['hashes'],permutations=sim['permutations'],assumed_mhz=150,time_ms=sim['compute_cycles']/150000,atp_slice_ms=b['equivalent_slice']*sim['compute_cycles']/150000,hierarchical_report=str((OUT/'final'/point/'core_hierarchical.rpt').relative_to(ROOT))))
 result=dict(baseline_commit='9dbcac8f154dabce9a5ce8e32cfbc4fb013d6779',comparison='frozen baseline explicitly LANES=1; current production has no lane parameter',rtl_sha256=identity(),part='xc7a200tffg1156-3',clock_period_ns=6.666667,profile_enable_synthesis=False,routed=False,actual_frequency_measured=False,normal_cases=len(normal),edge_cases=len(edges['cases']),slh_verify_cases=verify_count,rows=rows)
 write(OUT/'results.json',result)
 with (OUT/'results.csv').open('w') as f:
  w=csv.DictWriter(f,fieldnames=rows[0].keys());w.writeheader();w.writerows(rows)
 lines=['# 固定单 lane 与冗余裁剪（2026-10-08）','',
 '已从生产 top/common/core、仿真入口和当前 P/U 实验流程中删除 `LANES`、`SWAP_PHYSICAL_LANES`，没有兼容开关。唯一物理实例为 `core.lane`，默认 P1U2；P/U、六种 SLH 和四种实验 XMSS/LMS 的 Keygen/Sign/Verify 均保留。','',
 '基线为当前仓库提交 `9dbcac8f`，测量时显式固定旧实现为单 lane。历史多 lane 快照和报告未改写；旧驱动由 `legacy_lane_guard.py` 阻止在当前源码上运行。','',
 '## 综合结果','',
 '器件 xc7a200tffg1156-3，Vivado 2025.2，共同核 OOC、flatten rebuilt、6.666667 ns、PROFILE_ENABLE=0；不含外部 ROM 和签名缓存。总 LUT 已包含 LUTRAM，BRAM/DSP 均为零。这里只综合，未测布线频率。','',
 '| 配置 | 原 LUT | 当前 LUT | LUT 变化 | 原 FF | 当前 FF | LUTRAM | 原等效 Slice | 当前等效 Slice |',
 '|---|---:|---:|---:|---:|---:|---:|---:|---:|']
 for r in rows:lines.append(f"| {r['point']} | {r['baseline_lut']:,} | {r['lut']:,} | {r['lut_change']:,}（{r['lut_change_percent']:.2f}%） | {r['baseline_ff']:,} | {r['ff']:,} | {r['lutram']:,} | {r['baseline_equivalent_slice']:.3f} | {r['equivalent_slice']:.3f} |")
 lines += ['', '等效 Slice = LUT/4 + FF/8 + 232.4×BRAM36 + 102.4×DSP。旧基线已按单 lane 综合，第二套 Keccak 原本就不存在；收益来自控制与写回逻辑简化。', '', '## 删除内容','',
 '- 第二路任务、结果、capture 选择和统计汇总输入；移除 lane generate、交换映射及不存在的第二路流接口。',
 '- 双路启动/响应掩码、链批次掩码、verify_lane、FORS 成对叶消费和第二路输出状态。普通请求改为单个 ready/valid，流水窗口为 P。',
 '- 重复端点写地址/数据和双写仲裁。WOTS、FORS 根与 L-tree 共用一个写入口；136 项容量和相邻双读保留。L-tree 奇数尾节点、LMS 非对齐列表仍需要两个读值。',
 '- 统计关闭后的计数逻辑由综合裁剪；每个测量点通过网表统计寄存器审计。', '', '## 候选比较','',
 '| 候选 | P1U1 LUT / FF / 等效 Slice | P4U1 LUT / FF / 等效 Slice |',
 '|---|---:|---:|']
 for label,title in [('baseline','冻结旧单 lane'),('scalar','删除 L 配置与双路控制'),('single_write','进一步改为单写口（采用）')]:
  cells=[]
  for point in ('P1U1','P4U1'):
   a=load(OUT/label/point/'result.json')['area'];cells.append(f"{a['lut']:.0f} / {a['ff']:.0f} / {a['equivalent_slice']:.3f}")
  lines.append('| '+title+' | '+' | '.join(cells)+' |')
 lines += ['', '单写口是统一的最终接口：P1U1 的 LUT 比中间候选再少 514，P4U1 则多 934。单写口改善 P1 配置并删除冗余接口；P4U1 的最低面积仍为 scalar 候选，最终保留统一单写口结构。三个最终测量点均低于冻结旧单 lane 基线。`final` 与 `single_write` RTL 仅有空白清理差异，final 已重新综合，结果绑定最终 RTL 哈希。', '', '## 周期与 ATP','',
 '128f sign 的输出、握手、计算周期和 Hash/置换次数与旧单 lane 逐周期一致。Hash/置换均为 104937 / 105641。150 MHz 仅为假定值，未经布线验证；时间=计算周期/150000，ATP=等效 Slice×时间。', '',
 '| 配置 | 计算周期（前后相同） | 总周期 | 假定时间 ms | ATP Slice·ms |',
 '|---|---:|---:|---:|---:|']
 for r in rows:lines.append(f"| {r['point']} | {r['sign_cycles']:,} | {r['total_cycles']:,} | {r['time_ms']:.6f} | {r['atp_slice_ms']:.3f} |")
 lines += ['', '## 验证与证据','',
 f"- P1U1：10 参数×3 操作共 {len(normal)} 组，软件向量逐字节比较，冻结旧单 lane 并行对照逐周期事件与计数。",
 f"- 额外 {len(edges['cases'])} 组对照：P1～P4/U1～U2、统计关闭、普通/批次路径、消息/节点停顿、复位重放、截断、异常退出、q 边界和篡改。",
 f'- 六参数 SLH Verify 专用 bench：{verify_count} 项；覆盖零步/最大步、认证左右顺序、节点延迟、污染后复位、根高位忽略、统计关闭和提取前后等价。',
 '- P4U1 完整顶层与统计关闭的共同核提取版本、默认 P1U2 提取版本均通过；P4 的结果和周期一致。',
 '- 16 项核心单元、1 项启动协议、15 项 Python 合同检查及 RTL lint 通过。存储单元覆盖全部 136 项、127/128 边界、奇偶写与奇数尾项。', '',
 '本轮不提交、不推送、不布线。原始源码快照、候选补丁、综合日志和分层报告在 `manifests/experiments/single_lane_20261008/`；逐点分层报告：', '']
 for r in rows:lines.append(f"- [{r['point']}](../../{r['hierarchical_report']})")
 report='\n'.join(lines)+'\n';(OUT/'report.md').write_text(report)
 dest=ROOT/'docs/report/Single_Lane_Optimization';dest.with_suffix('.md').write_text(report)
 for ext in ('json','csv'):shutil.copy2(OUT/('results.'+ext),dest.with_suffix('.'+ext))
 print('SINGLE_LANE_REPORT_PASS',len(normal),len(edges['cases']),verify_count,flush=True)
if __name__=='__main__':main()
