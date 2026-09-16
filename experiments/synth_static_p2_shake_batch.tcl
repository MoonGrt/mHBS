set script_dir [file dirname [file normalize [info script]]]
set root [file normalize [file join $script_dir ..]]
set outdir [file normalize [file join $root build vivado static_p2_u2_batch]]
file mkdir $outdir

read_verilog -sv [file join $root rtl hash_lane micro_hbs_keccak_f1600.sv]
read_verilog -sv [file join $root rtl hash_lane micro_hbs_shake256_single_block.sv]
read_verilog -sv [file join $root rtl top micro_hbs_static_p2_shake_batch.sv]
synth_design -top micro_hbs_static_p2_shake_batch -part xc7a200tffg1156-2 \
    -mode out_of_context -flatten_hierarchy rebuilt \
    -generic MAX_TASKS=5 -generic UNROLL=2
create_clock -name clk -period 10.000 [get_ports clk]
opt_design
place_design
phys_opt_design
route_design

report_utilization -file [file join $outdir utilization.rpt]
report_utilization -hierarchical -file [file join $outdir utilization_hierarchical.rpt]
report_timing_summary -delay_type max -max_paths 10 \
    -file [file join $outdir timing_summary.rpt]
write_checkpoint -force [file join $outdir routed.dcp]

set fp [open [file join $outdir run_identity.txt] w]
puts $fp "scope=static_p2_u2_shake_batch_slice"
puts $fp "top=micro_hbs_static_p2_shake_batch"
puts $fp "part=xc7a200tffg1156-2"
puts $fp "clock_period_ns=10.000"
puts $fp "tool=[version -short]"
puts $fp "parallel_lanes=2"
puts $fp "unroll=2"
puts $fp "max_tasks=5"
puts $fp "scheduler=static_even_odd"
puts $fp "integrated_with_microsequencer=false"
puts $fp "paper_comparable=false"
close $fp
