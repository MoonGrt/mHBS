#!/usr/bin/env python3
"""Run the U1 lane, typed processor, CHAIN and independent TREE protocol units."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from model.microcode import ABI

ROOT = Path(__file__).resolve().parents[1]
PROCESSOR_SOURCES = (
    "rtl/hash/keccak.sv",
    "rtl/hash/shake-recipe.sv",
    "rtl/executor/executor.sv",
    "tb/tb_hash_backend_contracts.sv",
)
TREE_SOURCES=(
    "tb/tree_vectors.svh",
    "scripts/generate_tree_vectors.py",
)
LANE_SOURCES = (*PROCESSOR_SOURCES[:2], "tb/tb_recipe.sv",
                "scripts/check_recipes.py")


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def run(command, log):
    with log.open("w") as stream:
        try:
            subprocess.run(command, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, check=True)
        except subprocess.CalledProcessError as exc:
            raise RuntimeError(f"Micro unit failed; see {log}") from exc


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path("build/image-chain-tree/units"))
    parser.add_argument("--verilator", default="verilator")
    args = parser.parse_args()
    folder = args.out.resolve(); folder.mkdir(parents=True, exist_ok=True)
    inputs = {name: sha(ROOT/name) for name in sorted(set(PROCESSOR_SOURCES+LANE_SOURCES+TREE_SOURCES))}
    inputs["rtl/executor/instructions.svh"] = sha(ROOT/"rtl/executor/instructions.svh")
    inputs["model/microcode.py"] = sha(ROOT/"model/microcode.py")
    inputs["scripts/check_hash_backend_contracts.py"] = sha(Path(__file__))
    version = subprocess.check_output([args.verilator, "--version"], text=True).strip()
    key = hashlib.sha256(json.dumps((inputs, version), sort_keys=True).encode()).hexdigest()[:16]

    lane_log = folder/"hash_lane.log"
    tree_fixture_log=folder/"tree_fixture.log"
    run([sys.executable,"scripts/generate_tree_vectors.py","--check"],tree_fixture_log)
    run([sys.executable, "scripts/check_recipes.py", "--unroll", "1"], lane_log)
    lane_passes = re.findall(r"SINGLE_HASH_LANE_PASS cases=(\d+) UNROLL=1 MASK=([0-9a-f]+)", lane_log.read_text())
    if {mask for _, mask in lane_passes} != {"101e", "0006"}:
        raise RuntimeError(f"Missing lane unit success marker; see {lane_log}")
    turnover_passes = re.findall(r"SINGLE_HASH_TURNOVER_PASS cases=(\d+) UNROLL=1 MASK=([0-9a-f]+)", lane_log.read_text())
    turnover_cases = {mask: int(count) for count, mask in turnover_passes}
    if len(turnover_passes) != 2 or turnover_cases != {"101e": 5, "0006": 3}:
        raise RuntimeError(f"Missing single-Hash turnover protocol coverage; see {lane_log}")

    obj = folder/"processor"/key; obj.mkdir(parents=True, exist_ok=True)
    executable = obj/"micro_unit"
    if not executable.exists():
        run([args.verilator, "--binary", "--timing", "-O2", "-j", "2",
             "-Wno-fatal", "-Wno-WIDTH", "-Wno-UNOPTFLAT", "--top-module", "tb_hash_backend_contracts",
             "--Mdir", str(obj), "-o", "micro_unit", *PROCESSOR_SOURCES], obj/"compile.log")
    processor_log = folder/"processor.log"
    run([str(executable)], processor_log)
    if "MICRO_PROCESSOR_PASS" not in processor_log.read_text():
        raise RuntimeError(f"Missing processor unit success marker; see {processor_log}")
    macro_passes = re.findall(r'MICRO_CHAIN_MACRO_PASS cases=(\d+)([^\n]*)',processor_log.read_text())
    if ABI >= 3 and (len(macro_passes) != 1 or int(macro_passes[0][0]) != 384):
        raise RuntimeError(f"Missing complete ABI 3 CHAIN unit matrix; see {processor_log}")
    macro_cases = int(macro_passes[0][0]) if macro_passes else 0
    tree_passes=re.findall(r'MICRO_TREE_MACRO_PASS cases=(\d+)([^\n]*)',processor_log.read_text())
    if ABI>=4 and (len(tree_passes)!=1 or int(tree_passes[0][0])<1):
        raise RuntimeError(f"Missing ABI 4 TREE unit coverage; see {processor_log}")
    tree_cases=int(tree_passes[0][0]) if tree_passes else 0
    result = dict(passed=True,abi=ABI,macro_cases=macro_cases,tree_cases=tree_cases,
                  source_sha256=inputs, verilator_version=version,
                  lane_cases={mask: int(count) for count, mask in lane_passes},
                  turnover_cases=turnover_cases,
                  processor_binary_sha256=sha(executable),
                  logs={log.name: sha(log) for log in (lane_log, processor_log,tree_fixture_log)})
    (folder/"results.json").write_text(json.dumps(result, indent=2, sort_keys=True)+"\n")
    print("MICRO_UNITS_PASS", sum(result["lane_cases"].values()), "lane cases;",
          sum(turnover_cases.values()), "turnover cases; processor protocol unit;",macro_cases,"CHAIN cases;",
          tree_cases,"TREE cases", folder)


if __name__ == "__main__":
    main()
