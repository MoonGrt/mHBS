# Map inferred LUT truth-table inputs to logical ROM address bits.
proc export_rom_mapping {path} {
 set f [open $path w]
 foreach kind {program template descriptor} {
  set depth [dict get {program 16 template 16 descriptor 32} $kind]
  set abits [dict get {program 4 template 4 descriptor 5} $kind]
  set ports [expr {$kind eq "descriptor" ? 2 : 1}]
  set signal [expr {$kind eq "descriptor" ? "descriptor_addresses" : "${kind}_address"}]
  for {set p 0} {$p<$ports} {incr p} {
   for {set b 0} {$b<64} {incr b} {
    set dp [get_pins [format {common/%s_data[%d]} $kind [expr {$p*64+$b}]]]
    set dn [get_nets -of_objects $dp]
    set driver [get_pins -leaf -of_objects $dn -filter {DIRECTION == OUT}]
    if {[llength $driver]!=1} {error "ROM output driver $kind $p $b: $driver"}
    set c [get_cells -of_objects $driver]
    if {[get_property REF_NAME $c] ne "LUT$abits"} {error "Unsupported inferred ROM primitive $c"}
    set mapping {}
    for {set i 0} {$i<$abits} {incr i} {
     set input_net [get_nets -of_objects [get_pins $c/I$i]]
     set found -1
     for {set a 0} {$a<$abits} {incr a} {
      set ap [get_pins [format {common/%s[%d]} $signal [expr {$p*$abits+$a}]]]
      if {[get_nets -of_objects $ap] eq $input_net} {set found $a}
     }
     if {$found<0} {error "Unmapped input $c/I$i $input_net"}
     lappend mapping $found
    }
    set_property DONT_TOUCH true $c
    set_property DONT_TOUCH true $dn
    puts $f "$kind\t$p\t$b\t$c\t$abits\t[join $mapping ,]\t[get_property INIT $c]"
   }
  }
 }
 close $f
}
