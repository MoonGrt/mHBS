#!/usr/bin/env python3
"""Render the SLH-only comparison exclusively from archived measurements."""
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/'manifests/experiments/unified_hbs_v4.1'
ACTIVE=BASE/'slh_only'
OUT=ROOT/'docs/v4.1/SLH_Only_Huang_Comparison.md'
NAMES=('slh_128f','slh_192f','slh_256f')
HUANG_MS=(1.950,3.195,6.613)
HUANG_AREA=29410/4+14090/8+4*232.4
HUANG_ATP={name:HUANG_AREA*ms for name,ms in zip(NAMES,HUANG_MS)}

def main():
    old=json.loads((BASE/'candidates/u2_area_balanced_route/ppa.json').read_text())
    candidates=[]
    for path in sorted((ACTIVE/'candidates').glob('*/ppa.json')):
        item=json.loads(path.read_text())
        if item['profile_set']!='slh_only' or set(item['profiles'])!=set(NAMES):continue
        candidates.append(item)
    routed=[c for c in candidates if c['stage']=='post_route' and c.get('performance_pass')]
    selected=min(routed,key=lambda c:(c['worst_ratio'],c['equivalent_slice'])) if routed else None
    area_choice=min(candidates,key=lambda c:(c['equivalent_slice'],c['worst_ratio'])) if candidates else None
    lines=['# μHBS v4.1：仅 SLH 的共同硬件与 Huang 等人处理器对照','',
        '## 口径','',
        '- 项目：FIPS 205 SLH-DSA SHAKE 128f/192f/256f，一次上电 Keygen→Sign；同一候选的三点仅替换 ABI 4 ROM INIT。',
        '- 论文：Huang 等，*An Efficient and Reconfigurable Post-Quantum Crypto-Processor for SPHINCS+*，IEEE TCAS-I 2025，表 I/II/V；Artix-7 XC7A100T，179.8 MHz，29,410 LUT、14,090 FF、4 BRAM、0 DSP。',
        '- 两者算法版本、器件、数据路径与签名输入不完全一致；以下逐点 ATP 为 **NON_STRICT** 性能对照。论文采用四路交错、8-round Keccak；项目固定 U2 并扫描 1/2/4 个独立 Hash lane。',
        f'- 等效面积公式：LUT/4 + FF/8 + BRAM36×232.4 + DSP×102.4；论文面积重算为 **{HUANG_AREA:,.3f} Slice**。',
        '- 选择规则：三个 SLH 点 ATP 均小于原七点共同核；再最小化三点中最大的项目/论文 ATP 比值，同分选较小面积。论文数值是对照，不是硬通过门槛。',
        '- 旧 V3 三点 ATP 仅作历史参考，不参与本轮 SLH-only 选型。','',
        '## 论文原值与当前七点共同核基线','',
        '| 参数 | 论文 Sign ms | 论文 Sign ATP Slice·ms | 原共同核 Sign 周期 | 原共同核 Sign ATP Slice·ms |',
        '|---|---:|---:|---:|---:|']
    for name,ms in zip(NAMES,HUANG_MS):
        b=old['profiles'][name]
        lines.append(f'| {name} | {ms:.3f} | {HUANG_ATP[name]:,.3f} | {b["sign_cycles"]:,} | {b["sign_atp"]:,.3f} |')
    lines += ['', '## SLH-only 候选','',
              '| 候选 | 阶段 | Lane | LUT | FF | LUTRAM | BRAM36 | Slice | MHz | 最大论文 ATP 比值 | 三点均优于基线 |',
              '|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|']
    for c in candidates:
        lines.append(f'| {c["tag"]} | {c["stage"]} | {json.loads((ACTIVE/"candidates"/c["tag"]/"inputs.json").read_text())["lanes"]} | {c["lut"]:,} | {c["ff"]:,} | {c["lutram"]:,} | {c["bram36_equivalent"]:g} | {c["equivalent_slice"]:,.3f} | {c["frequency_mhz"]:.3f} | {c["worst_ratio"]:.3f} | {"是" if all(x["improved"] for x in c["profiles"].values()) else "否"} |')
    if selected:
        lines += ['',f'## 最优 ATP：`{selected["tag"]}`','',
                  '| 参数 | Boot 周期 | Keygen 周期 | Sign 周期 | Slice | MHz | Keygen ATP Slice·ms | Sign ATP Slice·ms | 项目/论文 ATP |',
                  '|---|---:|---:|---:|---:|---:|---:|---:|---:|']
        for name in NAMES:
            d=selected['profiles'][name]
            lines.append(f'| {name} | {d["boot_cycles"]:,} | {d["keygen_cycles"]:,} | '
                         f'{d["sign_cycles"]:,} | {selected["equivalent_slice"]:,.3f} | '
                         f'{selected["frequency_mhz"]:.3f} | {d["keygen_atp"]:,.3f} | '
                         f'{d["sign_atp"]:,.3f} | {d["ratio"]:.3f} |')
        area_drop=100*(1-selected['equivalent_slice']/old['equivalent_slice'])
        atp_drop=100*(1-selected['profiles'][NAMES[0]]['sign_atp']/old['profiles'][NAMES[0]]['sign_atp'])
        lines += ['',f'相对原七点共同核，等效面积下降 {area_drop:.2f}%，三个 SLH 点的签名 ATP 均下降 {atp_drop:.2f}%。']
        lines += ['',f'最小面积候选：`{area_choice["tag"]}`，{area_choice["equivalent_slice"]:,.3f} Slice（{area_choice["stage"]}；综合候选的 100 MHz 仅作归一化）。']
        lines += ['',f'三份 INIT 检查点具有相同单元、连接、布局及路由指纹 `{selected["frozen_hardware_sha256"]}`；最终 setup/hold 裕量分别为 {selected["timing"]["wns_ns"]:.3f}/{selected["timing"]["whs_ns"]:.3f} ns。']
        lines += ['',f'布线、时序覆盖和三份 INIT 结构证据见 [候选记录](../../manifests/experiments/unified_hbs_v4.1/slh_only/candidates/{selected["tag"]}/ppa.json)。']
    else:
        lines += ['', '## 验收状态','', '尚无同时通过三点 ATP 改善与 post-route 的候选；综合数据仅作筛选。']
        if area_choice:
            lines.append(f'当前最小综合面积：`{area_choice["tag"]}`，{area_choice["equivalent_slice"]:,.3f} Slice（{area_choice["stage"]}）。')
    lines += ['', '## 复现与限制','',
              '- 当前生产核只接收三个 SLH profile；Job 的 q 必须为零，镜像中的有状态配方、索引片段和认证路径缓存模式在上电校验阶段被拒绝。旧七点镜像和结果仍由封存源码核验。',
              '- 功能检查：`make area-software-test compile-microcode rtl-unit-test architecture-test rtl-verification`。',
              '- 证据核验：`make reproduce-slh-only reproduce-paper-comparison`；候选源码、镜像、仿真、工具报告和检查点保存在 `manifests/experiments/unified_hbs_v4.1/slh_only/`。',
              '- 当前时序口径是 OOC 内部寄存器路径；外部输出路径未赋予板级时序要求。',
              '原七点报告及其证据保持在 v4.1 历史路径中。论文原文 DOI：[10.1109/TCSI.2025.3544341](https://doi.org/10.1109/TCSI.2025.3544341)。','']
    OUT.write_text('\n'.join(lines))
    print(OUT)

if __name__=='__main__':main()
