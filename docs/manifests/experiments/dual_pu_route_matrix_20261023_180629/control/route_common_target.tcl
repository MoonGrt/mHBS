set hash_backend shake
if {[info exists ::env(HASH_BACKEND)]} {set hash_backend $::env(HASH_BACKEND)}
if {$hash_backend ni {shake sha2}} {error "HASH_BACKEND must be shake or sha2"}
# One synthesis and one implementation at the explicitly requested clock.
# No period search or timing exceptions are added.
if {[llength $argv] != 6} {error "Usage: source_root P U output frequency_mhz threads"}
lassign $argv root p u out frequency threads
if {![string is integer -strict $p] || ![string is integer -strict $u] ||
    $p < 1 || $u < 1 || $p*$u > 24 || 24%($p*$u) != 0} {error "Invalid P/U"}
if {![string is double -strict $frequency] || $frequency <= 0} {error "Invalid frequency"}
set root [file normalize $root]
set out [file normalize $out]
# Vivado stores clock periods on a 1 ps grid. Round toward the faster clock so
# a requested 150 MHz cannot become a below-target 149.9925 MHz (6.667 ns).
set period [format %.3f [expr {floor((1000.0/$frequency)*1000.0)/1000.0}]]
if {$period <= 0} {error "Requested period is below the supported 1 ps grid"}
set part xc7a200tffg1156-3
file mkdir [file join $out synth]
file mkdir [file join $out route]
set_param general.maxThreads $threads
proc save_json {path value} {
    set fd [open "${path}.tmp" w]
    puts $fd $value
    close $fd
    file rename -force "${path}.tmp" $path
}
proc stage {name} {
    global out
    set ::current_stage $name
    save_json [file join $out stage.json] [format {{"stage":"%s","epoch":%d}} $name [clock seconds]]
    puts "COMMON_TARGET_STAGE $name"
}
stage synthesis
create_project -in_memory -part $part
set defines [list SYNTHESIS]
if {$hash_backend eq "sha2"} {lappend defines MHBS_SHA2}
set_property verilog_define $defines [current_fileset]
set fd [open [file join $root sources.txt] r]
set sources [split [string trim [read $fd]] \n]
close $fd
foreach source $sources {read_verilog -sv [file join $root $source]}
set constraint [file join $out target_clock.xdc]
set fd [open $constraint w]
puts $fd "create_clock -name clk -period $period \[get_ports clk\]"
close $fd
read_xdc $constraint
set fd [open [file join $out settings.txt] w]
puts $fd "top=common\nPIPELINE=$p\nUNROLL=$u\nfrequency_mhz=$frequency\nperiod_ns=$period\nhash_backend=$hash_backend\npart=$part\nthreads=$threads\nmode=out_of_context\nkeccak=generic\ntiming_driven=default\nplace_directive=AltSpreadLogic_high\nphys_opt_directive=Default\nroute_directive=Explore\nimplementation_flow=congestion_spread_v1\nnew_timing_exceptions=none\nimplementation_count=1\nfrequency_search=none\nvivado=[version -short]"
close $fd
synth_design -top common -part $part -mode out_of_context -flatten_hierarchy rebuilt \
    -max_dsp 0 -generic PIPELINE=$p -generic UNROLL=$u
report_utilization -file [file join $out synth utilization.rpt]
report_utilization -hierarchical -file [file join $out synth hierarchical.rpt]
report_timing_summary -report_unconstrained -file [file join $out synth timing.rpt]
write_checkpoint -force [file join $out synth synthesized.dcp]
try {
    stage optimization
    opt_design
    stage placement
    # Use the same congestion-aware strategy for every backend and P/U.
    place_design -directive AltSpreadLogic_high
    report_design_analysis -congestion -min_congestion_level 3 \
        -file [file join $out route placed_congestion.rpt]
    write_checkpoint -force [file join $out placed.dcp]
    stage physical_optimization
    phys_opt_design
    stage routing
    route_design -directive Explore
    set setup [get_timing_paths -delay_type max -max_paths 1]
    set hold [get_timing_paths -delay_type min -max_paths 1]
    if {![llength $setup] || ![llength $hold]} {error "Missing constrained setup/hold paths"}
    set whs [get_property SLACK $hold]
    if {$whs < 0} {
        stage hold_repair
        phys_opt_design -hold_fix
        route_design -directive Explore
    }
} on error {message options} {
    # Preserve illegal/partial routes for diagnosis. Each report is independent;
    # none of these files constitutes a successful physical implementation.
    set failed_stage $::current_stage
    set failed [file join $out route]
    save_json [file join $out failure.json] [format \
        {{"failed_stage":"%s","diagnostic_only":true,"accepted_frequency":false,"implementation_flow":"congestion_spread_v1"}} $failed_stage]
    set fd [open [file join $out failure.txt] w]
    puts $fd "Partial/illegal implementation: diagnostic only.\nStage: $failed_stage\n$message"
    if {[dict exists $options -errorinfo]} {puts $fd [dict get $options -errorinfo]}
    close $fd
    foreach command [list \
        [list report_utilization -file [file join $failed failed_utilization.rpt]] \
        [list report_utilization -hierarchical -file [file join $failed failed_hierarchical.rpt]] \
        [list report_timing_summary -report_unconstrained -file [file join $failed failed_timing.rpt]] \
        [list report_timing -delay_type max -max_paths 20 -nworst 2 -input_pins -nets -file [file join $failed failed_critical_paths.rpt]] \
        [list report_route_status -file [file join $failed failed_route_status.rpt]] \
        [list report_design_analysis -congestion -min_congestion_level 3 -file [file join $failed failed_congestion.rpt]] \
        [list report_drc -file [file join $failed failed_drc.rpt]] \
        [list write_checkpoint -force [file join $out failed_partial.dcp]]] {
        if {[catch {uplevel #0 $command} report_error]} {
            puts "COMMON_TARGET_DIAGNOSTIC_UNAVAILABLE: [lindex $command 0]: $report_error"
        }
    }
    stage failed
    return -options $options $message
}
stage reporting
set routed [file join $out route]
set wns [get_property SLACK [get_timing_paths -delay_type max -max_paths 1]]
set whs [get_property SLACK [get_timing_paths -delay_type min -max_paths 1]]
set actual [get_property PERIOD [get_clocks clk]]
set fully_routed [report_route_status -boolean_check ROUTED_FULLY]
set route_errors [report_route_status -boolean_check ERRORS_IN_ROUTES]
report_utilization -file [file join $routed utilization.rpt]
report_utilization -hierarchical -file [file join $routed hierarchical.rpt]
report_timing_summary -report_unconstrained -file [file join $routed timing.rpt]
report_timing -delay_type max -max_paths 20 -nworst 2 -input_pins -nets \
    -file [file join $routed critical_paths.rpt]
report_route_status -file [file join $routed route_status.rpt]
report_drc -file [file join $routed drc.rpt]
report_clock_interaction -file [file join $routed clocks.rpt]
set drc_errors [llength [get_drc_violations -quiet -filter {SEVERITY == Error || SEVERITY == "Critical Warning"}]]
write_checkpoint -force [file join $routed routed.dcp]
save_json [file join $out result.json] [format {{"target_frequency_mhz":%.9f,"requested_period_ns":%.9f,"actual_period_ns":%.9f,"wns_ns":%.6f,"whs_ns":%.6f,"drc_errors":%d,"setup_hold_met":%s,"fully_routed":%s,"route_has_errors":%s,"implementation_flow":"congestion_spread_v1","implementation_count":1,"frequency_search":false,"scope":"common OOC internal constrained setup/hold paths"}} $frequency $period $actual $wns $whs $drc_errors [expr {$wns >= 0 && $whs >= 0 ? "true" : "false"}] [expr {$fully_routed ? "true" : "false"}] [expr {$route_errors ? "true" : "false"}]]
stage complete
puts "COMMON_TARGET_PASS P${p}U${u} frequency_mhz=$frequency wns_ns=$wns whs_ns=$whs"
exit
