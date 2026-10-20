set hash_backend shake
if {[info exists ::env(HASH_BACKEND)]} {set hash_backend $::env(HASH_BACKEND)}
if {$hash_backend ni {shake sha2}} {error "HASH_BACKEND must be shake or sha2"}
set package_root [file normalize [file join [file dirname [info script]] ..]]
cd $package_root
set profile slh_128f
if {[llength $argv]} {set profile [lindex $argv 0]}
# Preserve this script's historical signature-cache-enabled measurement scope.
# Override with a second argument (0/1) or MHBS_SIGNATURE_STORE in the environment.
set signature_store 1
if {[info exists ::env(MHBS_SIGNATURE_STORE)]} {
    set signature_store $::env(MHBS_SIGNATURE_STORE)
}
if {[llength $argv] > 1} {set signature_store [lindex $argv 1]}
if {$signature_store ni {0 1}} {error "MHBS_SIGNATURE_STORE must be 0 or 1"}
set defines [list SYNTHESIS]
if {$hash_backend eq "sha2"} {lappend defines MHBS_SHA2}
if {$signature_store} {lappend defines MHBS_SIGNATURE_STORE}
if {$profile ni {slh_128f slh_192f slh_256f slh_128s slh_192s slh_256s xmss_h10 xmss_h16 xmss_h20 lms_h10 lms_h15 lms_h20}} {error "Unsupported profile"}
set out [file join $package_root build synth top_P4U1_generic $profile]
if {!$signature_store} {append out _no_signature_store}
if {$hash_backend eq "sha2"} {append out _sha2}
file mkdir $out
set archive [exec python3 [file join $package_root scripts experiment_archive.py] --begin-synthesis $out]
set source_root [file join $archive source]
set part xc7a200tffg1156-3
set_param general.maxThreads 2
create_project -in_memory -part $part
set handle [open [file join $source_root sources.txt] r]
set sources [split [string trim [read $handle]] \n]
close $handle
set_property verilog_define $defines [current_fileset]
foreach source $sources {read_verilog -sv [file join $source_root $source]}
read_xdc [file join $source_root scripts clock.xdc]
# Sign top with optional signature cache, fixed fixture keys and per-profile ROM.
set folder [file join tb vectors $profile sign]
if {$hash_backend eq "sha2"} {
    if {$profile in {slh_192f slh_256f slh_192s slh_256s}} {error "SHA2 supports SLH 128f/s only"}
    set folder [file join tb vectors sha2 $profile sign]
}
set handle [open [file join $folder job.mem] r]
set job [split [string trim [read $handle]] \n]
close $handle
set command [list synth_design -top top -part $part -mode out_of_context \
    -flatten_hierarchy rebuilt -max_dsp 0 -generic PIPELINE=4 -generic UNROLL=1 \
    -generic OPERATION=1]
foreach name {PROGRAM TEMPLATE DESCRIPTOR} file {program template descriptor} {
    lappend command -generic "${name}_INIT_FILE=\"$folder/$file.mem\""
}
foreach name {SECRET_SEED SECRET_PRF PUBLIC_SEED RANDOMIZER PUBLIC_ROOT IDENTIFIER KEY_INDEX} index {0 1 2 3 4 5 6} width {256 256 256 256 256 128 32} {
    set value [string range [lindex $job $index] end-[expr {$width/4-1}] end]
    lappend command -generic "$name=${width}'h$value"
}
set handle [open [file join $out settings.txt] w]
puts $handle "top=top\nprofile=$profile\noperation=Sign\nPIPELINE=4\nUNROLL=1\nSYNTHESIS=1\nMHBS_SIGNATURE_STORE=$signature_store\nverilog_defines=$defines\nhash_backend=$hash_backend\npart=$part\nvivado=[version -short]\nmode=out_of_context\ncommand=$command"
close $handle
{*}$command
report_utilization -file [file join $out top_utilization.rpt]
report_utilization -hierarchical -file [file join $out top_hierarchical.rpt]
report_timing_summary -file [file join $out top_timing.rpt]
write_checkpoint -force [file join $out top_synth.dcp]
source [file join $source_root scripts audit_debug.tcl]
mhbs_audit_debug [file join $out debug_audit.json]
puts "MHBS_TOP_SYNTH_PASS profile=$profile P4U1 SYNTHESIS=1 MHBS_SIGNATURE_STORE=$signature_store"
exec python3 [file join $package_root scripts experiment_archive.py] --finish-synthesis $archive --results $out
exit
