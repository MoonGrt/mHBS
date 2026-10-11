`timescale 1ns/1ps
`default_nettype none
// Cross 2^32 using a real scalar request and its Keccak completion.
module tb_statistics #(parameter integer PIPELINE=1,UNROLL=1);
 logic clk=0;always #5 clk=~clk;
 logic rst=1,request_valid=0,response_ready=0;
 wire request_ready,response_valid;
 wire [391:0] response_value;
 wire [63:0] hash_count,permutation_count,batch_hashes,batch_permutations;
 integer elapsed=0,observed_permutations=0;
 // SHAKE256(public_seed || ADRS || value), all three fields 32 zero bytes.
 localparam [255:0] EXPECTED=256'h79e0588e734c8662b5c98df6a454c5155813bb2fc77c579ce637413a47b1f32b;
 recipe #(.N(32),.DIGEST_BYTES(49),.INDEX_BITS(8),.PIPELINE(PIPELINE),.UNROLL(UNROLL),.SHARED_STATE(1'b1)) dut(
  .clk,.rst,.node_bytes(6'd32),.batch_mode(1'b0),.batch_request_valid(1'b0),.batch_request_ready(),
  .batch_request_tag(1'b0),.batch_steps(5'd0),.batch_capture_after(5'd0),.batch_capture_enable(1'b0),
  .batch_leaf(20'd0),.batch_a(8'd0),.batch_b(32'd0),.batch_family(2'd0),.batch_no_seed(1'b1),
  .batch_start(4'd0),.batch_initial_value(256'd0),.batch_fixed_shape(4'd2),.batch_pair(1'b0),.batch_right(256'd0),
  .batch_seed_domain(8'd0),.batch_step_domain(8'd0),.batch_response_valid(),.batch_response_ready(1'b0),
  .batch_response_tag(),.batch_response_digest(),.batch_response_capture(),.batch_read_tag(1'b0),
  .batch_read_digest(),.batch_read_capture(),
`ifndef SYNTHESIS
  .batch_hashes,.batch_permutations,
`endif
  .request_valid,.request_ready,.request_recipe({4'd0,4'd2,8'd0,8'd1,10'd0,6'd63,24'd0}),.request_step_recipe(64'd0),
  .request_chain(1'b0),.request_steps(5'd0),.request_capture_after(5'd0),.request_capture(1'b0),
  .secret_seed(256'd0),.secret_prf(256'd0),.public_seed(256'd0),.root(256'd0),.randomizer(256'd0),.identifier(128'd0),
  .message_buffer(696'd0),.message_length(7'd0),.request_layer(5'd0),.request_tree(64'd0),
  .request_leaf(20'd0),.request_a(8'd0),.request_b(32'd0),.request_left(256'd0),.request_right(256'd0),
  .list_index0(),.list_index1(),.list_next_index0(),.list_data0(256'd0),.list_data1(256'd0),
  .response_valid,.response_ready,.response_value,.response_capture(),.error()
`ifndef SYNTHESIS
  ,.hash_count,.permutation_count
`endif
 );
 always @(posedge clk)begin
  if(rst)observed_permutations=0;
  else if(dut.permutation_complete || dut.batch_perm_done)observed_permutations++;
 end
 task automatic check_response;
  if(!response_valid || response_value!=={136'd0,EXPECTED} || observed_permutations!=1)
   $fatal(1,"fixed request completion/digest/permutation mismatch");
`ifndef SYNTHESIS
  if(hash_count+batch_hashes!=64'h100000000 || permutation_count+batch_permutations!=64'h100000000)
   $fatal(1,"64-bit carry lost");
`endif
 endtask
`ifndef SYNTHESIS
 generate if(PIPELINE==1)begin: scalar_carry
  initial begin
   wait(!rst);
   dut.hash_count=64'hffffffff;
   dut.permutation_count=64'hffffffff;
  end
 end else begin: scheduled_carry
  initial begin
   wait(!rst);
   dut.scheduled_execution.fixed_context.ctx_hash_count=64'hffffffff;
   dut.scheduled_execution.fixed_context.ctx_permutation_count=64'hffffffff;
  end
 end endgenerate
`endif
 initial begin
  repeat(3)@(negedge clk);rst=0;
  @(negedge clk);
  request_valid=1;#1;
  if(!request_ready)$fatal(1,"fixed request not ready");
  @(posedge clk);#1;@(negedge clk);request_valid=0;
  while(!response_valid)begin
   @(posedge clk);#1;elapsed++;
   if(elapsed>1000)$fatal(1,"fixed request completion timeout");
  end
  check_response();
  repeat(3)begin @(posedge clk);#1;check_response();end
  response_ready=1;@(posedge clk);#1;
  if(response_valid)$fatal(1,"completion did not retire");
  $display("STATISTICS_PASS P%0dU%0d",PIPELINE,UNROLL);$finish;
 end
endmodule
`default_nettype wire
