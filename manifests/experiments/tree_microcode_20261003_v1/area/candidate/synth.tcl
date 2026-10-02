set_param general.maxThreads 8
set part xc7a200tffg1156-3
set out {/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/manifests/experiments/tree_microcode_20261003_v1/area/candidate}
foreach name {slh_128f slh_192f slh_256f slh_128s slh_192s slh_256s} {
 set d [file join $out $name];file mkdir $d
 create_project -in_memory -part $part
 read_verilog -sv rtl/memory/mhbs_signature_store.sv
 read_verilog [file join $out common_stub.v]
 read_verilog -sv [file join $out ${name}.sv]
 read_xdc [file join $out clock.xdc]
 synth_design -top mhbs_top -part $part -mode out_of_context -flatten_hierarchy none
 report_utilization -file [file join $d shell_utilization.rpt]
 report_utilization -hierarchical -file [file join $d shell_hierarchical.rpt]
 write_edif -force [file join $d mhbs_top.edf]
 close_project
 create_project -in_memory -part $part
 read_edif [file join $out mhbs_common.edf]
 read_edif [file join $d mhbs_top.edf]
 link_design -top mhbs_top -part $part -mode out_of_context
 set_property DONT_TOUCH true [get_cells common]
 create_clock -name clk -period 10.0 [get_ports clk]
 report_utilization -file [file join $d utilization.rpt]
 report_utilization -hierarchical -file [file join $d hierarchical.rpt]
 close_project
 puts "TREE_STEP_SYNTH_PROFILE_PASS $name"
}
puts "TREE_STEP_SYNTH_PASS"
exit
