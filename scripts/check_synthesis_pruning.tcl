# Audit the actual common-core synthesis checkpoint, without routing.
set checkpoint [file normalize [lindex $argv 0]]
set output [file normalize [lindex $argv 1]]
set_param general.maxThreads 2
open_checkpoint $checkpoint
set names {boot_cycles keygen_cycles sign_cycles cycles hash_count permutation_count hash_base permutation_base macro_count macro_busy_cycles macro_hashes tree_count tree_busy_cycles tree_hashes tree_chains tree_input_wait_cycles tree_child_busy_cycles}
set expression "(^|/)([join $names |])_reg"
set failures {}
foreach cell [get_cells -hier -filter {IS_PRIMITIVE == 1}] {
    if {[string match FD* [get_property REF_NAME $cell]] && [regexp $expression $cell]} {
        lappend failures $cell
    }
}
if {[llength $failures]} {error "Statistics survived PROFILE_ENABLE=0: $failures"}
set handle [open $output w]
puts $handle {{"passed":true,"method":"primitive FF name audit on actual synthesized checkpoint","profile_enable":false,"statistic_registers":0,"scope":"cycles, bases, Hash, permutation, CHAIN and TREE statistics","placement_or_routing_run":false}}
close $handle
puts STATEFUL_PRUNING_PASS
exit
