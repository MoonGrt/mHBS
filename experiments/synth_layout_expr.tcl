set script_dir [file dirname [file normalize [info script]]]
set root [file normalize [file join $script_dir ..]]
set outdir [file normalize [file join $root build vivado layout_expr]]
file mkdir $outdir

read_verilog -sv [file join $root rtl composer micro_hbs_layout_expr_w288_rejected.sv]
synth_design -top micro_hbs_layout_expr -part xc7a200tffg1156-2 \
    -flatten_hierarchy rebuilt -mode out_of_context
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
puts $fp "scope=generic_layout_expression_only"
puts $fp "top=micro_hbs_layout_expr"
puts $fp "part=xc7a200tffg1156-2"
puts $fp "clock_period_ns=10.000"
puts $fp "tool=[version -short]"
puts $fp "value_width=288"
puts $fp "token_words=32"
puts $fp "stack_depth=8"
puts $fp "integrated_with_hash_lane=false"
puts $fp "paper_comparable=false"
close $fp
