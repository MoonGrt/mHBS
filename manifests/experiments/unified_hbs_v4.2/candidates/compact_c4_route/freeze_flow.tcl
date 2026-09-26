# One routed SLH body, three INIT substitutions. Never optimize/place/route after freezing.
set root [file normalize [file join [file dirname [info script]] ../..]]
cd $root
set tag [lindex $argv 0]
if {![regexp {^[a-zA-Z0-9_.-]+$} $tag]} {error "invalid tag"}
set outdir [file join $root build v4.2 $tag]
set frozen [file join $outdir frozen]
file mkdir $frozen
exec python3 scripts/v42_rom.py $outdir
file copy -force [file join $outdir init] $frozen
set rom_cells {}
set f [open [file join $outdir rom_mapping.tsv]]
foreach line [split [string trim [read $f]] \n] {dict set rom_cells [lindex [split $line \t] 3] 1}
close $f
open_checkpoint [file join $outdir post_route_final_clock.dcp]
# Serialize functional configuration, placement and routing. Querying every HD.*
# property can invoke Vivado isolation transforms even in an OOC checkpoint.
# list_property itself can invoke these transforms on a hierarchy. Use an
# explicit property list, including every configuration of the primitive types
# used here (LUT, FF, carry, distributed RAM, mux and clock/reset buffers).
proc structure {path} {
    global rom_cells
    set f [open $path w]
    foreach c [lsort [get_cells -hier]] {
        puts $f "CELL $c"
        foreach prop {REF_NAME ORIG_REF_NAME IS_PRIMITIVE LOC BEL IS_LOC_FIXED IS_BEL_FIXED LOCK_PINS PIN_MAP DONT_TOUCH KEEP_HIERARCHY INIT INIT_A INIT_B INIT_C INIT_D INIT_00 INIT_01 SRVAL IS_C_INVERTED IS_D_INVERTED IS_R_INVERTED IS_S_INVERTED IS_CLK_INVERTED IS_WCLK_INVERTED} {
            if {$prop eq "INIT" && [dict exists $rom_cells $c]} {continue}
            puts $f "  $prop=[get_property -quiet $prop $c]"
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
foreach profile {slh_128f_keygen slh_128f_sign slh_192f_keygen slh_192f_sign slh_256f_keygen slh_256f_sign} {
    source [file join $frozen init ${profile}.tcl]
    structure [file join $frozen ${profile}_hardware.txt]
    set hash [lindex [exec sha256sum [file join $frozen ${profile}_hardware.txt]] 0]
    if {$hash ne $base_hash} {error "Hardware changed for $profile"}
    file delete [file join $frozen ${profile}_hardware.txt]
    write_checkpoint -force [file join $frozen ${profile}.dcp]
    report_utilization -file [file join $frozen ${profile}_utilization.rpt]
    report_timing_summary -delay_type min_max -file [file join $frozen ${profile}_timing.rpt]
    set f [open [file join $frozen ${profile}_init.tsv] w]
    foreach c [lsort [dict keys $rom_cells]] {puts $f "$c\t[get_property INIT [get_cells $c]]"}
    close $f
    puts $records "$profile\t$hash"
    puts "FROZEN_IMAGE_PASS profile=$profile hardware_sha256=$hash"
}
close $records
