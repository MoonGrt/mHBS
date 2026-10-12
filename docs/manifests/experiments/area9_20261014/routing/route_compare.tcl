# Route an already frozen common netlist; never add timing exceptions.
if {[llength $argv]!=2} {error "Usage: checkpoint output"}
lassign $argv checkpoint out
set checkpoint [file normalize $checkpoint]
set out [file normalize $out]
file mkdir $out
set_param general.maxThreads 2
proc attempt {checkpoint out period} {
    open_checkpoint $checkpoint
    create_clock -name clk -period $period [get_ports clk]
    opt_design
    place_design
    phys_opt_design
    route_design
    set folder [file join $out route_[format %.6f $period]]
    file mkdir $folder
    report_utilization -file [file join $folder utilization.rpt]
    report_timing_summary -file [file join $folder timing.rpt]
    report_route_status -file [file join $folder route_status.rpt]
    write_checkpoint -force [file join $folder routed.dcp]
    set wns [get_property SLACK [get_timing_paths -delay_type max -max_paths 1]]
    set whs [get_property SLACK [get_timing_paths -delay_type min -max_paths 1]]
    close_design
    return [list $folder $wns $whs]
}
set start 6.666667
set period $start
set closed 0
for {set n 0} {$n<5} {incr n} {
    lassign [attempt $checkpoint $out $period] folder wns whs
    if {$wns>=0 && $whs>=0} {set closed 1;break}
    set period [expr {$period+max(0.1,ceil(-$wns/0.1)*0.1+0.1)}]
}
if {!$closed} {error "No setup/hold closure after measured-delay relaxation"}
open_checkpoint [file join $folder routed.dcp]
set samples {}
for {set tick 0} {$tick<=300} {incr tick} {
    set period [expr {$start+$tick*0.1}]
    create_clock -name clk -period $period [get_ports clk]
    set wns [get_property SLACK [get_timing_paths -delay_type max -max_paths 1]]
    set whs [get_property SLACK [get_timing_paths -delay_type min -max_paths 1]]
    set actual [get_property PERIOD [get_clocks clk]]
    lappend samples [format {{"requested_period_ns":%.7f,"period_ns":%.7f,"wns_ns":%.7f,"whs_ns":%.7f}} $period $actual $wns $whs]
    if {$wns>=0 && $whs>=0} {break}
}
set handle [open [file join $out sta_sweep.json] w]
puts $handle "\{\"rows\":\[[join $samples ,]\]\}"
close $handle
if {$tick>300} {error "Fixed-route STA sweep did not close"}
set final [file join $out closed]
file mkdir $final
report_utilization -file [file join $final utilization.rpt]
report_utilization -hierarchical -file [file join $final hierarchical.rpt]
report_timing_summary -file [file join $final timing.rpt]
report_route_status -file [file join $final route_status.rpt]
report_drc -file [file join $final drc.rpt]
report_clock_interaction -file [file join $final clocks.rpt]
write_checkpoint -force [file join $final routed.dcp]
set handle [open [file join $final result.txt] w]
puts $handle "period_ns=$actual\nwns_ns=$wns\nwhs_ns=$whs\nphysical_checkpoint=[file join $folder routed.dcp]"
close $handle
puts "COMMON_ROUTE_PASS period_ns=$actual"
exit
