# Reproduce the common-core OOC implementation without timing exceptions.
if {[llength $argv]!=2} {error "Usage: implement_p4.tcl source_root output_directory"}
set source_root [file normalize [lindex $argv 0]]
set out [file normalize [lindex $argv 1]]
file mkdir $out
set_param general.maxThreads 4
set part xc7a200tffg1156-3
set settings "part=$part\nvivado=[version -short]\nPIPELINE=4\nUNROLL=1\nPROFILE_ENABLE=0\nKECCAK_LUT6=0\nmaxThreads=4\ninitial_period_ns=6.666667"
set settings_file [file join $out settings.txt]
if {[file exists $settings_file]} {
    set handle [open $settings_file r]
    set previous_settings [string trim [read $handle]]
    close $handle
    if {$previous_settings ne $settings} {error "Settings changed: use a new implementation directory"}
} else {
    set handle [open $settings_file w]
    puts $handle $settings
    close $handle
}
create_project -in_memory -part $part
set f [open [file join $source_root sources.txt] r]
set sources [split [string trim [read $f]] \n]
close $f
foreach source $sources {read_verilog -sv [file join $source_root $source]}
set source_files {}
foreach source $sources {lappend source_files [file join $source_root $source]}
set fingerprint [exec sha256sum {*}$source_files]
set fingerprint_file [file join $out source.sha256]
if {[file exists $fingerprint_file]} {
    set handle [open $fingerprint_file r]
    set previous [string trim [read $handle]]
    close $handle
    if {$previous ne $fingerprint} {error "Source changed: use a new implementation directory"}
} else {
    set handle [open $fingerprint_file w]
    puts $handle $fingerprint
    close $handle
}
set f [open [file join $out synth_clock.xdc] w]
puts $f {create_clock -name clk -period 6.666667 [get_ports clk]}
close $f
read_xdc [file join $out synth_clock.xdc]
if {![file exists [file join $out synth.dcp]]} {
synth_design -top common -part $part -mode out_of_context -flatten_hierarchy rebuilt -max_dsp 0 \
    -generic PIPELINE=4 -generic UNROLL=1 -generic PROFILE_ENABLE=0
report_utilization -file [file join $out synth_utilization.rpt]
report_utilization -hierarchical -file [file join $out synth_hierarchical.rpt]
report_timing_summary -file [file join $out synth_timing.rpt]
foreach cell [get_cells -hier -filter {IS_PRIMITIVE == 1}] {
    if {[string match FD* [get_property REF_NAME $cell]] &&
        [regexp {(cycles|hash_count|permutation_count|hash_base|permutation_base)_reg} $cell]} {
        error "Statistics register remains: $cell"
    }
}
write_checkpoint -force [file join $out synth.dcp]
close_design
}
proc attempt {out period} {
    open_checkpoint [file join $out synth.dcp]
    create_clock -name clk -period $period [get_ports clk]
    opt_design
    place_design
    phys_opt_design
    route_design
    set tag [format %.6f $period]
    set folder [file join $out route_$tag]
    file mkdir $folder
    report_utilization -file [file join $folder utilization.rpt]
    report_utilization -hierarchical -file [file join $folder hierarchical.rpt]
    report_timing_summary -file [file join $folder timing.rpt]
    report_route_status -file [file join $folder route_status.rpt]
    set wns [get_property SLACK [get_timing_paths -delay_type max -max_paths 1]]
    set whs [get_property SLACK [get_timing_paths -delay_type min -max_paths 1]]
    set f [open [file join $folder result.txt] w]
    puts $f "period_ns=$period\nwns_ns=$wns\nwhs_ns=$whs"
    close $f
    write_checkpoint -force [file join $folder routed.dcp]
    close_design
    return [expr {$wns>=0 && $whs>=0}]
}
# First route at 150 MHz, then relax to the measured critical delay rather
# than repeat implementations at constraints already known to fail. All
# designs use the same flow. The final frequency is STA on one frozen route.
set start 6.666667
set first [file join $out route_6.666667 routed.dcp]
if {[file exists [file join $out closed routed.dcp]]} {
    set routed [file join $out closed routed.dcp]
} else {
if {![file exists $first]} {attempt $out $start}
open_checkpoint $first
set wns [get_property SLACK [get_timing_paths -delay_type max -max_paths 1]]
set whs [get_property SLACK [get_timing_paths -delay_type min -max_paths 1]]
close_design
set routed $first
if {$wns<0 || $whs<0} {
    set tick [expr {int(ceil(-$wns/0.1))+1}]
    for {set n 0} {$n<4} {incr n} {
        set period [expr {$start+$tick*0.1}]
        set closed [attempt $out $period]
        set routed [file join $out route_[format %.6f $period] routed.dcp]
        if {$closed} {break}
        open_checkpoint $routed
        set wns [get_property SLACK [get_timing_paths -delay_type max -max_paths 1]]
        close_design
        set tick [expr {$tick+max(1,int(ceil(-$wns/0.1))+1)}]
    }
    if {!$closed} {error "No closed implementation after measured-delay relaxation"}
}
}
# Narrow the constraint to 0.1 ns on the same placed/routed netlist. This
# changes only the clock period, never path exceptions or physical delays.
open_checkpoint $routed
set f [open [file join $out sta_sweep.csv] w]
puts $f "requested_period_ns,period_ns,wns_ns,whs_ns"
for {set tick 0} {$tick<=200} {incr tick} {
    set period [expr {$start+$tick*0.1}]
    create_clock -name clk -period $period [get_ports clk]
    set wns [get_property SLACK [get_timing_paths -delay_type max -max_paths 1]]
    set whs [get_property SLACK [get_timing_paths -delay_type min -max_paths 1]]
    set actual_period [get_property PERIOD [get_clocks clk]]
    puts $f "$period,$actual_period,$wns,$whs"
    if {$wns>=0 && $whs>=0} {break}
}
close $f
if {$tick>200} {error "STA sweep failed"}
set folder [file join $out closed]
file mkdir $folder
report_utilization -file [file join $folder utilization.rpt]
report_utilization -hierarchical -file [file join $folder hierarchical.rpt]
report_timing_summary -file [file join $folder timing.rpt]
report_route_status -file [file join $folder route_status.rpt]
report_drc -file [file join $folder drc.rpt]
report_clock_interaction -file [file join $folder clocks.rpt]
set handle [open [file join $folder result.txt] w]
puts $handle "period_ns=$actual_period\nrequested_period_ns=$period\nwns_ns=$wns\nwhs_ns=$whs\nphysical_checkpoint=$routed"
close $handle
write_checkpoint -force [file join $folder routed.dcp]
set handle [open [file join $out closed_period.txt] w]
puts $handle $actual_period
close $handle
puts "P4_IMPLEMENT_PASS period_ns=$actual_period"
exit
