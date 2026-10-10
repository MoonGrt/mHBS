set package_root [file normalize [file join [file dirname [info script]] ..]]
cd $package_root
set profile slh_128f
if {[llength $argv]} {set profile [lindex $argv 0]}
if {$profile ni {slh_128f slh_192f slh_256f slh_128s slh_192s slh_256s xmss_h10 xmss_h16 xmss_h20 lms_h10 lms_h15 lms_h20}} {error "Unsupported profile"}
set out [file join $package_root build synth top_P4U1_generic $profile]
file mkdir $out
set part xc7a200tffg1156-3
set_param general.maxThreads 4
create_project -in_memory -part $part
set handle [open sources.txt r]
set sources [split [string trim [read $handle]] \n]
close $handle
foreach source $sources {read_verilog -sv [file join $package_root $source]}
read_xdc [file join $package_root scripts clock.xdc]
# Sign top, complete signature cache, fixed fixture keys and per-profile ROM.
set folder [file join tb vectors $profile sign]
set handle [open [file join $folder job.mem] r]
set job [split [string trim [read $handle]] \n]
close $handle
set command [list synth_design -top top -part $part -mode out_of_context \
    -flatten_hierarchy rebuilt -max_dsp 0 -generic PIPELINE=4 -generic UNROLL=1 \
    -generic PROFILE_ENABLE=0 -generic SIGNATURE_STORE_ENABLE=1 -generic OPERATION=1]
foreach name {PROGRAM TEMPLATE DESCRIPTOR} file {program template descriptor} {
    lappend command -generic "${name}_INIT_FILE=\"$folder/$file.mem\""
}
foreach name {SECRET_SEED SECRET_PRF PUBLIC_SEED RANDOMIZER PUBLIC_ROOT IDENTIFIER KEY_INDEX} index {0 1 2 3 4 5 6} width {256 256 256 256 256 128 32} {
    set value [string range [lindex $job $index] end-[expr {$width/4-1}] end]
    lappend command -generic "$name=${width}'h$value"
}
set handle [open [file join $out settings.txt] w]
puts $handle "top=top\nprofile=$profile\noperation=Sign\nPIPELINE=4\nUNROLL=1\nPROFILE_ENABLE=0\nSIGNATURE_STORE_ENABLE=1\npart=$part\nvivado=[version -short]\nmode=out_of_context\ncommand=$command"
close $handle
{*}$command
report_utilization -file [file join $out top_utilization.rpt]
report_utilization -hierarchical -file [file join $out top_hierarchical.rpt]
report_timing_summary -file [file join $out top_timing.rpt]
write_checkpoint -force [file join $out top_synth.dcp]
set bad [get_cells -hier -filter {IS_PRIMITIVE == 1 && REF_NAME =~ FD*}]
foreach cell $bad {
    if {[regexp {(cycles|hash_count|permutation_count|hash_base|permutation_base)_reg} $cell]} {error "Statistics register remains: $cell"}
}
puts "MHBS_TOP_SYNTH_PASS profile=$profile P4U1 PROFILE_ENABLE=0 SIGNATURE_STORE_ENABLE=1"
exit
