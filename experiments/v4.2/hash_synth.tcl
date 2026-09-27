set root [file normalize [file join [file dirname [info script]] ../..]]
cd $root
set tag [lindex $argv 0]
set out build/v4.2/$tag/hash_synth
file mkdir $out
set_param general.maxThreads 4
foreach mask {4126 6} {
 create_project -in_memory -part xc7a200tffg1156-3
 read_verilog -sv rtl/hash_lane/mhbs_keccak.sv
 read_verilog -sv rtl/hash_lane/mhbs_compact_shake_context_lane.sv
 read_verilog -sv rtl/hash_lane/mhbs_recipe_lane.sv
 synth_design -top mhbs_recipe_lane -part xc7a200tffg1156-3 -mode out_of_context -generic N=32 -generic DIGEST_BYTES=49 -generic PROFILE_ENABLE=1 -generic RECIPE_MASK=$mask -max_dsp 0
 create_clock -name clk -period 10.0 [get_ports clk]
 report_utilization -file $out/mask${mask}_utilization.rpt
 report_timing_summary -file $out/mask${mask}_timing.rpt
 close_project
}
puts V42_HASH_SYNTH_PASS
