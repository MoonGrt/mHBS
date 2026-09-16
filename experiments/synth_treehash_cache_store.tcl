if {$argc != 3} {
    error "usage: synth_treehash_cache_store.tcl <cache_mode> <subtree_height> <label>"
}
set cache_mode [lindex $argv 0]
set subtree_height [lindex $argv 1]
set label [lindex $argv 2]
set script_dir [file dirname [file normalize [info script]]]
set root [file normalize [file join $script_dir ..]]
set outdir [file normalize [file join $root build vivado treehash_cache_$label]]
file mkdir $outdir

read_verilog -sv [file join $root rtl treehash micro_hbs_treehash_cache_store.sv]
synth_design -top micro_hbs_treehash_cache_store -part xc7a200tffg1156-2 \
    -mode out_of_context -flatten_hierarchy rebuilt \
    -generic TREE_HEIGHT=10 -generic CACHE_MODE=$cache_mode \
    -generic SUBTREE_HEIGHT=$subtree_height
create_clock -name clk -period 10.000 [get_ports clk]
opt_design
place_design
phys_opt_design
route_design

report_utilization -file [file join $outdir utilization.rpt]
report_timing_summary -delay_type max -max_paths 10 \
    -file [file join $outdir timing_summary.rpt]
write_checkpoint -force [file join $outdir routed.dcp]

set fp [open [file join $outdir run_identity.txt] w]
puts $fp "scope=treehash_cache_store_only"
puts $fp "top=micro_hbs_treehash_cache_store"
puts $fp "part=xc7a200tffg1156-2"
puts $fp "clock_period_ns=10.000"
puts $fp "tool=[version -short]"
puts $fp "tree_height=10"
puts $fp "cache_mode=$cache_mode"
puts $fp "subtree_height=$subtree_height"
puts $fp "label=$label"
puts $fp "integrated=false"
puts $fp "paper_comparable=false"
close $fp
