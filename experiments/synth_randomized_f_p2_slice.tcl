set script_dir [file dirname [file normalize [info script]]]
set root [file normalize [file join $script_dir ..]]
set outdir [file normalize [file join $root build vivado randomized_f_p2_u2_raw]]
file mkdir $outdir

read_verilog -sv [file join $root rtl sequencer micro_hbs_program_store.sv]
read_verilog -sv [file join $root rtl sequencer micro_hbs_sequencer.sv]
read_verilog -sv [file join $root rtl hash_lane micro_hbs_keccak_f1600.sv]
read_verilog -sv [file join $root rtl hash_lane micro_hbs_shake256_single_block.sv]
read_verilog -sv [file join $root rtl composer micro_hbs_randomized_hash.sv]
read_verilog -sv [file join $root rtl top micro_hbs_randomized_f_p2_slice.sv]

synth_design -top micro_hbs_randomized_f_p2_slice \
    -part xc7a200tffg1156-2 -mode out_of_context -flatten_hierarchy rebuilt \
    -generic PROGRAM_WORDS=512 -generic UNROLL=2
create_clock -name clk -period 10.000 [get_ports clk]
opt_design
place_design
phys_opt_design
route_design

report_utilization -file [file join $outdir utilization.rpt]
report_utilization -hierarchical \
    -file [file join $outdir utilization_hierarchical.rpt]
report_timing_summary -delay_type max -max_paths 10 \
    -file [file join $outdir timing_summary.rpt]
write_checkpoint -force [file join $outdir routed.dcp]

set fp [open [file join $outdir run_identity.txt] w]
puts $fp "scope=microsequencer_raw_job_randomized_f_p2_u2_slice"
puts $fp "top=micro_hbs_randomized_f_p2_slice"
puts $fp "part=xc7a200tffg1156-2"
puts $fp "clock_period_ns=10.000"
puts $fp "tool=[version -short]"
puts $fp "parallel_lanes=2"
puts $fp "unroll=2"
puts $fp "program_words=512"
puts $fp "input_semantics=raw_pub_seed_address_two_nodes_public_bound"
puts $fp "scheduler=static_11_or_01_microcode"
puts $fp "integrated_with_microsequencer=true"
puts $fp "preassembled_hash_messages=false"
puts $fp "host_writes_while_busy=false"
puts $fp "paper_comparable=false"
close $fp
