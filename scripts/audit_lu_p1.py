#!/usr/bin/env python3
"""Read measured checkpoints and verify disabled profiling and lane count."""
import sys,concurrent.futures,re
import run_lu_p1 as m
label=sys.argv[1] if len(sys.argv)>1 else 'structure'
def one(point):
 l,u=point;d=m.OUT/label/f'L{l}U{u}';checkpoint=m.BUILD/label/f'synth_L{l}U{u}'/'synth.dcp'
 if not checkpoint.exists():return dict(point=point,passed=False,reason='no completed checkpoint')
 tcl=d/'audit.tcl';tcl.write_text('set_param general.maxThreads 4\nopen_checkpoint {'+str(checkpoint)+'}\n'+r'''
set stats [get_cells -hier -quiet -regexp {.*(boot_cycles_reg|keygen_cycles_reg|sign_cycles_reg|hash_count_reg|permutation_count_reg|hash_base_reg|permutation_base_reg|cycles_reg).*}]
puts "PROFILE_REGISTERS [llength $stats]"
if {[llength $stats]} { puts $stats; error "profiling registers remain" }
set lanes [get_cells -hier -quiet -filter {REF_NAME =~ mhbs_recipe_lane*}]
puts "LANE_INSTANCES [llength $lanes]"
set rounds [get_cells -hier -quiet -filter {REF_NAME =~ mhbs_keccak*}]
puts "ROUND_INSTANCES [llength $rounds]"
exit
''')
 with m.synth_slot():m.run(['vivado','-mode','batch','-nolog','-nojournal','-source',tcl],d/'audit.log',checkpoint.parent)
 text=(d/'audit.log').read_text();lanes=int(re.search(r'LANE_INSTANCES (\d+)',text)[1]);rounds=int(re.search(r'ROUND_INSTANCES (\d+)',text)[1])
 assert lanes==l,(l,u,lanes)
 return dict(point=point,passed=True,lanes=lanes,round_hierarchies_retained=rounds,rtl_round_instances=l*u,profiling_registers=0)
if __name__=='__main__':
 with concurrent.futures.ThreadPoolExecutor(6) as pool:rows=list(pool.map(one,m.POINTS))
 m.write(m.OUT/label/'netlist_audit.json',dict(passed=all(x['passed'] for x in rows),rows=rows))
 print('NETLIST_AUDIT',label,all(x['passed'] for x in rows))
