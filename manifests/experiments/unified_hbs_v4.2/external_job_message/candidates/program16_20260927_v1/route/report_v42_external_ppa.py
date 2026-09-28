#!/usr/bin/env python3
"""Report current measured area and routed OOC timing, bound to the measured RTL."""
import json
from v42_external_flow import BASE, ROOT, sha

final = json.loads((BASE / 'final.json').read_text())
candidate = BASE / 'candidates' / final['candidate']
synth = json.loads((candidate / 'result.json').read_text())
assert sha(candidate / 'result.json') == final['result_sha256']
fresh = all((ROOT/p).is_file() and sha(ROOT/p) == h for p, h in synth['rtl_sha256'].items())
fresh = fresh and all(sha(BASE / 'images' / p.relative_to(candidate / 'images')) == sha(p)
                      for p in (candidate / 'images').rglob('*.mem'))
lines = ['# 当前面积与频率实测', '', f'候选：`{final["candidate"]}`。生产 RTL 和镜像与测量快照哈希一致：**{"是" if fresh else "否"}**。', '',
         '器件：`xc7a200tffg1156-3`；Vivado 2025.2；U2、双 Hash lane。等效 Slice = LUT/4 + FF/8 + BRAM36×232.4 + DSP×102.4，并非物理占用 Slice 数。', '',
         '## 综合面积', '', '| 对象 | LUT | FF | LUTRAM | BRAM36 | DSP | 等效 Slice |', '|---|---:|---:|---:|---:|---:|---:|']
for name, row in [('共同核', synth['core']), *synth['tops'].items()]:
    lines.append(f'| {name} | {row["lut"]:,.0f} | {row["ff"]:,.0f} | {row["lutram"]:,.0f} | {row["bram36"]:g} | {row["dsp"]:g} | {row["equivalent_slice"]:,.3f} |')
routed_final = BASE / 'routed_final.json'
if routed_final.exists() and json.loads(routed_final.read_text())['candidate'] == final['candidate']:
    rf = json.loads(routed_final.read_text())
    assert sha(candidate / 'route/result.json') == rf['route_result_sha256']
    routed = json.loads((candidate / 'route/result.json').read_text())
    lines += ['', '## 布线面积与频率', '',
              '六个参数外壳分别实现并通过核内时序检查。频率口径为 OOC 核内寄存器到寄存器路径，外部输入/输出路径排除；核内同步控制路径仍参与检查。周期取 0.1 ns 网格，保留至少 0.1 ns setup 裕量；核内 hold、脉宽、布线完整性和 ROM 内容均检查通过。**外部接口未完成时序签核**：初始 0 ns 输入/输出延迟假设产生不可由 OOC 路由修复的端口 hold 违例，原始报告保存在各配置的 core_timing/io_zero_delay_timing.rpt（恢复流程）或 io_zero_delay_timing.rpt。这里不声明板级或整接口工作频率。', '',
              f'六组核内时序均通过的共同频率：**{routed["common_frequency_mhz"]:.6f} MHz**。', '',
              '| 顶层 | LUT | FF | 等效 Slice | 周期 ns | 频率 MHz | WNS ns | WHS ns | 操作延迟 ms |',
              '|---|---:|---:|---:|---:|---:|---:|---:|---:|']
    for name, row in routed['tops'].items():
        lines.append(f'| {name} | {row["lut"]:,.0f} | {row["ff"]:,.0f} | {row["equivalent_slice"]:,.3f} | {row["period_ns"]:.1f} | {row["frequency_mhz"]:.6f} | {row["wns_ns"]:.3f} | {row["whs_ns"]:.3f} | {row["latency_ms"]:.6f} |')
else:
    lines += ['', '尚无此候选的完整布线验收，不声明频率。']
lines += ['', '## 证据与复现', '',
          f'源码快照 SHA-256：`{synth["source_snapshot_sha256"]}`。', '',
          f'完整证据：`manifests/experiments/unified_hbs_v4.2/external_job_message/candidates/{final["candidate"]}/`。功能证据包含 6 组正常执行、33 项扩展验证、6 组共同核等价、65 项 verify 节点测试，以及统计关闭和异常退出回归。', '',
          '```bash', 'python3 scripts/reproduce_v42_external.py', 'python3 scripts/reproduce_v42_external_route.py', 'make report-v42', '```', '']
(ROOT / 'docs/v4.2/Current_PPA.md').write_text('\n'.join(lines))
print('EXTERNAL_PPA_REPORT_PASS', final['candidate'], 'rtl_matches=', fresh)
