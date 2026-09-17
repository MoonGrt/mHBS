set script_dir [file dirname [file normalize [info script]]]
set root [file normalize [file join $script_dir ..]]
set outdir [file normalize [file join $root build vivado scratchpad_banked]]
file mkdir $outdir
set_param general.maxThreads 8

read_verilog -sv [file join $root rtl memory micro_hbs_scratchpad64.sv]
read_verilog -sv [file join $root rtl memory micro_hbs_scratchpad64_banked.sv]
synth_design -top micro_hbs_scratchpad64_banked \
    -part xc7a200tffg1156-2 -mode out_of_context \
    -flatten_hierarchy rebuilt -generic WORDS=1024
create_clock -name clk -period 10.000 [get_ports clk]
opt_design
place_design
route_design
report_utilization -file [file join $outdir utilization.rpt]
report_timing_summary -delay_type max -max_paths 5 \
    -file [file join $outdir timing_summary.rpt]
write_checkpoint -force [file join $outdir routed.dcp]
