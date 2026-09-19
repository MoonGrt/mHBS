set script_dir [file dirname [file normalize [info script]]]
set root [file normalize [file join $script_dir ..]]
set source_variant "stateful_xmss_a200t_3"
set result_variant "stateful_xmss_a200t_3_postroute"
if {$argc >= 1} { set source_variant [lindex $argv 0] }
if {$argc >= 2} { set result_variant [lindex $argv 1] }
foreach variant [list $source_variant $result_variant] {
    if {![regexp {^[A-Za-z0-9_.-]+$} $variant]} {
        error "invalid build variant: $variant"
    }
}
set source_dcp [file normalize [file join $root build vivado $source_variant post_synth.dcp]]
set outdir [file normalize [file join $root build vivado $result_variant]]
if {![file exists $source_dcp]} { error "missing checkpoint: $source_dcp" }
file mkdir $outdir
set_param general.maxThreads 24
open_checkpoint $source_dcp
opt_design
place_design
phys_opt_design
route_design
phys_opt_design -directive AggressiveExplore
report_route_status -file [file join $outdir route_status.rpt]
report_utilization -hierarchical \
    -file [file join $outdir utilization_hierarchical.rpt]
report_utilization -file [file join $outdir utilization.rpt]
report_timing_summary -delay_type max -max_paths 10 \
    -file [file join $outdir timing_summary.rpt]
write_checkpoint -force [file join $outdir routed_postphys.dcp]
