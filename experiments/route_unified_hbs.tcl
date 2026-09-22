set root [file normalize [file join [file dirname [info script]] ..]]
set tag [lindex $argv 0]
if {![regexp {^[A-Za-z0-9_.-]+$} $tag]} {error "invalid synthesis tag"}
set period 10.000
if {$argc > 1} {set period [lindex $argv 1]}
set route_tag "${tag}_route"
if {$argc > 2} {set route_tag [lindex $argv 2]}
if {![regexp {^[A-Za-z0-9_.-]+$} $route_tag]} {error "invalid route tag"}
set outdir [file join $root build vivado $route_tag]
file mkdir $outdir
file copy -force [file join $root build vivado $tag inputs.json] [file join $outdir inputs.json]
exec python3 -c {import hashlib,json,pathlib,sys; p=pathlib.Path(sys.argv[1]); pathlib.Path(sys.argv[2]).write_text(json.dumps({"script_sha256":hashlib.sha256(p.read_bytes()).hexdigest(),"period_ns":float(sys.argv[3]),"timing_scope":"OOC_INTERNAL_REGISTER_PATHS"},indent=2)+"\n")} [info script] [file join $outdir route_inputs.json] $period
set_param general.maxThreads 16
open_checkpoint [file join $root build vivado $tag post_synth.dcp]
create_clock -name clk -period $period [get_ports clk]
set_property HD.CLK_SRC BUFGCTRL_X0Y0 [get_ports clk]
# Physical locations of external streaming/control pins are unspecified.
# Measure only internal register paths, including the registered abort signal.
# These exceptions cannot be used as board-level interface timing closure.
set_false_path -from [get_ports -filter {DIRECTION == IN && NAME != clk}]
set_false_path -to [all_outputs]
opt_design
place_design -directive Explore
phys_opt_design -directive AggressiveExplore
route_design -directive Explore
write_checkpoint -force [file join $outdir post_route.dcp]
report_utilization -file [file join $outdir utilization.rpt]
report_utilization -hierarchical -file [file join $outdir utilization_hierarchical.rpt]
report_timing_summary -delay_type min_max -report_unconstrained -max_paths 10 -file [file join $outdir timing_summary.rpt]
report_route_status -file [file join $outdir route_status.rpt]
check_timing -verbose -file [file join $outdir check_timing.rpt]
write_xdc -force [file join $outdir constraints.xdc]
