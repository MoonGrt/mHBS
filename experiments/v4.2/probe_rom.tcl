set root [file normalize [file join [file dirname [info script]] ../..]]
cd $root
set out build/v4.2/rom_probe
file mkdir $out
set_param general.maxThreads 4
create_project -in_memory -part xc7a200tffg1156-3
read_verilog -sv build/v4.2/probe_stub.sv
read_verilog -sv build/v4.2/probe_shell.sv
synth_design -top mhbs_top -part xc7a200tffg1156-3 -mode out_of_context -flatten_hierarchy none
report_utilization -file $out/utilization.rpt
write_checkpoint -force $out/probe.dcp
set f [open $out/cells.tsv w]
foreach c [lsort [get_cells -hier -filter {IS_PRIMITIVE == 1}]] {
 puts $f "CELL\t$c\t[get_property REF_NAME $c]\t[get_property -quiet INIT $c]"
 foreach p [get_pins -of_objects $c] {puts $f "PIN\t$p\t[get_property DIRECTION $p]\t[get_nets -of_objects $p]"}
}
close $f
puts ROM_PROBE_PASS
