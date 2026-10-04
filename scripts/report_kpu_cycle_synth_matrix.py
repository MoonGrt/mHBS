#!/usr/bin/env python3
"""Rank the frozen K/P/U 128f Sign matrix using stated assumed clocks."""
import csv
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXPERIMENT = ROOT / 'manifests/experiments/kpu_cycle_synth_20261008_v1'
OUT = ROOT / 'docs/report'
NAME = 'KPU_128f_Sign_ATP_20261008'
PAPER_AREA = 11587.975
PAPER_SIGN_MS = 4.95
PAPER_ATP = PAPER_AREA * PAPER_SIGN_MS


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    status = json.loads((EXPERIMENT / 'status.json').read_text())
    data = json.loads((EXPERIMENT / 'results.json').read_text())
    assert status['state'] == 'complete' and status['completed'] == 16 and status['failed'] == 0
    assert data['output_agreement'] and len(data['rows']) == 16
    rows = []
    for raw in data['rows']:
        assert raw['simulation'] == raw['synthesis'] == 'pass'
        assert (raw['hashes'], raw['permutations']) == (104937, 105641)
        point = raw['point']
        assert sha(EXPERIMENT / point / 'core_utilization.rpt') == json.loads((EXPERIMENT / point / 'synthesis.json').read_text())['evidence_sha256']['core_utilization.rpt']
        frequency = {1: 150, 2: 110}[raw['u']]
        elapsed_ms = raw['sign_cycles'] / (frequency * 1000)
        area = raw['lut'] / 4 + raw['ff'] / 8 + raw['bram36'] * 232.4 + raw['dsp'] * 102.4
        assert abs(area - raw['equivalent_slice']) < 1e-8
        keccak_utilization = raw['permutations'] * 24 / (raw['k'] * raw['p'] * raw['u'] * raw['sign_cycles'])
        assert 0 < keccak_utilization <= 1
        rows.append(dict(point=point, k=raw['k'], p=raw['p'], u=raw['u'],
                         lut=int(raw['lut']), ff=int(raw['ff']), lutram=int(raw['lutram']),
                         bram36=raw['bram36'], dsp=raw['dsp'], equivalent_slice=area,
                         sign_cycles=raw['sign_cycles'], assumed_mhz=frequency,
                         estimated_sign_ms=elapsed_ms, estimated_atp_slice_ms=area * elapsed_ms,
                         keccak_utilization=keccak_utilization,
                         paper_atp_ratio=area * elapsed_ms / PAPER_ATP,
                         output_sha256=raw['output_sha256']))
    assert len({r['output_sha256'] for r in rows}) == 1
    rows.sort(key=lambda r: (r['estimated_atp_slice_ms'], r['point']))
    for index, row in enumerate(rows, 1):
        row['rank'] = index
    OUT.mkdir(parents=True, exist_ok=True)
    csv_file = OUT / f'{NAME}.csv'
    with csv_file.open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    best, low_area = rows[0], next(r for r in rows if r['point'] == 'K1P4U1')
    lines = [
        '# K/P/U 128f Sign：周期、综合面积与 ATP 排序', '',
        '## 口径', '',
        '- 当前完成 **16/16** 个受生产 RTL 支持的点：K∈{1,2}、P∈{1,2,3,4}、U∈{1,2}。K3/K4 尚未实现，未列入排名。',
        '- 同一份冻结 RTL、128f Sign 的 **1 字节消息**和软件参考向量。16 点输出一致，均为 104,937 次 Hash、105,641 次 Keccak 置换。',
        '- 面积为 `mhbs_common` 的 **共同核 OOC 综合**：Vivado 2025.2、`xc7a200tffg1156-3`、10 ns 综合约束、`PROFILE_ENABLE=0`；LUT 已含 LUTRAM。共同核含通用控制与计算路径，但**不含外部 Program/Template/Descriptor ROM 和完整签名缓存**。',
        '- 按指定的 **U1=150 MHz、U2=110 MHz** 计算时间；这两个频率未对本次各 P 点布局布线签核。`时间(ms)=Sign 周期/(MHz×1000)`；`等效 Slice=LUT/4+FF/8+BRAM36×232.4+DSP×102.4`；`ATP=等效 Slice×时间(ms)`。',
        '- Keccak 利用率＝`置换次数×24/(K×P×U×Sign 周期)`，表示有效轮吞吐比例，不是逐级实测占用率。',
        '', '## ATP 升序', '',
        '| 排名 | K/P/U | LUT | FF | LUTRAM | BRAM36 | 等效 Slice | Sign 周期 | Keccak 利用率 | 假定 MHz | 估算 ms | 估算 ATP（Slice·ms） |',
        '|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|',
    ]
    for r in rows:
        lines.append(f'| {r["rank"]} | {r["point"]} | {r["lut"]:,} | {r["ff"]:,} | {r["lutram"]:,} | {r["bram36"]:g} | {r["equivalent_slice"]:,.3f} | {r["sign_cycles"]:,} | {r["keccak_utilization"]*100:.2f}% | {r["assumed_mhz"]} | {r["estimated_sign_ms"]:.6f} | {r["estimated_atp_slice_ms"]:,.3f} |')
    lines += [
        '', '## 与 Unified HBS 论文对照', '',
        '论文：[原文 PDF](../references/papers/Unified_Stateful_Stateless_HBS_Architecture_2026.pdf)；[阅读稿](../references/papers/Unified_HBS_Architecture_2026_Reader/paper.md)；[Table 5/6/7 原始数值及重算](../references/papers/Unified_HBS_Architecture_2026_Reader/Extracted_Data_and_Analysis.md)。对照论文 **This work / SPHINCS+ n=128**，不混入 Table 7 引用的其他设计。',
        '', '| 对象 | 面积口径 | LUT | FF | BRAM36 | 等效 Slice | Sign 周期 | MHz | Sign ms | ATP（Slice·ms） |',
        '|---|---|---:|---:|---:|---:|---:|---:|---:|---:|',
        f'| 论文 This work | 完整统一架构 | 24,184 | 13,659 | 16.5 | {PAPER_AREA:,.3f} | 537,636 | 108 | 4.95（原文报告） | {PAPER_ATP:,.3f}（按原文 ms 重算） |',
        f'| 当前 {best["point"]} | 共同核综合 | {best["lut"]:,} | {best["ff"]:,} | {best["bram36"]:g} | {best["equivalent_slice"]:,.3f} | {best["sign_cycles"]:,} | {best["assumed_mhz"]}（假定） | {best["estimated_sign_ms"]:.6f}（估算） | {best["estimated_atp_slice_ms"]:,.3f}（估算） |',
        f'| 当前 {low_area["point"]} | 共同核综合 | {low_area["lut"]:,} | {low_area["ff"]:,} | {low_area["bram36"]:g} | {low_area["equivalent_slice"]:,.3f} | {low_area["sign_cycles"]:,} | {low_area["assumed_mhz"]}（假定） | {low_area["estimated_sign_ms"]:.6f}（估算） | {low_area["estimated_atp_slice_ms"]:,.3f}（估算） |',
        '',
        f'- 直接比较表内数字，{best["point"]} 的共同核估算 ATP 比论文完整架构值低 **{(1-best["estimated_atp_slice_ms"]/PAPER_ATP)*100:.2f}%**；其 Sign 时间低 **{(1-best["estimated_sign_ms"]/PAPER_SIGN_MS)*100:.2f}%**，但共同核面积高 **{(best["equivalent_slice"]/PAPER_AREA-1)*100:.2f}%**。这只是描述性数字比较，**不能据此宣称完整设计 ATP 或最高频率优于论文**。',
        '- 论文比较的是可配置、支持 LMS/XMSS/SPHINCS+ 的完整架构；本轮只测当前源码的 SLH-DSA-SHAKE-128f Sign。SPHINCS+ 与 SLH-DSA、测试消息和统计边界并不逐项相同。论文的频率是报告值，本轮 U1/U2 频率是指定假设。',
        '- 当前设计完整签名缓存单独综合的历史记录为 11.5 BRAM36 等效、484 LUT、293 FF，但缓存 RTL 在本次快照中已改变；本报告不把旧模块数值直接加到本轮共同核面积。完整顶层还含 ROM 和外壳逻辑，需按相同快照重新综合及布线后才能作正式 ATP 对照。',
        '- 论文 Table 5 的 537,636 周期除以 108 MHz 得到 4.978111 ms，与其报告的 4.95 ms 不完全一致；此处沿用论文**原报告时间**重算论文 ATP。',
        '', '## 证据', '',
        f'- [实验状态](../../manifests/experiments/kpu_cycle_synth_20261008_v1/status.json)、[配置](../../manifests/experiments/kpu_cycle_synth_20261008_v1/config.json)、[原始结果](../../manifests/experiments/kpu_cycle_synth_20261008_v1/results.json)、[各点综合报告](../../manifests/experiments/kpu_cycle_synth_20261008_v1/report.md)。',
        '- [排序 CSV](KPU_128f_Sign_ATP_20261008.csv)。原始资源、仿真日志和冻结源码位于实验归档。',
        f'- 冻结源码快照 SHA-256：`{json.loads((EXPERIMENT / "config.json").read_text())["snapshot_sha256"]}`。论文 PDF SHA-256：`{sha(ROOT / "docs/references/papers/Unified_Stateful_Stateless_HBS_Architecture_2026.pdf")}`。',
    ]
    (OUT / f'{NAME}.md').write_text('\n'.join(lines) + '\n')
    print(OUT / f'{NAME}.md')


if __name__ == '__main__':
    main()
