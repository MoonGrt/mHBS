# Core-control screening with opaque Hash lanes. All ROM ports remain inputs.
set root [file normalize [file join [file dirname [info script]] ../..]]
cd $root
set tag [lindex $argv 0]
set core_file [lindex $argv 1]
if {$core_file eq ""} {set core_file rtl/top/uhbs_hbs.sv}
set outdir [file join build v4.1 units $tag]
file mkdir $outdir
set_param general.maxThreads 4
set started [clock seconds]
set f [open rtl/hash_lane/uhbs_recipe_lane.sv];set lane [read $f];close $f
set end [string first ");" $lane]
set header [string range $lane 0 [expr {$end+1}]]
regsub {module uhbs_recipe_lane} $header {(* black_box="yes" *) module uhbs_recipe_lane} header
set f [open [file join $outdir lane_stub.sv] w];puts $f "$header\nendmodule";close $f
create_project -in_memory -part xc7a200tffg1156-3
read_verilog -sv [file join $outdir lane_stub.sv]
set f [open manifests/unified_sources.txt];set sources [split [string trim [read $f]] \n];close $f
foreach source $sources {
    if {[string match rtl/hash_lane/* $source] || [string match rtl/top/* $source] || $source eq "rtl/memory/uhbs_image_rom.sv"} {continue}
    read_verilog -sv $source
}
read_verilog -sv $core_file
set f [open [file join $outdir clock.xdc] w];puts $f {create_clock -name clk -period 10 [get_ports clk]};close $f
read_xdc [file join $outdir clock.xdc]
synth_design -top uhbs_hbs -mode out_of_context -flatten_hierarchy rebuilt -directive Default -generic LANES=2 -generic UNROLL=2 -generic PROFILE_ENABLE=1
report_utilization -file [file join $outdir utilization.rpt]
report_timing_summary -max_paths 5 -file [file join $outdir timing_summary.rpt]
write_checkpoint -force [file join $outdir post_synth.dcp]
set f [open [file join $outdir elapsed_seconds.txt] w];puts $f [expr {[clock seconds]-$started}];close $f
puts "CONTROL_SYNTH_PASS $tag"
