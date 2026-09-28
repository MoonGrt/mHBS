# One fixed-period internal timing attempt, resumable from an atomic checkpoint.
set source_dcp [file normalize [lindex $argv 0]]
set out [file normalize [lindex $argv 1]]
set period [lindex $argv 2]
set resume [lindex $argv 3]
file mkdir $out
set_param general.maxThreads 8
set started [clock seconds]
proc save_stage {out name period} {
 set pending [file join $out ${name}.pending.dcp]
 set checkpoint [file join $out ${name}.dcp]
 write_checkpoint -force $pending
 file rename -force $pending $checkpoint
 set digest [lindex [exec sha256sum $checkpoint] 0]
 set f [open [file join $out stage.pending.json] w]
 puts $f "{\"stage\":\"$name\",\"period_ns\":$period,\"checkpoint_sha256\":\"$digest\"}"
 close $f
 file rename -force [file join $out stage.pending.json] [file join $out stage.json]
}
if {$resume eq "post_route" || $resume eq "post_place"} {
 open_checkpoint [file join $out ${resume}.dcp]
} else {
 open_checkpoint $source_dcp
}
create_clock -name clk -period $period [get_ports clk]
set_property HD.CLK_SRC BUFGCTRL_X0Y0 [get_ports clk]
set io_inputs [get_ports -filter {DIRECTION == IN && NAME != clk}]
set_input_delay -clock clk -max 0.0 $io_inputs
set_input_delay -clock clk -min 0.0 $io_inputs
set_output_delay -clock clk -max 0.0 [all_outputs]
set_output_delay -clock clk -min 0.0 [all_outputs]
set_false_path -from $io_inputs
set_false_path -to [all_outputs]
if {$resume ni {post_place post_route}} {
 opt_design
 place_design -directive Explore
 phys_opt_design -directive AggressiveExplore
 save_stage $out post_place $period
}
if {$resume ne "post_route"} {
 route_design -directive Explore
 save_stage $out post_route $period
}
set hold_path [lindex [get_timing_paths -delay_type min -max_paths 1] 0]
if {[get_property SLACK $hold_path] < 0} {
 phys_opt_design -aggressive_hold_fix
 route_design -preserve -directive Default
 save_stage $out post_route $period
}
set wns [get_property SLACK [lindex [get_timing_paths -delay_type max -max_paths 1] 0]]
set whs [get_property SLACK [lindex [get_timing_paths -delay_type min -max_paths 1] 0]]
report_utilization -file [file join $out utilization.rpt]
report_utilization -hierarchical -file [file join $out hierarchical.rpt]
report_timing_summary -delay_type min_max -report_unconstrained -max_paths 10 -file [file join $out timing_summary.rpt]
report_route_status -file [file join $out route_status.rpt]
report_drc -file [file join $out drc.rpt]
check_timing -verbose -file [file join $out check_timing.rpt]
write_xdc -force [file join $out constraints.xdc]
source {/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/build/worktrees/ku_matrix_20260927_v1/experiments/v4.2/external_job_message/rom_mapping.tcl}
export_rom_mapping [file join $out initialized_rom.tsv]
set f [open [file join $out clock.pending.json] w]
puts $f "{\"period_ns\":$period,\"wns_ns\":$wns,\"whs_ns\":$whs,\"seconds_this_session\":[expr {[clock seconds]-$started}],\"io_timing_qualified\":false}"
close $f
file rename -force [file join $out clock.pending.json] [file join $out clock.json]
if {$wns <= 0 || $whs < 0} {error "SIGN_SCAN_TIMING_FAILED setup=$wns hold=$whs target=$period"}
puts "SIGN_SCAN_ROUTE_PASS period_ns=$period setup_slack_ns=$wns hold_slack_ns=$whs"
