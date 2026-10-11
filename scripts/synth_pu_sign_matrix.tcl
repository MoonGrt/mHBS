# Each invocation runs in its own output directory; no shared Vivado .Xil state.
if {[llength $argv] != 6} {error "Usage: P U common output threads part"}
lassign $argv p u profile out threads part
foreach value [list $p $u $threads] {
    if {![string is integer -strict $value]} {error "P/U/threads must be integers"}
}
if {$p < 1 || $p > 24 || $u < 1 || $p*$u > 24 || 24%($p*$u) != 0} {error "Invalid P/U"}
if {$threads < 1 || $threads > 2} {error "Use at most two Vivado threads"}
if {$profile ne "common"} {error "Matrix area must use the common core for each P/U"}
set root [file normalize [file join [file dirname [info script]] ..]]
set out [file normalize $out]
file mkdir $out
set_param general.maxThreads $threads
create_project -in_memory -part $part
set handle [open [file join $root sources.txt] r]
set sources [split [string trim [read $handle]] \n]
close $handle
foreach source $sources {read_verilog -sv [file join $root $source]}
read_xdc [file join $root scripts clock.xdc]
set top common
set command [list synth_design -top $top -part $part -mode out_of_context \
    -flatten_hierarchy rebuilt -max_dsp 0 -generic PIPELINE=$p \
    -generic UNROLL=$u]
set handle [open [file join $out settings.txt] w]
puts $handle "top=$top\nprofile=$profile\noperation=runtime\nPIPELINE=$p\nUNROLL=$u\nSYNTHESIS=1\nMHBS_SIGNATURE_STORE=undefined (common has no signature storage)\npart=$part\nvivado=[version -short]\nthreads=$threads\nmode=out_of_context\nkeccak=generic\nclock_period_ns=6.666667\ncommand=$command"
close $handle
{*}$command
report_utilization -file [file join $out utilization.rpt]
report_utilization -hierarchical -file [file join $out hierarchical.rpt]
report_timing_summary -file [file join $out timing.rpt]
write_checkpoint -force [file join $out synthesized.dcp]
source [file join $root scripts audit_debug.tcl]
mhbs_audit_debug [file join $out debug_audit.json]
puts "MHBS_MATRIX_SYNTH_PASS P${p}U${u} profile=$profile top=$top threads=$threads SYNTHESIS=1"
exit
