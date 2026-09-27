set root [file normalize [file join [file dirname [info script]] ../..]]
cd $root
set tag [lindex $argv 0]
set lanes [lindex $argv 1]
set unroll [lindex $argv 2]
if {![regexp {^[a-zA-Z0-9_.-]+$} $tag] || $lanes ni {1 2 4} || $unroll != 2} {error "tag lanes unroll"}
set directive Default
if {$argc>3} {set directive [lindex $argv 3]}
set flatten rebuilt
if {$argc>4} {set flatten [lindex $argv 4]}
if {$flatten ni {none rebuilt}} {error "invalid flatten policy"}
set started [clock seconds]
set part xc7a200tffg1156-3
set outdir [file join $root build v4.1 $tag]
file mkdir $outdir
set_param general.maxThreads 8
# Processor synthesis sees unconstrained ROM data ports, never initialization.
create_project -in_memory -part $part
set f [open manifests/unified_sources.txt];set sources [split [string trim [read $f]] \n];close $f
foreach source $sources {
    if {$source ni {rtl/top/mhbs_top.sv rtl/memory/mhbs_image_rom.sv}} {read_verilog -sv $source}
}
# Make the internal register timing target visible during synthesis, not
# only in the linked reporting design. ROM initialization remains opaque.
set f [open [file join $outdir synth_clock.xdc] w]
puts $f {create_clock -name clk -period 10.0 [get_ports clk]}
close $f
read_xdc [file join $outdir synth_clock.xdc]
synth_design -top mhbs_processor -part $part -mode out_of_context -flatten_hierarchy $flatten -directive $directive -max_dsp 0 -generic LANES=$lanes -generic UNROLL=$unroll
write_checkpoint -force [file join $outdir processor.dcp]
write_edif -force [file join $outdir mhbs_processor.edf]
write_verilog -force -mode synth_stub [file join $outdir processor_stub.v]
close_project
# Independently synthesize physical ROMs and reset adapter, then link the frozen core.
create_project -in_memory -part $part
read_verilog [file join $outdir processor_stub.v]
read_verilog -sv rtl/memory/mhbs_image_rom.sv
read_verilog -sv rtl/top/mhbs_top.sv
# The generated stub has no parameters. Make a shell copy with its override removed.
set f [open rtl/top/mhbs_top.sv];set shell [read $f];close $f
regsub {mhbs_processor #\([^\n]+\) processor} $shell {mhbs_processor processor} shell
set f [open [file join $outdir shell.sv] w];puts $f $shell;close $f
remove_files rtl/top/mhbs_top.sv
read_verilog -sv [file join $outdir shell.sv]
synth_design -top mhbs_top -part $part -mode out_of_context -flatten_hierarchy none
write_checkpoint -force [file join $outdir shell.dcp]
write_edif -force [file join $outdir mhbs_top.edf]
close_project
read_edif [file join $outdir mhbs_processor.edf]
read_edif [file join $outdir mhbs_top.edf]
link_design -top mhbs_top -part $part -mode out_of_context
if {[llength [get_cells -hier -filter {IS_BLACKBOX == 1}]]} {error "Unresolved black box after link"}
create_clock -name clk -period 10.0 [get_ports clk]
set_property DONT_TOUCH true [get_cells processor]
report_utilization -file [file join $outdir utilization.rpt]
report_utilization -hierarchical -file [file join $outdir utilization_hierarchical.rpt]
report_timing_summary -delay_type max -max_paths 10 -file [file join $outdir timing_summary.rpt]
write_checkpoint -force [file join $outdir post_synth.dcp]
set f [open [file join $outdir rom_cells.tsv] w]
foreach c [get_cells -hier -filter {NAME =~ *rom* && IS_PRIMITIVE == 1}] {puts $f "$c\t[get_property REF_NAME $c]\t[get_property INIT $c]"}
close $f
puts "COMMON_SYNTH_PASS tag=$tag lanes=$lanes unroll=$unroll"

set f [open [file join $outdir synth_seconds.txt] w]
puts $f [expr {[clock seconds]-$started}]
close $f

set f [open [file join $outdir synthesis.json] w]
puts $f "{\"lanes\":$lanes,\"unroll\":$unroll,\"directive\":\"$directive\",\"flatten_hierarchy\":\"$flatten\",\"synthesis_period_ns\":10.0}"
close $f
