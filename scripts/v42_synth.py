#!/usr/bin/env python3
"""Run synthesis solely from a sealed snapshot, then collect its artifacts."""
import json,shutil,subprocess,sys,tarfile,time
from pathlib import Path
from v42_flow import ROOT,BUILD,sha,write
folder=BUILD/sys.argv[1];inputs=json.loads((folder/'inputs.json').read_text())
assert sha(folder/'source_snapshot.tar.gz')==inputs['snapshot_sha256']
workspace=folder/'workspace';workspace.mkdir(exist_ok=False)
with tarfile.open(folder/'source_snapshot.tar.gz') as t:t.extractall(workspace,filter='data')
for name,digest in inputs['source_sha256'].items():assert sha(workspace/name)==digest
cmd=['vivado','-mode','batch','-nolog','-nojournal','-source','experiments/v4.2/synth.tcl','-tclargs',sys.argv[1],'2','2']
write(folder/'synth_invocation.json',dict(command=cmd,driver_sha256=sha(Path(__file__)),started=time.time()))
with (folder/'synth.log').open('w') as log:
 subprocess.run(cmd,cwd=workspace,stdout=log,stderr=subprocess.STDOUT,check=True)
for p in (workspace/'build/v4.2'/sys.argv[1]).iterdir():
 if p.is_file():shutil.copy2(p,folder/p.name)
subprocess.run([sys.executable,str(ROOT/'scripts/v42_rom.py'),str(folder)],check=True,cwd=ROOT)
print('V42_SYNTH_PASS',sys.argv[1])
