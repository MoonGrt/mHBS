#!/usr/bin/env python3
"""Reject source/build dependencies on external architecture projects."""

from __future__ import annotations

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
SCANNED_SUFFIXES = {".py", ".sv", ".v", ".vh", ".tcl", ".mk"}
SCANNED_NAMES = {"Makefile"}
# Construct tokens so this checker does not need an exemption for itself.
RUNTIME_PROJECT = "Hash" + "Flow"
FIXED_FSM_PROJECT = "SLH" + "-Flow"
COPIED_FSM_PREFIX = "slh" + "_flow_"
COPIED_FSM_DIRECTORY = "rtl/slh" + "_dsa_full"
PATTERNS = (
    re.compile(r"\.\./" + RUNTIME_PROJECT, re.IGNORECASE),
    re.compile(r"\b(?:from|import)\s+" + RUNTIME_PROJECT + r"\b", re.IGNORECASE),
    re.compile(RUNTIME_PROJECT + r"/(?:build|experiments/raw)", re.IGNORECASE),
    re.compile(r"\.\./" + FIXED_FSM_PROJECT, re.IGNORECASE),
    re.compile(COPIED_FSM_PREFIX, re.IGNORECASE),
    re.compile(COPIED_FSM_DIRECTORY, re.IGNORECASE),
)


def main() -> int:
    failures: list[str] = []
    for path in ROOT.rglob("*"):
        if not path.is_file() or "build" in path.parts or ".git" in path.parts:
            continue
        if path.name not in SCANNED_NAMES and path.suffix not in SCANNED_SUFFIXES:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for lineno, line in enumerate(text.splitlines(), 1):
            if any(pattern.search(line) for pattern in PATTERNS):
                failures.append(f"{path.relative_to(ROOT)}:{lineno}: forbidden dependency")
    if failures:
        print("\n".join(failures))
        return 1
    print("independence scan: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
