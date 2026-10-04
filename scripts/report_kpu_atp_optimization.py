from pathlib import Path
import json,csv,hashlib,shutil,subprocess
root=Path.cwd();out=root/'manifests/experiments/kpu_atp_opt_20261007'
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
names=['c1_shared_results','c2_direct_store','c3_continuous_slots','c4_shared_sponge','c4b_shared_sponge_write']
labels=['结果/capture 单份存储','WOTS 完成直接写回','连续任务槽位调度','sponge 状态复用首版','sponge 状态复用：去除自身写回']
baseline=json.loads((root/'manifests/experiments/l1up_128f_20261007_v1/results.json').read_text())['points']
summary=[];selected=None
for name,label in zip(names,labels):
 d=out/name;decision=json.loads((d/'decision.json').read_text());rows=json.loads((d/'results.json').read_text())
 summary.append(dict(candidate=name,change=label,accepted=decision['accepted'],best=decision['best'],points=rows,source_snapshot_sha256=sha(d/'source_snapshot.tar.gz')))
 if decision['accepted']:selected=name
 log=root/'build/kpu_atp_opt'/name/'driver.log'
 if log.exists():shutil.copy2(log,d/'driver.log')
 manifest={str(p.relative_to(d)):sha(p) for p in sorted(d.rglob('*')) if p.is_file() and p.suffix!='.dcp' and p.name!='evidence_sha256.json'}
 (d/'evidence_sha256.json').write_text(json.dumps(manifest,indent=2)+'\n')
rows=json.loads((out/selected/'results.json').read_text());best=min(rows,key=lambda r:r['atp_slice_ms'])
identity=json.loads((out/selected/'inputs.json').read_text())['source_sha256']
rtl_identity={p:h for p,h in identity.items() if p.startswith('rtl/')}
assert all(sha(root/p)==h for p,h in rtl_identity.items()),'Selected RTL differs from measured snapshot'
result=dict(scope='128f sign; common core',assumed_mhz=150,clock_ns=6.666667,routed=False,selected_candidate=selected,rtl_sha256=rtl_identity,baseline=baseline,candidates=summary,points=rows)
(out/'results.json').write_text(json.dumps(result,indent=2)+'\n')
with (out/'results.csv').open('w') as f:w=csv.DictWriter(f,fieldnames=rows[0]);w.writeheader();w.writerows(rows)
text='# K1P1U1～K1P4U1：ATP 优化\n\n'
text+='共同核综合，器件 xc7a200tffg1156-3，约束 6.666667 ns，综合关闭统计。统一假定 150 MHz，未布局布线，不能据此认定实际可达频率。基线为本轮开始时工作区及 `l1up_128f_20261007_v1` 冻结测量；历史文件名不改写。\n\n'
text+='| 独立候选 | 改动 | 最低 ATP（Slice·ms） | 最优点 | 决策 |\n|---|---|---:|---|---|\n'
text+='| 基线 | 原实现 | 42458.153 | K1P4U1 | 对照 |\n'
for c in summary:text+=f"| {c['candidate']} | {c['change']} | {c['best']['atp_slice_ms']:.3f} | {c['best']['point']} | {'保留' if c['accepted'] else '撤回'} |\n"
text+='\n四项优化共保存五个候选，第四项单独修正一次冗余自身写回。以四组最低 ATP 严格下降为保留标准，允许其他 P 档退步。候选 3 虽缩短周期，但面积增量抵消收益，未进入完整回归，已恢复候选 2 后继续候选 4。其四组签名字节及五组槽位释放单元检查通过，失败原因是 ATP，而非功能。\n\n'
text+='| 最终配置 | LUT | FF | LUTRAM | BRAM36 | 等效 Slice | 计算周期 | 总周期 | Hash | 置换 | 时间 ms | ATP Slice·ms | Keccak 利用率 |\n|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|\n'
for r in rows:text+=f"| {r['point']} | {r['lut']:.0f} | {r['ff']:.0f} | {r['lutram']:.0f} | {r['bram36']:g} | {r['equivalent_slice']:.3f} | {r['compute_cycles']} | {r['total_cycles']} | {r['hashes']} | {r['permutations']} | {r['time_ms']:.6f} | {r['atp_slice_ms']:.3f} | {r['keccak_utilization']:.2%} |\n"
text+='\n| 配置 | 相对基线 Δ等效 Slice | Δ计算周期 | ΔATP Slice·ms | ATP 变化 |\n|---|---:|---:|---:|---:|\n'
for r,b in zip(rows,baseline):
 text+=f"| {r['point']} | {r['equivalent_slice']-b['equivalent_slice']:+.3f} | {r['compute_cycles']-b['compute_cycles']:+d} | {r['atp_slice_ms']-b['atp_slice_ms']:+.3f} | {r['atp_slice_ms']/b['atp_slice_ms']-1:+.2%} |\n"
text+=f"\n最终保留 `{selected}`。最低 ATP 为 **{best['atp_slice_ms']:.3f}**，较基线下降 **{1-best['atp_slice_ms']/42458.15269333333:.2%}**。旧 K4P1U1 的 40862.122 仅作历史参考：源码版本不同，旧共同核采用 10 ns 综合约束；本轮没有重测旧 K4。\n\n"
text+=f"\n相对旧 K4P1U1 历史参考，最终最低 ATP 高 {best['atp_slice_ms']/40862.1219025-1:.3%}；本轮不能据此断言流水已优于旧四核。\n\n"
text+='等效 Slice = LUT/4 + FF/8 + BRAM36×232.4 + DSP×102.4；LUT 已包含 LUTRAM。时间 = 计算周期/150000 ms；ATP = 等效 Slice×时间。Keccak 有效轮利用率 = 置换次数×24/(K×P×U×计算周期)。面积不含外部 ROM 和签名存储。\n\n'
text+='保留候选均通过四组逐字节软件参考、统计关闭一致性、停顿/复位中断/连续重放、共同核等价、异常退出以及相关 Keccak/链/多块填充单元回归；默认 K2P1U2 仍为 729983 周期，K2P4U1 仍为 486328 周期。新增节点暂存读回检查覆盖 16/24/32 字节、零步、不同链长、capture 首/中/末及 tag 复用。最终另通过 17 项原有基础单元回归和 14 项 Python 流程契约测试；旧 recipe testbench 补接新增内部读口。未扩大其他参数集/操作的性能验收。\n\n'
text+='最终控制器保留批次边界：WOTS 完成即写端点、capture 按序输出，FORS 节点按序消费。没有保留候选 3 的连续补任务和显式释放调度；不能将其较短周期作为最终版本周期。外部接口、默认 K2P1U2、微码和存储深度不变。内部增加按 tag 读取结果/capture；最终保留修正版状态复用；网表审计确认原 1600 个私有 sponge FF 已消失。置换完成时不再把末级状态写回自身，仅初始化、吸收和链反馈需要显式写入。\n\n'
text+='实验目录：`manifests/experiments/kpu_atp_opt_20261007/`。每个候选保存源码快照、配置、补丁、完整日志、仿真结果及四组分层面积报告；最终报告路径为 `<候选>/K1P<n>U1/core_hierarchical.rpt`。复现单个新候选：`python3 scripts/run_kpu_atp_candidate.py --candidate <新标签> --best <前一最低ATP>`。以对应快照源码运行，不能直接用最终源码代替历史候选。\n'
(out/'report.md').write_text(text);(root/'docs/v4.2/KPU_ATP_Optimization.md').write_text(text)
shutil.copy2(out/'results.json',root/'docs/v4.2/KPU_ATP_Optimization.json')
shutil.copy2(out/'results.csv',root/'docs/v4.2/KPU_ATP_Optimization.csv')
(out/'final_source_audit.json').write_text(json.dumps(dict(passed=True,selected=selected,rtl_sha256=rtl_identity),indent=2)+'\n')
print('REPORT_READY',selected,best['point'],best['atp_slice_ms'])
