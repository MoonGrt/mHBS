`timescale 1ns/1ps
module mhbs_batch_test_driver #(parameter UNROLL=1,PIPELINE=2)(
 input wire clk,rst,request_valid,output wire request_ready,
 input wire [1599:0] request_state,input wire [1:0] request_tag,
 output wire response_valid,output wire [1599:0] response_state,output wire [1:0] response_tag);
 mhbs_compact_shake_context_lane #(.UNROLL(UNROLL),.PIPELINE(PIPELINE),.SHARED_STATE(1)) dut(
  .clk,.rst,.batch_mode(1'b1),.batch_valid(request_valid),.batch_ready(request_ready),
  .batch_state(request_state),.batch_tag(request_tag),.batch_done(response_valid),
  .batch_digest(response_state),.batch_result_tag(response_tag),
  .node_bytes(6'd16),.chain_prefix_data(384'd0),.context_valid(1'b0),.context_ready(),
  .fast_block_valid(1'b0),.fast_block_ready(),.fast_block_data(1088'd0),
  .chain_enable(1'b0),.chain_prefix(1'b0),.chain_prefix_preserve_counter(1'b0),
  .chain_prefix_domain(3'd0),.chain_count(5'd0),.capture_enable(1'b0),.capture_after(5'd0),
  .block_valid(1'b0),.block_ready(),.block_data(128'd0),.block_last(1'b0),
  .response_valid(),.response_digest(),.chain_feedback_valid(),.chain_feedback_counter(),
  .finish_valid(),.finish_digest(),.capture_digest(),.capture_valid(),.error());
endmodule
