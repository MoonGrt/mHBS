import json,hashlib,shutil
from pathlib import Path
TAG='program16_20260927_v1'
BASE=Path('manifests/experiments/unified_hbs_v4.2/external_job_message')
f=Path('build/v4.2/external_job_message')/TAG
out=BASE/'candidates'/TAG
s=json.loads((out/'result.json').read_text());r=json.loads((out/'route/result.json').read_text())
b=json.loads((BASE/'candidates/shared_list_store_20260927_v1/result.json').read_text())
c=json.loads((f/'program16_comparison.json').read_text())
assert c['passed'] and s['post_synth_acceptance'] and r['passed']
result=dict(candidate=TAG,baseline='shared_list_store_20260927_v1',program_words_before=32,program_words_after=16,used_program_words=14,core_before=b['core'],core_after=s['core'],area_change=s['core']['equivalent_slice']-b['core']['equivalent_slice'],common_frequency_mhz=r['common_frequency_mhz'],baseline_frequency_mhz=None,timing_scope=r['timing_scope'],cycles_unchanged=True,profile_enable=False)
(out/'program16_result.json').write_text(json.dumps(result,indent=2)+'\n')
(BASE/'program16.json').write_text(json.dumps(result,indent=2)+'\n')
shutil.copy2(f/'program16_comparison.json',out/'program16_comparison.json')
shutil.copy2('build/program16/incremental.patch',out/'incremental.patch')
shutil.copytree('build/program16',out/'progress',ignore=shutil.ignore_patterns('edit.py','__pycache__'),dirs_exist_ok=True)
rows=[]
for metric,label in [('lut','LUT'),('ff','FF'),('lutram','LUTRAM（包含于 LUT）'),('equivalent_slice','等效 Slice')]:
 old=b['core'][metric];new=s['core'][metric]
 rows.append(f'| {label} | {old:g} | {new:g} | {new-old:+g} |')
route_rows=[]
for name,row in r['tops'].items():
 route_rows.append(f'| {name} | {row["operation_cycles"]} | {row["period_ns"]:.1f} | {row["frequency_mhz"]:.6f} | {row["wns_ns"]:.3f} | {row["whs_ns"]:.3f} |')
text=f'''# Program 16 条容量实验与新频率

候选 `{TAG}`：program 从 32×64 缩为 16×64；六组布局布线全部通过，最低核内频率 **{r['common_frequency_mhz']:.6f} MHz**。共同核面积 **{s['core']['equivalent_slice']:.3f} 等效 Slice**，比上一版增加 **{result['area_change']:.3f}（{result['area_change']/b['core']['equivalent_slice']*100:.3f}%）**；本次缩容没有带来整核面积下降。

## 实现与资源

三种 f 参数的 program 均使用地址 0～13，剩余两条空闲；template 仍为 16 条，descriptor 仍为 32 条。三组 ROM 合计逻辑容量从 640 B 缩为 512 B。

PC、循环返回 PC、程序地址及内部入口地址从 5 位缩为 4 位。头部原有 5 位入口字段位置保持不变，软件检查入口小于 16，拒绝超过容量的镜像及 legacy 转换中的非零溢出指令。共同核提取、仿真 stub、ROM 构造镜像、INIT 映射和逐位审计同步更新。

| 共同核指标 | 32 条版本 | 16 条版本 | 差值 |
|---|---:|---:|---:|
{chr(10).join(rows)}

序列器本身从 169 LUT / 155 FF 降至 165 LUT / 152 FF。综合网表确认 PC/循环 PC 少了 3 个 FF，头部入口少了 2 个 FF；同时 Vivado 新增 8 个 list_cursor 和 6 个 node_level 复制寄存器、减少 1 个 message_received 复制寄存器，因此整核 FF 净增 8。这些是综合自动产生的寄存器副本，没有增加 RTL 状态或流水级；详细差异保存在 progress/register_difference.json。其他层级的 LUT 映射变化也抵消了序列器的节省。程序 ROM 每个数据位由 LUT5 改为 LUT4，仍需一个逻辑 LUT，存储位数减半不代表 FPGA LUT 数减半。完整分层报告保留了实际映射结果，未把逻辑容量缩减当作面积收益。

## 验证

模型六组参考输出、镜像容量与入口越界检查、14 项单元测试及合约/lint 通过。序列器新增从地址 12 启动、嵌套循环回跳、地址 15 停机测试，并保留握手停顿和延迟完成检查。

完整 RTL 回归通过：6 组 keygen/sign、33 项扩展、6 组共同核等价、12 组统计关闭、2 项统计关闭扩展、6 项故障退出、65 项 verify 节点测试。与 `shared_list_store_20260927_v1` 比较，六组输出 SHA-256、启动/计算/总周期、Hash/置换次数一致；62 项非故障 verify 的结果、节点数、Hash/置换数和扣除输入等待后的周期一致。

生产综合 `PROFILE_ENABLE=0`，统计和目标冗余寄存器审计通过。六个参数外壳的共同核指纹一致，综合和布线后的 ROM 每一位均核验通过。

## 本轮实测频率

器件 `xc7a200tffg1156-3`，Vivado 2025.2；保留至少 0.1 ns setup 裕量，核内 hold、脉宽与布线完整性检查通过。

| 配置 | 计算周期 | 时钟周期 ns | 核内频率 MHz | WNS ns | WHS ns |
|---|---:|---:|---:|---:|---:|
{chr(10).join(route_rows)}

以上为当前支持 verify 的共同核在六个 keygen/sign 参数外壳中的 OOC 核内时序。外部输入/输出路径不计入频率，接口未时序签核；没有额外测量 verify 专用外壳。上一版 32 条共享存储版本仅做过综合，未测频率，因此不能用本轮数据断言 PC 缩短带来了频率提升。更早的 104.166667 MHz 属于新增 verify 之前的历史实现，不作为同版本对照。

## 证据

- [当前 PPA](Current_PPA.md)
- [分层面积](../../manifests/experiments/unified_hbs_v4.2/external_job_message/candidates/{TAG}/synthesis/core_hierarchical.rpt)
- [布线结果](../../manifests/experiments/unified_hbs_v4.2/external_job_message/candidates/{TAG}/route/result.json)
- [输出与周期对照](../../manifests/experiments/unified_hbs_v4.2/external_job_message/candidates/{TAG}/program16_comparison.json)

候选目录保存独立源码快照、增量补丁、完整日志、功能证据和六组综合网表/布线检查点。源码快照 SHA-256：`{s['source_snapshot_sha256']}`。本轮未提交或推送。
'''
Path('docs/v4.2/Program16.md').write_text(text)
(out/'evidence_sha256.json').write_text(json.dumps({str(p.relative_to(out)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(out.rglob('*')) if p.is_file() and p.name!='evidence_sha256.json'},indent=2)+'\n')
print(json.dumps(result,indent=2))
