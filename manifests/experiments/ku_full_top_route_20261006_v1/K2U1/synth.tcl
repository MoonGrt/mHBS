set_param general.maxThreads 6
create_project -in_memory -part xc7a200tffg1156-3
read_verilog -sv {/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/manifests/experiments/ku_sixteen_area_20261006_v1/snapshot/rtl/hash_lane/mhbs_keccak.sv}
read_verilog -sv {/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/manifests/experiments/ku_sixteen_area_20261006_v1/snapshot/rtl/hash_lane/mhbs_compact_shake_context_lane.sv}
read_verilog -sv {/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/manifests/experiments/ku_sixteen_area_20261006_v1/snapshot/rtl/hash_lane/mhbs_recipe_lane.sv}
read_verilog -sv {/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/manifests/experiments/ku_sixteen_area_20261006_v1/snapshot/rtl/memory/mhbs_value_store.sv}
read_verilog -sv {/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/manifests/experiments/ku_sixteen_area_20261006_v1/snapshot/rtl/memory/mhbs_signature_store.sv}
read_verilog -sv {/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/manifests/experiments/ku_sixteen_area_20261006_v1/snapshot/rtl/sequencer/mhbs_program_sequencer.sv}
read_verilog -sv {/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/manifests/experiments/ku_sixteen_area_20261006_v1/snapshot/rtl/top/mhbs_hbs.sv}
read_verilog -sv {/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/manifests/experiments/ku_sixteen_area_20261006_v1/snapshot/mhbs_common.sv}
read_xdc {/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/manifests/experiments/ku_full_top_route_20261006_v1/K2U1/clock.xdc}
synth_design -top mhbs_common -part xc7a200tffg1156-3 -mode out_of_context -flatten_hierarchy rebuilt -max_dsp 0 -generic LANES=2 -generic UNROLL=1 -generic PROFILE_ENABLE=0
write_edif -force {/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/manifests/experiments/ku_full_top_route_20261006_v1/K2U1/mhbs_common.edf}
write_verilog -force -mode synth_stub {/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/manifests/experiments/ku_full_top_route_20261006_v1/K2U1/common_stub.v}
close_project
create_project -in_memory -part xc7a200tffg1156-3
read_verilog -sv {/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/manifests/experiments/ku_sixteen_area_20261006_v1/snapshot/rtl/memory/mhbs_signature_store.sv}
read_verilog {/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/manifests/experiments/ku_full_top_route_20261006_v1/K2U1/common_stub.v}
read_verilog -sv {/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/manifests/experiments/ku_full_top_route_20261006_v1/K2U1/shell.sv}
synth_design -top mhbs_top -part xc7a200tffg1156-3 -mode out_of_context -flatten_hierarchy none
write_edif -force {/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/manifests/experiments/ku_full_top_route_20261006_v1/K2U1/mhbs_top.edf}
close_project
read_edif {/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/manifests/experiments/ku_full_top_route_20261006_v1/K2U1/mhbs_common.edf}
read_edif {/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/manifests/experiments/ku_full_top_route_20261006_v1/K2U1/mhbs_top.edf}
link_design -top mhbs_top -part xc7a200tffg1156-3 -mode out_of_context
if {[llength [get_cells -hier -filter {IS_BLACKBOX == 1}]]} {error "Unresolved blackbox"}
set_property DONT_TOUCH true [get_cells common]
create_clock -name clk -period 10.0 [get_ports clk]
source {/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/experiments/v4.2/external_job_message/rom_mapping.tcl}
export_rom_mapping {/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/manifests/experiments/ku_full_top_route_20261006_v1/K2U1/rom_mapping.tsv}
exec python3 {/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/scripts/v42_external_rom.py} {/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/manifests/experiments/ku_full_top_route_20261006_v1/K2U1} slh_128f
source {/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/manifests/experiments/ku_full_top_route_20261006_v1/K2U1/init.tcl}
export_rom_mapping {/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/manifests/experiments/ku_full_top_route_20261006_v1/K2U1/initialized_rom.tsv}
exec python3 {/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/scripts/v42_external_rom.py} {/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/manifests/experiments/ku_full_top_route_20261006_v1/K2U1} slh_128f --audit
report_utilization -file {/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/manifests/experiments/ku_full_top_route_20261006_v1/K2U1/synth_utilization.rpt}
report_utilization -hierarchical -file {/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/manifests/experiments/ku_full_top_route_20261006_v1/K2U1/synth_hierarchical.rpt}
write_checkpoint -force {/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/manifests/experiments/ku_full_top_route_20261006_v1/K2U1/post_synth.dcp}
puts "KU_FULL_TOP_SYNTH_PASS"
exit
