set_param general.maxThreads 8
puts "VIVADO_THREADS [get_param general.maxThreads]"
create_project -in_memory -part xc7a200tffg1156-3
read_verilog -sv {/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/manifests/experiments/single_lane_13_20261009_v2/source/rtl/hash_lane/mhbs_keccak.sv}
read_verilog -sv {/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/manifests/experiments/single_lane_13_20261009_v2/source/rtl/hash_lane/mhbs_chain_pipeline_lane.sv}
read_verilog -sv {/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/manifests/experiments/single_lane_13_20261009_v2/source/rtl/hash_lane/mhbs_recipe_lane.sv}
read_verilog -sv {/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/manifests/experiments/single_lane_13_20261009_v2/source/rtl/memory/mhbs_value_store.sv}
read_verilog -sv {/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/manifests/experiments/single_lane_13_20261009_v2/source/rtl/memory/mhbs_signature_store.sv}
read_verilog -sv {/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/manifests/experiments/single_lane_13_20261009_v2/source/rtl/sequencer/mhbs_program_sequencer.sv}
read_verilog -sv {/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/manifests/experiments/single_lane_13_20261009_v2/source/rtl/top/mhbs_hbs.sv}
read_verilog -sv {/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/manifests/experiments/single_lane_13_20261009_v2/P2U2/diagnostics/no_timing_driven_110mhz/mhbs_common.sv}
read_xdc {/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/manifests/experiments/single_lane_13_20261009_v2/P2U2/diagnostics/no_timing_driven_110mhz/clock.xdc}
synth_design -no_timing_driven -top mhbs_common -part xc7a200tffg1156-3 -mode out_of_context -flatten_hierarchy rebuilt -max_dsp 0 -generic PIPELINE=2 -generic UNROLL=2 -generic PROFILE_ENABLE=0
report_utilization -file {/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/manifests/experiments/single_lane_13_20261009_v2/P2U2/diagnostics/no_timing_driven_110mhz/core_utilization.rpt}
report_utilization -hierarchical -file {/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/manifests/experiments/single_lane_13_20261009_v2/P2U2/diagnostics/no_timing_driven_110mhz/core_hierarchical.rpt}
report_timing_summary -file {/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/manifests/experiments/single_lane_13_20261009_v2/P2U2/diagnostics/no_timing_driven_110mhz/core_timing.rpt}
set bad {}
foreach c [get_cells -hier -filter {IS_PRIMITIVE == 1}] {if {[string match FD* [get_property REF_NAME $c]] && [regexp {(cycles|hash_count|permutation_count|hash_base|permutation_base)_reg} $c]} {lappend bad $c}}
if {[llength $bad]} {error "Statistics registers remain: $bad"}
write_checkpoint -force {/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/manifests/experiments/single_lane_13_20261009_v2/P2U2/diagnostics/no_timing_driven_110mhz/post_synth.dcp}
report_timing -max_paths 10 -file {/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/manifests/experiments/single_lane_13_20261009_v2/P2U2/diagnostics/no_timing_driven_110mhz/critical_paths.rpt}
check_timing -verbose -file {/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/manifests/experiments/single_lane_13_20261009_v2/P2U2/diagnostics/no_timing_driven_110mhz/check_timing.rpt}
puts "PU_SYNTH_PASS P2U2"
exit
