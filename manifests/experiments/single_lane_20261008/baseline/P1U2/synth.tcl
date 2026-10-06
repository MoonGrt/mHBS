set_param general.maxThreads 8
create_project -in_memory -part xc7a200tffg1156-3
read_verilog -sv {/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/build/single_lane_20261008/baseline/rtl/hash_lane/mhbs_keccak.sv}
read_verilog -sv {/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/build/single_lane_20261008/baseline/rtl/hash_lane/mhbs_chain_pipeline_lane.sv}
read_verilog -sv {/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/build/single_lane_20261008/baseline/rtl/hash_lane/mhbs_recipe_lane.sv}
read_verilog -sv {/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/build/single_lane_20261008/baseline/rtl/memory/mhbs_value_store.sv}
read_verilog -sv {/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/build/single_lane_20261008/baseline/rtl/memory/mhbs_signature_store.sv}
read_verilog -sv {/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/build/single_lane_20261008/baseline/rtl/sequencer/mhbs_program_sequencer.sv}
read_verilog -sv {/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/build/single_lane_20261008/baseline/rtl/top/mhbs_hbs.sv}
read_verilog -sv {/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/manifests/experiments/single_lane_20261008/baseline/P1U2/common.sv}
read_xdc {/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/manifests/experiments/single_lane_20261008/baseline/P1U2/clock.xdc}
synth_design -top mhbs_common -part xc7a200tffg1156-3 -mode out_of_context -flatten_hierarchy rebuilt -max_dsp 0 -generic UNROLL=2 -generic PIPELINE=1 -generic PROFILE_ENABLE=0 -generic LANES=1
report_utilization -file {/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/manifests/experiments/single_lane_20261008/baseline/P1U2/core_utilization.rpt}
report_utilization -hierarchical -file {/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/manifests/experiments/single_lane_20261008/baseline/P1U2/core_hierarchical.rpt}
set bad {}
foreach c [get_cells -hier -filter {IS_PRIMITIVE == 1}] {if {[string match FD* [get_property REF_NAME $c]] && [regexp {(cycles|hash_count|permutation_count|hash_base|permutation_base)_reg} $c]} {lappend bad $c}}
if {[llength $bad]} {error "statistics remain: $bad"}
write_checkpoint -force {/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/manifests/experiments/single_lane_20261008/baseline/P1U2/post_synth.dcp}
puts "SINGLE_LANE_SYNTH_PASS"
exit
