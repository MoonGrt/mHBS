#!/usr/bin/env python3
"""Publish separate XMSS/LMS omega4 Keygen ATP rankings from frozen evidence."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXP = ROOT / 'manifests/experiments/stateful_keygen_pu13_20261012_v1'
DEST = ROOT / 'docs/report'
PROFILES = (('xmss_omega4', 'XMSS'), ('lms_omega4', 'LMS'))
FREQUENCY = {1: 150, 2: 110}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def number(value, places=0):
    return f'{value:,.{places}f}'


def main():
    status = json.loads((EXP / 'status.json').read_text())
    config = json.loads((EXP / 'config.json').read_text())
    evidence = json.loads((EXP / 'results.json').read_text())
    assert (EXP / 'DONE').read_text().strip() == 'complete'
    assert status['state'] == 'complete' and status['completed_points'] == 13
    assert status['completed_cases'] == 26 and status['failed_points'] == 0
    assert config['operations'] == ['Keygen'] and config['profiles'] == [p for p, _ in PROFILES]
    assert config['max_parallel_vivado'] == 6 and config['vivado_threads'] == 4
    assert digest(EXP / 'source_snapshot.tar.gz') == config['snapshot_sha256']
    assert len(evidence['rows']) == 26
    DEST.mkdir(parents=True, exist_ok=True)
    for profile, title in PROFILES:
        entries = [row for row in evidence['rows'] if row['profile'] == profile]
        assert len(entries) == 13 and all(row['status'] == 'pass' for row in entries)
        assert len({row['point'] for row in entries}) == 13
        counts = {(row['hashes'], row['permutations'], row['output_bytes']) for row in entries}
        assert len(counts) == 1, counts
        for row in entries:
            folder = EXP / row['point']
            assert (folder / 'synthesis.json').exists()
            assert (folder / profile / 'simulation.json').exists()
            assert 'STATEFUL_PU_SYNTH_PASS ' + row['point'] in (folder / 'vivado.log').read_text()
            assert 'STATEFUL_PASS ' + row['point'] in (folder / profile / 'run.log').read_text()
            frequency = FREQUENCY[row['u']]
            row['assumed_mhz'] = frequency
            row['time_ms'] = row['compute_cycles'] / (frequency * 1000)
            row['atp_slice_ms'] = row['equivalent_slice'] * row['time_ms']
            row['area_cycles'] = row['equivalent_slice'] * row['compute_cycles']
        entries.sort(key=lambda row: (row['atp_slice_ms'], row['point']))
        hashes, permutations, output_bytes = counts.pop()
        filename = DEST / f'{title}_w4_Keygen_PU13_ATP_150_110.md'
        lines = [f'# {title} w=4 Keygen：13 个 P/U 配置 ATP 排名', '',
                 '13/13 点综合、13/13 组本参数集 Keygen 仿真通过。输出逐字节比对冻结参考向量；'
                 f'每点 Hash={number(hashes)}、置换={number(permutations)}、输出={number(output_bytes)} B。', '',
                 '器件 `xc7a200tffg1156-3`，Vivado 2025.2；共同核 OOC 综合约束 6.666667 ns，'
                 '统计关闭，最多同时运行 6 个 Vivado、每个 4 线程。面积不含外部镜像 ROM 和签名缓存；'
                 'LUT 已包含 LUTRAM。全部点 BRAM36=0、DSP=0。', '',
                 '**频率仅用于估算**：U1 取 150 MHz，U2 取 110 MHz，沿用此前 SLH 实验的约定值。'
                 '本轮没有布局布线，也没有验证这些频率在 XMSS/LMS 或各 P 点上可达；因此 ATP 排名是条件性的。'
                 '时间(ms)=计算周期/(假定 MHz×1000)；等效 Slice=LUT/4+FF/8+232.4×BRAM36+102.4×DSP；'
                 'ATP=等效 Slice×时间。', '',
                 '| 排名 | P/U | 假定 MHz | LUT | FF | LUTRAM | 等效 Slice | Keygen 计算周期 | 总周期 | 时间 ms | ATP Slice·ms |',
                 '|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|']
        for rank, row in enumerate(entries, 1):
            lines.append(f'| {rank} | {row["point"]} | {row["assumed_mhz"]} | '
                         f'{number(row["lut"])} | {number(row["ff"])} | {number(row["lutram"])} | '
                         f'{number(row["equivalent_slice"], 3)} | {number(row["compute_cycles"])} | '
                         f'{number(row["total_cycles"])} | {number(row["time_ms"], 3)} | '
                         f'{number(row["atp_slice_ms"], 3)} |')
        top = entries[0]
        p1u1 = next(row for row in entries if row['point'] == 'P1U1')
        p1u2 = next(row for row in entries if row['point'] == 'P1U2')
        u1_late = {row['compute_cycles'] for row in entries if row['u'] == 1 and row['p'] > 1}
        u2_late = {row['compute_cycles'] for row in entries if row['u'] == 2 and row['p'] > 1}
        assert len(u1_late) == len(u2_late) == 1
        lines += ['', f'**最低估算 ATP：{top["point"]}，{number(top["atp_slice_ms"], 3)} Slice·ms。**', '',
                  f'P2 及以上的计算周期在 U1 均为 {number(next(iter(u1_late)))}，'
                  f'在 U2 均为 {number(next(iter(u2_late)))}；提高 P 没有继续缩短本组 Keygen。'
                  '在这个条件频率口径下，P1U2 的面积增加由周期缩短抵消，'
                  f'ATP 相比 P1U1 低 {number(100 * (1 - p1u2["atp_slice_ms"] / p1u1["atp_slice_ms"]), 2)}%。', '',
                  f'冻结源码 SHA256：`{config["snapshot_sha256"]}`。'
                  f'原始数据与日志：[实验目录](../../manifests/experiments/stateful_keygen_pu13_20261012_v1/)；'
                  '每点 `core_hierarchical.rpt` 为分层综合面积报告。',
                  '重生成：`python3 scripts/report_stateful_keygen_pu13.py`。', '']
        filename.write_text('\n'.join(lines))
        print(filename.relative_to(ROOT), top['point'], number(top['atp_slice_ms'], 3))


if __name__ == '__main__':
    main()
