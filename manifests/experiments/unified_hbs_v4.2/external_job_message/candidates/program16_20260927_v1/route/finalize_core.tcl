# Resume saved routing; preserve the expensive global route while fixing hold.
set source_dcp [file normalize [lindex $argv 0]]
set out [file normalize [lindex $argv 1]]
file mkdir $out
set_param general.maxThreads 8
set started [clock seconds]
open_checkpoint $source_dcp
report_timing_summary -delay_type min_max -file [file join $out io_zero_delay_timing.rpt]
report_timing -delay_type min -max_paths 10 -file [file join $out hold_before.rpt]
set io_inputs [get_ports -filter {DIRECTION == IN && NAME != clk}]
set io_hold [get_property SLACK [lindex [get_timing_paths -from $io_inputs -delay_type min -max_paths 1] 0]]
# Core Fmax benchmark, as in the previous project measurements. External
# interfaces require system-level launch/capture constraints and are not signed off.
set_false_path -from $io_inputs
set_false_path -to [all_outputs]
set hold_path [get_timing_paths -delay_type min -max_paths 1]
if {[get_property SLACK $hold_path] < 0} {
    phys_opt_design -aggressive_hold_fix
    route_design -preserve -directive Default
}
write_checkpoint -force [file join $out post_route.dcp]
set route_period [get_property PERIOD [get_clocks clk]]
set route_wns [get_property SLACK [lindex [get_timing_paths -delay_type max -max_paths 1] 0]]
# Reanalyse the retained routed netlist at a 0.1 ns grid with >=0.1 ns margin.
set period [expr {ceil(($route_period-$route_wns+0.1)*10.0)/10.0}]
create_clock -name clk -period $period [get_ports clk]
set wns [get_property SLACK [lindex [get_timing_paths -delay_type max -max_paths 1] 0]]
set whs [get_property SLACK [lindex [get_timing_paths -delay_type min -max_paths 1] 0]]
report_utilization -file [file join $out utilization.rpt]
report_utilization -hierarchical -file [file join $out hierarchical.rpt]
report_timing_summary -delay_type min_max -report_unconstrained -max_paths 10 -file [file join $out timing_summary.rpt]
report_route_status -file [file join $out route_status.rpt]
report_drc -file [file join $out drc.rpt]
check_timing -verbose -file [file join $out check_timing.rpt]
write_xdc -force [file join $out constraints.xdc]
write_checkpoint -force [file join $out post_route_final_clock.dcp]
# Record the actual post-route ROM connectivity/INIT, including pin permutations.
source [file join [file dirname [info script]] rom_mapping.tcl]
export_rom_mapping [file join $out initialized_rom.tsv]
set f [open [file join $out final_clock.json] w]
puts $f "{\"route_period_ns\":$route_period,\"route_wns_ns\":$route_wns,\"period_ns\":$period,\"wns_ns\":$wns,\"whs_ns\":$whs,\"setup_margin_ns\":0.1,\"io_zero_delay_whs_ns\":$io_hold,\"io_timing_qualified\":false,\"seconds\":[expr {[clock seconds]-$started}]}"
close $f
if {$wns < 0.0999 || $whs < 0} {error "Final timing failed: setup=$wns hold=$whs"}
puts "EXTERNAL_ROUTE_PASS period_ns=$period setup_slack_ns=$wns hold_slack_ns=$whs"
