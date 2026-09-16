set script_dir [file dirname [file normalize [info script]]]
set root [file normalize [file join $script_dir ..]]
set outdir [file normalize [file join $root build vivado treehash_warm_active_cache_h10w4]]
file mkdir $outdir

read_verilog -sv [file join $root rtl treehash micro_hbs_treehash_warm_active_cache.sv]
synth_design -top micro_hbs_treehash_warm_active_cache \
    -part xc7a200tffg1156-2 -mode out_of_context -flatten_hierarchy rebuilt \
    -generic TREE_HEIGHT=10 -generic WINDOW_HEIGHT=4
create_clock -name clk -period 10.000 [get_ports clk]
opt_design
place_design
phys_opt_design
route_design

report_utilization -hierarchical -file [file join $outdir utilization_hierarchical.rpt]
report_utilization -file [file join $outdir utilization.rpt]
report_timing_summary -delay_type max -max_paths 10 \
    -file [file join $outdir timing_summary.rpt]
write_checkpoint -force [file join $outdir routed.dcp]

set fp [open [file join $outdir run_identity.txt] w]
puts $fp "scope=treehash_warm_active_cache"
puts $fp "top=micro_hbs_treehash_warm_active_cache"
puts $fp "tree_height=10"
puts $fp "window_height=4"
puts $fp "upper_capacity_nodes=127"
puts $fp "lower_capacity_nodes=30"
puts $fp "total_capacity_nodes=157"
puts $fp "logical_capacity_bytes=5024"
puts $fp "node_width_bits=256"
puts $fp "activation_control=target_leaf_internal_alignment"
puts $fp "part=xc7a200tffg1156-2"
puts $fp "clock_period_ns=10.000"
puts $fp "tool=[version -short]"
puts $fp "integrated=false"
puts $fp "complete_algorithm=false"
puts $fp "paper_comparable=false"
close $fp
