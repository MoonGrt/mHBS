#!/usr/bin/env python3
"""Record a full algorithm simulation with the exact RTL/image identity."""
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from model.profiles import PROFILES


def logic_hashes(profile):
    paths=(ROOT/'manifests/unified_sources.txt').read_text().splitlines()
    paths += [f'rtl/microcode/mhbs_{profile}_{k}.mem' for k in ('tokens','templates','descriptors')]
    return {p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in sorted(paths)}


def main():
    tag,profile,unroll,lanes,binary=sys.argv[1:]
    before=logic_hashes(profile)
    proc=subprocess.run([str(ROOT/binary)],cwd=ROOT,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
    print(proc.stdout,end='')
    out=ROOT/'build/sim';out.mkdir(parents=True,exist_ok=True)
    log=out/(tag+'.log');log.write_text(proc.stdout)
    match=re.search(r'UNIFIED_PASS profile=(\d+) keygen_cycles=(\d+) sign_cycles=(\d+)',proc.stdout)
    passed=proc.returncode==0 and match is not None and int(match[1])==list(PROFILES).index(profile) and before==logic_hashes(profile)
    data=dict(q=int(re.search(r"backpressure=\d+ q=(\d+)",proc.stdout)[1]) if " q=" in proc.stdout else 5,profile=profile,unroll=int(unroll),lanes=int(lanes),passed=passed,
              logic_sha256=before,log_sha256=hashlib.sha256(log.read_bytes()).hexdigest(),
              keygen_cycles=int(match[2]) if match else None,sign_cycles=int(match[3]) if match else None,
              tool=subprocess.check_output(['verilator','--version'],text=True).strip())
    (out/(tag+'.json')).write_text(json.dumps(data,indent=2)+'\n')
    if not passed:raise SystemExit(1)


if __name__=='__main__':main()
