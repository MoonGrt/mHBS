#!/usr/bin/env python3
"""Source-frozen single-lane common-core synthesis, no routing."""
from pathlib import Path
import sys,json,tarfile,subprocess,concurrent.futures
from experiment_support import snapshot,area,PART
from v42_external_flow import ROOT,sha
OUT=ROOT/'manifests/experiments/single_lane_20261008';BUILD=ROOT/'build/single_lane_20261008'
def freeze(label):
 d=OUT/label;d.mkdir(exist_ok=True);snapshot(d)
 ws=BUILD/(label+'_source');ws.mkdir(exist_ok=True)
 with tarfile.open(d/'source_snapshot.tar.gz') as t:t.extractall(ws,filter='data')
 (d/'changes.patch').write_bytes(subprocess.check_output(['git','diff','--binary'],cwd=ROOT))
 return ws

def synth(label,p,old=False,u=1):
 ws=BUILD/'baseline' if old else BUILD/(label+'_source');out=OUT/label/f'P{p}U{u}';out.mkdir(parents=True,exist_ok=True)
 ns={};exec((ws/'scripts/v42_common_partition.py').read_text(),ns)
 common,_=ns['partition']((ws/'rtl/top/mhbs_top.sv').read_text());(out/'common.sv').write_text(common)
 (out/'clock.xdc').write_text('create_clock -name clk -period 6.666667 [get_ports clk]\n')
 cmd=['set_param general.maxThreads 8',f'create_project -in_memory -part {PART}']
 cmd += [f'read_verilog -sv {{{ws/f}}}' for f in (ws/'manifests/v42_sources.txt').read_text().split() if not f.endswith('mhbs_top.sv')]
 cmd += [f'read_verilog -sv {{{out/"common.sv"}}}',f'read_xdc {{{out/"clock.xdc"}}}',f'synth_design -top mhbs_common -part {PART} -mode out_of_context -flatten_hierarchy rebuilt -max_dsp 0 -generic UNROLL={u} -generic PIPELINE={p} -generic PROFILE_ENABLE=0'+(' -generic LANES=1' if old else ''),f'report_utilization -file {{{out/"core_utilization.rpt"}}}',f'report_utilization -hierarchical -file {{{out/"core_hierarchical.rpt"}}}',
 'set bad {}','foreach c [get_cells -hier -filter {IS_PRIMITIVE == 1}] {if {[string match FD* [get_property REF_NAME $c]] && [regexp {(cycles|hash_count|permutation_count|hash_base|permutation_base)_reg} $c]} {lappend bad $c}}','if {[llength $bad]} {error "statistics remain: $bad"}',f'write_checkpoint -force {{{out/"post_synth.dcp"}}}','puts "SINGLE_LANE_SYNTH_PASS"','exit']
 (out/'synth.tcl').write_text('\n'.join(cmd)+'\n')
 with (out/'vivado.log').open('w') as f:subprocess.run(['vivado','-mode','batch','-nolog','-nojournal','-source',str(out/'synth.tcl')],cwd=ws,stdout=f,stderr=subprocess.STDOUT,check=True)
 assert 'SINGLE_LANE_SYNTH_PASS' in (out/'vivado.log').read_text()
 r=dict(passed=True,area=area(out/'core_utilization.rpt'),statistics_pruned=True,rtl_sha256={f:sha(ws/f) for f in (ws/'manifests/v42_sources.txt').read_text().split()},routed=False,clock_period_ns=6.666667)
 (out/'result.json').write_text(json.dumps(r,indent=2)+'\n');print('SYNTH_PASS',label,f'P{p}U{u}',r['area'],flush=True)
if __name__=='__main__':
 import argparse
 a=argparse.ArgumentParser();a.add_argument('label');a.add_argument('--old',action='store_true');a.add_argument('--u',type=int,default=1);a.add_argument('--p',nargs='+',type=int,default=[1,4]);args=a.parse_args()
 if not args.old:freeze(args.label)
 with concurrent.futures.ThreadPoolExecutor(2) as pool:list(pool.map(lambda p:synth(args.label,p,args.old,args.u),args.p))
