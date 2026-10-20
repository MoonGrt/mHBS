# Diagnostics must disappear from the production interface and storage.
# Call after synth_design (or after opening the candidate checkpoint).
proc mhbs_audit_debug {{report_file ""}} {
    set debug_name {(^|/)([a-zA-Z0-9_]*error_code|([a-zA-Z0-9_]*_)?(cycles|hash_count|permutation_count|hash_base|permutation_base)|batch_hashes|batch_permutations|diagnostic_[a-zA-Z0-9_]+|(lane|pipe|total)_(hashes|permutations))(\[|_|$)}
    set bad_ports {}
    foreach port [get_ports -quiet] {
        if {[regexp $debug_name [get_property NAME $port]]} {lappend bad_ports $port}
    }
    set bad_registers {}
    foreach cell [get_cells -quiet -hier -filter {IS_PRIMITIVE == 1 && REF_NAME =~ FD*}] {
        if {[regexp $debug_name [get_property NAME $cell]]} {lappend bad_registers $cell}
    }
    if {[llength $bad_ports] || [llength $bad_registers]} {
        error "Diagnostic resources remain: ports=$bad_ports registers=$bad_registers"
    }
    if {$report_file ne ""} {
        set handle [open $report_file w]
        puts $handle "{\"passed\": true, \"diagnostic_ports\": 0, \"diagnostic_registers\": 0, \"functional_error_present\": [expr {[llength [get_ports -quiet error]] > 0}], \"scope\": \"synthesized design\"}"
        close $handle
    }
    puts "MHBS_DEBUG_AUDIT_PASS diagnostic_ports=0 diagnostic_registers=0"
}
