set root [file normalize [file join [file dirname [info script]] ../..]]
cd $root
set out build/v4.2/ring_c0/local
file mkdir $out
create_project -in_memory -part xc7a200tffg1156-3
set_param general.maxThreads 4
read_verilog -sv rtl/hash_lane/uhbs_keccak.sv
read_verilog -sv rtl/hash_lane/uhbs_keccak_ring2.sv
synth_design -top uhbs_keccak_ring2 -part xc7a200tffg1156-3 -mode out_of_context -max_dsp 0
create_clock -name clk -period 10.0 [get_ports clk]
report_utilization -file $out/utilization.rpt
report_timing_summary -file $out/timing.rpt
puts RING_LOCAL_SYNTH_PASS
