set script_dir [file dirname [file normalize [info script]]]
set root [file normalize [file join $script_dir ..]]
set outdir [file normalize [file join $root build vivado randomized_chain_p1u2]]
file mkdir $outdir

read_verilog -sv [file join $root rtl sequencer micro_hbs_program_store.sv]
read_verilog -sv [file join $root rtl sequencer micro_hbs_sequencer.sv]
read_verilog -sv [file join $root rtl memory micro_hbs_scratchpad64.sv]
read_verilog -sv [file join $root rtl hash_lane micro_hbs_keccak_f1600.sv]
read_verilog -sv [file join $root rtl hash_lane micro_hbs_shake256_single_block.sv]
read_verilog -sv [file join $root rtl composer micro_hbs_randomized_hash.sv]
read_verilog -sv [file join $root rtl composer micro_hbs_randomized_f_scratch_adapter.sv]
read_verilog -sv [file join $root rtl top micro_hbs_randomized_chain_slice.sv]

synth_design -top micro_hbs_randomized_chain_slice -part xc7a200tffg1156-2 \
    -mode out_of_context -flatten_hierarchy rebuilt
create_clock -name clk -period 10.000 [get_ports clk]
opt_design
place_design
phys_opt_design
route_design

report_utilization -hierarchical -file [file join $outdir utilization_hierarchical.rpt]
report_utilization -file [file join $outdir utilization.rpt]
report_timing_summary -delay_type max -max_paths 10 -file [file join $outdir timing_summary.rpt]
write_checkpoint -force [file join $outdir routed.dcp]

set fp [open [file join $outdir run_identity.txt] w]
puts $fp "scope=randomized_f_vertical_slice"
puts $fp "top=micro_hbs_randomized_chain_slice"
puts $fp "lanes=1"
puts $fp "unroll=2"
puts $fp "program_words=512"
puts $fp "scratch_words=32"
puts $fp "part=xc7a200tffg1156-2"
puts $fp "clock_period_ns=10.000"
puts $fp "tool=[version -short]"
puts $fp "contains_real_hash_lane=true"
puts $fp "complete_algorithm=false"
puts $fp "paper_comparable=false"
close $fp
