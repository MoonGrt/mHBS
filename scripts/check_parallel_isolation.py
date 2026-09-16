#!/usr/bin/env python3
"""Run both projects concurrently in separate disposable workspaces."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time


ROOT = Path(__file__).resolve().parents[1]
SIBLING_NAME = "Hash" + "Flow"


def ignore_micro(_directory: str, names: list[str]) -> set[str]:
    ignored = {"build", "artifact", ".git", ".Xil", "__pycache__"}
    return {
        name
        for name in names
        if name in ignored
        or name.startswith("vivado")
        or name == "clockInfo.txt"
        or name.endswith(".pyc")
    }


def ignore_sibling(_directory: str, names: list[str]) -> set[str]:
    ignored = {"build", ".git", ".Xil", "__pycache__"}
    return {
        name
        for name in names
        if name in ignored
        or name.startswith("vivado")
        or name == "clockInfo.txt"
        or name.endswith(".pyc")
    }


def tail(text: str, lines: int = 30) -> str:
    return "\n".join(text.splitlines()[-lines:])


def main() -> int:
    sibling = ROOT.parent / SIBLING_NAME
    if not sibling.is_dir():
        raise RuntimeError("optional sibling project is not present for the parallel check")

    with tempfile.TemporaryDirectory(prefix="micro-hbs-parallel-") as temporary:
        temp_root = Path(temporary)
        micro_copy = temp_root / "micro-hbs"
        sibling_copy = temp_root / "sibling"
        utility_source = ROOT.parent / "SLH-Util"
        utility_copy = temp_root / "SLH-Util"
        shutil.copytree(ROOT, micro_copy, ignore=ignore_micro)
        shutil.copytree(sibling, sibling_copy, ignore=ignore_sibling)
        if utility_source.is_dir():
            shutil.copytree(utility_source, utility_copy, ignore=ignore_sibling)
        env = dict(os.environ)
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        started = time.monotonic()
        processes = {
            "micro_hbs": subprocess.Popen(
                ["make", "ci-core"], cwd=micro_copy, env=env,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            ),
            "sibling": subprocess.Popen(
                ["make", "test"], cwd=sibling_copy, env=env,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            ),
        }
        results: dict[str, dict[str, object]] = {}
        for name, process in processes.items():
            try:
                output, _ = process.communicate(timeout=240)
            except subprocess.TimeoutExpired:
                process.terminate()
                output, _ = process.communicate(timeout=10)
                results[name] = {"returncode": 124, "tail": tail(output)}
            else:
                results[name] = {"returncode": process.returncode, "tail": tail(output)}

        result = {
            "schema_version": 1,
            "classification": "engineering_independence_check",
            "elapsed_seconds": round(time.monotonic() - started, 3),
            "separate_working_directories": micro_copy.parent == sibling_copy.parent
            and micro_copy != sibling_copy,
            "shared_output_directory": False,
            "results": results,
        }
        output_path = ROOT / "build" / "parallel_isolation.json"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(result, indent=2))
        return 0 if all(item["returncode"] == 0 for item in results.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
