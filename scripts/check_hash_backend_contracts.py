#!/usr/bin/env python3
"""Run the production U1 Hash lane vectors and the microprocessor protocol unit."""
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
    parser.add_argument("--out", type=Path, default=Path("build/hashflow/units"))
    parser.add_argument("--verilator", default="verilator")
    args = parser.parse_args()
    folder = args.out.resolve(); folder.mkdir(parents=True, exist_ok=True)
    inputs = {name: sha(ROOT/name) for name in sorted(set(PROCESSOR_SOURCES+LANE_SOURCES))}
    inputs["rtl/executor/instructions.svh"] = sha(ROOT/"rtl/executor/instructions.svh")
    inputs["scripts/check_hash_backend_contracts.py"] = sha(Path(__file__))
    version = subprocess.check_output([args.verilator, "--version"], text=True).strip()
    key = hashlib.sha256(json.dumps((inputs, version), sort_keys=True).encode()).hexdigest()[:16]

    lane_log = folder/"hash_lane.log"
    run([sys.executable, "scripts/check_recipes.py", "--unroll", "1"], lane_log)
    lane_passes = re.findall(r"SINGLE_HASH_LANE_PASS cases=(\d+) UNROLL=1 MASK=([0-9a-f]+)", lane_log.read_text())
    if {mask for _, mask in lane_passes} != {"101e", "0006", "fffe"}:
        raise RuntimeError(f"Missing lane unit success marker; see {lane_log}")
    turnover_passes = re.findall(r"SINGLE_HASH_TURNOVER_PASS cases=(\d+) UNROLL=1 MASK=([0-9a-f]+)", lane_log.read_text())
    turnover_cases = {mask: int(count) for count, mask in turnover_passes}
    if len(turnover_passes) != 3 or turnover_cases != {"101e": 5, "0006": 3, "fffe": 11}:
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
    stateful_passes=re.findall(r'MICRO_STATEFUL_CHAIN_PASS cases=(\d+)',processor_log.read_text())
    if stateful_passes!=['256']:raise RuntimeError('Missing stateful CHAIN family/mode/digit matrix')
    boundary_passes=re.findall(r'MICRO_STATEFUL_BOUNDARY_PASS cases=(\d+)',processor_log.read_text())
    if boundary_passes!=['64']:raise RuntimeError('Missing stateful widths, RAM partitions and family permissions')
    ownership_passes=re.findall(r'MICRO_STATEFUL_KEY_OWNERSHIP_PASS lifetimes=(\d+)',processor_log.read_text())
    if len(ownership_passes)!=1 or int(ownership_passes[0])<1440:
        raise RuntimeError('Missing persistent XMSS KEY ownership assertions')
    if any(sha(ROOT/name)!=value for name,value in inputs.items()):
        raise RuntimeError('Unit sources changed during verification')
    result = dict(passed=True,abi=ABI,macro_cases=macro_cases,stateful_macro_cases=256,stateful_boundary_cases=64,
                  stateful_key_lifetimes=int(ownership_passes[0]),source_sha256=inputs, verilator_version=version,
                  lane_cases={mask: int(count) for count, mask in lane_passes},
                  turnover_cases=turnover_cases,
                  processor_binary_sha256=sha(executable),
                  logs={log.name: sha(log) for log in (lane_log, processor_log)})
    (folder/"results.json").write_text(json.dumps(result, indent=2, sort_keys=True)+"\n")
    print("MICRO_UNITS_PASS", sum(result["lane_cases"].values()), "lane cases;",
          sum(turnover_cases.values()), "turnover cases; processor protocol unit;",macro_cases,"CHAIN cases", folder)


if __name__ == "__main__":
    main()
