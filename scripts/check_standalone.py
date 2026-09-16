#!/usr/bin/env python3
"""Copy μHBS alone and run its core CI in the isolated copy."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parents[1]


def ignore(_directory: str, names: list[str]) -> set[str]:
    return {name for name in names if name in {"build", "artifact", "__pycache__", ".git"}}


def main() -> int:
    subprocess.run(["python3", "scripts/check_independence.py"], cwd=ROOT, check=True)
    with tempfile.TemporaryDirectory(prefix="micro-hbs-standalone-") as temp:
        copy = Path(temp) / "micro-hbs"
        shutil.copytree(ROOT, copy, ignore=ignore)
        env = dict(os.environ)
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        subprocess.run(["make", "ci-core"], cwd=copy, env=env, check=True)
        forbidden_parent = copy.parent / ("Hash" + "Flow")
        if forbidden_parent.exists():
            raise RuntimeError("standalone fixture unexpectedly contains sibling project")
    print("standalone copy CI: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
