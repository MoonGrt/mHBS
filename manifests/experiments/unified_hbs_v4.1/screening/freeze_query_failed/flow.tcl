# One routed hardware body, seven INIT substitutions. Never optimize/place/route after freezing.
set root [file normalize [file join [file dirname [info script]] ../..]]
cd $root
set tag [lindex $argv 0]
if {![regexp {^[a-zA-Z0-9_.-]+$} $tag]} {error "invalid tag"}
set outdir [file join $root build v4.1 $tag]
set frozen [file join $outdir frozen]
file mkdir $frozen
exec python3 scripts/rom_initialization.py [file join $frozen init]
open_checkpoint [file join $outdir post_route_final_clock.dcp]
# Serialize functional configuration, placement and routing. Querying every HD.*
# property can invoke Vivado isolation transforms even in an OOC checkpoint.
# Only read the safe structural/primitive properties needed for this proof.
proc structure {path} {
    set f [open $path w]
    foreach c [lsort [get_cells -hier]] {
        puts $f "CELL $c"
        foreach prop [lsort [list_property $c]] {
            if {$prop eq "INIT" && [regexp {^(program|template|descriptor)_rom/port_bank\[} $c]} {continue}
            if {$prop in {REF_NAME ORIG_REF_NAME IS_PRIMITIVE LOC BEL IS_LOC_FIXED IS_BEL_FIXED LOCK_PINS PIN_MAP DONT_TOUCH KEEP_HIERARCHY} ||
                [regexp {^(INIT($|_)|SRVAL|IS_.*_INVERTED$|READ_WIDTH|WRITE_WIDTH|WRITE_MODE|DO[AB]_REG$|RAM_MODE$|RAM_EXTENSION|EN_ECC)} $prop]} {
                puts $f "  $prop=[get_property $prop $c]"
            }
        }
    }
    foreach n [lsort [get_nets -hier]] {
        puts $f "NET $n"
        puts $f "  PINS=[lsort [get_pins -quiet -of_objects $n]]"
        puts $f "  PORTS=[lsort [get_ports -quiet -of_objects $n]]"
        puts $f "  ROUTE=[get_property ROUTE $n]"
    }
    close $f
}
structure [file join $frozen hardware.txt]
set base_hash [lindex [exec sha256sum [file join $frozen hardware.txt]] 0]
set records [open [file join $frozen evidence.tsv] w]
foreach profile {slh_128f slh_192f slh_256f xmss_omega2 xmss_omega4 lms_omega2 lms_omega4} {
    source [file join $frozen init ${profile}.tcl]
    structure [file join $frozen ${profile}_hardware.txt]
    set hash [lindex [exec sha256sum [file join $frozen ${profile}_hardware.txt]] 0]
    if {$hash ne $base_hash} {error "Hardware changed for $profile"}
    file delete [file join $frozen ${profile}_hardware.txt]
    write_checkpoint -force [file join $frozen ${profile}.dcp]
    report_utilization -file [file join $frozen ${profile}_utilization.rpt]
    set f [open [file join $frozen ${profile}_init.tsv] w]
    foreach c [lsort [get_cells -hier -filter {REF_NAME == RAM64X1S || REF_NAME == RAM128X1S}]] {
        if {[regexp {^(program|template|descriptor)_rom/} $c]} {puts $f "$c\t[get_property INIT $c]"}
    }
    close $f
    puts $records "$profile\t$hash"
    puts "FROZEN_IMAGE_PASS profile=$profile hardware_sha256=$hash"
}
close $records
