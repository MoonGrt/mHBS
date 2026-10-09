#!/usr/bin/env python3
"""Build an ATP comparison from frozen source, simulation and Vivado evidence."""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
TARGETS = (("slh_128f", "sign"), ("xmss_omega4", "keygen"), ("lms_omega4", "keygen"))
PASS = re.compile(r"STATEFUL_PASS P(\d+)U(\d+) op=(\d+) cycles=(\d+) total=(\d+) "
                  r"hashes=(\d+) permutations=(\d+) tamper=(\d+)")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def area(folder):
    log = (folder / "vivado.log").read_text()
    if "MHBS_SYNTH_PASS" not in log or re.search(r"^ERROR:", log, re.M):
        raise ValueError(f"synthesis did not pass: {folder}")
    report = (folder / "core_utilization.rpt").read_text()
    def used(label):
        match = re.search(r"^\|\s*" + re.escape(label) + r"\s*\|\s*([\d.]+)\s*\|", report, re.M)
        if not match:
            raise ValueError(f"missing {label}: {folder}")
        return float(match[1])
    result = dict(lut=used("Slice LUTs*"), ff=used("Slice Registers"),
                  lutram=used("LUT as Memory"), bram36=used("Block RAM Tile"), dsp=used("DSPs"))
    result["equivalent_slices"] = (result["lut"]/4 + result["ff"]/8
                                   + 232.4*result["bram36"] + 102.4*result["dsp"])
    timing = (folder / "core_timing.rpt").read_text()
    slack = re.search(r"Setup\s*:\s*\d+\s+Failing Endpoints,\s+Worst Slack\s+([-\d.]+)ns", timing)
    result["synthesis_wns_ns"] = float(slack[1]) if slack else None
    return result


def simulation(path, p, u, op):
    text = path.read_text()
    matches = list(PASS.finditer(text))
    if len(matches) != 1 or "%Error" in text:
        raise ValueError(f"invalid benchmark log: {path}")
    fields = list(map(int, matches[0].groups()))
    if fields[:3] != [p, u, op] or fields[-1] != 0:
        raise ValueError(f"wrong benchmark configuration: {path}")
    return dict(cycles=fields[3], total_cycles=fields[4], hashes=fields[5], permutations=fields[6])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--experiment", type=Path, default=ROOT / "docs/manifests/experiments/atp_optimization_20261013")
    parser.add_argument("--candidate", default="shared_read")
    parser.add_argument("--mapping", choices=("generic", "lut6"), default="generic")
    parser.add_argument("--config", nargs="+", default=["P4U1", "P12U1"])
    parser.add_argument("--output", type=Path, default=ROOT / "docs/report/ATP_Optimization_20261013")
    args = parser.parse_args()
    experiment = args.experiment.resolve()
    rows, resources, evidence = [], {}, {}
    for config in args.config:
        m = re.fullmatch(r"P(\d+)U(\d+)", config)
        if not m:
            raise ValueError(f"invalid configuration: {config}")
        p, u = map(int, m.groups())
        if u not in (1, 2):
            raise ValueError("frequency assumptions cover U1/U2 only")
        mhz = 150 if u == 1 else 110
        resources[config] = {}
        for variant in ("baseline", args.candidate):
            synth_root = experiment / variant / "synth"
            if not synth_root.is_dir():
                synth_root = experiment / variant / "build/synth"
            folder = synth_root / (config +
                     ("_generic" if variant != "baseline" and args.mapping == "generic" else ""))
            resources[config][variant] = area(folder)
            for filename in ("vivado.log", "core_utilization.rpt", "core_hierarchical.rpt", "core_timing.rpt"):
                path = folder / filename
                evidence[str(path.relative_to(experiment))] = digest(path)
        for profile, operation in TARGETS:
            values = {}
            for variant in ("baseline", args.candidate):
                path = experiment / variant / "runs" / config / f"{profile}_{operation}.log"
                metrics = simulation(path, p, u, 1 if operation == "sign" else 0)
                metrics.update(resources[config][variant])
                metrics["time_ms"] = metrics["cycles"] / (mhz * 1000)
                metrics["atp"] = metrics["equivalent_slices"] * metrics["time_ms"]
                values[variant] = metrics
                evidence[str(path.relative_to(experiment))] = digest(path)
            before, after = values["baseline"], values[args.candidate]
            if (before["hashes"], before["permutations"]) != (after["hashes"], after["permutations"]):
                raise ValueError(f"changed cryptographic workload: {profile}/{operation}/{config}")
            rows.append(dict(profile=profile, operation=operation, config=config, assumed_mhz=mhz,
                             before=before, after=after,
                             cycles_change_pct=(after["cycles"]/before["cycles"]-1)*100,
                             area_change_pct=(after["equivalent_slices"]/before["equivalent_slices"]-1)*100,
                             atp_change_pct=(after["atp"]/before["atp"]-1)*100))
    for variant in ("baseline", args.candidate):
        for path in sorted((experiment / variant / "rtl").rglob("*.sv")):
            evidence[str(path.relative_to(experiment))] = digest(path)
        for path in sorted((experiment / variant / "scripts").glob("*")):
            if path.is_file():
                evidence[str(path.relative_to(experiment))] = digest(path)
    checks = {}
    validation = experiment / args.candidate / "validation"
    for path in sorted(validation.rglob("*.log")):
        log = path.read_text()
        if "%Error" in log or not (PASS.search(log) or "STATEFUL_FAULT_PASS" in log):
            raise ValueError(f"validation has not passed: {path}")
        checks[str(path.relative_to(validation))] = len(PASS.findall(log)) or 1
        evidence[str(path.relative_to(experiment))] = digest(path)
    round_checks = experiment / "keccak_check"
    if not round_checks.is_dir():
        round_checks = ROOT / "build/keccak_check"
    for path in sorted(round_checks.glob("*.log")):
        if path.stem in ("generic", "lut6"):
            if "KECCAK_ROUND_PASS vectors=816" not in path.read_text():
                raise ValueError(f"round check has not passed: {path}")
            checks[f"keccak_{path.stem}"] = 816
            evidence[str(path.relative_to(ROOT))] = digest(path)
    for pattern in ("model/*.py", "model/reference/*.py", "tb/tb.sv", "sources.txt",
                    "tb/vectors/*/verify/*.mem", "tb/vectors/*/keygen/meta.mem",
                    "tb/vectors/*/sign/meta.mem"):
        for path in sorted(ROOT.glob(pattern)):
            evidence[str(path.relative_to(ROOT))] = digest(path)
    for folder in ("custom_xmss", "custom_lms"):
        for path in sorted((experiment / folder).rglob("*")):
            if path.is_file():
                evidence[str(path.relative_to(experiment))] = digest(path)
    current_source = {str(path.relative_to(ROOT)): digest(path) for path in
                      sorted((ROOT / "rtl").rglob("*.sv"))}
    for name, sha256 in current_source.items():
        if digest(experiment / args.candidate / name) != sha256:
            raise ValueError(f"working RTL differs from measured candidate: {name}")
    result = dict(schema="mhbs.atp_optimization.v1", date="2026-10-13", candidate=args.candidate,
                  keccak_mapping=args.mapping,
                  experiment=str(experiment.relative_to(ROOT)), routed=False,
                  frequency_basis="assumed 150 MHz U1 / 110 MHz U2; not measured",
                  area_formula="LUT/4 + FF/8 + 232.4*BRAM36 + 102.4*DSP",
                  resources=resources, rows=rows, validation=checks,
                  current_rtl_sha256=current_source, evidence_sha256=evidence)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.with_suffix(".json").write_text(json.dumps(result, indent=2) + "\n")
    with args.output.with_suffix(".csv").open("w", newline="") as handle:
        fields = ("profile", "operation", "config", "assumed_mhz", "before_cycles", "after_cycles",
                  "before_slices", "after_slices", "before_atp", "after_atp", "cycles_change_pct",
                  "area_change_pct", "atp_change_pct")
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({**{k: row[k] for k in fields if k in row},
                             "before_cycles": row["before"]["cycles"], "after_cycles": row["after"]["cycles"],
                             "before_slices": row["before"]["equivalent_slices"],
                             "after_slices": row["after"]["equivalent_slices"],
                             "before_atp": row["before"]["atp"], "after_atp": row["after"]["atp"]})
    lines = ["# 三目标 ATP 优化实测（2026-10-13）", "",
             "基线为本工作区修改前的冻结源码；本轮只比较列出的配置，不宣称覆盖全部 P/U 的全局最优。",
             "器件 xc7a200tffg1156-3，Vivado 2025.2，共同核 OOC，6.666667 ns，4 线程，统计关闭。",
             "U1 按 150 MHz、U2 按 110 MHz 假定计算。没有布局布线，ATP 是同频率假设下的面积×时间。",
             "等效 Slice = LUT/4 + FF/8 + 232.4×BRAM36 + 102.4×DSP；LUT 包含 LUTRAM。", "",
             "## 面积", "", "| 配置 | 基线 LUT / FF | 优化 LUT / FF | 等效 Slice 变化 |", "|---|---:|---:|---:|"]
    for config in args.config:
        b, a = resources[config]["baseline"], resources[config][args.candidate]
        lines.append(f"| {config} | {b['lut']:,.0f} / {b['ff']:,.0f} | {a['lut']:,.0f} / {a['ff']:,.0f} | {(a['equivalent_slices']/b['equivalent_slices']-1)*100:+.2f}% |")
    lines += ["", "## 周期与 ATP", "", "| 目标 | 配置 | 基线周期 | 优化周期 | 周期变化 | 基线 ATP | 优化 ATP | ATP 变化 |",
              "|---|---|---:|---:|---:|---:|---:|---:|"]
    for r in rows:
        lines.append(f"| {r['profile']} {r['operation']} | {r['config']} | {r['before']['cycles']:,} | {r['after']['cycles']:,} | {r['cycles_change_pct']:+.2f}% | {r['before']['atp']:,.3f} | {r['after']['atp']:,.3f} | {r['atp_change_pct']:+.2f}% |")
    lines += ["", "P12U1 是本轮两个配置中三个目标 ATP 都最低的配置。P4U1 的面积增长抵消了 SLH/XMSS 的周期收益，因此不能仅凭周期下降判定 ATP 改善。", "",
              "## 实现与剩余瓶颈", "",
              "1. XMSS/LMS 完整链端点直接写入现有端点 RAM，省去逐条 PIPE_LOAD、CHAIN_STORE、CHAIN_NEXT 消费。",
              "2. 不需要输出捕获的批次在最终响应边沿推进，省去等待完成掩码寄存一拍的气泡；捕获输出保留原顺序。",
              "3. 直接写回和批后读取先选标签，再共用上下文读取，删除重复的 digest/key 输出选择和部分 RAM 读端口。",
              "4. Keccak 支持通用表达式与显式 LUT6 候选。两者均逐轮检查；面积以本报告选定映射的实际综合为准。", "",
              "XMSS omega4 Keygen：1,024 片叶子，每片 67 条链；链部分 3,155,968 次 SHAKE，L-tree 部分 270,336 次，树父节点 4,092 次，总计 3,430,396 次。",
              "L-tree 的 66 次二输入归约/叶子，每次需要 4 次 SHAKE，目前串行。仅其置换延迟就至少 270,336×24=6,488,064 周期；P 增大后仍无法摊薄这部分串行延迟。下一项有明确收益潜力的结构优化是交错执行同一 L-tree 层内的独立归约。", "",
              "LMS omega4 Keygen：链部分 1,097,728 次 SHAKE，列表压缩、叶子包装与树父节点共 3,071 次，总计 1,100,799 次 Hash / 1,116,159 次置换。",
              "每片叶子的 2,166 字节列表需要 16 次置换。当前链吞吐已较高，后续应优先评估列表吸收与下一片叶子的链运算重叠，避免简单增加 P 带来的面积增长。", "",
              "SLH 128f Sign：104,937 次 Hash / 105,641 次置换。链结果已有直接写回，本轮周期收益主要来自批次推进；面积收益来自共同控制与存储选择逻辑。以上后续结构优化尚未实现，不计入本轮收益。", "",
              "## 时序与验证", "", "| 配置 | 基线综合 WNS (ns) | 优化综合 WNS (ns) |", "|---|---:|---:|"]
    for config in args.config:
        b, a = resources[config]["baseline"], resources[config][args.candidate]
        lines.append(f"| {config} | {b['synthesis_wns_ns']} | {a['synthesis_wns_ns']} |")
    lines += ["", "综合 WNS 未收敛，不能据此宣称达到 150 MHz 或实际 Fmax 提升。表中的 ATP 仅在给定频率假设下成立，实际频率和 ATP 仍需布局布线确认。", "",
              "两个 U1 配置分别通过十参数 Verify + 128f Keygen/Sign 冒烟，以及三个目标操作的字节、计数及排空检查。",
              "另有 U2、P1、统计关闭、停顿、复位重放、截断输入、篡改拒绝和在途故障检查。",
              "q=1023、消息 010203 的 XMSS/LMS 自定义向量由软件重生成并通过独立验证，再由 RTL 执行 Sign/Verify，覆盖末叶捕获。",
              "XMSS/LMS omega2 完整 Sign 检查覆盖 133 条链在 P12 下只有一个有效槽的尾批，并逐字节读取签名缓存。",
              f"归档补充检查共 {sum(checks.values())} 个通过项（包括两组各 816 项逐轮检查）；明细见 JSON。", "",
              "## 源码与证据", "",
              f"冻结源码、完整仿真日志、分层面积及综合时序：[`{result['experiment']}`](../../{result['experiment']}/)。",
              "同名 JSON 保存逐文件 SHA-256、Hash/置换计数与综合 WNS；CSV 保存可直接比较的数据。",
              "XMSS/LMS 的 omega4 表示每个链数字占 4 位，n=32、h=10，使用本仓库实验 SHAKE 配方。",
              "旧报告的历史面积不替代本轮冻结源码复测。", ""]
    args.output.with_suffix(".md").write_text("\n".join(lines))
    print(f"ATP_REPORT_PASS {len(rows)} comparisons: {args.output.with_suffix('.md')}")


if __name__ == "__main__":
    main()
