#!/usr/bin/env python3
"""Protocol wrapper units plus existing macro/storage/Hash units."""
import hashlib,json,shutil,subprocess,sys
from pathlib import Path
from v42_external_flow import ROOT,BASE,BUILD,identity,sha,write,run
out=BUILD/'units';out.mkdir(parents=True,exist_ok=True)
files=['rtl/memory/mhbs_signature_store.sv','tb/unit/mhbs_external_core_stub.sv','rtl/top/mhbs_top.sv','tb/unit/tb_mhbs_external_boot.sv']
run(['verilator','--binary','--timing','-j','2','-Wno-fatal','--top-module','tb_mhbs_external_boot','--Mdir',str(out/'boot'),*files],out/'boot_compile.log')
run([str(out/'boot/Vtb_mhbs_external_boot')],out/'boot.log')
assert 'EXTERNAL_BOOT_UNIT_PASS' in (out/'boot.log').read_text()
logic=identity();lid=hashlib.sha256(json.dumps(logic,sort_keys=True).encode()).hexdigest()[:16]
legacy=ROOT/'manifests/experiments/unified_hbs_v4.2/unit'/lid
# Test sources can change without changing the RTL identity. Always run them.
run([sys.executable,'scripts/verify_v42_units.py'],out/'existing_units.log')
old=json.loads((legacy/'results.json').read_text());assert old['passed'] and old['logic_sha256']==logic
for p,h in old['test_source_sha256'].items():assert sha(ROOT/p)==h
for name,h in old['logs'].items():assert sha(legacy/(name+'.log'))==h
archive=ROOT/'manifests/experiments/lu_p1_20261012/unit_wrapper'/lid;archive.mkdir(parents=True,exist_ok=True)
for p in out.glob('*.log'):shutil.copy2(p,archive/p.name)
shutil.copytree(legacy,archive/'macro_hash',dirs_exist_ok=True)
write(archive/'results.json',dict(passed=True,rtl_sha256=logic,boot_sources={p:sha(ROOT/p) for p in files},logs={str(p.relative_to(archive)):sha(p) for p in archive.rglob('*.log')},macro_hash_gate_sha256=sha(legacy/'results.json')))
print('EXTERNAL_UNITS_PASS')
