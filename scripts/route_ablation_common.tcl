# One frozen ablation common core, synthesized and routed at the requested clock.
# No frequency search, timing exceptions, or alternative hash mapping is added.
if {[llength $argv] != 6} {
    error "Usage: source_root design backend output frequency_mhz threads"
}
lassign $argv root design backend out frequency threads
if {$design ni {i c t}} {error "design must be i, c or t"}
if {$backend ni {shake sha2}} {error "backend must be shake or sha2"}
if {![string is double -strict $frequency] || $frequency <= 0} {
    error "frequency_mhz must be positive"
}
if {![string is integer -strict $threads] || $threads != 2} {
    error "This comparison requires exactly 2 threads per Vivado"
}
set root [file normalize $root]
set out [file normalize $out]
set part xc7a200tffg1156-3
# Vivado uses a 1 ps period grid. Round toward the faster clock so the
# implemented constraint is never below the explicitly requested frequency.
set target_period [expr {1000.0 / $frequency}]
set period [format %.3f [expr {floor($target_period * 1000.0) / 1000.0}]]
if {$period <= 0} {error "Requested period is below the supported 1 ps grid"}
file mkdir [file join $out synth]
file mkdir [file join $out route]
set_param general.maxThreads $threads

proc save_json {path value} {
    set handle [open "${path}.tmp" w]
    puts $handle $value
    close $handle
    file rename -force "${path}.tmp" $path
}

proc stage {name} {
    global out
    set ::current_stage $name
    save_json [file join $out stage.json] \
        [format {{"stage":"%s","epoch":%d}} $name [clock seconds]]
    puts "ABLATION_COMMON_STAGE $name"
}

stage initialization
try {
    create_project -in_memory -part $part
    set defines [list SYNTHESIS]
    if {$backend eq "sha2"} {lappend defines MHBS_SHA2}
    set_property verilog_define $defines [current_fileset]
    set_property include_dirs [list $root] [current_fileset]
    # i/c instructions.svh uses a project-root relative include path.
    cd $root
    set handle [open [file join $root sources.txt] r]
    set sources [split [read $handle] \n]
    close $handle
    foreach source $sources {
        set source [string trim $source]
        if {$source eq "" || [string match "#*" $source]} {continue}
        read_verilog -sv [file join $root $source]
    }
    set constraint [file join $out target_clock.xdc]
    set handle [open $constraint w]
    puts $handle "create_clock -name clk -period $period \[get_ports clk\]"
    close $handle
    read_xdc $constraint

    set handle [open [file join $out settings.txt] w]
    puts $handle "design=$design\nhash_backend=$backend\nsource_root=$root\ntop=common\nPIPELINE=1\nUNROLL=1\npart=$part\nfrequency_mhz=$frequency\nperiod_ns=$period\nthreads=$threads\nmode=out_of_context\nstatistics=SYNTHESIS\nkeccak=generic\ndefines=[join $defines ,]\nflatten_hierarchy=rebuilt\nmax_dsp=0\ntiming_driven=default\nplace_directive=AltSpreadLogic_high\nphys_opt_directive=Default\nroute_directive=Explore\nimplementation_flow=congestion_spread_v1\nnew_timing_exceptions=none\nimplementation_count=1\nfrequency_search=none\narea_scope=common; ROM and signature cache excluded\ntiming_scope=OOC internal constrained setup/hold paths\nvivado=[version -short]"
    close $handle

    stage synthesis
    synth_design -top common -part $part -mode out_of_context \
        -flatten_hierarchy rebuilt -max_dsp 0 \
        -generic PIPELINE=1 -generic UNROLL=1
    report_utilization -file [file join $out synth utilization.rpt]
    report_utilization -hierarchical -file [file join $out synth hierarchical.rpt]
    report_timing_summary -report_unconstrained -file [file join $out synth timing.rpt]
    report_timing -delay_type max -max_paths 20 -nworst 2 -input_pins -nets \
        -file [file join $out synth critical_paths.rpt]
    source [file join $root scripts audit_debug.tcl]
    mhbs_audit_debug [file join $out synth debug_audit.json]
    write_checkpoint -force [file join $out synth synthesized.dcp]

    stage optimization
    opt_design
    stage placement
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
    if {![llength $setup] || ![llength $hold]} {
        error "Missing constrained setup/hold paths after routing"
    }
    if {[get_property SLACK $hold] < 0} {
        stage hold_repair
        phys_opt_design -hold_fix
        route_design -directive Explore
    }

    stage reporting
    set routed [file join $out route]
    set setup [get_timing_paths -delay_type max -max_paths 1]
    set hold [get_timing_paths -delay_type min -max_paths 1]
    if {![llength $setup] || ![llength $hold]} {
        error "Missing constrained setup/hold paths in final implementation"
    }
    set wns [get_property SLACK $setup]
    set whs [get_property SLACK $hold]
    set actual [get_property PERIOD [get_clocks clk]]
    if {![string is double -strict $wns] || ![string is double -strict $whs] ||
        ![string is double -strict $actual] || $actual <= 0} {
        error "Invalid final setup/hold slack or clock period"
    }
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
    set drc_errors [llength [get_drc_violations -quiet \
        -filter {SEVERITY == Error || SEVERITY == "Critical Warning"}]]
    set setup_hold_met [expr {$wns >= 0 && $whs >= 0}]
    set accepted [expr {$setup_hold_met && $fully_routed && !$route_errors &&
        $drc_errors == 0 && $actual <= $target_period + 1.0e-9}]
    write_checkpoint -force [file join $routed routed.dcp]
    save_json [file join $out result.json] [format \
        {{"design":"%s","hash_backend":"%s","configuration":"P1U1","target_frequency_mhz":%.9f,"requested_period_ns":%.9f,"actual_period_ns":%.9f,"wns_ns":%.6f,"whs_ns":%.6f,"setup_hold_met":%s,"fully_routed":%s,"route_has_errors":%s,"drc_errors":%d,"accepted_frequency":%s,"implementation_flow":"congestion_spread_v1","implementation_count":1,"frequency_search":false,"scope":"common OOC internal constrained setup/hold paths"}} \
        $design $backend $frequency $period $actual $wns $whs \
        [expr {$setup_hold_met ? "true" : "false"}] \
        [expr {$fully_routed ? "true" : "false"}] \
        [expr {$route_errors ? "true" : "false"}] $drc_errors \
        [expr {$accepted ? "true" : "false"}]]
    stage complete
    puts "ABLATION_COMMON_COMPLETE design=$design backend=$backend P1U1 frequency_mhz=$frequency accepted_frequency=$accepted wns_ns=$wns whs_ns=$whs"
} on error {message options} {
    set failed_stage $::current_stage
    save_json [file join $out failure.json] [format \
        {{"design":"%s","hash_backend":"%s","failed_stage":"%s","diagnostic_only":true,"accepted_frequency":false,"implementation_flow":"congestion_spread_v1"}} \
        $design $backend $failed_stage]
    set handle [open [file join $out failure.txt] w]
    puts $handle "Incomplete or illegal implementation; diagnostic only.\nStage: $failed_stage\n$message"
    if {[dict exists $options -errorinfo]} {puts $handle [dict get $options -errorinfo]}
    close $handle
    set failed [file join $out route]
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
            puts "ABLATION_COMMON_DIAGNOSTIC_UNAVAILABLE: [lindex $command 0]: $report_error"
        }
    }
    stage failed
    puts stderr "ABLATION_COMMON_FAILED design=$design backend=$backend stage=$failed_stage: $message"
    exit 1
}
exit
