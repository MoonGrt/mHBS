set hash_backend shake
if {[info exists ::env(HASH_BACKEND)]} {set hash_backend $::env(HASH_BACKEND)}
if {$hash_backend ni {shake sha2}} {error "HASH_BACKEND must be shake or sha2"}
set package_root [file normalize [file join [file dirname [info script]] ..]]
cd $package_root
set p 1
set u 1
if {[llength $argv] > 0} {set p [lindex $argv 0]}
if {[llength $argv] > 1} {set u [lindex $argv 1]}
if {![string is integer -strict $p] || ![string is integer -strict $u]} {error "P/U must be integers"}
if {$p != 1 || $u != 1} {error "image-chain requires K1U1"}
set part xc7a200tffg1156-3
set lut6 0
if {[info exists ::env(KECCAK_LUT6)]} {set lut6 $::env(KECCAK_LUT6)}
if {$lut6 ni {0 1}} {error "KECCAK_LUT6 must be 0 or 1"}
set out [file join $package_root build synth P${p}U${u}]
if {!$lut6} {append out _generic}
if {$hash_backend eq "sha2"} {append out _sha2}
file mkdir $out
set archive [exec python3 [file join $package_root scripts experiment_archive.py] --begin-synthesis $out]
set source_root [file join $archive source]
set_param general.maxThreads 2
create_project -in_memory -part $part
set defines [list SYNTHESIS]
if {$lut6} {lappend defines MHBS_XILINX_LUT6}
if {$hash_backend eq "sha2"} {lappend defines MHBS_SHA2}
set_property verilog_define $defines [current_fileset]
set_property include_dirs [list $source_root] [current_fileset]
cd $source_root
set handle [open [file join $source_root sources.txt] r]
set sources [split [string trim [read $handle]] \n]
close $handle
foreach source $sources {read_verilog -sv [file join $source_root $source]}
read_xdc [file join $source_root scripts clock.xdc]
synth_design -top common -part $part -mode out_of_context \
    -flatten_hierarchy rebuilt -max_dsp 0 \
    -generic PIPELINE=$p -generic UNROLL=$u
report_utilization -file [file join $out core_utilization.rpt]
report_utilization -hierarchical -file [file join $out core_hierarchical.rpt]
report_timing_summary -file [file join $out core_timing.rpt]
source [file join $source_root scripts audit_debug.tcl]
mhbs_audit_debug [file join $out debug_audit.json]
puts "MHBS_SYNTH_PASS P${p}U${u} SYNTHESIS=1"
exec python3 [file join $package_root scripts experiment_archive.py] --finish-synthesis $archive --results $out
exit
