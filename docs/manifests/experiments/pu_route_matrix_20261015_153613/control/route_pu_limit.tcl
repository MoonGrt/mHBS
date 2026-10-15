# Explicitly requested common-OOC routing. No timing exceptions are introduced.
if {[llength $argv] != 4} {error "Usage: synthesized.dcp output max_implementations initial_period_ns"}
lassign $argv checkpoint out max_implementations initial_period
if {![string is double -strict $initial_period] || $initial_period <= 0} {
    error "initial_period_ns must be positive"
}
set checkpoint [file normalize $checkpoint]
set out [file normalize $out]
file mkdir $out
set_param general.maxThreads 2

proc json_string {value} {
    return "\"[string map [list \\ \\\\ \" \\\" \n \\n \r \\r] $value]\""
}
proc save_json {path value} {
    set fd [open "${path}.tmp" w]
    puts $fd $value
    close $fd
    file rename -force "${path}.tmp" $path
}
proc sta_at {period} {
    create_clock -name clk -period $period [get_ports clk]
    set setup [get_timing_paths -delay_type max -max_paths 1]
    set hold [get_timing_paths -delay_type min -max_paths 1]
    if {![llength $setup] || ![llength $hold]} {error "Missing constrained setup/hold paths"}
    set wns [get_property SLACK $setup]
    set whs [get_property SLACK $hold]
    set actual [get_property PERIOD [get_clocks clk]]
    return [list $actual $wns $whs]
}
proc fixed_route_limit {folder requested} {
    # Binary search the routed netlist, on an absolute 0.1 ns period grid.
    set samples {}
    lassign [sta_at $requested] actual wns whs
    if {$whs < 0} {error "Hold timing still fails after physical hold repair"}
    set high [expr {max(2,int(ceil(($actual-$wns+0.2)*10.0)))}]
    while {1} {
        lassign [sta_at [expr {$high/10.0}]] actual wns whs
        lappend samples [format {{"period_ns":%.6f,"wns_ns":%.6f,"whs_ns":%.6f}} $actual $wns $whs]
        if {$wns >= 0 && $whs >= 0} {break}
        set high [expr {$high+max(2,int(ceil(-$wns*10.0))+1)}]
        if {$high > 1000} {error "No fixed-route closure below 100 ns"}
    }
    set low 1
    lassign [sta_at 0.1] actual wns whs
    lappend samples [format {{"period_ns":%.6f,"wns_ns":%.6f,"whs_ns":%.6f}} $actual $wns $whs]
    if {$wns >= 0 && $whs >= 0} {error "Search lower bound unexpectedly closes"}
    while {$high-$low > 1} {
        set mid [expr {($high+$low)/2}]
        lassign [sta_at [expr {$mid/10.0}]] actual wns whs
        lappend samples [format {{"period_ns":%.6f,"wns_ns":%.6f,"whs_ns":%.6f}} $actual $wns $whs]
        if {$wns >= 0 && $whs >= 0} {set high $mid} else {set low $mid}
    }
    lassign [sta_at [expr {$low/10.0}]] failed_period failed_wns failed_whs
    lassign [sta_at [expr {$high/10.0}]] actual wns whs
    save_json [file join $folder sta_sweep.json] [format {{"step_ns":0.1,"samples":[%s],"closed_period_ns":%.6f,"failing_period_ns":%.6f,"failing_wns_ns":%.6f,"failing_whs_ns":%.6f}} [join $samples ,] $actual $failed_period $failed_wns $failed_whs]
    return [list $actual $wns $whs $failed_period $failed_wns $failed_whs]
}

set requested $initial_period
set tried {}
set attempts {}
set best_period 1000000.0
set best_folder ""
for {set attempt 0} {$attempt < $max_implementations} {incr attempt} {
    set folder [file join $out [format "attempt_%02d_%.6f" $attempt $requested]]
    file mkdir $folder
    lappend tried [format %.6f $requested]
    puts "PU_ROUTE_ATTEMPT_START attempt=$attempt requested_ns=$requested"
    open_checkpoint $checkpoint
    create_clock -name clk -period $requested [get_ports clk]
    opt_design
    place_design
    phys_opt_design
    route_design
    lassign [sta_at $requested] actual initial_wns initial_whs
    if {$initial_whs < 0} {
        phys_opt_design -hold_fix
        route_design
        lassign [sta_at $requested] actual initial_wns initial_whs
    }
    report_utilization -file [file join $folder implementation_utilization.rpt]
    report_timing_summary -report_unconstrained -file [file join $folder implementation_timing.rpt]
    report_route_status -file [file join $folder route_status.rpt]
    write_checkpoint -force [file join $folder implemented.dcp]
    lassign [fixed_route_limit $folder $requested] period wns whs failed_period failed_wns failed_whs
    report_utilization -hierarchical -file [file join $folder hierarchical.rpt]
    report_timing_summary -report_unconstrained -file [file join $folder timing.rpt]
    write_checkpoint -force [file join $folder closed.dcp]
    set item [format {{"attempt":%d,"folder":%s,"implementation_period_ns":%.7f,"implementation_wns_ns":%.6f,"implementation_whs_ns":%.6f,"closed_period_ns":%.6f,"wns_ns":%.6f,"whs_ns":%.6f,"failing_period_ns":%.6f}} $attempt [json_string $folder] $requested $initial_wns $initial_whs $period $wns $whs $failed_period]
    lappend attempts $item
    save_json [file join $out attempts.json] "\{\"attempts\":\[[join $attempts ,]\]\}"
    puts "PU_ROUTE_ATTEMPT_PASS attempt=$attempt closed_ns=$period wns_ns=$wns whs_ns=$whs"
    close_design
    if {$period < $best_period} {set best_period $period;set best_folder $folder}
    # Reimplement near the measured threshold, then probe the adjacent faster grid point.
    set next [format %.6f $best_period]
    if {[lsearch -exact $tried $next] >= 0} {set next [format %.6f [expr {$best_period-0.1}]]}
    if {$next <= 0 || [lsearch -exact $tried $next] >= 0} {break}
    set requested $next
}
if {$best_folder eq ""} {error "No measured route"}
set final [file join $out closed]
file mkdir $final
open_checkpoint [file join $best_folder closed.dcp]
lassign [sta_at $best_period] period wns whs
if {$wns < 0 || $whs < 0} {error "Selected route did not retain setup/hold closure"}
report_utilization -file [file join $final utilization.rpt]
report_utilization -hierarchical -file [file join $final hierarchical.rpt]
report_timing_summary -report_unconstrained -file [file join $final timing.rpt]
report_route_status -file [file join $final route_status.rpt]
report_drc -file [file join $final drc.rpt]
report_clock_interaction -file [file join $final clocks.rpt]
write_checkpoint -force [file join $final routed.dcp]
save_json [file join $final result.json] [format {{"initial_period_ns":%.7f,"period_ns":%.6f,"frequency_mhz":%.9f,"wns_ns":%.6f,"whs_ns":%.6f,"period_grid_ns":0.1,"best_attempt":%s,"attempt_count":%d,"max_implementations":%d,"scope":"common OOC internal constrained paths; best observed placement and fixed-route STA grid threshold"}} $initial_period $period [expr {1000.0/$period}] $wns $whs [json_string $best_folder] [llength $attempts] $max_implementations]
puts "PU_ROUTE_LIMIT_PASS period_ns=$period frequency_mhz=[expr {1000.0/$period}]"
exit
