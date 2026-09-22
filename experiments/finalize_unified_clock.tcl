# Recheck the retained routed netlist at a clock rounded to 0.1 ns, with
# >= 0.1 ns setup margin. This changes timing constraints, not the routing.
set root [file normalize [file join [file dirname [info script]] ..]]
set tag [lindex $argv 0]
if {![regexp {^[A-Za-z0-9_.-]+$} $tag]} {error "invalid route tag"}
set outdir [file join $root build vivado $tag]
set_param general.maxThreads 16
open_checkpoint [file join $outdir post_route.dcp]
set original_period [get_property PERIOD [get_clocks clk]]
set original_slack [get_property SLACK [lindex [get_timing_paths -delay_type max -max_paths 1] 0]]
set period [expr {ceil(($original_period-$original_slack+0.1)*10.0)/10.0}]
create_clock -name clk -period $period [get_ports clk]
set slack [get_property SLACK [lindex [get_timing_paths -delay_type max -max_paths 1] 0]]
set hold [get_property SLACK [lindex [get_timing_paths -delay_type min -max_paths 1] 0]]
if {$slack < 0 || $hold < 0} {error "final clock fails timing: setup=$slack hold=$hold"}
file copy -force [file join $outdir timing_summary.rpt] [file join $outdir timing_at_route_clock.rpt]
report_timing_summary -delay_type min_max -report_unconstrained -max_paths 10 -file [file join $outdir timing_summary.rpt]
check_timing -verbose -file [file join $outdir check_timing.rpt]
write_xdc -force [file join $outdir constraints.xdc]
write_checkpoint -force [file join $outdir post_route_final_clock.dcp]
set meta [open [file join $outdir final_clock.json] w]
set script_sha [lindex [exec sha256sum [info script]] 0]
puts $meta "{\"route_period_ns\":$original_period,\"route_wns_ns\":$original_slack,\"period_ns\":$period,\"wns_ns\":$slack,\"whs_ns\":$hold,\"setup_margin_ns\":0.1,\"script_sha256\":\"$script_sha\"}"
close $meta
puts "FINAL_CLOCK_PASS period_ns=$period setup_slack_ns=$slack hold_slack_ns=$hold"
