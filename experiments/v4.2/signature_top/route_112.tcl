# Fixed-frequency top-level route. Never relax the final clock.
lassign $argv source_dcp out resume_stage
set_param general.maxThreads 8
file mkdir $out
proc checkpoint {path} {
    write_checkpoint -force $path
    set f [open "${path}.sha256" w]
    puts $f [lindex [exec sha256sum $path] 0]
    close $f
}
open_checkpoint $source_dcp
create_clock -name clk -period 8.928 [get_ports clk]
set_property HD.CLK_SRC BUFGCTRL_X0Y0 [get_ports clk]
set inputs [get_ports -filter {DIRECTION == IN && NAME != clk}]
set_input_delay -clock clk -max 0 $inputs
set_input_delay -clock clk -min 0 $inputs
set_output_delay -clock clk -max 0 [all_outputs]
set_output_delay -clock clk -min 0 [all_outputs]
# Includes all internal common/shell/storage paths. I/O requires board constraints.
set_false_path -from $inputs
set_false_path -to [all_outputs]
if {$resume_stage eq "synthesis"} {
    opt_design
    place_design -directive Explore
    phys_opt_design -directive AggressiveExplore
    checkpoint [file join $out post_place.dcp]
    report_timing_summary -delay_type min_max -file [file join $out post_place_timing.rpt]
}
if {$resume_stage ne "route"} {
    route_design -directive Explore
    checkpoint [file join $out post_route.dcp]
}
report_utilization -file [file join $out utilization.rpt]
report_utilization -hierarchical -file [file join $out hierarchical.rpt]
report_timing_summary -delay_type min_max -report_unconstrained -max_paths 10 -file [file join $out timing_summary.rpt]
report_timing -delay_type max -max_paths 10 -file [file join $out setup_paths.rpt]
report_timing -delay_type min -max_paths 10 -file [file join $out hold_paths.rpt]
report_route_status -file [file join $out route_status.rpt]
report_drc -file [file join $out drc.rpt]
check_timing -verbose -file [file join $out check_timing.rpt]
write_xdc -force [file join $out constraints.xdc]
source experiments/v4.2/external_job_message/rom_mapping.tcl
export_rom_mapping [file join $out initialized_rom.tsv]
set wns [get_property SLACK [get_timing_paths -delay_type max -max_paths 1]]
set whs [get_property SLACK [get_timing_paths -delay_type min -max_paths 1]]
set period [get_property PERIOD [get_clocks clk]]
set errors [llength [get_drc_violations -quiet -filter {SEVERITY == Error}]]
set f [open [file join $out timing.json] w]
puts $f "{\"period_ns\":$period,\"wns_ns\":$wns,\"whs_ns\":$whs,\"drc_errors\":$errors,\"io_timing_qualified\":false}"
close $f
puts "SIGNATURE_TOP_ROUTE_FINISHED setup=$wns hold=$whs period=$period"
exit
