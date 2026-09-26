#!/usr/bin/env python3
"""Protocol wrapper units plus existing macro/storage/Hash units."""
import hashlib,json,shutil,subprocess
from pathlib import Path
from v42_external_flow import ROOT,BASE,BUILD,identity,sha,write,run
out=BUILD/'units';out.mkdir(exist_ok=True)
files=['tb/unit/uhbs_external_core_stub.sv','rtl/top/uhbs_top.sv','tb/unit/tb_uhbs_external_boot.sv']
run(['iverilog','-g2012','-s','tb_uhbs_external_boot','-o',str(out/'boot.vvp'),*files],out/'boot_compile.log')
run(['vvp',str(out/'boot.vvp')],out/'boot.log')
assert 'EXTERNAL_BOOT_UNIT_PASS' in (out/'boot.log').read_text()
logic=identity();lid=hashlib.sha256(json.dumps(logic,sort_keys=True).encode()).hexdigest()[:16]
legacy=ROOT/'manifests/experiments/unified_hbs_v4.2/unit'/lid
if not (legacy/'results.json').exists():run(['python3','scripts/verify_v42_units.py'],out/'existing_units.log')
old=json.loads((legacy/'results.json').read_text());assert old['passed'] and old['logic_sha256']==logic
for p,h in old['test_source_sha256'].items():assert sha(ROOT/p)==h
for name,h in old['logs'].items():assert sha(legacy/(name+'.log'))==h
archive=BASE/'unit';archive.mkdir(exist_ok=True)
for p in out.glob('*.log'):shutil.copy2(p,archive/p.name)
shutil.copytree(legacy,archive/'macro_hash',dirs_exist_ok=True)
write(archive/'results.json',dict(passed=True,rtl_sha256=logic,boot_sources={p:sha(ROOT/p) for p in files},logs={str(p.relative_to(archive)):sha(p) for p in archive.rglob('*.log')},macro_hash_gate_sha256=sha(legacy/'results.json')))
print('EXTERNAL_UNITS_PASS')
