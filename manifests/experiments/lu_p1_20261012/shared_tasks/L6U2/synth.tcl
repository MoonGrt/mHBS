set_param general.maxThreads 4
create_project -in_memory -part xc7a200tffg1156-3
read_verilog -sv {/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/build/lu_p1_20261012/shared_tasks/source/rtl/hash_lane/mhbs_keccak.sv}
read_verilog -sv {/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/build/lu_p1_20261012/shared_tasks/source/rtl/hash_lane/mhbs_recipe_lane.sv}
read_verilog -sv {/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/build/lu_p1_20261012/shared_tasks/source/rtl/memory/mhbs_value_store.sv}
read_verilog -sv {/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/build/lu_p1_20261012/shared_tasks/source/rtl/memory/mhbs_signature_store.sv}
read_verilog -sv {/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/build/lu_p1_20261012/shared_tasks/source/rtl/sequencer/mhbs_program_sequencer.sv}
read_verilog -sv {/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/build/lu_p1_20261012/shared_tasks/source/rtl/top/mhbs_hbs.sv}
read_verilog -sv {/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/manifests/experiments/lu_p1_20261012/shared_tasks/L6U2/mhbs_common.sv}
read_xdc {/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/manifests/experiments/lu_p1_20261012/shared_tasks/L6U2/clock.xdc}
synth_design -top mhbs_common -part xc7a200tffg1156-3 -mode out_of_context -flatten_hierarchy rebuilt -max_dsp 0 -generic LANES=6 -generic UNROLL=2 -generic PROFILE_ENABLE=0
report_utilization -file {/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/manifests/experiments/lu_p1_20261012/shared_tasks/L6U2/core_utilization.rpt}
report_utilization -hierarchical -file {/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/manifests/experiments/lu_p1_20261012/shared_tasks/L6U2/core_hierarchical.rpt}
report_timing_summary -file {/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/manifests/experiments/lu_p1_20261012/shared_tasks/L6U2/core_timing.rpt}
write_checkpoint -force {/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/build/lu_p1_20261012/shared_tasks/synth_L6U2/synth.dcp}
puts "LU_SYNTH_PASS"
exit
