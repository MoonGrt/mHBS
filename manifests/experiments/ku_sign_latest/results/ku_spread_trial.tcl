# Common K/U matrix routing contract: internal paths only, shared 20 ns start.
set source_dcp [file normalize [lindex $argv 0]]
set out [file normalize [lindex $argv 1]]
file mkdir $out
set_param general.maxThreads 4
set started [clock seconds]
open_checkpoint $source_dcp
create_clock -name clk -period 20.0 [get_ports clk]
set_property HD.CLK_SRC BUFGCTRL_X0Y0 [get_ports clk]
set io_inputs [get_ports -filter {DIRECTION == IN && NAME != clk}]
set_input_delay -clock clk -max 0.0 $io_inputs
set_input_delay -clock clk -min 0.0 $io_inputs
set_output_delay -clock clk -max 0.0 [all_outputs]
set_output_delay -clock clk -min 0.0 [all_outputs]
set_false_path -from $io_inputs
set_false_path -to [all_outputs]
opt_design
place_design -directive AltSpreadLogic_high
phys_opt_design -directive AggressiveExplore
write_checkpoint -force [file join $out post_place.dcp]
route_design -directive Explore
write_checkpoint -force [file join $out post_route.dcp]
set hold_path [get_timing_paths -delay_type min -max_paths 1]
if {[get_property SLACK $hold_path] < 0} {
 phys_opt_design -aggressive_hold_fix
 route_design -preserve -directive Default
}
set route_period [get_property PERIOD [get_clocks clk]]
set route_wns [get_property SLACK [lindex [get_timing_paths -delay_type max -max_paths 1] 0]]
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
source {/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/build/worktrees/ku_matrix_20260927_v1/experiments/v4.2/external_job_message/rom_mapping.tcl}
export_rom_mapping [file join $out initialized_rom.tsv]
set f [open [file join $out final_clock.json] w]
puts $f "{\"route_period_ns\":$route_period,\"route_wns_ns\":$route_wns,\"period_ns\":$period,\"wns_ns\":$wns,\"whs_ns\":$whs,\"setup_margin_ns\":0.1,\"io_timing_qualified\":false,\"seconds\":[expr {[clock seconds]-$started}]}"
close $f
if {$wns < 0.0999 || $whs < 0} {error "Final timing failed: setup=$wns hold=$whs"}
puts "KU_ROUTE_PASS period_ns=$period setup_slack_ns=$wns hold_slack_ns=$whs"
