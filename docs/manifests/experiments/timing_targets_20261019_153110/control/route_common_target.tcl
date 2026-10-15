# One synthesis and one implementation at the explicitly requested clock.
# No period search or timing exceptions are added.
if {[llength $argv] != 6} {error "Usage: source_root P U output frequency_mhz threads"}
lassign $argv root p u out frequency threads
if {![string is integer -strict $p] || ![string is integer -strict $u] ||
    $p < 1 || $u < 1 || $p*$u > 24 || 24%($p*$u) != 0} {error "Invalid P/U"}
if {![string is double -strict $frequency] || $frequency <= 0} {error "Invalid frequency"}
set root [file normalize $root]
set out [file normalize $out]
set period [format %.9f [expr {1000.0/$frequency}]]
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
    save_json [file join $out stage.json] [format {{"stage":"%s","epoch":%d}} $name [clock seconds]]
    puts "COMMON_TARGET_STAGE $name"
}
stage synthesis
create_project -in_memory -part $part
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
puts $fd "top=common\nPIPELINE=$p\nUNROLL=$u\nfrequency_mhz=$frequency\nperiod_ns=$period\npart=$part\nthreads=$threads\nmode=out_of_context\nkeccak=generic\ntiming_driven=default\nnew_timing_exceptions=none\nimplementation_count=1\nfrequency_search=none\nvivado=[version -short]"
close $fd
synth_design -top common -part $part -mode out_of_context -flatten_hierarchy rebuilt \
    -max_dsp 0 -generic PIPELINE=$p -generic UNROLL=$u
report_utilization -file [file join $out synth utilization.rpt]
report_utilization -hierarchical -file [file join $out synth hierarchical.rpt]
report_timing_summary -report_unconstrained -file [file join $out synth timing.rpt]
write_checkpoint -force [file join $out synth synthesized.dcp]
stage optimization
opt_design
stage placement
place_design
stage physical_optimization
phys_opt_design
stage routing
route_design
set setup [get_timing_paths -delay_type max -max_paths 1]
set hold [get_timing_paths -delay_type min -max_paths 1]
if {![llength $setup] || ![llength $hold]} {error "Missing constrained setup/hold paths"}
set whs [get_property SLACK $hold]
if {$whs < 0} {
    stage hold_repair
    phys_opt_design -hold_fix
    route_design
}
stage reporting
set routed [file join $out route]
set wns [get_property SLACK [get_timing_paths -delay_type max -max_paths 1]]
set whs [get_property SLACK [get_timing_paths -delay_type min -max_paths 1]]
set actual [get_property PERIOD [get_clocks clk]]
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
save_json [file join $out result.json] [format {{"target_frequency_mhz":%.9f,"requested_period_ns":%.9f,"actual_period_ns":%.9f,"wns_ns":%.6f,"whs_ns":%.6f,"drc_errors":%d,"setup_hold_met":%s,"implementation_count":1,"frequency_search":false,"scope":"common OOC internal constrained setup/hold paths"}} $frequency $period $actual $wns $whs $drc_errors [expr {$wns >= 0 && $whs >= 0 ? "true" : "false"}]]
stage complete
puts "COMMON_TARGET_PASS P${p}U${u} frequency_mhz=$frequency wns_ns=$wns whs_ns=$whs"
exit
