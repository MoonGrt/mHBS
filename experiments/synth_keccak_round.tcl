set script_dir [file dirname [file normalize [info script]]]
set root [file normalize [file join $script_dir ..]]
set outdir [file normalize [file join $root build vivado keccak_round_a200t_3]]
file mkdir $outdir
set_param general.maxThreads 24
read_verilog -sv [file join $root rtl/hash_lane/uhbs_keccak.sv]
synth_design -top uhbs_keccak -part xc7a200tffg1156-3 \
    -mode out_of_context -flatten_hierarchy rebuilt -directive AreaOptimized_high
report_utilization -file [file join $outdir utilization.rpt]
write_checkpoint -force [file join $outdir post_synth.dcp]
