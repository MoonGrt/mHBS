`timescale 1ns/1ps
`default_nettype none
// Independent byte-serialization vectors, including rate and node boundaries.
module tb_scalar_batch #(parameter integer PIPELINE=4,UNROLL=1,parameter [15:0] RECIPE_MASK=16'hffff);
 logic clk=0;always #5 clk=~clk;
 logic rst=1,request_valid=0,response_ready=0;
 wire request_ready,response_valid,error;
 logic [5:0] node_bytes;
 logic [63:0] request_recipe;
 logic [6:0] message_length;
 logic [255:0] secret_seed,secret_prf,public_seed,root,randomizer,left,right;
 logic [127:0] identifier;
 logic [695:0] message_buffer;
 wire [7:0] list_index0,list_index1,list_next_index0;
 logic [255:0] nodes[0:135];
 wire [391:0] response_value;
 wire [255:0] response_capture;
 logic capture_requested=0;
 logic batch_mode=0,batch_valid=0,batch_ready=0;
 wire batch_accept,batch_done; wire [255:0] batch_digest;
 logic [19:0] leaf=0;
 wire [63:0] hashes,permutations,batch_hashes,batch_permutations;
 recipe #(.N(32),.DIGEST_BYTES(49),.INDEX_BITS(8),.PIPELINE(PIPELINE),.UNROLL(UNROLL),.SHARED_STATE(1'b1),.RECIPE_MASK(RECIPE_MASK)) dut(
  .clk,.rst,.batch_mode,.batch_request_valid(batch_valid),.batch_request_ready(batch_accept),
  .batch_request_tag(2'd0),.batch_steps(5'd0),.batch_capture_after(5'd0),.batch_capture_enable(1'b0),
  .batch_leaf(10'd0),.batch_a(8'd0),.batch_b(32'd0),.batch_family(2'd0),.batch_no_seed(1'b0),
  .batch_start(4'd0),.batch_initial_value(256'd0),.batch_fixed_shape(4'd4),.batch_pair(1'b0),.batch_right(256'd0),
  .batch_seed_domain(8'd0),.batch_step_domain(8'd0),.batch_response_valid(batch_done),.batch_response_ready(batch_ready),
  .batch_response_tag(),.batch_response_digest(batch_digest),.batch_response_capture(),.batch_read_tag(2'd0),
  .batch_read_digest(),.batch_read_capture(),
`ifndef SYNTHESIS
  .batch_hashes,.batch_permutations,
`endif
  .node_bytes,.request_valid,.request_ready,.request_recipe,.request_step_recipe(64'd0),
  .request_chain(1'b0),.request_steps(5'd0),.request_capture_after(5'd0),.request_capture(capture_requested),
  .secret_seed,.secret_prf,.public_seed,.root,.randomizer,.identifier,.message_buffer,.message_length,
  .request_layer(5'd3),.request_tree(64'h0123456789abcdef),.request_leaf(leaf),
  .request_a(8'd67),.request_b(32'h12345678),.request_left(left),.request_right(right),
  .list_index0,.list_index1,.list_next_index0,
  .list_data0(list_index0<136 ? nodes[list_index0] : 256'd0),
  .list_data1(list_index1<136 ? nodes[list_index1] : 256'd0),
  .response_valid,.response_ready,.response_value,.response_capture,.error
`ifndef SYNTHESIS
  ,.hash_count(hashes),.permutation_count(permutations)
`endif
 );

 task automatic tick;@(posedge clk);#1;endtask
 initial begin
  node_bytes=16;message_length=5;secret_seed=0;secret_prf=0;public_seed=0;root=0;randomizer=0;left=0;right=0;identifier=0;message_buffer=696'h0504030201;request_recipe=0;
  for(integer k=0;k<136;k++)nodes[k]=0;
  tick();tick();rst=0;
  for(integer c=0;c<3;c++)begin
   batch_mode=0;request_recipe=64'h0400000000000000;request_recipe[37:32]=c==1 ? 30 : 34;
   request_valid=1;#1;while(!request_ready)tick();tick();request_valid=0;
   while(!response_valid)tick();
   if(response_value!==((c==1) ? 392'h4411969ff8d02ec6a17c2470b328b563cc428f07d5983805e904fe7cd02f : 392'h246f8ce64411969ff8d02ec6a17c2470b328b563cc428f07d5983805e904fe7cd02f))$fatal(1,"scalar bytes c=%0d",c);
   response_ready=1;tick();response_ready=0;tick();
   batch_mode=1;batch_valid=1;#1;while(!batch_accept)tick();tick();batch_valid=0;
   while(!batch_done)tick();
   if(batch_digest!==256'h8ce64411969ff8d02ec6a17c2470b328b563cc428f07d5983805e904fe7cd02f || batch_hashes!=64'(2*(c+1)) || batch_permutations!=64'(3*(c+1)))$fatal(1,"batch after scalar length c=%0d",c);
   repeat(5)begin tick();if(!batch_done || batch_digest!==256'h8ce64411969ff8d02ec6a17c2470b328b563cc428f07d5983805e904fe7cd02f)$fatal(1,"batch stalled result");end
   batch_ready=1;tick();batch_ready=0;tick();
  end
  $display("SCALAR_BATCH_PASS 34/30/34 bytes; batch MGF only once; resetless replay and backpressure");$finish;
 end
 initial begin #1000000;$fatal(1,"timeout");end
endmodule
`default_nettype wire
