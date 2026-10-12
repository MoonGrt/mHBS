# Inspect an existing synthesis checkpoint without changing timing constraints.
# This command does not optimize, place, or route the design.
if {[llength $argv] != 2} {error "Usage: synthesized.dcp output_directory"}
lassign $argv checkpoint out
set checkpoint [file normalize $checkpoint]
set out [file normalize $out]
if {![file isfile $checkpoint]} {error "Missing synthesis checkpoint: $checkpoint"}
file mkdir $out
set_param general.maxThreads 2

proc json_string {value} {
    return "\"[string map [list \\ \\\\ \" \\\" \n \\n \r \\r \t \\t] $value]\""
}

proc json_object {values} {
    set fields {}
    dict for {key value} $values {
        lappend fields "[json_string $key]:$value"
    }
    return "\{[join $fields ,]\}"
}

proc json_number {value} {
    if {$value eq "" || ![string is double -strict $value]} {return null}
    if {[regexp -nocase {inf|nan} $value]} {return null}
    return [format %.9f $value]
}

proc path_property {path property available} {
    if {[lsearch -exact $available $property] < 0} {return ""}
    return [get_property $property $path]
}

open_checkpoint $checkpoint
set design [current_design]
report_timing_summary -report_unconstrained -file [file join $out timing_summary.rpt]
report_timing -delay_type max -max_paths 100 -nworst 4 -unique_pins \
    -path_type full_clock_expanded -input_pins -file [file join $out setup_top100.rpt]
set paths [get_timing_paths -delay_type max -max_paths 100 -nworst 4 -unique_pins]
set encoded_paths {}
set endpoint_counts [dict create]
set startpoint_counts [dict create]
set available {}
if {[llength $paths]} {set available [list_property [lindex $paths 0]]}
set index 0
foreach path $paths {
    incr index
    set fields [dict create rank $index]
    foreach {field property} {
        slack_ns SLACK data_path_delay_ns DATAPATH_DELAY logic_levels LOGIC_LEVELS
        logic_delay_ns DATAPATH_LOGIC_DELAY estimated_net_delay_ns DATAPATH_NET_DELAY
        max_fanout MAX_FANOUT requirement_ns REQUIREMENT clock_skew_ns SKEW
    } {
        dict set fields $field [json_number [path_property $path $property $available]]
    }
    foreach {field property} {
        startpoint STARTPOINT_PIN endpoint ENDPOINT_PIN path_group GROUP
        source_clock STARTPOINT_CLOCK destination_clock ENDPOINT_CLOCK
    } {
        dict set fields $field [json_string [path_property $path $property $available]]
    }
    set startpoint [path_property $path STARTPOINT_PIN $available]
    set endpoint [path_property $path ENDPOINT_PIN $available]
    dict incr startpoint_counts $startpoint
    dict incr endpoint_counts $endpoint
    lappend encoded_paths [json_object $fields]
}
set encoded_clocks {}
foreach clock [get_clocks -quiet] {
    lappend encoded_clocks [json_object [dict create name [json_string [get_property NAME $clock]] \
        period_ns [json_number [get_property PERIOD $clock]]]]
}
set metadata [dict create schema [json_string mhbs.synthesis.paths.v1] \
    created_at [json_string [clock format [clock seconds] -format {%Y-%m-%dT%H:%M:%S%z}]] \
    checkpoint [json_string $checkpoint] design [json_string $design] \
    tool_version [json_string [version -short]] \
    scope [json_string {Synthesized common OOC internal constrained setup paths; unplaced estimated interconnect delays; no board IO or external ROM/signature timing; not routed STA or measured Fmax}] \
    constraints_modified false physical_implementation_run false \
    requested_max_paths 100 requested_nworst 4 unique_pins true returned_paths $index \
    distinct_startpoints [dict size $startpoint_counts] distinct_endpoints [dict size $endpoint_counts] \
    startpoint_path_counts [json_object $startpoint_counts] \
    endpoint_path_counts [json_object $endpoint_counts] \
    clocks "\[[join $encoded_clocks ,]\]" \
    path_properties_available [json_string $available] \
    paths "\[[join $encoded_paths ,]\]"]
set handle [open [file join $out paths.json] w]
puts $handle [json_object $metadata]
close $handle
close_design
puts "MHBS_SYNTH_PATHS_PASS paths=$index checkpoint=$checkpoint"
exit
