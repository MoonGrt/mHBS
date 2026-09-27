set root [file normalize [file join [file dirname [info script]] ..]]
set family [lindex $argv 0]
if {$family ni {slh_128f slh_192f slh_256f xmss_omega2 xmss_omega4 lms_omega2 lms_omega4}} {error "unknown profile"}
set tag [lindex $argv 1]
if {$tag eq ""} {set tag "unified_${family}_v4"}
if {![regexp {^[A-Za-z0-9_.-]+$} $tag]} {error "invalid output tag"}
set part "xc7a200tffg1156-3"
set unroll 2
set lanes 2
if {$argc > 2} {set unroll [lindex $argv 2]}
if {$argc > 3} {set lanes [lindex $argv 3]}
set outdir [file join $root build vivado $tag]
file mkdir $outdir
set_param general.maxThreads 16
exec python3 [file join $root scripts collect_unified_ppa.py] $tag $family --capture --unroll $unroll --lanes $lanes
set source_manifest [open [file join $root manifests unified_sources.txt] r]
set source_list [split [string trim [read $source_manifest]] "\n"]
close $source_manifest
foreach source $source_list {read_verilog -sv [file join $root $source]}

set top "mhbs_${family}_top"
synth_design -top $top -part $part -mode out_of_context -flatten_hierarchy rebuilt \
    -directive AreaOptimized_high -max_dsp 0 -generic UNROLL=$unroll -generic LANES=$lanes -generic PROFILE_ENABLE=0
set abort_registers [get_cells -hierarchical -filter {NAME =~ *abort_execution_reg}]
if {[llength $abort_registers] != 1 || ![regexp {^FD} [get_property REF_NAME $abort_registers]]} {
    error "execution abort must remain a dedicated register"
}
puts "REGISTERED_ABORT_PASS [get_property REF_NAME $abort_registers]"
create_clock -name clk -period 10.000 [get_ports clk]
report_utilization -file [file join $outdir utilization.rpt]
report_utilization -hierarchical -file [file join $outdir utilization_hierarchical.rpt]
report_timing_summary -delay_type max -max_paths 10 -file [file join $outdir timing_summary.rpt]
write_checkpoint -force [file join $outdir post_synth.dcp]
