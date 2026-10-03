set_param general.maxThreads 6
open_checkpoint {/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/manifests/experiments/ku_full_top_route_20261006_v1/K4U2/post_synth.dcp}
create_clock -name clk -period 9.090909091 [get_ports clk]
set_property HD.CLK_SRC BUFGCTRL_X0Y0 [get_ports clk]
set inputs [get_ports -filter {DIRECTION == IN && NAME != clk}]
set_input_delay -clock clk -max 0 $inputs
set_input_delay -clock clk -min 0 $inputs
set_output_delay -clock clk -max 0 [all_outputs]
set_output_delay -clock clk -min 0 [all_outputs]
set_false_path -from $inputs
set_false_path -to [all_outputs]
opt_design
place_design -directive Explore
phys_opt_design -directive AggressiveExplore
write_checkpoint -force {/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/manifests/experiments/ku_full_top_route_20261006_v1/K4U2/post_place.dcp}
route_design -directive Explore
write_checkpoint -force {/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/manifests/experiments/ku_full_top_route_20261006_v1/K4U2/post_route_initial.dcp}
set initial_wns [get_property SLACK [get_timing_paths -delay_type max -max_paths 1]]
if {$initial_wns eq ""} {error "No internal setup path"}
set delay [expr {9.090909091 - $initial_wns}]
set final_period [expr {ceil(($delay + 0.050)*1000.0)/1000.0}]
if {$final_period < 1.0} {set final_period 1.0}
create_clock -name clk -period $final_period [get_ports clk]
report_utilization -file {/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/manifests/experiments/ku_full_top_route_20261006_v1/K4U2/route_utilization.rpt}
report_utilization -hierarchical -file {/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/manifests/experiments/ku_full_top_route_20261006_v1/K4U2/route_hierarchical.rpt}
report_timing_summary -delay_type min_max -report_unconstrained -max_paths 10 -file {/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/manifests/experiments/ku_full_top_route_20261006_v1/K4U2/timing_summary.rpt}
report_timing -delay_type max -max_paths 10 -file {/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/manifests/experiments/ku_full_top_route_20261006_v1/K4U2/setup_paths.rpt}
report_timing -delay_type min -max_paths 10 -file {/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/manifests/experiments/ku_full_top_route_20261006_v1/K4U2/hold_paths.rpt}
report_route_status -file {/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/manifests/experiments/ku_full_top_route_20261006_v1/K4U2/route_status.rpt}
report_drc -file {/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/manifests/experiments/ku_full_top_route_20261006_v1/K4U2/drc.rpt}
check_timing -verbose -file {/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/manifests/experiments/ku_full_top_route_20261006_v1/K4U2/check_timing.rpt}
write_xdc -force {/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/manifests/experiments/ku_full_top_route_20261006_v1/K4U2/final_constraints.xdc}
write_checkpoint -force {/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/manifests/experiments/ku_full_top_route_20261006_v1/K4U2/post_route.dcp}
set final_wns [get_property SLACK [get_timing_paths -delay_type max -max_paths 1]]
set final_whs [get_property SLACK [get_timing_paths -delay_type min -max_paths 1]]
set drc_errors [llength [get_drc_violations -quiet -filter {SEVERITY == Error}]]
set f [open {/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/manifests/experiments/ku_full_top_route_20261006_v1/K4U2/timing.json} w]
puts $f "{\"target_period_ns\":9.090909091,\"initial_wns_ns\":$initial_wns,\"final_period_ns\":$final_period,\"final_wns_ns\":$final_wns,\"final_whs_ns\":$final_whs,\"drc_errors\":$drc_errors}"
close $f
puts "KU_FULL_TOP_ROUTE_PASS"
exit
