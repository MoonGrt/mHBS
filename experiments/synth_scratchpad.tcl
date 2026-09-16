if {$argc != 2} {
    error "usage: synth_scratchpad.tcl <words64> <label>"
}
set words [lindex $argv 0]
set label [lindex $argv 1]
set script_dir [file dirname [file normalize [info script]]]
set root [file normalize [file join $script_dir ..]]
set outdir [file normalize [file join $root build vivado scratchpad_$label]]
file mkdir $outdir

read_verilog -sv [file join $root rtl memory micro_hbs_scratchpad64.sv]
synth_design -top micro_hbs_scratchpad64 -part xc7a200tffg1156-2 \
    -mode out_of_context -flatten_hierarchy rebuilt -generic WORDS=$words
create_clock -name clk -period 10.000 [get_ports clk]
opt_design
place_design
phys_opt_design
route_design

report_utilization -file [file join $outdir utilization.rpt]
report_timing_summary -delay_type max -max_paths 10 -file [file join $outdir timing_summary.rpt]
write_checkpoint -force [file join $outdir routed.dcp]
set fp [open [file join $outdir run_identity.txt] w]
puts $fp "scope=scratchpad_storage_proxy"
puts $fp "top=micro_hbs_scratchpad64"
puts $fp "words64=$words"
puts $fp "logical_bytes=[expr {$words * 8}]"
puts $fp "label=$label"
puts $fp "part=xc7a200tffg1156-2"
puts $fp "clock_period_ns=10.000"
puts $fp "tool=[version -short]"
puts $fp "integrated=false"
puts $fp "paper_comparable=false"
close $fp
