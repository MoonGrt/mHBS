# Controller-only comparison with an opaque macro executor and opaque ROM ports.
set root [file normalize [file join [file dirname [info script]] ../..]]
cd $root
set tag [lindex $argv 0]
set processor_file [lindex $argv 1]
if {$processor_file eq ""} {set processor_file rtl/top/uhbs_processor.sv}
set outdir [file join build v4.1 units $tag]
file mkdir $outdir
set_param general.maxThreads 4
set started [clock seconds]
set f [open rtl/top/uhbs_hbs.sv];set core [read $f];close $f
set end [string first ");" $core]
set header [string range $core 0 [expr {$end+1}]]
regsub {module uhbs_hbs} $header {(* black_box="yes" *) module uhbs_hbs} header
set f [open [file join $outdir core_stub.sv] w];puts $f "$header\nendmodule";close $f
create_project -in_memory -part xc7a200tffg1156-3
read_verilog -sv [file join $outdir core_stub.sv]
read_verilog -sv $processor_file
set f [open [file join $outdir clock.xdc] w];puts $f {create_clock -name clk -period 10 [get_ports clk]};close $f
read_xdc [file join $outdir clock.xdc]
synth_design -top uhbs_processor -mode out_of_context -flatten_hierarchy rebuilt -directive Default -generic LANES=2 -generic UNROLL=2
report_utilization -file [file join $outdir utilization.rpt]
report_timing_summary -max_paths 5 -file [file join $outdir timing_summary.rpt]
write_checkpoint -force [file join $outdir post_synth.dcp]
set f [open [file join $outdir elapsed_seconds.txt] w];puts $f [expr {[clock seconds]-$started}];close $f
puts "BOOT_SYNTH_PASS $tag"
