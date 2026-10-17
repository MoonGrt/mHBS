# Source-equivalent K1U1 common-core OOC synthesis. No placement/routing.
set out [file normalize [lindex $argv 0]]
file mkdir $out
set part xc7a200tffg1156-3
set_param general.maxThreads 2
create_project -in_memory -part $part
set f [open sources.txt];set sources [split [string trim [read $f]] \n];close $f
foreach path $sources {
    if {$path ne "rtl/top/top.sv" && $path ne ""} {read_verilog -sv $path}
}
set f [open [file join $out clock.xdc] w]
puts $f {create_clock -name clk -period 10.0 [get_ports clk]}
close $f
read_xdc [file join $out clock.xdc]
synth_design -top common -part $part -mode out_of_context -flatten_hierarchy rebuilt -max_dsp 0 -generic LANES=1 -generic UNROLL=1 -generic PROFILE_ENABLE=0
report_utilization -file [file join $out utilization.rpt]
report_utilization -hierarchical -file [file join $out hierarchical.rpt]
report_timing_summary -max_paths 10 -file [file join $out timing.rpt]
set f [open [file join $out timing.json] w]
set path [get_timing_paths -max_paths 1]
if {[llength $path]} {
    set slack [get_property SLACK $path]
    set delay [get_property DATAPATH_DELAY $path]
    puts $f "{\"measurement\":\"post_synthesis_estimate\",\"clock_period_ns\":10.0,\"worst_slack_ns\":$slack,\"data_path_delay_ns\":$delay,\"routed_frequency_measured\":false}"
} else {
    puts $f {{"measurement":"post_synthesis_estimate","clock_period_ns":10.0,"worst_slack_ns":null,"data_path_delay_ns":null,"routed_frequency_measured":false}}
}
close $f
set redundant {}
foreach cell [get_cells -hier -filter {IS_PRIMITIVE == 1}] {
    if {[string match FD* [get_property REF_NAME $cell]] && [regexp {(boot_cycles|keygen_cycles|sign_cycles|cycles|hash_count|permutation_count|macro_count|macro_busy_cycles|macro_hashes)_reg} $cell]} {lappend redundant $cell}
}
if {[llength $redundant]} {error "unpruned statistic registers: $redundant"}
set f [open [file join $out pruning_audit.json] w]
puts $f {{"passed":true,"profile_enable":false,"statistic_registers":0,"method":"actual primitive FF name audit"}}
close $f
write_checkpoint -force [file join $out common.dcp]
puts MHBS_COMMON_SYNTH_PASS
exit
