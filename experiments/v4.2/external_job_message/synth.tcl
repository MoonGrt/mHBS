set root [file normalize [file join [file dirname [info script]] ../../..]]
cd $root
set tag [lindex $argv 0]
if {![regexp {^[a-zA-Z0-9_.-]+$} $tag]} {error "invalid tag"}
set out [file join $root build v4.2 external_job_message $tag synthesis]
file mkdir $out
set started [clock seconds]
set part xc7a200tffg1156-3
set_param general.maxThreads 8
create_project -in_memory -part $part
set f [open manifests/v42_sources.txt];set sources [split [string trim [read $f]] \n];close $f
foreach p $sources {if {$p ne "rtl/top/mhbs_top.sv"} {read_verilog -sv $p}}
set f [open [file join $out clock.xdc] w];puts $f {create_clock -name clk -period 10.0 [get_ports clk]};close $f
read_xdc [file join $out clock.xdc]
read_verilog -sv [file join $out mhbs_common.sv]
synth_design -top mhbs_common -part $part -mode out_of_context -flatten_hierarchy rebuilt -max_dsp 0 -generic PIPELINE=1 -generic UNROLL=2 -generic PROFILE_ENABLE=0
report_utilization -file [file join $out core_utilization.rpt]
report_utilization -hierarchical -file [file join $out core_hierarchical.rpt]
report_timing_summary -file [file join $out core_timing.rpt]
# Audit actual sequential cells, rather than relying on a disabled RTL flag.
set redundant_registers {}
foreach cell [get_cells -hier -filter {IS_PRIMITIVE == 1}] {
 if {[string match FD* [get_property REF_NAME $cell]] &&
     [regexp {(boot_cycles|keygen_cycles|sign_cycles|cycles|hash_count|permutation_count|hash_base|permutation_base|legacy_value|current_value|saved_capture)_reg} $cell]} {
  lappend redundant_registers $cell
 }
}
if {[llength $redundant_registers]} {error "Unpruned registers: $redundant_registers"}
set audit [open [file join $out pruning_audit.json] w]
puts $audit {{"passed": true, "profile_enable": false, "redundant_registers": 0}}
close $audit
write_checkpoint -force [file join $out common.dcp]
write_edif -force [file join $out mhbs_common.edf]
write_verilog -force -mode synth_stub [file join $out common_stub.v]
set core_seconds [expr {[clock seconds]-$started}]
close_project
if {[lindex $argv 1] eq "--core-only"} {
 puts "EXTERNAL_CORE_SYNTH_PASS seconds=$core_seconds"
 exit
}
# Fingerprint internal cell configuration and connections. Boundary nets are
# excluded because their constant drivers belong to the parameterized shell.
proc core_structure {path} {
 set f [open $path w]
 foreach c [lsort [get_cells -hier -filter {NAME =~ common/* && IS_PRIMITIVE == 1}]] {
  puts $f "CELL $c"
  foreach prop {REF_NAME INIT INIT_A INIT_B INIT_C INIT_D SRVAL IS_C_INVERTED IS_D_INVERTED IS_R_INVERTED IS_S_INVERTED IS_CLK_INVERTED IS_WCLK_INVERTED} {
   puts $f "$prop=[get_property -quiet $prop $c]"
  }
 }
 foreach n [lsort [get_nets -hier -filter {NAME =~ common/*}]] {
  set seg [get_nets -segments $n]
  set bp [get_pins -quiet -of_objects $seg -filter {NAME =~ common/* && IS_LEAF == 0}]
  set boundary 0
  foreach p $bp {if {[llength [split $p /]]==2} {set boundary 1}}
  if {$boundary} {continue}
  puts $f "NET $n PINS=[lsort [get_pins -quiet -of_objects $n]]"
 }
 close $f
}
source experiments/v4.2/external_job_message/rom_mapping.tcl
set previous_hash ""
set times [open [file join $out elapsed.tsv] w];puts $times "core\t$core_seconds"
foreach name {slh_128f_keygen slh_128f_sign slh_192f_keygen slh_192f_sign slh_256f_keygen slh_256f_sign slh_128s_keygen slh_128s_sign slh_192s_keygen slh_192s_sign slh_256s_keygen slh_256s_sign} {
 set start [clock seconds]
 set d [file join $out $name];file mkdir $d
 create_project -in_memory -part $part
 read_verilog -sv rtl/memory/mhbs_signature_store.sv
 read_verilog [file join $out common_stub.v]
 read_verilog -sv [file join $out ${name}_shell.sv]
 synth_design -top mhbs_top -part $part -mode out_of_context -flatten_hierarchy none
 write_edif -force [file join $d mhbs_top.edf]
 close_project
 read_edif [file join $out mhbs_common.edf]
 read_edif [file join $d mhbs_top.edf]
 link_design -top mhbs_top -part $part -mode out_of_context
 if {[llength [get_cells -hier -filter {IS_BLACKBOX == 1}]]} {error "unresolved blackbox"}
 set_property DONT_TOUCH true [get_cells common]
 create_clock -name clk -period 10.0 [get_ports clk]
 core_structure [file join $d core_structure.txt]
 set h [lindex [exec sha256sum [file join $d core_structure.txt]] 0]
 if {$previous_hash ne "" && $h ne $previous_hash} {error "common core changed for $name"}
 set previous_hash $h
 export_rom_mapping [file join $d rom_mapping.tsv]
 set profile [join [lrange [split $name _] 0 1] _]
 exec python3 scripts/v42_external_rom.py $d $profile
 source [file join $d init.tcl]
 export_rom_mapping [file join $d initialized_rom.tsv]
 exec python3 scripts/v42_external_rom.py $d $profile --audit
 report_utilization -file [file join $d utilization.rpt]
 report_utilization -hierarchical -file [file join $d hierarchical.rpt]
 report_timing_summary -max_paths 10 -file [file join $d timing.rpt]
 write_checkpoint -force [file join $d post_synth.dcp]
 set f [open [file join $d core_sha256.txt] w];puts $f $h;close $f
 puts $times "$name\t[expr {[clock seconds]-$start}]"
 puts "EXTERNAL_TOP_SYNTH_PASS $name core_sha256=$h"
 close_project
}
close $times
puts "EXTERNAL_COMMON_SYNTH_PASS seconds=[expr {[clock seconds]-$started}]"
