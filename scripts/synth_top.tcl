set package_root [file normalize [file join [file dirname [info script]] ..]]
cd $package_root
set out [file join $package_root build synth top_P4U1_generic]
file mkdir $out
set part xc7a200tffg1156-3
set_param general.maxThreads 4
create_project -in_memory -part $part
set handle [open sources.txt r]
set sources [split [string trim [read $handle]] \n]
close $handle
foreach source $sources {read_verilog -sv [file join $package_root $source]}
read_xdc [file join $package_root scripts clock.xdc]
# Elaborate the actual top defaults: SLH 128f Sign ROMs, fixed key inputs,
# and the complete signature store. OOC omits pad insertion only.
synth_design -top top -part $part -mode out_of_context \
    -flatten_hierarchy rebuilt -max_dsp 0 \
    -generic PIPELINE=4 -generic UNROLL=1 -generic PROFILE_ENABLE=0 \
    -generic SIGNATURE_STORE_ENABLE=1
report_utilization -file [file join $out top_utilization.rpt]
report_utilization -hierarchical -file [file join $out top_hierarchical.rpt]
report_timing_summary -file [file join $out top_timing.rpt]
write_checkpoint -force [file join $out top_synth.dcp]
puts "MHBS_TOP_SYNTH_PASS P4U1 PROFILE_ENABLE=0 SIGNATURE_STORE_ENABLE=1"
exit
