set_param general.maxThreads 8
read_verilog -sv rtl/memory/mhbs_signature_store.sv
synth_design -top mhbs_signature_store -part xc7a200tffg1156-3 -mode out_of_context
create_clock -name clk -period 10.0 [get_ports clk]
report_utilization -file manifests/validation/signature_store_20261002/utilization.rpt
report_utilization -hierarchical -file manifests/validation/signature_store_20261002/hierarchical.rpt
report_timing_summary -file manifests/validation/signature_store_20261002/timing.rpt
exit
