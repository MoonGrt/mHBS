open_checkpoint {/media/sk1/25700d07-be6e-4225-bd06-13baa4403116/Vivado/mHBS/manifests/experiments/ku_full_top_route_20261006_v1/K2U2/post_synth.dcp}
create_clock -name clk -period 9.0 [get_ports clk]
create_clock -name clk -period 9.5 [get_ports clk]
puts "CLOCK_PROBE_PERIOD=[get_property PERIOD [get_clocks clk]]"
exit
