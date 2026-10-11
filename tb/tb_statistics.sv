`timescale 1ns/1ps
// Event-driven carry check: exercise a real accepted fixed request across 2^32.
module tb_statistics;
 logic clk=0;always #5 clk=~clk;
 logic rst=1,request_valid=0,perm_done=0;
 wire request_ready,response_valid,perm_valid;
 wire [63:0] hash_count,permutation_count;
 pipeline #(.PIPELINE(1)) dut(
  .clk,.rst,.node_bytes(6'd32),.request_valid,.request_ready,.request_tag(1'b0),
  .request_steps(5'd0),.request_capture_after(5'd0),.request_capture(1'b0),
  .request_family(2'd0),.request_no_seed(1'b1),.request_start(4'd0),.request_initial_value(256'd0),
  .request_fixed_shape(4'd2),.request_pair(1'b0),.request_right(256'd0),
  .identifier(128'd0),.secret_seed(256'd0),.public_seed(256'd0),
  .request_layer(5'd0),.request_tree(64'd0),.request_leaf(20'd0),.request_a(8'd0),.request_b(32'd0),
  .seed_domain(8'd0),.step_domain(8'd0),.read_tag(1'b0),.read_digest(),.read_capture(),
  .response_valid,.response_ready(1'b1),.response_tag(),.response_digest(),.response_capture(),
  .perm_valid,.perm_ready(1'b1),.perm_state(),.perm_tag(),.perm_done,.perm_digest(1600'd0),.perm_result_tag(1'b0)
`ifndef SYNTHESIS
  ,.hash_count,.permutation_count
`endif
 );
 initial begin
  repeat(3)@(negedge clk);rst=0;
`ifndef SYNTHESIS
  dut.hash_count=64'hffffffff;dut.permutation_count=64'hffffffff;
`endif
  request_valid=1;@(posedge clk);#1;
  if(!perm_valid && !dut.busy[0])$fatal(1,"fixed request not accepted");
  @(negedge clk);request_valid=0;perm_done=1;
  @(posedge clk);#1;
`ifdef SYNTHESIS
  if(!response_valid)$fatal(1,"functional completion lost when diagnostics absent");
`else
  if(hash_count!=64'h100000000 || permutation_count!=64'h100000000)$fatal(1,"64-bit carry lost");
`endif
  $display("STATISTICS_PASS");$finish;
 end
endmodule
