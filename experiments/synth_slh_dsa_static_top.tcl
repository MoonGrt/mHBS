set script_dir [file dirname [file normalize [info script]]]
set root [file normalize [file join $script_dir ..]]
set variant "slh_dsa_static_full"
if {$argc >= 1} { set variant [lindex $argv 0] }
if {![regexp {^[A-Za-z0-9_.-]+$} $variant]} {
    error "invalid build variant: $variant"
}
set outdir [file normalize [file join $root build vivado $variant]]
file mkdir $outdir
set_param general.maxThreads 8

foreach source {
    rtl/sequencer/micro_hbs_program_store.sv
    rtl/sequencer/micro_hbs_sequencer.sv
    rtl/composer/micro_hbs_layout_descriptor_store.sv
    rtl/composer/micro_hbs_layout_component_store.sv
    rtl/hash_lane/micro_hbs_keccak_f1600.sv
    rtl/hash_lane/micro_hbs_shake256_single_block.sv
    rtl/hash_lane/micro_hbs_shake256_stream.sv
    rtl/composer/micro_hbs_rate_append64.sv
    rtl/composer/micro_hbs_rate_append128.sv
    rtl/composer/micro_hbs_hash_feedback_cache.sv
    rtl/composer/micro_hbs_descriptor_shake_composer.sv
    rtl/memory/micro_hbs_scratchpad64.sv
    rtl/memory/micro_hbs_scratchpad64_banked.sv
    rtl/memory/micro_hbs_scratch_bitfield_load.sv
    rtl/memory/micro_hbs_bitfield_load_adapter.sv
    rtl/composer/micro_hbs_layout_expr.sv
    rtl/memory/micro_hbs_expr_load_adapter.sv
    rtl/composer/micro_hbs_base_w_checksum.sv
    rtl/memory/micro_hbs_base_w_load_adapter.sv
    rtl/memory/micro_hbs_wide_shift_load_adapter.sv
    rtl/agu/micro_hbs_affine_agu.sv
    rtl/memory/micro_hbs_data_descriptor_store.sv
    rtl/memory/micro_hbs_address_binding_store.sv
    rtl/memory/micro_hbs_scratch_load.sv
    rtl/memory/micro_hbs_scratch_alu.sv
    rtl/output/micro_hbs_output_stream.sv
    rtl/memory/micro_hbs_data_engine.sv
    rtl/treehash/micro_hbs_treehash_min_dynamic.sv
    rtl/treehash/micro_hbs_slh_dsa_tree_parent.sv
    rtl/treehash/micro_hbs_slh_dsa_tree_adapter.sv
    rtl/top/micro_hbs_slh_dsa_job_stream_loader.sv
    rtl/top/micro_hbs_slh_dsa_top.sv
    rtl/top/micro_hbs_slh_dsa_static_top.sv
} {
    read_verilog -sv [file join $root $source]
}

synth_design -top micro_hbs_slh_dsa_static_top \
    -part xc7a200tffg1156-2 -mode out_of_context -flatten_hierarchy rebuilt \
    -generic UNROLL=2
create_clock -name clk -period 10.000 [get_ports clk]
opt_design
place_design
phys_opt_design
route_design

report_utilization -file [file join $outdir utilization.rpt]
report_utilization -hierarchical \
    -file [file join $outdir utilization_hierarchical.rpt]
report_timing_summary -delay_type max -max_paths 10 \
    -file [file join $outdir timing_summary.rpt]
write_checkpoint -force [file join $outdir routed.dcp]

set fp [open [file join $outdir run_identity.txt] w]
puts $fp "scope=static_rom_complete_slh_dsa_shake_128f_sign"
puts $fp "variant=$variant"
puts $fp "top=micro_hbs_slh_dsa_static_top"
puts $fp "part=xc7a200tffg1156-2"
puts $fp "clock_period_ns=10.000"
puts $fp "tool=[version -short]"
puts $fp "unroll=2"
puts $fp "program_words_used=160"
puts $fp "component_words_used=110"
puts $fp "scratch_words_64bit=1024"
puts $fp "maximum_message_bytes=1024"
puts $fp "hash_lanes_effective=2"
puts $fp "external_configuration_ports=false"
puts $fp "image_integrity_xor=b93bccd63245d8aa"
puts $fp "validated_sign_cycles=1003278"
puts $fp "measured_function=complete_deterministic_sign"
close $fp
