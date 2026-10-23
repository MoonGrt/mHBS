#!/usr/bin/env python3
"""Archive and report the isolated c area experiment; never launch hardware jobs."""
from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import shutil
import time


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RUN = ROOT / "build/c_atp_optimization/20261023_121549"
STAGES = ("combined", "area_banks", "area_banks_shared", "area_legal_decode", "area_legal_bytes", "area_cursor")
BACKENDS = ("shake", "sha2")
NEW_JOBS = tuple((stage, backend) for stage in ("area_banks", "area_banks_shared", "area_legal_bytes", "area_cursor")
                 for backend in BACKENDS)
REPORT_FILES = (
    "hierarchical.rpt", "timing.rpt", "utilization.rpt", "critical_paths.rpt",
    "settings.txt", "debug_audit.json", "vivado.log", "diagnostic_clock.xdc",
)
BASELINE_REPORT = Path(
    "docs/manifests/experiments/macro_atp_restart_20261021_164834/"
    "reports/Macro_ATP_Restart.md"
)
TERMINAL = {"passed", "failed", "error", "stopped", "cancelled"}


def digest(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def write_if_changed(path: Path, data: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists() or path.read_text() != data:
        temporary = path.with_name(path.name + ".tmp")
        temporary.write_text(data)
        temporary.replace(path)


def save_json(path: Path, data: dict) -> None:
    write_if_changed(path, json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def copy_evidence(source: Path, target: Path, archive: Path, items: dict) -> None:
    if not source.is_file():
        return
    checksum = digest(source)
    if not target.is_file() or digest(target) != checksum:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    items[str(target.relative_to(archive))] = {
        "source": str(source), "sha256": checksum, "bytes": source.stat().st_size,
    }


def baseline() -> tuple[dict, str | None]:
    """Read the archived final c values, never a different design's area."""
    path = ROOT / BASELINE_REPORT
    if not path.is_file():
        return {}, "历史基线报告缺失；不填入其他实现的面积。"
    text = path.read_text()
    rows = {}
    for backend in BACKENDS:
        found = re.search(
            rf"^\| image-chain \| {backend} \|([^\n]+)", text, re.MULTILINE
        )
        if not found:
            continue
        fields = [value.strip().replace(",", "") for value in found[1].split("|")]
        rows[backend] = {
            "lut": int(fields[1]), "ff": int(fields[3]),
            "equivalent_slice": float(fields[5]),
            "bram": None, "dsp": None,
            "status": "historical_measured", "report": str(BASELINE_REPORT),
            "report_sha256": digest(path), "new_measurement": False,
        }
    return rows, None


def extract(pattern: str, text: str, cast=float):
    found = re.search(pattern, text, re.MULTILINE)
    return cast(found[1].replace(",", "")) if found else None


def synth_row(run: Path, stage: str, backend: str, state: dict, old: dict) -> dict:
    directory = run / "stages" / stage / "synth" / backend
    log = (directory / "vivado.log").read_text(errors="replace") if (directory / "vivado.log").is_file() else ""
    status = state.get(f"{stage}/{backend}", {}).get("status", "pending")
    complete_marker = "MHBS_TIMING_DIAGNOSTIC_PASS" in log
    if complete_marker:
        status = "passed"
    elif re.search(r"^ERROR:", log, re.MULTILINE) and "Exiting Vivado" in log:
        status = "failed"
    elif log and status == "pending":
        status = "running"
    withdrawal = read_json(run / "stages" / stage / "WITHDRAWN.json")
    if withdrawal:
        status = "withdrawn"
    row = {
        "stage": stage, "backend": backend, "status": status,
        "synthesis_complete": complete_marker, "directory": str(directory),
        "withdrawal": withdrawal or None,
        "validation_status": "partial_checks_only" if stage == "combined" else "not_simulated_per_user",
        "routed": False, "actual_fmax_mhz": None,
        "candidate_cycles": None, "candidate_atp": None,
        "required_reports_missing": [name for name in REPORT_FILES if not (directory / name).is_file()],
    }
    utilization = (directory / "utilization.rpt").read_text() if (directory / "utilization.rpt").is_file() else ""
    for key, label, cast in (("lut", r"Slice LUTs\*?", int), ("ff", "Slice Registers", int),
                             ("bram", "Block RAM Tile", float), ("dsp", "DSPs", int)):
        row[key] = extract(rf"^\|\s*{label}\s*\|\s*([\d,.]+)", utilization, cast)
    # Only completed synthesis contributes an accepted area comparison.
    row["equivalent_slice"] = (row["lut"] / 4 + row["ff"] / 8
                               if complete_marker and row["lut"] is not None and row["ff"] is not None else None)
    area = row["equivalent_slice"]
    row["area_change_pct"] = ((area / old["equivalent_slice"] - 1) * 100
                              if area is not None and old else None)
    timing_path = directory / "timing.rpt"
    timing = timing_path.read_text() if timing_path.is_file() else ""
    row["synth_wns_ns"] = extract(r"Setup\s*:.*?Worst Slack\s+([-\d.]+)ns", timing)
    row["synth_whs_ns"] = extract(r"Hold\s*:.*?Worst Slack\s+([-\d.]+)ns", timing)
    row["debug_audit"] = read_json(directory / "debug_audit.json") or None
    row["settings"] = {}
    settings_path = directory / "settings.txt"
    if settings_path.is_file():
        row["settings"] = dict(line.split("=", 1) for line in settings_path.read_text().splitlines() if "=" in line)
    row["decision"] = ("withdrawn_semantic_regression" if withdrawal else
                       "rejected_sha2_area_regression" if stage == "combined" else "await_selection")
    return row


def validation_summary(run: Path) -> dict:
    # Read only the explicitly completed checks; never copy detailed sim logs.
    directory = run / "stages/combined/source/build/ablation/c/top_signature_check"
    views = []
    for log in sorted(directory.glob("*/run.log")):
        marker = re.search(r"TOP_SIGNATURE_PASS[^\n]*", log.read_text(errors="replace"))
        if marker:
            views.append({"view": log.parent.name, "marker": marker[0],
                          "raw_log": str(log), "sha256": digest(log)})
    return {"combined_top_signature_completed": views,
            "full44_regression_complete": False,
            "full44_note": "回归运行器已按用户要求停止；不声明44项全通过。",
            "area_banks": "not_simulated_per_user",
            "area_banks_shared": "not_simulated_per_user",
            "area_legal_decode": "withdrawn_semantic_regression",
            "area_legal_bytes": "not_simulated_per_user",
            "area_cursor": "not_simulated_per_user"}


def fmt(value, digits=3):
    if value is None:
        return "—"
    return f"{value:,.{digits}f}" if isinstance(value, float) else f"{value:,}"


def markdown(data: dict) -> str:
    lines = [
        "# c 实现面积优化：SHAKE／SHA2", "",
        f"更新时间：{data['updated_at']}；{len(NEW_JOBS)}项面积候选综合全部结束：{data['new_area_synthesis_terminal']}。", "",
        "范围：K1U1、单 Hash 通道、c 的 RTL CHAIN＋软件树控制；面积取同后端的 common。",
        "共同设置：Vivado 2025.2、xc7a200tffg1156-3、OOC、2线程、默认时序驱动综合、10ns诊断约束。",
        "等效Slice=LUT/4+FF/8；不含程序／模板／描述符ROM及签名缓存。", "",
        "用户已改为面积优先、仅综合。本轮未启动布局布线；10ns综合WNS只用于诊断，不能证明100MHz或150MHz达标，也不代表实际Fmax。", "",
        "| 阶段 | 后端 | 状态 | LUT | FF | BRAM | DSP | 等效Slice | 相对历史c | 综合WNS/ns | 验证／取舍 |",
        "|---|---|---|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for backend in BACKENDS:
        old = data["baseline"].get(backend)
        if old:
            lines.append(f"| 历史c C1 | {backend} | 历史已测 | {fmt(old['lut'])} | {fmt(old['ff'])} | — | — | {fmt(old['equivalent_slice'])} | 基线 | — | 原冻结设计的历史证据 |")
        for row in (item for item in data["rows"] if item["backend"] == backend):
            delta = f"{row['area_change_pct']:+.3f}%" if row["area_change_pct"] is not None else "—"
            label = "组合候选淘汰：SHA2面积回退" if row["stage"] == "combined" else "仅综合，未仿真"
            if row["withdrawal"]:
                label = "语义审计发现回退，已撤回"
            elif row["stage"] == data["selection"].get("selected_stage"):
                label = "已选用；仅综合，未仿真"
            lines.append(f"| {row['stage']} | {backend} | {row['status']} | {fmt(row['lut'])} | {fmt(row['ff'])} | {fmt(row['bram'])} | {fmt(row['dsp'])} | {fmt(row['equivalent_slice'])} | {delta} | {fmt(row['synth_wns_ns'])} | {label} |")
    lines += ["", "combined 合并了控制／周期和配方优化，但SHA2等效面积相对历史c约增加2.2%，故不作为最终面积候选。后续面积候选按相同设置仅综合；未仿真，功能和周期仍待验证。",
              "", "area_legal_decode 曾将SHA2 profile_code固定为0，但合法自定义stateful程序仍可读取FORS_TARGET上下文；该折叠改变可观察语义，已撤回。该阶段不计入等待任务、不作为候选；撤回原因、冻结源码及已产生日志仍保留。",
              "", "area_legal_bytes 保留原始 profile_code=config_code[1:0]，仅简化SHA2合法配置的节点字节数选择：stateful为32字节、SLH为16字节。它旨在保持全部合法ROM行为；本阶段仅综合，尚未经过仿真验收，不声明功能等价已验证。",
              "", "area_cursor 基于私有游标生命周期审计，将互斥使用的 transform_index／chain_cursor／lt_cursor 合并为8位 work_cursor，供消息半字节选择等逻辑复用。该候选未改变预定调度或外部指令集；仅综合，功能和周期仍未仿真验证。",
              "", "候选未得到完整测量周期及布线频率，因此本报告不填写候选ATP，也不把历史周期移植到未验证候选。", "",
              "## 最终选择", ""]
    if data["selection"]:
        lines += ["以下按运行目录 SELECTION.json 原样记录：", "", "```json",
                  json.dumps(data["selection"], ensure_ascii=False, indent=2), "```"]
    else:
        lines.append("尚未收到 SELECTION.json；不自动宣布任何未完成／未验证候选胜出。")
    lines += ["", "## 已有检查及适用范围", "",
              "combined 的部分配方／整核检查已完成，随后测试任务按用户要求停止；不得声称44项回归全部通过。最新面积候选按用户要求未执行仿真。"]
    views = data["validation"]["combined_top_signature_completed"]
    if views:
        lines += ["", f"combined 已完成 top 签名视图检查 {len(views)}/8 项：", ""]
        lines += [f"- `{item['view']}`：`{item['marker']}`。" for item in views]
    if data["validation_scope"]:
        lines += ["", "运行器提供的验证范围摘要：", "", "```json",
                  json.dumps(data["validation_scope"], ensure_ascii=False, indent=2), "```"]
    lines += ["", "## 冻结与归档", "",
              "各阶段保留其自身 frozen_rtl.tar.gz、冻结源码 SOURCE.json，以及综合 hierarchical、timing、utilization、settings、debug_audit 和 Vivado日志。缺项记录在JSON；不使用当前RTL替换历史快照。",
              "不归档DCP或仿真明细日志；原始运行日志仍在build目录。MD／JSON报告与证据路径见本实验 ARTIFACTS.json。",
              f"后台模式每60秒检查一次，{len(NEW_JOBS)}项新候选综合结束后退出，不持续重写完成报告。", ""]
    if data["baseline_warning"]:
        lines += [data["baseline_warning"], ""]
    return "\n".join(lines)


def report(run: Path, archive: Path) -> dict:
    state = read_json(run / "AREA_STATE.json")
    old, warning = baseline()
    rows = [synth_row(run, stage, backend, state, old.get(backend, {}))
            for stage in STAGES for backend in BACKENDS]
    selection = read_json(run / "SELECTION.json")
    for row in rows:
        if row["stage"] == selection.get("selected_stage"):
            row["decision"] = "selected_area_only"
    terminal = all(next(row for row in rows if row["stage"] == stage and row["backend"] == backend)["status"] in TERMINAL
                   for stage, backend in NEW_JOBS)
    data = {
        "schema": "mhbs.c_area_optimization.v1", "updated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "run_directory": str(run), "archive_directory": str(archive),
        "baseline_report": str(BASELINE_REPORT), "baseline_warning": warning, "baseline": old,
        "rows": rows, "new_area_synthesis_terminal": terminal,
        "required_jobs": [f"{stage}/{backend}" for stage, backend in NEW_JOBS],
        "selection": read_json(run / "SELECTION.json"), "validation": validation_summary(run),
        "validation_scope": read_json(run / "VALIDATION_SCOPE.json") or read_json(run / "validation_scope.json"),
        "policy": {"poll_seconds": 60, "simulation_for_new_area_candidates": False,
                   "place_route_started": False, "wns_is_synthesis_diagnosis_only": True},
    }
    evidence = {}
    sources = {}
    for stage in STAGES:
        source = run / "stages" / stage
        for relative in ("frozen_rtl.tar.gz", "source/SOURCE.json", "WITHDRAWN.json"):
            copy_evidence(source / relative, archive / "stages" / stage / relative, archive, evidence)
        manifest = source / "source/SOURCE.json"
        sources[stage] = {"source_manifest": f"stages/{stage}/source/SOURCE.json",
                          "sha256": digest(manifest) if manifest.is_file() else None,
                          "frozen_rtl_sha256": digest(source / "frozen_rtl.tar.gz") if (source / "frozen_rtl.tar.gz").is_file() else None}
        for backend in BACKENDS:
            for name in REPORT_FILES:
                copy_evidence(source / "synth" / backend / name,
                              archive / "stages" / stage / "synth" / backend / name, archive, evidence)
    copy_evidence(ROOT / BASELINE_REPORT, archive / "baseline/Macro_ATP_Restart.md", archive, evidence)
    copy_evidence(run / "SELECTION.json", archive / "SELECTION.json", archive, evidence)
    for scope_name in ("VALIDATION_SCOPE.json", "validation_scope.json"):
        copy_evidence(run / scope_name, archive / scope_name, archive, evidence)
    copy_evidence(run / "AREA_STATE.json", archive / "AREA_STATE.json", archive, evidence)
    for name in ("LEGAL_BYTES_STATE.json", "CURSOR_STATE.json", "FROZEN_SOURCE_AUDIT.json"):
        copy_evidence(run / name, archive / name, archive, evidence)
    for name in ("changes.patch", "tools/initial_c_atp_runner.py"):
        path = archive / name
        if path.is_file():
            evidence[name] = {"source": str(path), "sha256": digest(path), "bytes": path.stat().st_size}
    copy_evidence(Path(__file__), archive / "tools" / Path(__file__).name, archive, evidence)
    save_json(archive / "SOURCE.json", {"schema": "mhbs.c_area_archive_sources.v1", "stages": sources,
                                        "reporter_sha256": digest(Path(__file__)),
                                        "base_commit": "240ee5677253a8817dae8e9df303efd751c55afd"})
    save_json(archive / "VALIDATION_SUMMARY.json", data["validation"])
    name = "C_Area_Optimization_20261023"
    save_json(archive / "reports" / f"{name}.json", data)
    write_if_changed(archive / "reports" / f"{name}.md", markdown(data))
    save_json(archive / "ARTIFACTS.json", {
        "schema": "mhbs.c_area_evidence.v1", "updated_at": data["updated_at"],
        "complete": terminal, "files": evidence,
        "reports": [f"reports/{name}.md", f"reports/{name}.json"],
        "missing": {f"{row['stage']}/{row['backend']}": row["required_reports_missing"] for row in rows if row["required_reports_missing"]},
        "excluded": ["DCP", "simulation detailed logs", "README.md"],
    })
    print(f"{data['updated_at']} area_synthesis_terminal={terminal} report={archive / 'reports' / (name + '.md')}", flush=True)
    return data


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, default=DEFAULT_RUN)
    parser.add_argument("--archive", type=Path)
    parser.add_argument("--watch", action="store_true", help=f"Poll every60s; exit after all {len(NEW_JOBS)} area syntheses become terminal")
    args = parser.parse_args()
    run = args.run.resolve()
    archive = args.archive or ROOT / "docs/manifests/experiments/c_atp_optimization_20261023_121549"
    while True:
        result = report(run, archive.resolve())
        if not args.watch or result["new_area_synthesis_terminal"]:
            break
        time.sleep(60)


if __name__ == "__main__":
    main()
