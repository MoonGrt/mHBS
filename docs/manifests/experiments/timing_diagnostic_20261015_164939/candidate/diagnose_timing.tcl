# Relaxed-clock synthesis for locating combinational paths, not Fmax/ATP sign-off.
if {[llength $argv] != 5} {error "Usage: source_root P U output period_ns"}
lassign $argv root p u out period
if {![string is integer -strict $p] || ![string is integer -strict $u] ||
    $p < 1 || $u < 1 || $p*$u > 24 || 24%($p*$u) != 0} {error "Invalid P/U"}
if {![string is double -strict $period] || $period <= 0} {error "Invalid clock period"}
set root [file normalize $root]
set out [file normalize $out]
file mkdir $out
set part xc7a200tffg1156-3
set_param general.maxThreads 2
create_project -in_memory -part $part
set handle [open [file join $root sources.txt] r]
set sources [split [string trim [read $handle]] \n]
close $handle
foreach source $sources {read_verilog -sv [file join $root $source]}
set clock_file [file join $out diagnostic_clock.xdc]
set handle [open $clock_file w]
puts $handle "create_clock -name clk -period $period \[get_ports clk\]"
close $handle
read_xdc $clock_file
set handle [open [file join $out settings.txt] w]
puts $handle "diagnostic_only=1\ntop=common\nPIPELINE=$p\nUNROLL=$u\nperiod_ns=$period\npart=$part\nthreads=2\nmode=out_of_context\nkeccak=generic\ntiming_driven=default\nnew_timing_exceptions=none\nvivado=[version -short]"
close $handle
synth_design -top common -part $part -mode out_of_context -flatten_hierarchy rebuilt \
    -max_dsp 0 -generic PIPELINE=$p -generic UNROLL=$u
report_utilization -file [file join $out utilization.rpt]
report_utilization -hierarchical -file [file join $out hierarchical.rpt]
report_timing_summary -max_paths 10 -file [file join $out timing.rpt]
report_timing -delay_type max -max_paths 20 -nworst 2 -sort_by group -input_pins -nets \
    -file [file join $out critical_paths.rpt]
write_checkpoint -force [file join $out synthesized.dcp]
puts "MHBS_TIMING_DIAGNOSTIC_PASS P${p}U${u} period_ns=$period"
exit
