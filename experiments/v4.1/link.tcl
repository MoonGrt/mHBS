# Resume shell/link stages using the frozen processor checkpoint.
set root [file normalize [file join [file dirname [info script]] ../..]]
cd $root
set tag [lindex $argv 0]
if {![regexp {^[a-zA-Z0-9_.-]+$} $tag]} {error "invalid tag"}
set outdir [file join $root build v4.1 $tag]
set part xc7a200tffg1156-3
set_param general.maxThreads 8
open_checkpoint [file join $outdir processor.dcp]
write_edif -force [file join $outdir mhbs_processor.edf]
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
puts "COMMON_LINK_PASS tag=$tag"
