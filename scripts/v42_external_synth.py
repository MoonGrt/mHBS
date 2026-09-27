#!/usr/bin/env python3
"""Synthesize one generic body and six parameter shells from a sealed snapshot."""
import json,re,shutil,subprocess,sys,tarfile,time
from pathlib import Path
from v42_external_flow import ROOT,BASE,BUILD,NAMES,PARAMS,capture,sha,write,tool_version
from v42_common_partition import partition
vivado_version=tool_version('vivado','-version')
f=capture(sys.argv[1]);inp=json.loads((f/'inputs.json').read_text())
workspace=f/'synth_source';workspace.mkdir(exist_ok=False)
with tarfile.open(f/'source_snapshot.tar.gz') as t:t.extractall(workspace,filter='data')
for p,h in inp['source_sha256'].items():assert sha(workspace/p)==h
out=workspace/'build/v4.2/external_job_message'/f.name/'synthesis';out.mkdir(parents=True)
src=(workspace/'rtl/top/mhbs_top.sv').read_text()
common,base_shell=partition(src,stub=True)
(out/'mhbs_common.sv').write_text(common)
for n in NAMES:
 for op in ('keygen','sign'):
  cfg=json.loads((workspace/BASE.relative_to(ROOT)/'vectors'/n/op/'job.json').read_text())
  shell=base_shell
  for k in PARAMS:
   shell=re.sub(r'(parameter \[255:0\] '+k.upper()+r'=)[^,]+',lambda m:m[1]+f"256'h{int.from_bytes(bytes.fromhex(cfg[k]),'little'):064x}",shell)
  shell=re.sub(r'(parameter bit OPERATION=)[^,]+',lambda m:m[1]+f"1'b{cfg['operation']}",shell)
  for kind in ('program','template','descriptor'):
   shell=re.sub(r'(parameter '+kind.upper()+r'_INIT_FILE=)"[^"]+"',lambda m:m[1]+f'"experiments/v4.2/external_job_message/{kind}_construction.mem"',shell)
  (out/(n+'_'+op+'_shell.sv')).write_text(shell)
cmd=['vivado','-mode','batch','-nolog','-nojournal','-source','experiments/v4.2/external_job_message/synth.tcl','-tclargs',f.name]
start=time.time();write(f/'synth_invocation.json',dict(command=cmd,started=start,driver_sha256=sha(Path(__file__)),profile_enable=False,statistics_ports='constant_zero',tool_versions={'vivado':vivado_version}))
with (f/'synth.log').open('w') as log:subprocess.run(cmd,cwd=workspace,stdout=log,stderr=subprocess.STDOUT,check=True)
shutil.copytree(out,f/'synthesis')
write(f/'synth_elapsed.json',dict(seconds=time.time()-start))
print('EXTERNAL_SYNTH_PASS',f.name)
