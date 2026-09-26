#!/usr/bin/env python3
"""Audit all inferred ROM logical pins again after place/route."""
import argparse,json,subprocess
from pathlib import Path
from v42_flow import ROOT,BUILD,sha,write
p=argparse.ArgumentParser();p.add_argument('tag');p.add_argument('--existing',action='store_true');a=p.parse_args()
f=BUILD/a.tag
script=ROOT/'experiments/v4.2/audit_routed_rom.tcl'
if not a.existing:
 with (f/'routed_rom_audit.log').open('w') as log:
  subprocess.run(['vivado','-mode','batch','-nolog','-nojournal','-source',str(script),'-tclargs',a.tag],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,check=True)
assert (f/'rom_mapping.tsv').read_bytes()==(f/'routed_rom_mapping.tsv').read_bytes(),'ROM mapping changed during routing'
write(f/'routed_rom_audit.json',dict(passed=True,cells=len((f/'rom_mapping.tsv').read_text().splitlines()),
 source_sha256=sha(f/'rom_mapping.tsv'),routed_sha256=sha(f/'routed_rom_mapping.tsv'),script_sha256=sha(script),driver_sha256=sha(Path(__file__))))
print('V42_ROUTED_ROM_MAP_PASS')
