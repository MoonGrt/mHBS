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
# Finalize the core timing benchmark and preserve the separate zero-delay I/O report.
close_project
set argv [list [file join $out post_route.dcp] $out]
source [file join [file dirname [info script]] finalize_core.tcl]
