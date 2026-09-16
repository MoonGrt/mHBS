set script_dir [file dirname [file normalize [info script]]]
set root [file normalize [file join $script_dir ..]]
set outdir [file normalize [file join $root build vivado control_slice_p1]]
file mkdir $outdir

read_verilog -sv [file join $root rtl sequencer micro_hbs_program_store.sv]
read_verilog -sv [file join $root rtl sequencer micro_hbs_sequencer.sv]
read_verilog -sv [file join $root rtl hash_lane micro_hbs_hash_latency_stub.sv]
read_verilog -sv [file join $root rtl top micro_hbs_job_latch.sv]
read_verilog -sv [file join $root rtl top micro_hbs_control_slice.sv]

synth_design -top micro_hbs_control_slice -part xc7a200tffg1156-2 -flatten_hierarchy rebuilt
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
puts $fp "scope=control_slice_only"
puts $fp "top=micro_hbs_control_slice"
puts $fp "part=xc7a200tffg1156-2"
puts $fp "clock_period_ns=10.000"
puts $fp "tool=[version -short]"
puts $fp "contains_real_hash_lane=false"
puts $fp "paper_comparable=false"
close $fp
