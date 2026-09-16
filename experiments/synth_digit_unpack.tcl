set script_dir [file dirname [file normalize [info script]]]
set root [file normalize [file join $script_dir ..]]
set outdir [file normalize [file join $root build vivado digit_unpack]]
file mkdir $outdir

read_verilog -sv [file join $root rtl composer micro_hbs_digit_unpack.sv]
synth_design -top micro_hbs_digit_unpack -part xc7a200tffg1156-2 \
    -flatten_hierarchy rebuilt -mode out_of_context

report_utilization -file [file join $outdir utilization.rpt]
write_checkpoint -force [file join $outdir synthesized.dcp]

set fp [open [file join $outdir run_identity.txt] w]
puts $fp "scope=msb_first_digit_unpack_wiring_only"
puts $fp "top=micro_hbs_digit_unpack"
puts $fp "part=xc7a200tffg1156-2"
puts $fp "tool=[version -short]"
puts $fp "input_bytes=34"
puts $fp "digit_bits=6"
puts $fp "count=33"
puts $fp "implementation_stage=post_synthesis"
puts $fp "paper_comparable=false"
close $fp
