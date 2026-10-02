#!/usr/bin/env python3
"""Matched OOC area comparison; no placement, routing, or clock claims."""
import concurrent.futures,hashlib,json,re,shutil,subprocess,sys,tarfile,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'scripts'))
from v42_common_partition import partition
from v42_external_route import resources
from v42_external_flow import PARAMS
OUT=ROOT/'manifests/experiments/tree_microcode_20261003_v1'
BASE=Path('manifests/experiments/unified_hbs_v4.2/external_job_message')
NAMES=('slh_128f','slh_192f','slh_256f','slh_128s','slh_192s','slh_256s')

def one(variant):
 out=OUT/'area'/variant;out.mkdir(parents=True,exist_ok=True)
 if variant=='baseline':
  ws=ROOT/'build/tree_microcode_area_baseline_20261003_v1'
  ws.mkdir(exist_ok=True)
  with tarfile.open(OUT/'baseline/source_snapshot.tar.gz') as t:t.extractall(ws,filter='data')
 else:ws=ROOT/'build/tree_microcode_20261003_v1'
 common,shell=partition((ws/'rtl/top/mhbs_top.sv').read_text(),stub=True)
 if variant=='candidate':common=common.replace('output wire [3:0] program_address,','output wire [6:0] program_address,')
 (out/'common.sv').write_text(common)
 for name in NAMES:
  cfg=json.loads((ws/BASE/'vectors'/name/'sign/job.json').read_text());s=shell
  for k in PARAMS:
   v=int.from_bytes(bytes.fromhex(cfg[k]),'little')
   s=re.sub(r'(parameter \[255:0\] '+k.upper()+r'=)[^,]+',lambda m:m[1]+f"256'h{v:064x}",s)
  for kind in ('program','template','descriptor'):
   s=re.sub(r'(parameter '+kind.upper()+r'_INIT_FILE=)"[^"]+"',lambda m:m[1]+f'"{BASE}/images/{name}/{kind}.mem"',s)
  (out/(name+'.sv')).write_text(s)
 (out/'clock.xdc').write_text('create_clock -name clk -period 10.0 [get_ports clk]\n')
 tcl='''set_param general.maxThreads 8
set part xc7a200tffg1156-3
set out {%s}
create_project -in_memory -part $part
set f [open manifests/v42_sources.txt];set files [split [string trim [read $f]] \\n];close $f
foreach p $files {if {$p ne "rtl/top/mhbs_top.sv"} {read_verilog -sv $p}}
read_verilog -sv [file join $out common.sv]
read_xdc [file join $out clock.xdc]
synth_design -top mhbs_common -part $part -mode out_of_context -flatten_hierarchy rebuilt -max_dsp 0 -generic LANES=2 -generic UNROLL=2 -generic PROFILE_ENABLE=0
report_utilization -file [file join $out core_utilization.rpt]
report_utilization -hierarchical -file [file join $out core_hierarchical.rpt]
write_edif -force [file join $out mhbs_common.edf]
write_verilog -force -mode synth_stub [file join $out common_stub.v]
close_project
foreach name {slh_128f slh_192f slh_256f slh_128s slh_192s slh_256s} {
 set d [file join $out $name];file mkdir $d
 create_project -in_memory -part $part
 read_verilog -sv rtl/memory/mhbs_signature_store.sv
 read_verilog [file join $out common_stub.v]
 read_verilog -sv [file join $out ${name}.sv]
 read_xdc [file join $out clock.xdc]
 synth_design -top mhbs_top -part $part -mode out_of_context -flatten_hierarchy none
 report_utilization -file [file join $d shell_utilization.rpt]
 report_utilization -hierarchical -file [file join $d shell_hierarchical.rpt]
 write_edif -force [file join $d mhbs_top.edf]
 close_project
 create_project -in_memory -part $part
 read_edif [file join $out mhbs_common.edf]
 read_edif [file join $d mhbs_top.edf]
 link_design -top mhbs_top -part $part -mode out_of_context
 set_property DONT_TOUCH true [get_cells common]
 create_clock -name clk -period 10.0 [get_ports clk]
 report_utilization -file [file join $d utilization.rpt]
 report_utilization -hierarchical -file [file join $d hierarchical.rpt]
 close_project
 puts "TREE_STEP_SYNTH_PROFILE_PASS $name"
}
puts "TREE_STEP_SYNTH_PASS"
exit
'''%out
 # Resume shell measurement from the already synthesized, frozen common core.
 if (out/'common.edf').exists() and not (out/'mhbs_common.edf').exists():
  shutil.copy2(out/'common.edf',out/'mhbs_common.edf')
 if (out/'mhbs_common.edf').exists():
  start_core=tcl.index('create_project -in_memory')
  end_core=tcl.index('foreach name {slh_128f')
  tcl=tcl[:start_core]+tcl[end_core:]
 if (out/'driver.log').exists():shutil.copy2(out/'driver.log',out/f'driver_previous_{time.time_ns()}.log')
 (out/'synth.tcl').write_text(tcl)
 start=time.time()
 with (out/'driver.log').open('w') as log:
  subprocess.run(['vivado','-mode','batch','-nolog','-nojournal','-source',str(out/'synth.tcl')],cwd=ws,stdout=log,stderr=subprocess.STDOUT,check=True)
 result=dict(core=resources(out/'core_utilization.rpt'),profiles={n:resources(out/n/'utilization.rpt') for n in NAMES},seconds=time.time()-start)
 (out/'result.json').write_text(json.dumps(result,indent=2)+'\n');print('SYNTH_PASS',variant,result['core'],flush=True)
 return variant,result
if __name__=='__main__':
 with concurrent.futures.ThreadPoolExecutor(2) as pool:r=dict(pool.map(one,('baseline','candidate')))
 (OUT/'area/result.json').write_text(json.dumps(r,indent=2)+'\n')
