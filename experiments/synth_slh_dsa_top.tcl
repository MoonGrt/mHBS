set script_dir [file dirname [file normalize [info script]]]
set root [file normalize [file join $script_dir ..]]
set variant "slh_dsa_full"
if {$argc >= 1} {
    set variant [lindex $argv 0]
}
if {![regexp {^[A-Za-z0-9_.-]+$} $variant]} {
    error "invalid build variant: $variant"
}
set outdir [file normalize [file join $root build vivado $variant]]
file mkdir $outdir
set_param general.maxThreads 8

read_verilog -sv [file join $root rtl sequencer micro_hbs_program_store.sv]
read_verilog -sv [file join $root rtl sequencer micro_hbs_sequencer.sv]
read_verilog -sv [file join $root rtl composer micro_hbs_layout_descriptor_store.sv]
read_verilog -sv [file join $root rtl composer micro_hbs_layout_component_store.sv]
read_verilog -sv [file join $root rtl hash_lane micro_hbs_keccak_f1600.sv]
read_verilog -sv [file join $root rtl hash_lane micro_hbs_shake256_single_block.sv]
read_verilog -sv [file join $root rtl hash_lane micro_hbs_shake256_stream.sv]
read_verilog -sv [file join $root rtl composer micro_hbs_rate_append64.sv]
read_verilog -sv [file join $root rtl composer micro_hbs_rate_append128.sv]
read_verilog -sv [file join $root rtl composer micro_hbs_hash_feedback_cache.sv]
read_verilog -sv [file join $root rtl composer micro_hbs_descriptor_shake_composer.sv]
read_verilog -sv [file join $root rtl memory micro_hbs_scratchpad64.sv]
read_verilog -sv [file join $root rtl memory micro_hbs_scratchpad64_banked.sv]
read_verilog -sv [file join $root rtl memory micro_hbs_scratch_bitfield_load.sv]
read_verilog -sv [file join $root rtl memory micro_hbs_bitfield_load_adapter.sv]
read_verilog -sv [file join $root rtl composer micro_hbs_layout_expr.sv]
read_verilog -sv [file join $root rtl memory micro_hbs_expr_load_adapter.sv]
read_verilog -sv [file join $root rtl composer micro_hbs_base_w_checksum.sv]
read_verilog -sv [file join $root rtl memory micro_hbs_base_w_load_adapter.sv]
read_verilog -sv [file join $root rtl memory micro_hbs_wide_shift_load_adapter.sv]
read_verilog -sv [file join $root rtl agu micro_hbs_affine_agu.sv]
read_verilog -sv [file join $root rtl memory micro_hbs_data_descriptor_store.sv]
read_verilog -sv [file join $root rtl memory micro_hbs_address_binding_store.sv]
read_verilog -sv [file join $root rtl memory micro_hbs_scratch_load.sv]
read_verilog -sv [file join $root rtl memory micro_hbs_scratch_alu.sv]
read_verilog -sv [file join $root rtl output micro_hbs_output_stream.sv]
read_verilog -sv [file join $root rtl memory micro_hbs_data_engine.sv]
read_verilog -sv [file join $root rtl treehash micro_hbs_treehash_min_dynamic.sv]
read_verilog -sv [file join $root rtl treehash micro_hbs_slh_dsa_tree_parent.sv]
read_verilog -sv [file join $root rtl treehash micro_hbs_slh_dsa_tree_adapter.sv]
read_verilog -sv [file join $root rtl top micro_hbs_slh_dsa_job_stream_loader.sv]
read_verilog -sv [file join $root rtl top micro_hbs_slh_dsa_top.sv]

# Measure the complete no-DMA Sign datapath with the capacity used by the
# verified 144-word program and 121-component layout image.
synth_design -top micro_hbs_slh_dsa_top \
    -part xc7a200tffg1156-2 -mode out_of_context -flatten_hierarchy rebuilt \
    -generic PROGRAM_WORDS=256 -generic COMPONENT_WORDS=128 -generic UNROLL=2
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
puts $fp "scope=no_dma_complete_slh_dsa_shake_128f_sign"
puts $fp "variant=$variant"
puts $fp "top=micro_hbs_slh_dsa_top"
puts $fp "part=xc7a200tffg1156-2"
puts $fp "clock_period_ns=10.000"
puts $fp "tool=[version -short]"
puts $fp "unroll=2"
puts $fp "program_words=256"
puts $fp "component_words=128"
puts $fp "scratch_words_64bit=1024"
puts $fp "maximum_message_bytes=1024"
puts $fp "hash_lanes_effective=2"
puts $fp "dma=false"
puts $fp "measured_function=complete_deterministic_sign"
puts $fp "paper_comparable=false"
close $fp
