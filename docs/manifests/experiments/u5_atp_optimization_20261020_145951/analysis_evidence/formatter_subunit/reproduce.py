#!/usr/bin/env python3
"""Reproduce extracted local RTL equivalence; this does not compile the full core."""
from pathlib import Path
import hashlib,json,os,subprocess,tempfile
HERE=Path(__file__).resolve().parent
checks=json.loads((HERE/'SHA256.json').read_text())
for name,digest in checks.items():
    assert hashlib.sha256((HERE/name).read_bytes()).hexdigest()==digest, 'changed evidence: '+name
bench=(HERE/'equivalence.sv').read_text()
assert (HERE/'new_fragment.sv.inc').read_text() in bench
assert (HERE/'old_fragment.sv.inc').read_text() in bench
with tempfile.TemporaryDirectory(prefix='mhbs_local_equivalence_') as temp:
    obj=Path(temp)/'obj'
    command=[os.environ.get('VERILATOR','verilator'),'--binary','--timing','--top-module','tb','--Mdir',str(obj),'-Wno-fatal','-j','2',str(HERE/'equivalence.sv')]
    compile_result=subprocess.run(command,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
    if compile_result.returncode:
        print(compile_result.stdout);raise SystemExit(compile_result.returncode)
    result=subprocess.run([str(obj/'Vtb')],text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
    print(result.stdout,end='');result.check_returncode()
    assert 'PASS formatter_directed=2048 formatter_random=100000 stream_valid_checks=49046' in result.stdout
