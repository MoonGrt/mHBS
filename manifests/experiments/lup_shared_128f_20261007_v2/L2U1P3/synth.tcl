set_param general.maxThreads 8
create_project -in_memory -part xc7a200tffg1156-3
read_verilog -sv {/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/build/lup_shared_128f_20261007_v2/synth_source/rtl/hash_lane/mhbs_keccak.sv}
read_verilog -sv {/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/build/lup_shared_128f_20261007_v2/synth_source/rtl/hash_lane/mhbs_keccak_pipeline.sv}
read_verilog -sv {/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/build/lup_shared_128f_20261007_v2/synth_source/rtl/hash_lane/mhbs_chain_pipeline_lane.sv}
read_verilog -sv {/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/build/lup_shared_128f_20261007_v2/synth_source/rtl/hash_lane/mhbs_compact_shake_context_lane.sv}
read_verilog -sv {/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/build/lup_shared_128f_20261007_v2/synth_source/rtl/hash_lane/mhbs_recipe_lane.sv}
read_verilog -sv {/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/build/lup_shared_128f_20261007_v2/synth_source/rtl/memory/mhbs_value_store.sv}
read_verilog -sv {/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/build/lup_shared_128f_20261007_v2/synth_source/rtl/memory/mhbs_signature_store.sv}
read_verilog -sv {/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/build/lup_shared_128f_20261007_v2/synth_source/rtl/sequencer/mhbs_program_sequencer.sv}
read_verilog -sv {/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/build/lup_shared_128f_20261007_v2/synth_source/rtl/top/mhbs_hbs.sv}
read_verilog -sv {/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/manifests/experiments/lup_shared_128f_20261007_v2/L2U1P3/mhbs_common.sv}
read_xdc {/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/manifests/experiments/lup_shared_128f_20261007_v2/L2U1P3/clock.xdc}
synth_design -top mhbs_common -part xc7a200tffg1156-3 -mode out_of_context -flatten_hierarchy rebuilt -max_dsp 0 -generic LANES=2 -generic UNROLL=1 -generic PIPELINE=3 -generic PROFILE_ENABLE=0
report_utilization -file {/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/manifests/experiments/lup_shared_128f_20261007_v2/L2U1P3/core_utilization.rpt}
report_utilization -hierarchical -file {/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/manifests/experiments/lup_shared_128f_20261007_v2/L2U1P3/core_hierarchical.rpt}
report_timing_summary -file {/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/manifests/experiments/lup_shared_128f_20261007_v2/L2U1P3/core_timing.rpt}
set bad {}
foreach c [get_cells -hier -filter {IS_PRIMITIVE == 1}] {
 if {[string match FD* [get_property REF_NAME $c]] && [regexp {(cycles|hash_count|permutation_count|hash_base|permutation_base)_reg} $c]} {lappend bad $c}
}
if {[llength $bad]} {error "Statistics registers remain: $bad"}
set f [open {/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/manifests/experiments/lup_shared_128f_20261007_v2/L2U1P3/pruning_audit.json} w]
puts $f {{"passed":true,"profile_enable":false,"statistics_registers":0}}
close $f
write_checkpoint -force {/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/manifests/experiments/lup_shared_128f_20261007_v2/L2U1P3/post_synth.dcp}
puts "LUP_COMMON_SYNTH_PASS L2U1P3"
exit
