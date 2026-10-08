set_param general.maxThreads 4
create_project -in_memory -part xc7a200tffg1156-3
read_verilog -sv {/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/manifests/experiments/stateful_keygen_pu13_20261012_v1/source/rtl/hash_lane/mhbs_keccak.sv}
read_verilog -sv {/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/manifests/experiments/stateful_keygen_pu13_20261012_v1/source/rtl/hash_lane/mhbs_chain_pipeline_lane.sv}
read_verilog -sv {/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/manifests/experiments/stateful_keygen_pu13_20261012_v1/source/rtl/hash_lane/mhbs_recipe_lane.sv}
read_verilog -sv {/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/manifests/experiments/stateful_keygen_pu13_20261012_v1/source/rtl/memory/mhbs_value_store.sv}
read_verilog -sv {/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/manifests/experiments/stateful_keygen_pu13_20261012_v1/source/rtl/memory/mhbs_signature_store.sv}
read_verilog -sv {/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/manifests/experiments/stateful_keygen_pu13_20261012_v1/source/rtl/sequencer/mhbs_program_sequencer.sv}
read_verilog -sv {/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/manifests/experiments/stateful_keygen_pu13_20261012_v1/source/rtl/top/mhbs_hbs.sv}
read_verilog -sv {/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/manifests/experiments/stateful_keygen_pu13_20261012_v1/P2U2/mhbs_common.sv}
read_xdc {/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/manifests/experiments/stateful_keygen_pu13_20261012_v1/P2U2/clock.xdc}
synth_design -top mhbs_common -part xc7a200tffg1156-3 -mode out_of_context -flatten_hierarchy rebuilt -max_dsp 0 -generic PIPELINE=2 -generic UNROLL=2 -generic PROFILE_ENABLE=0
report_utilization -file {/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/manifests/experiments/stateful_keygen_pu13_20261012_v1/P2U2/core_utilization.rpt}
report_utilization -hierarchical -file {/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/manifests/experiments/stateful_keygen_pu13_20261012_v1/P2U2/core_hierarchical.rpt}
report_timing_summary -file {/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/manifests/experiments/stateful_keygen_pu13_20261012_v1/P2U2/core_timing.rpt}
set bad {}
foreach c [get_cells -hier -filter {IS_PRIMITIVE == 1}] {if {[string match FD* [get_property REF_NAME $c]] && [regexp {(cycles|hash_count|permutation_count|hash_base|permutation_base)_reg} $c]} {lappend bad $c}}
if {[llength $bad]} {error "Statistics registers remain: $bad"}
puts "STATEFUL_PU_SYNTH_PASS P2U2"
exit
