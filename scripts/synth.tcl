# Fixed K1U1 common-core synthesis; no ROM, signature cache, or routing.
set source_root [file normalize [lindex $argv 0]]
set out [file normalize [lindex $argv 1]]
set hash_backend [lindex $argv 2]
if {$hash_backend ne "shake"} {error "ABI4 source supports SHAKE only"}
cd $source_root
file mkdir $out
set part xc7a200tffg1156-3
set_param general.maxThreads 2
create_project -in_memory -part $part
set defines [list SYNTHESIS]
set_property verilog_define $defines [current_fileset]
set handle [open sources.txt r]
set sources [split [string trim [read $handle]] \n]
close $handle
foreach path $sources {
    if {[string trim $path] ne ""} {read_verilog -sv [file join $source_root $path]}
}
set handle [open [file join $out clock.xdc] w]
puts $handle {create_clock -name clk -period 10.0 [get_ports clk]}
close $handle
read_xdc [file join $out clock.xdc]
synth_design -top common -part $part -mode out_of_context -flatten_hierarchy rebuilt -max_dsp 0 \
    -generic LANES=1 -generic UNROLL=1 -generic PROFILE_ENABLE=0
report_utilization -file [file join $out utilization.rpt]
report_utilization -hierarchical -file [file join $out hierarchical.rpt]
report_timing_summary -max_paths 10 -file [file join $out timing.rpt]
set handle [open [file join $out timing.json] w]
set path [get_timing_paths -max_paths 1]
if {[llength $path]} {
    set slack [get_property SLACK $path]
    set delay [get_property DATAPATH_DELAY $path]
    puts $handle "{\"measurement\":\"post_synthesis_estimate\",\"clock_period_ns\":10.0,\"worst_slack_ns\":$slack,\"data_path_delay_ns\":$delay,\"routed_frequency_measured\":false}"
} else {
    puts $handle {{"measurement":"post_synthesis_estimate","clock_period_ns":10.0,"worst_slack_ns":null,"data_path_delay_ns":null,"routed_frequency_measured":false}}
}
close $handle
set redundant {}
foreach cell [get_cells -hier -filter {IS_PRIMITIVE == 1}] {
    if {[string match FD* [get_property REF_NAME $cell]] &&
        [regexp {(boot_cycles|keygen_cycles|sign_cycles|cycles|hash_count|permutation_count)_reg} $cell]} {
        lappend redundant $cell
    }
}
if {[llength $redundant]} {error "Unpruned statistics: $redundant"}
set handle [open [file join $out pruning_audit.json] w]
puts $handle {{"passed":true,"profile_enable":false,"statistic_registers":0,"method":"actual primitive FF name audit"}}
close $handle
write_checkpoint -force [file join $out common.dcp]
puts "MHBS_SYNTH_PASS K1U1 backend=$hash_backend period_ns=10.0"
exit
