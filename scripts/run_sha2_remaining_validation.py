#!/usr/bin/env python3
"""Measure SHA2 P1 Remaining and validate isolated frozen-RTL Sign candidates.

All outputs stay under --work. This runner never invokes synthesis or routing,
never generates h20 vectors, and checks full output, signature cache and counts
through the existing fast testbench. The matched 33-byte SLOTH KAT is measured
separately from the repository's default target vectors.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
from pathlib import Path
import re
import subprocess
import time


ROOT = Path(__file__).resolve().parents[1]
CONFIGURATIONS = {"P1U1": (1, 1), "P4U1": (4, 1), "P4U2": (4, 2), "P12U1": (12, 1)}
PROFILES = ("slh_128f", "xmss_h10", "lms_h10")


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n")


def replace_once(text, before, after):
    if text.count(before) != 1:
        raise ValueError("Profiling anchor is not unique: " + repr(before))
    return text.replace(before, after, 1)


def profile_sources(source, work):
    """Add instrumentation to private testbench copies, never production RTL."""
    folder = work / "instrumentation"
    folder.mkdir(parents=True, exist_ok=True)
    tb = (source / "tb/tb_fast.sv").read_text()
    tb = replace_once(tb, "output wire [31:0] configuration_pipeline,configuration_unroll\n",
                      "output wire [31:0] configuration_pipeline,configuration_unroll,\n"
                      " output wire profile_hash,profile_round,profile_feedforward,\n"
                      " output wire [7:0] profile_format_state,profile_core_state\n")
    tb = replace_once(tb, " assign execution_reset=dut.core.execution_rst;",
                      " assign execution_reset=dut.core.execution_rst;\n"
                      " assign profile_round=!dut.core.lane.compression.stalled && dut.core.lane.compression.stages[0].source_valid;\n"
                      " assign profile_feedforward=!dut.core.lane.compression.stalled && dut.core.lane.compression.finished;\n"
                      " assign profile_hash=profile_round || profile_feedforward;\n"
                      " assign profile_format_state=8'(dut.core.lane.formatter);\n"
                      " assign profile_core_state=8'(dut.core.state);")
    cpp = (source / "tb/fast_main.cpp").read_text()
    cpp = replace_once(cpp, "#include <chrono>", "#include <chrono>\n#include <map>\n#include <utility>")
    cpp = replace_once(cpp, "    unsigned sent=0,accepted=0;",
                       "    uint64_t prof_hash=0,prof_other=0,prof_round=0,prof_ff=0;\n"
                       "    std::map<std::pair<unsigned,unsigned>,uint64_t> remaining_states;\n"
                       "    unsigned sent=0,accepted=0;")
    cpp = replace_once(cpp,
                       "if(dut.execution_reset){hashes=0;perms=0;observed_cycles=0;}",
                       "if(dut.execution_reset){hashes=0;perms=0;observed_cycles=0;prof_hash=0;prof_other=0;prof_round=0;prof_ff=0;remaining_states.clear();}")
    cpp = replace_once(cpp,
                       "else {observed_cycles+=dut.execution_active;hashes+=dut.hash_event+dut.batch_event;perms+=dut.permutation_event+dut.batch_event;}",
                       "else {observed_cycles+=dut.execution_active;hashes+=dut.hash_event+dut.batch_event;perms+=dut.permutation_event+dut.batch_event;\n"
                       "                if(dut.execution_active){prof_hash+=dut.profile_hash;prof_other+=!dut.profile_hash;prof_round+=dut.profile_round;prof_ff+=dut.profile_feedforward;\n"
                       "                    if(!dut.profile_hash)remaining_states[{dut.profile_format_state,dut.profile_core_state}]++;}}")
    cpp = replace_once(cpp, "    dut.final();return 0;",
                       "    if(prof_hash+prof_other!=cycles || observed_cycles!=cycles || prof_round+prof_ff!=prof_hash)\n"
                       "        throw std::runtime_error(\"Cycle partition differs from production counter\");\n"
                       '    std::cout<<"CLOCK_BREAKDOWN total="<<cycles<<" hash="<<prof_hash<<" transfer=0 remaining="<<prof_other\n'
                       '             <<" rounds="<<prof_round<<" feedforward="<<prof_ff<<std::endl;\n'
                       "    for(const auto &entry:remaining_states)\n"
                       '        std::cout<<"REMAINING_STATE format="<<entry.first.first<<" core="<<entry.first.second<<" cycles="<<entry.second<<std::endl;\n'
                       "    dut.final();return 0;")
    tb_path, cpp_path = folder / "tb_remaining.sv", folder / "remaining_main.cpp"
    tb_path.write_text(tb)
    cpp_path.write_text(cpp)
    return tb_path, cpp_path


def source_manifest(source, relative_paths):
    return {name: hashlib.sha256((source / name).read_bytes()).hexdigest() for name in relative_paths}


def run_logged(command, log, cwd):
    with log.open("w") as stream:
        result = subprocess.run(command, cwd=cwd, stdout=stream, stderr=subprocess.STDOUT)
    if result.returncode:
        raise RuntimeError(f"Command returned {result.returncode}; see {log}")


def parse_result(log):
    text = log.read_text()
    match = re.search(r"STATEFUL_PASS P(\d+)U(\d+) op=(\d+) cycles=(\d+) total=(\d+) hashes=(\d+) permutations=(\d+).*?logical_permutations=(\d+)", text)
    if not match:
        raise RuntimeError("Missing STATEFUL_PASS; see " + str(log))
    result = dict(zip(("pipeline", "unroll", "operation", "cycles", "total_ticks", "hashes", "compressions", "logical_compressions"), map(int, match.groups())))
    match = re.search(r"CLOCK_BREAKDOWN total=(\d+) hash=(\d+) transfer=(\d+) remaining=(\d+) rounds=(\d+) feedforward=(\d+)", text)
    if match:
        result["cycle_breakdown"] = dict(zip(("total", "hash", "transfer", "remaining", "rounds", "feedforward"), map(int, match.groups())))
        states = [{"formatter": int(a), "executor": int(b), "cycles": int(c)}
                  for a, b, c in re.findall(r"REMAINING_STATE format=(\d+) core=(\d+) cycles=(\d+)", text)]
        assert sum(row["cycles"] for row in states) == result["cycle_breakdown"]["remaining"]
        result["remaining_joint_states"] = states
        result["remaining_formatter_totals"] = {str(state): sum(row["cycles"] for row in states if row["formatter"] == state)
                                                 for state in sorted({row["formatter"] for row in states})}
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True, help="Frozen tree containing sources.txt, rtl/ and tb/.")
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--vectors", type=Path, default=ROOT / "tb/vectors/sha2")
    parser.add_argument("--kat", type=Path, default=ROOT / "tmp/sloth_cycle_comparison/kat_inputs/sha2/slh_128f/sign")
    parser.add_argument("--config", action="append", choices=CONFIGURATIONS, help="Repeat to restrict focus configurations.")
    parser.add_argument("--profile", action="append", choices=PROFILES, help="Repeat to restrict focus algorithms.")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--profile-only", action="store_true", help="Only run matched 33-byte P1U1 KAT and cycle partition.")
    group.add_argument("--focus-only", action="store_true", help="Only run target Sign vectors without extra profiling binary.")
    parser.add_argument("--workers", type=int, default=4, choices=range(1, 9))
    parser.add_argument("--plan", action="store_true", help="Write the plan without compilation or simulation.")
    args = parser.parse_args()
    source, work = args.source.resolve(), args.work.resolve()
    work.mkdir(parents=True, exist_ok=True)
    relative_sources = [name.strip() for name in (source / "sources.txt").read_text().splitlines() if name.strip()]
    relative_all = relative_sources + ["sources.txt", "tb/tb_fast.sv", "tb/fast_main.cpp"]
    manifest = source_manifest(source, relative_all)
    manifest_path = work / "SOURCE.json"
    if manifest_path.exists() and json.loads(manifest_path.read_text())["sha256"] != manifest:
        raise ValueError("--work already belongs to a different frozen source; choose a fresh directory")
    write_json(manifest_path, {"source": str(source), "sha256": manifest})
    configurations = args.config or list(CONFIGURATIONS)
    profiles = args.profile or list(PROFILES)
    tasks = []
    if not args.focus_only:
        tasks.append({"name": "matched33_kat/P1U1/slh_128f", "configuration": "P1U1", "profile": "slh_128f", "profiled": True, "vectors": str(args.kat.resolve())})
    if not args.profile_only:
        tasks.extend({"name": f"focus/{config}/{profile}", "configuration": config, "profile": profile, "profiled": False,
                      "vectors": str((args.vectors / profile / "sign").resolve())} for config in configurations for profile in profiles)
    for task in tasks:
        vector = Path(task["vectors"])
        if not (vector / "expected.mem").is_file():
            raise ValueError("Missing vector: " + task["vectors"])
        task["vector_sha256"] = {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                                 for path in sorted(vector.glob("*.mem"))}
        task["message_bytes"] = int((vector / "job.mem").read_text().split()[8], 16)
    write_json(work / "PLAN.json", {"tasks": tasks, "workers": args.workers, "compile_threads": 2, "synthesis": False, "routing": False, "h20": False})
    if args.plan:
        print(json.dumps({"plan": str(work / "PLAN.json"), "tasks": len(tasks)}))
        return

    def check_source():
        if source_manifest(source, relative_all) != manifest:
            raise RuntimeError("Frozen source changed while validation was running")

    binaries = {}
    build_specs = [(config, False) for config in configurations] if not args.profile_only else []
    if not args.focus_only:
        build_specs.insert(0, ("P1U1", True))
    instrumentation = profile_sources(source, work) if not args.focus_only else None

    def compile_binary(spec):
        config, profiled = spec
        check_source()
        p, u = CONFIGURATIONS[config]
        folder = work / "compile" / (config + ("_profile" if profiled else ""))
        folder.mkdir(parents=True, exist_ok=True)
        tb, cpp = instrumentation if profiled else (source / "tb/tb_fast.sv", source / "tb/fast_main.cpp")
        command = ["verilator", "--cc", "--exe", "--build", "-O3", "-j", "2", "-Wno-fatal", "--top-module", "tb_fast",
                   f"-GPIPELINE={p}", f"-GUNROLL={u}", "-DMHBS_SHA2", "--Mdir", str(folder / "obj"),
                   "-MAKEFLAGS", "OPT_FAST=-O3 OPT_SLOW=-O1", "-CFLAGS", "-O3 -march=native"]
        command += [str(source / name) for name in relative_sources] + [str(tb), str(cpp)]
        write_json(folder / "COMMAND.json", command)
        run_logged(command, folder / "compile.log", source)
        check_source()
        return spec, folder / "obj/Vtb_fast"

    with ThreadPoolExecutor(max_workers=min(args.workers, len(build_specs))) as pool:
        for spec, binary in pool.map(compile_binary, build_specs):
            binaries[spec] = binary

    def simulate(task):
        check_source()
        vector = Path(task["vectors"])
        if any(hashlib.sha256((vector / name).read_bytes()).hexdigest() != expected
               for name, expected in task["vector_sha256"].items()):
            raise RuntimeError("Validation vector changed after planning")
        started = time.monotonic()
        folder = work / task["name"]
        folder.mkdir(parents=True, exist_ok=True)
        result = {**task, "passed": False, "full_output_and_signature_cache_checked": False}
        binary = binaries[task["configuration"], task["profiled"]]
        command = [str(binary), "+VECTOR=" + task["vectors"], "+OUTPUT_BIN=" + str(folder / "signature.bin"), "+CACHE_BIN=" + str(folder / "cache.bin")]
        write_json(folder / "COMMAND.json", command)
        try:
            run_logged(command, folder / "run.log", source)
            result.update(parse_result(folder / "run.log"))
            if (folder / "signature.bin").read_bytes() != (folder / "cache.bin").read_bytes():
                raise RuntimeError("Output/cache binary mismatch")
            result.update(passed=True, full_output_and_signature_cache_checked=True,
                          signature_sha256=hashlib.sha256((folder / "signature.bin").read_bytes()).hexdigest())
            check_source()
            if any(hashlib.sha256((vector / name).read_bytes()).hexdigest() != expected
                   for name, expected in task["vector_sha256"].items()):
                raise RuntimeError("Validation vector changed during simulation")
        except Exception as error:
            result["passed"] = False
            result["error"] = str(error)
        result["elapsed_seconds"] = time.monotonic() - started
        write_json(folder / "RESULT.json", result)
        print(json.dumps(result), flush=True)
        return result

    results = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(simulate, task) for task in tasks]
        for future in as_completed(futures):
            results.append(future.result())
            write_json(work / "PROGRESS.json", {"complete": False, "completed": len(results), "required": len(tasks), "results": results})
    check_source()
    summary = {"complete": True, "passed": all(result["passed"] for result in results), "source": str(source), "source_sha256": manifest,
               "completed": len(results), "required": len(tasks), "results": sorted(results, key=lambda result: result["name"])}
    write_json(work / "RESULTS.json", summary)
    write_json(work / "PROGRESS.json", summary)
    print("SHA2_REMAINING_VALIDATION_COMPLETE " + json.dumps({key: summary[key] for key in ("complete", "passed", "completed", "required")}), flush=True)
    if not summary["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
