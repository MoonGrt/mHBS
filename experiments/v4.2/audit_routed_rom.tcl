# Re-derive logical LUT-pin mapping after physical optimization and routing.
set root [file normalize [file join [file dirname [info script]] ../..]]
cd $root
set tag [lindex $argv 0]
if {![regexp {^[a-zA-Z0-9_.-]+$} $tag]} {error "invalid tag"}
set out [file join $root build v4.2 $tag]
open_checkpoint [file join $out post_route_final_clock.dcp]
source experiments/v4.2/rom_mapping.tcl
export_rom_mapping [file join $out routed_rom_mapping.tsv]
puts "ROUTED_ROM_MAPPING_EXPORTED"
