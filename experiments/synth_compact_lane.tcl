set script_dir [file dirname [file normalize [info script]]]
set root [file normalize [file join $script_dir ..]]
set outdir [file normalize [file join $root build vivado compact_lane_a200t_3]]
file mkdir $outdir
set_param general.maxThreads 24
read_verilog -sv [file join $root rtl/hash_lane/micro_hbs_keccak_round_explicit.sv]
read_verilog -sv [file join $root rtl/hash_lane/micro_hbs_compact_shake_context_lane.sv]
synth_design -top micro_hbs_compact_shake_context_lane \
    -part xc7a200tffg1156-3 -mode out_of_context -flatten_hierarchy rebuilt \
    -directive AreaOptimized_high -generic UNROLL=2
report_utilization -hierarchical -file [file join $outdir utilization_hierarchical.rpt]
report_utilization -file [file join $outdir utilization.rpt]
write_checkpoint -force [file join $outdir post_synth.dcp]
