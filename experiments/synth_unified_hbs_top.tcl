set script_dir [file dirname [file normalize [info script]]]
set root [file normalize [file join $script_dir ..]]
set variant "unified_hbs_a200t_3"
set part "xc7a200tffg1156-3"
if {$argc >= 1} { set variant [lindex $argv 0] }
if {$argc >= 2} { set part [lindex $argv 1] }
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
    rtl/sequencer/micro_hbs_event_scoreboard.sv
    rtl/sequencer/micro_hbs_static_task_sequencer.sv
    rtl/sequencer/micro_hbs_unified_program_rom.sv
    rtl/sequencer/micro_hbs_unified_task_sequencer.sv
    rtl/hash_lane/micro_hbs_keccak_round_explicit.sv
    rtl/hash_lane/micro_hbs_compact_shake_context_lane.sv
    rtl/hash_lane/micro_hbs_stateful_recipe_lane.sv
    rtl/hash_lane/micro_hbs_recipe_lane_controller.sv
    rtl/hash_lane/micro_hbs_shared_recipe_fabric.sv
    rtl/control/micro_hbs_stateful_index_guard.sv
    rtl/memory/micro_hbs_endpoint_scratch256.sv
    rtl/memory/micro_hbs_full_tree_cache256.sv
    rtl/memory/micro_hbs_local_value_memories.sv
    rtl/treehash/micro_hbs_tree_push_reducer.sv
    rtl/output/micro_hbs_byte_output_packer.sv
    rtl/top/micro_hbs_horizontal_hbs_top.sv
    rtl/top/micro_hbs_horizontal_stateful_hbs_top.sv
    rtl/top/micro_hbs_unified_top.sv
} {
    read_verilog -sv [file join $root $source]
}

synth_design -top micro_hbs_unified_top -part $part -mode out_of_context \
    -flatten_hierarchy rebuilt -directive AreaOptimized_high \
    -generic UNROLL=2 -generic PROFILE_ENABLE=0
create_clock -name clk -period 10.000 [get_ports clk]
report_utilization -hierarchical \
    -file [file join $outdir utilization_hierarchical.rpt]
report_utilization -file [file join $outdir utilization.rpt]
report_timing_summary -delay_type max -max_paths 10 \
    -file [file join $outdir timing_summary.rpt]
write_checkpoint -force [file join $outdir post_synth.dcp]
