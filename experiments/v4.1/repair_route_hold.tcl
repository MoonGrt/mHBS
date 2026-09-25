set root [file normalize [file join [file dirname [info script]] ../..]]
cd $root
set tag [lindex $argv 0]
if {![regexp {^[a-zA-Z0-9_.-]+$} $tag]} {error "invalid tag"}
set outdir [file join $root build v4.1 $tag]
set_param general.maxThreads 8
set started [clock seconds]
set hold_option -hold_fix
if {$argc>1} {
    if {[lindex $argv 1] ne "aggressive"} {error "expected aggressive hold mode"}
    set hold_option -aggressive_hold_fix
}
open_checkpoint [file join $outdir input_routed.dcp]
# Relax setup to the measured path before repairing hold; final period is
# recalculated after physical repair and routing, with the same 0.1 ns margin.
set old_period [get_property PERIOD [get_clocks clk]]
set old_slack [get_property SLACK [lindex [get_timing_paths -delay_type max -max_paths 1] 0]]
set repair_period [expr {ceil(($old_period-$old_slack+0.2)*10.0)/10.0}]
create_clock -name clk -period $repair_period [get_ports clk]
phys_opt_design $hold_option
route_design -preserve -directive Default
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
set f [open [file join $outdir route_seconds.txt] w];puts $f [expr {[clock seconds]-$started}];close $f
puts "COMMON_ROUTE_PASS tag=$tag period_ns=$period setup_slack_ns=$slack hold_slack_ns=$hold"
