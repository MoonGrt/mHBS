set_param general.maxThreads 6
read_edif {/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/manifests/experiments/ku_full_top_route_20261006_v1/K2U2/mhbs_common.edf}
read_edif {/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/manifests/experiments/ku_full_top_route_20261006_v1/K2U2/mhbs_top.edf}
link_design -top mhbs_top -part xc7a200tffg1156-3 -mode out_of_context
if {[llength [get_cells -hier -filter {IS_BLACKBOX == 1}]]} {error "Unresolved blackbox"}
set_property DONT_TOUCH true [get_cells common]
create_clock -name clk -period 10.0 [get_ports clk]
source {/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/experiments/v4.2/external_job_message/rom_mapping.tcl}
export_rom_mapping {/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/manifests/experiments/ku_full_top_route_20261006_v1/K2U2/rom_mapping.tsv}
exec python3 {/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/scripts/v42_external_rom.py} {/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/manifests/experiments/ku_full_top_route_20261006_v1/K2U2} slh_128f
source {/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/manifests/experiments/ku_full_top_route_20261006_v1/K2U2/init.tcl}
export_rom_mapping {/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/manifests/experiments/ku_full_top_route_20261006_v1/K2U2/initialized_rom.tsv}
report_utilization -file {/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/manifests/experiments/ku_full_top_route_20261006_v1/K2U2/synth_utilization.rpt}
report_utilization -hierarchical -file {/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/manifests/experiments/ku_full_top_route_20261006_v1/K2U2/synth_hierarchical.rpt}
write_checkpoint -force {/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/manifests/experiments/ku_full_top_route_20261006_v1/K2U2/post_synth.dcp}
puts "KU_FULL_TOP_SYNTH_PASS"
exit
