set script_dir [file dirname [file normalize [info script]]]
set root [file normalize [file join $script_dir ..]]
set family "xmss"
set variant "stateful_xmss_a200t_3"
set part "xc7a200tffg1156-3"
if {$argc >= 1} { set family [lindex $argv 0] }
if {$argc >= 2} { set variant [lindex $argv 1] }
if {$argc >= 3} { set part [lindex $argv 2] }
if {$family ni {xmss lms}} { error "family must be xmss or lms" }
if {![regexp {^[A-Za-z0-9_.-]+$} $variant]} {
    error "invalid build variant: $variant"
}
if {![regexp {^xc7a200tffg1156-[123]$} $part]} {
    error "unsupported part: $part"
}
set outdir [file normalize [file join $root build vivado $variant]]
file mkdir $outdir
set_param general.maxThreads 24

foreach source {
    rtl/sequencer/uhbs_event_scoreboard.sv
    rtl/sequencer/uhbs_static_task_sequencer.sv
    rtl/hash_lane/uhbs_keccak.sv
    rtl/hash_lane/uhbs_compact_shake_context_lane.sv
    rtl/hash_lane/uhbs_stateful_recipe_lane.sv
    rtl/control/uhbs_stateful_index_guard.sv
    rtl/memory/uhbs_endpoint_scratch256.sv
    rtl/memory/uhbs_full_tree_cache256.sv
    rtl/treehash/uhbs_tree_push_reducer.sv
    rtl/output/uhbs_byte_output_packer.sv
    rtl/top/uhbs_stateful_hbs.sv
    rtl/top/uhbs_xmss_top.sv
    rtl/top/uhbs_lms_top.sv
} {
    read_verilog -sv [file join $root $source]
}

set top [expr {$family eq "xmss"
    ? "uhbs_xmss_top" : "uhbs_lms_top"}]
synth_design -top $top -part $part -mode out_of_context \
    -flatten_hierarchy rebuilt -directive AreaOptimized_high \
    -generic UNROLL=2 -generic PROFILE_ENABLE=0
create_clock -name clk -period 10.000 [get_ports clk]
report_utilization -hierarchical \
    -file [file join $outdir utilization_hierarchical.rpt]
report_utilization -file [file join $outdir utilization.rpt]
report_timing_summary -delay_type max -max_paths 10 \
    -file [file join $outdir timing_summary.rpt]
write_checkpoint -force [file join $outdir post_synth.dcp]
