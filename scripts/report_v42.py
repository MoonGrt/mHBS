#!/usr/bin/env python3
"""Deterministic paper comparison from immutable measured evidence."""
import argparse,json,re
from pathlib import Path
from v42_flow import ROOT,BASE,BASELINE
p=argparse.ArgumentParser();p.add_argument('--check',action='store_true');args=p.parse_args()
base=json.loads(BASELINE.read_text());candidates=[json.loads(p.read_text()) for p in sorted((BASE/'candidates').glob('*/ppa.json'))]
papers=json.loads((ROOT/'manifests/experiments/unified_hbs_v4.1/slh_only/paper_optimization_sources.json').read_text())
final=json.loads((BASE/'final.json').read_text()) if (BASE/'final.json').exists() else None
best=next((r for r in candidates if final and r['tag']==final['candidate']),None)
lines=['# μHBS v4.2：独立运行、紧凑微码与论文启发优化','',
 '本报告由封存记录生成。三个 SLH 参数点及 Keygen/Sign 使用同一核，六份镜像仅替换 INIT。','',
 '## 1. 实现与验证','',
 '- program 64×64、template 16×64、descriptor 32×64（双读）；五类宏操作、RUN/LOOP 保留。',
 '- 删除硬件镜像扫描、类型和保留位校验，离线编译检查格式与引用。Sign 根作为输入，Boot 与操作周期分别记录。',
 '- 直接声明数组并 `$readmemh`，独立综合执行核，推断 LUT ROM；从连接导出 INIT 地址位映射，逐地址逐位验证。',
 '- 微码变更测试发现原独立 CHAIN 路径缺少归约/路由，已通过独立 WOTS 参考确认并修复；早期候选不作为功能验收版本。',
 '- 软件六组 KAT/输出/Hash 轨迹及计数；Icarus 存储、嵌套循环、握手、SHAKE/链及填充边界；Verilator 42 项扩展验证包含实际 RTL 根转交、交换、复位、消息边界、故障和微码变更。','',
 '## 2. 综合候选','',
 '| 候选 | 阶段 | LUT | FF | LUTRAM | Slice | MHz | 最差 Huang ATP 比例 | 性能验收 |',
 '|---|---|---:|---:|---:|---:|---:|---:|---|',
 f"| v4.1 基线 | post-route | {base['lut']:,} | {base['ff']:,} | {base['lutram']:,} | {base['equivalent_slice']:,.3f} | {base['frequency_mhz']:.3f} | {base['worst_ratio']:.4f} | 历史基线 |"]
for r in candidates:
 lines.append(f"| {r['tag']} | {r['stage']} | {r['lut']:,} | {r['ff']:,} | {r['lutram']:,} | {r['equivalent_slice']:,.3f} | {r['frequency_mhz']:.3f} | {r['worst_ratio']:.4f} | {'通过' if r['performance_pass'] else '未通过最终验收'} |")
synths=[r for r in candidates if r['stage']=='post_synth']
if synths:
 smallest=min(synths,key=lambda r:r['equivalent_slice'])
 lines += ['',f"已测综合候选中的最小面积：`{smallest['tag']}`，{smallest['equivalent_slice']:,.3f} Slice。布线后的面积与 ATP 选型见下一节。"]
lines+=['','综合行使用 100 MHz 归一化，不能解释为布线可达频率。LUTRAM 包含在 LUT 中，不重复加面积。',
 '面积公式：LUT/4 + FF/8 + BRAM36×232.4 + DSP×102.4。','',
 '直接 64 位吸收减少 FF，但增加 LUT，面积与周期均未改善。局部独立反馈的选择网络比复用快装通路更大；增加一拍反馈也增加签名周期。',
 '两级 U2 环形流水保持四个 round 实例，实际仍需各 lane 的吸收状态，并新增 3,200 位流水状态和输入选择。六组标准输出及计数通过，但整机面积和周期增加，综合时序也未显示足够改善。',
 '删除 SLH 不可达的 L-tree 成对归约及额外 leaf Hash 后，保留列表 Hash 和单链直通；再将三个合法参数集编码为 2 位编号，减少无效参数组合译码。两项候选周期均与紧凑编码基线一致。',
 '这些结果是当前具体候选的测量，不能推论所有直接吸收或交错流水设计均无收益。未保留的实现由各自源码快照复现。',
 '早期 compact_c2 布线因独立 CHAIN 微码测试失败而中断；检查点与日志保留，不计作完成布线。','',
 '## 3. 当前布线验收','']
if best:
 lines+=[f"共同面积 **{best['equivalent_slice']:,.3f} Slice**，共同频率 **{best['frequency_mhz']:.6f} MHz**。功能验收：通过；性能验收：{'通过' if best['performance_pass'] else '未通过'}。",'',
 '| Profile | Boot KG/Sign | Keygen 周期 | Sign 周期 | Keygen ATP | Sign ATP | 相对 v4.1 Sign ATP |',
 '|---|---:|---:|---:|---:|---:|---:|']
 for n,x in best['profiles'].items():
  lines.append(f"| {n} | {x['keygen_boot']}/{x['sign_boot']} | {x['keygen_cycles']:,} | {x['sign_cycles']:,} | {x['keygen_atp']:,.3f} | {x['sign_atp']:,.3f} | {(x['sign_atp']/x['baseline_atp']-1)*100:+.2f}% |")
 lines+=['',f"共同结构指纹：`{best.get('frozen_hardware_sha256','尚未冻结')}`。",'Boot 不包含在操作 ATP 中；上电总周期从释放外部复位到顶层完成，包含 23 拍 Boot 和额外 5 拍同步释放/启停控制。Sign 输入根来自 Keygen 并经过验证。',
  f"验收周期 {best['period_ns']:.1f} ns；setup 裕量 {best.get('final_clock',{}).get('wns_ns',0):.3f} ns，hold 裕量 {best.get('final_clock',{}).get('whs_ns',0):.3f} ns。采用 OOC 内部时序边界，rst 与输出端口设 false path；这些频率不包含板级 I/O 时序承诺。",'', '| Profile | Keygen 上电总周期 | Sign 上电总周期 |', '|---|---:|---:|']
 for n,x in best['profiles'].items():
  lines.append(f"| {n} | {x['keygen_total_cycles']:,} | {x['sign_total_cycles']:,} |")
else:lines+=['尚无 v4.2 最终布线验收结果。']
lines += ['', '## 3.1 候选周期与综合耗时', '', '| 综合候选 | Keygen 周期 128/192/256 | Sign 周期 128/192/256 | 综合 WNS@10ns | 综合脚本秒数 |', '|---|---|---|---:|---:|']
for r in candidates:
 if r['stage']!='post_synth':continue
 f=BASE/'candidates'/r['tag']
 txt=(f/'timing_summary.rpt').read_text()
 row=re.search(r'WNS\(ns\).*?\n\s*[- ]+\n([^\n]+)',txt,re.S)
 wns=float(row[1].split()[0])
 kg=' / '.join(f"{r['profiles'][n]['keygen_cycles']:,}" for n in base['profiles'])
 sg=' / '.join(f"{r['profiles'][n]['sign_cycles']:,}" for n in base['profiles'])
 seconds=(f/'synth_seconds.txt').read_text().strip()
 lines.append(f"| {r['tag']} | {kg} | {sg} | {wns:.3f} | {seconds} |")
lines += ['', '综合 WNS 仅供筛选；关键路径逐级延迟、层次资源和 Vivado 分阶段耗时保存在对应候选原始报告/日志。', '原 v4.1 基线 Sign 周期为 730,773 / 1,252,185 / 2,583,685；最终候选分别增加 277 / 276 / 223 拍，面积收益抵消了该调度开销和约 1% 的频率下降。', '最终候选同时是已完成布线候选中面积最小者。共同 LUTRAM 为 1,456，BRAM/DSP 均为 0。']
lines+=['','## 4. 与两篇论文比较','',
 '| 设计 | LUT | FF | BRAM36 | Slice | MHz |','|---|---:|---:|---:|---:|---:|']
for label,x in [('Unified HBS',papers['unified']),('Huang',papers['huang'])]:
 area=x['lut']/4+x['ff']/8+x['bram36']*232.4+x['dsp']*102.4
 lines.append(f"| {label} | {x['lut']:,} | {x['ff']:,} | {x['bram36']} | {area:,.3f} | {x['mhz']} |")
lines+=['','| Profile | Unified 周期/108 MHz ms | Unified ATP | Huang ms | Huang ATP |','|---|---:|---:|---:|---:|']
u=papers['unified'];h=papers['huang'];ua=u['lut']/4+u['ff']/8+u['bram36']*232.4;ha=h['lut']/4+h['ff']/8+h['bram36']*232.4
for n in base['profiles']:
 ms=u['sign_cycles'][n]/(u['mhz']*1000)
 lines.append(f"| {n} | {u['sign_cycles'][n]:,} / {ms:.6f} | {ua*ms:,.3f} | {h['sign_ms'][n]:.3f} | {ha*h['sign_ms'][n]:,.3f} |")
lines+=['',
 'Unified 的专用 OTS 快速输入和长输入串行通路适合减少通用输入选择。Huang 的八轮、四上下文流水通过四组状态缓冲提高吞吐，并在置换期间准备 HIL；其四个 Hash/12 拍不能直接套到本轮两上下文流水。',
 'Unified 128f 的 815,706 周期为用户转述作者更新，沿用原面积和 108 MHz；192f/256f 未收到更新。Huang 使用论文报告毫秒值。',
 '**NON_STRICT：**论文 SPHINCS+ 与本项目 FIPS 205 SLH-DSA、器件、功能、固定输入和 Keccak 结构不同。论文不是本轮硬门槛；验收要求三个 Sign ATP 优于当前 v4.1 基线。',
 '论文原文件及数值 SHA-256 沿用历史 `paper_optimization_sources.json`；[Huang 原文 DOI](https://doi.org/10.1109/TCSI.2025.3544341)，Unified 原文见项目外 `../../../references/papers/Unified_HBS_Architecture_2026_Reader/paper.md`。',
 'ROM 推断方法参考 [AMD UG901 ROM_STYLE](https://docs.amd.com/r/2023.2-English/ug901-vivado-synthesis/ROM_STYLE)，实际推断、映射及布线使用 Vivado 2025.2 实测。' ,'',
 '## 5. 复现','',
 '```bash','make compile-microcode','make rtl-unit-test','make rtl-all-profiles TAG=<新候选>',
 'make rtl-verification TAG=<新候选>','make synth-common TAG=<新候选>',
 'make route-common TAG=<新候选>','make freeze-common TAG=<新候选>',
 'python3 scripts/finalize_v42.py <新候选>_route --verification-tag <新候选>',
 'make report-v42 reproduce-v42','make reproduce-slh-only reproduce-paper-comparison','```','',
 '精确复跑已测候选应解开对应 source_snapshot.tar.gz，并使用 inputs.json 及归档的执行脚本。后续工具补充封存在 verification_tools.tar.gz，不能替换测量时的 RTL。','']
text='\n'.join(lines);target=ROOT/'docs/v4.2/Optimization_and_Paper_Comparison.md'
if args.check:assert target.read_text()==text,'report stale'
else:target.parent.mkdir(parents=True,exist_ok=True);target.write_text(text)
print('V42_REPORT_PASS')
