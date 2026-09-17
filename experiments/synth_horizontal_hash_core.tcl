set root [file normalize [file join [file dirname [info script]] ..]]
set out_dir [file join $root build vivado horizontal_hash_core]
file mkdir $out_dir

read_verilog -sv [file join $root rtl sequencer micro_hbs_event_scoreboard.sv]
read_verilog -sv [file join $root rtl sequencer micro_hbs_horizontal_program_store.sv]
read_verilog -sv [file join $root rtl sequencer micro_hbs_horizontal_sequencer.sv]
read_verilog -sv [file join $root rtl hash_lane micro_hbs_keccak_f1600.sv]
read_verilog -sv [file join $root rtl hash_lane micro_hbs_horizontal_keccak_lane.sv]
read_verilog -sv [file join $root rtl top micro_hbs_horizontal_hash_core.sv]

synth_design -top micro_hbs_horizontal_hash_core \
    -part xc7k325tffg900-2 -mode out_of_context -flatten_hierarchy rebuilt
create_clock -name clk -period 10.000 [get_ports clk]
opt_design
place_design
phys_opt_design
route_design

report_utilization -hierarchical -file [file join $out_dir utilization_hierarchical.rpt]
report_utilization -file [file join $out_dir utilization.rpt]
report_timing_summary -delay_type max -max_paths 10 \
    -file [file join $out_dir timing_summary.rpt]
write_checkpoint -force [file join $out_dir horizontal_hash_core_routed.dcp]

set fp [open [file join $out_dir status.txt] w]
puts $fp "status=ROUTED"
puts $fp "part=xc7k325tffg900-2"
puts $fp "clock_period_ns=10.000"
puts $fp "program_words=6144"
puts $fp "word_bits=128"
puts $fp "lanes=2"
puts $fp "unroll=2"
close $fp
