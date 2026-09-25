# Local area screening; all ports are arbitrary, never image constants.
set root [file normalize [file join [file dirname [info script]] ../..]]
cd $root
set top [lindex $argv 0]
set tag [lindex $argv 1]
set depth [lindex $argv 2]
set flatten [lindex $argv 3]
if {$flatten eq ""} {set flatten rebuilt}
set directive [lindex $argv 4]
if {$directive eq ""} {set directive AreaOptimized_high}
set outdir [file join $root build v4.1 units $tag]
file mkdir $outdir
set started [clock seconds]
set_param general.maxThreads 4
create_project -in_memory -part xc7a200tffg1156-3
switch $top {
    uhbs_recipe_lane {
        foreach f {uhbs_keccak uhbs_compact_shake_context_lane uhbs_recipe_lane} {read_verilog -sv rtl/hash_lane/$f.sv}
        set params {N=32 DIGEST_BYTES=49 INDEX_BITS=8 UNROLL=2 MAX_MESSAGE_BYTES=87}
    }
    uhbs_value_store {
        read_verilog -sv rtl/memory/uhbs_value_store.sv
        set params [list WIDTH=256 ADDRESS_BITS=8 DEPTH=$depth]
    }
    uhbs_root_store {
        read_verilog -sv rtl/memory/uhbs_root_store.sv
        set params {}
    }
    uhbs_program_sequencer {
        read_verilog -sv rtl/sequencer/uhbs_event_scoreboard.sv
        read_verilog -sv rtl/sequencer/uhbs_program_sequencer.sv
        set params {}
    }
    uhbs_image_rom {
        read_verilog -sv rtl/memory/uhbs_image_rom.sv
        if {$depth==1} {set params {WIDTH=128 ADDRESS_BITS=6 PORTS=1 PACKING=1}} elseif {$depth==2} {set params {WIDTH=64 ADDRESS_BITS=7 PORTS=2 PACKING=2}} else {error "ROM packing must be 1 or 2"}
    }
    default {error "Unknown local unit $top"}
}
synth_design -top $top -mode out_of_context -flatten_hierarchy $flatten -directive $directive -max_dsp 0 -generic $params
create_clock -name clk -period 10 [get_ports clk]
report_utilization -file [file join $outdir utilization.rpt]
report_utilization -hierarchical -file [file join $outdir utilization_hierarchical.rpt]
report_timing_summary -max_paths 5 -file [file join $outdir timing_summary.rpt]
write_checkpoint -force [file join $outdir post_synth.dcp]
set f [open [file join $outdir elapsed_seconds.txt] w]
puts $f [expr {[clock seconds]-$started}]
close $f
puts "UNIT_SYNTH_PASS $tag"
