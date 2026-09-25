set root [file normalize [file join [file dirname [info script]] ../..]]
cd $root
set tag [lindex $argv 0]
if {![regexp {^[a-zA-Z0-9_.-]+$} $tag]} {error "invalid tag"}
set outdir [file join $root build v4.1 $tag]
set_param general.maxThreads 8
open_checkpoint [file join $outdir post_synth.dcp]
create_clock -name clk -period 10.0 [get_ports clk]
set_property HD.CLK_SRC BUFGCTRL_X0Y0 [get_ports clk]
# OOC internal timing only. rst is synchronized internally; board timing is unspecified.
set_false_path -from [get_ports rst]
set_false_path -to [all_outputs]
# Preserve the ROM boundary while allowing common processor optimization.
# check_rom_boundary.tcl verifies INIT-independent cells/connectivity.
set_property DONT_TOUCH false [get_cells processor]
foreach c [get_cells -hier -filter {REF_NAME == RAM64X1S || REF_NAME == RAM128X1S}] {
    if {![regexp {^(program|template|descriptor)_rom/} $c]} {continue}
    set_property DONT_TOUCH true $c
    set_property DONT_TOUCH true [get_nets -of_objects [get_pins $c/O]]
}
opt_design
# Reuse physical data only; the 32-bit candidate's netlist remains authoritative.
read_checkpoint -incremental -directive RuntimeOptimized [file join $outdir reference_routed.dcp]
report_incremental_reuse -hierarchical -file [file join $outdir incremental_reuse_before.rpt]
if {![file exists [file join $outdir incremental_reuse_before.rpt]]} {
    error "Incremental criteria not met; refuse an unrequested fallback to fresh placement"
}
place_design
report_timing_summary -delay_type min_max -max_paths 10 -file [file join $outdir post_place_timing.rpt]
write_checkpoint -force [file join $outdir post_place.dcp]
route_design
report_incremental_reuse -hierarchical -file [file join $outdir incremental_reuse_after.rpt]
write_checkpoint -force [file join $outdir post_route.dcp]
set original_period [get_property PERIOD [get_clocks clk]]
set original_slack [get_property SLACK [lindex [get_timing_paths -delay_type max -max_paths 1] 0]]
set period [expr {ceil(($original_period-$original_slack+0.1)*10.0)/10.0}]
create_clock -name clk -period $period [get_ports clk]
set slack [get_property SLACK [lindex [get_timing_paths -delay_type max -max_paths 1] 0]]
set hold [get_property SLACK [lindex [get_timing_paths -delay_type min -max_paths 1] 0]]
if {$slack < 0.0999 || $hold < 0} {error "Final timing failed: setup=$slack hold=$hold"}
report_utilization -file [file join $outdir utilization.rpt]
report_utilization -hierarchical -file [file join $outdir utilization_hierarchical.rpt]
report_timing_summary -delay_type min_max -report_unconstrained -max_paths 10 -file [file join $outdir timing_summary.rpt]
report_route_status -file [file join $outdir route_status.rpt]
check_timing -verbose -file [file join $outdir check_timing.rpt]
write_xdc -force [file join $outdir constraints.xdc]
write_checkpoint -force [file join $outdir post_route_final_clock.dcp]
set f [open [file join $outdir final_clock.json] w]
puts $f "{\"route_period_ns\":$original_period,\"route_wns_ns\":$original_slack,\"period_ns\":$period,\"wns_ns\":$slack,\"whs_ns\":$hold,\"setup_margin_ns\":0.1}"
close $f
puts "COMMON_ROUTE_PASS tag=$tag period_ns=$period setup_slack_ns=$slack hold_slack_ns=$hold"
