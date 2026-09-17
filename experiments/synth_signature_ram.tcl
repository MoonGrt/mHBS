set root [file normalize [file join [file dirname [info script]] ..]]
set outdir [file join $root build vivado signature_ram]
file mkdir $outdir
read_verilog -sv [file join $root rtl memory micro_hbs_signature_ram128_banked.sv]
synth_design -top micro_hbs_signature_ram128_banked \
    -part xc7a200tffg1156-2 -mode out_of_context -flatten_hierarchy rebuilt
report_utilization -hierarchical -file [file join $outdir utilization.rpt]
