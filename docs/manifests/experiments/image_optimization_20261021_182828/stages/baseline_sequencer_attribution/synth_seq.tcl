set_param general.maxThreads 2
create_project -in_memory -part xc7a200tffg1156-3
read_verilog -sv /tmp/image_seq_audit/sequencer.sv
synth_design -top sequencer -part xc7a200tffg1156-3 -mode out_of_context -flatten_hierarchy rebuilt
report_utilization -file /tmp/image_seq_audit/standalone_utilization.rpt
report_timing_summary -file /tmp/image_seq_audit/standalone_timing.rpt
exit
