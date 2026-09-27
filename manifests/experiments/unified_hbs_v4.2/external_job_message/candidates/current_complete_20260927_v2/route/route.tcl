# Route each layout-3 parameter shell independently. Do not substitute a
# differently connected Job shell into an already routed netlist.
set source_dcp [file normalize [lindex $argv 0]]
set out [file normalize [lindex $argv 1]]
file mkdir $out
set_param general.maxThreads 8
set started [clock seconds]
open_checkpoint $source_dcp
create_clock -name clk -period 10.0 [get_ports clk]
set_property HD.CLK_SRC BUFGCTRL_X0Y0 [get_ports clk]
# Out-of-context timing contract: zero board delay on every data/status port.
# In particular rst is synchronous and is timed, not declared a false path.
set data_inputs [get_ports -filter {DIRECTION == IN && NAME != clk}]
set_input_delay -clock clk -max 0.0 $data_inputs
set_input_delay -clock clk -min 0.0 $data_inputs
set_output_delay -clock clk -max 0.0 [all_outputs]
set_output_delay -clock clk -min 0.0 [all_outputs]
# Keep the generic common core and ROM boundary protected as in synthesis.
opt_design
place_design -directive Explore
phys_opt_design -directive AggressiveExplore
write_checkpoint -force [file join $out post_place.dcp]
report_timing_summary -delay_type min_max -max_paths 10 -file [file join $out post_place_timing.rpt]
route_design -directive Explore
write_checkpoint -force [file join $out post_route.dcp]
set hold_path [get_timing_paths -delay_type min -max_paths 1]
if {[llength $hold_path] && [get_property SLACK $hold_path] < 0} {
    phys_opt_design -directive AggressiveHoldFix
    route_design -directive Explore
    write_checkpoint -force [file join $out post_route.dcp]
}
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
puts $f "{\"route_period_ns\":$route_period,\"route_wns_ns\":$route_wns,\"period_ns\":$period,\"wns_ns\":$wns,\"whs_ns\":$whs,\"setup_margin_ns\":0.1,\"seconds\":[expr {[clock seconds]-$started}]}"
close $f
if {$wns < 0.0999 || $whs < 0} {error "Final timing failed: setup=$wns hold=$whs"}
puts "EXTERNAL_ROUTE_PASS period_ns=$period setup_slack_ns=$wns hold_slack_ns=$whs"
