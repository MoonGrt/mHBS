# Check common optimization with the processor open and only ROM cells/nets protected.
set root [file normalize [file join [file dirname [info script]] ../..]]
cd $root
set tag [lindex $argv 0]
set out [file join build v4.1 ${tag}_boundary]
file mkdir $out
set_param general.maxThreads 4
foreach variant {0 1} {
    open_checkpoint [file join build v4.1 $tag post_synth.dcp]
    set_property DONT_TOUCH false [get_cells processor]
    foreach c [get_cells -hier -filter {REF_NAME == RAM64X1S || REF_NAME == RAM128X1S}] {
        if {![regexp {^(program|template|descriptor)_rom/} $c]} {continue}
        set_property DONT_TOUCH true $c
        set_property DONT_TOUCH true [get_nets -of_objects [get_pins $c/O]]
        if {$variant} {
            if {[get_property REF_NAME $c] eq "RAM64X1S"} {
                set_property INIT 64'h0123456789abcdef $c
            } else {set_property INIT 128'hfedcba98765432100123456789abcdef $c}
        }
    }
    opt_design
    set f [open [file join $out structure_${variant}.txt] w]
    foreach c [lsort [get_cells -hier]] {
        set init [get_property -quiet INIT $c]
        if {[regexp {^(program|template|descriptor)_rom/} $c]} {set init IMAGE}
        puts $f "CELL $c [get_property REF_NAME $c] $init"
    }
    foreach n [lsort [get_nets -hier]] {
        puts $f "NET $n [lsort [get_pins -of_objects $n]] [lsort [get_ports -quiet -of_objects $n]]"
    }
    close $f
    report_utilization -file [file join $out utilization_${variant}.rpt]
    write_checkpoint -force [file join $out optimized_${variant}.dcp]
    close_design
}
set first [lindex [exec sha256sum [file join $out structure_0.txt]] 0]
set second [lindex [exec sha256sum [file join $out structure_1.txt]] 0]
if {$first ne $second} {error "ROM initialization affected common optimization"}
puts "ROM_BOUNDARY_PASS hardware_sha256=$first"
