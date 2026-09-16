if {$argc != 1} {
    error "usage: synth_keccak_lane.tcl <unroll: 1|2>"
}
set unroll [lindex $argv 0]
if {$unroll != 1 && $unroll != 2} {
    error "unroll must be 1 or 2"
}

set script_dir [file dirname [file normalize [info script]]]
set root [file normalize [file join $script_dir ..]]
set outdir [file normalize [file join $root build vivado keccak_u$unroll]]
file mkdir $outdir

read_verilog -sv [file join $root rtl hash_lane micro_hbs_keccak_f1600.sv]
synth_design -top micro_hbs_keccak_f1600 -part xc7a200tffg1156-2 \
    -mode out_of_context -flatten_hierarchy rebuilt -generic UNROLL=$unroll
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
puts $fp "scope=keccak_f1600_lane_only"
puts $fp "top=micro_hbs_keccak_f1600"
puts $fp "unroll=$unroll"
puts $fp "part=xc7a200tffg1156-2"
puts $fp "clock_period_ns=10.000"
puts $fp "tool=[version -short]"
puts $fp "paper_comparable=false"
close $fp
