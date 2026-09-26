#!/usr/bin/env python3
"""Route a captured common body, preserving its source and invocation evidence."""
import json,shutil,subprocess,sys,time
from v42_flow import ROOT,BUILD,sha,write
src=BUILD/sys.argv[1];out=BUILD/(sys.argv[1]+'_route');out.mkdir(exist_ok=False)
for name in ('inputs.json','source_snapshot.tar.gz','post_synth.dcp','rom_mapping.tsv','synth_seconds.txt'):
 shutil.copy2(src/name,out/name)
for name in ('route','freeze'):
 shutil.copy2(ROOT/f'experiments/v4.2/{name}.tcl',out/(name+'_flow.tcl'))
write(out/'route_invocation.json',dict(source_tag=src.name,script_sha256=sha(out/'route_flow.tcl'),started=time.time()))
# The archived script uses the project-relative root; execute the bound source script.
with (out/'route.log').open('w') as log:
 subprocess.run(['vivado','-mode','batch','-nolog','-nojournal','-source','experiments/v4.2/route.tcl','-tclargs',out.name],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,check=True)
assert sha(ROOT/'experiments/v4.2/route.tcl')==sha(out/'route_flow.tcl')
print('V42_ROUTE_PASS',out.name)
