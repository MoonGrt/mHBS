`timescale 1ns/1ps
`default_nettype none
// Independent byte-serialization vectors, including rate and node boundaries.
module tb_scalar_chain #(parameter integer PIPELINE=4,UNROLL=1,parameter [15:0] RECIPE_MASK=16'hffff);
 logic clk=0;always #5 clk=~clk;
 logic rst=1,request_valid=0,response_ready=0;
 wire request_ready,response_valid,error;
 logic [5:0] node_bytes;
 logic [63:0] request_recipe,step_recipe;
 logic [4:0] chain_steps,capture_after;
 logic [6:0] message_length;
 logic [255:0] secret_seed,secret_prf,public_seed,root,randomizer,left,right;
 logic [127:0] identifier;
 logic [695:0] message_buffer;
 wire [7:0] list_index0,list_index1,list_next_index0;
 logic [255:0] nodes[0:135];
 wire [391:0] response_value;
 wire [255:0] response_capture;
 logic capture_requested=0;
 wire [63:0] hashes,permutations,batch_hashes,batch_permutations;
 recipe #(.N(32),.DIGEST_BYTES(49),.INDEX_BITS(8),.PIPELINE(PIPELINE),.UNROLL(UNROLL),.SHARED_STATE(1'b1),.RECIPE_MASK(RECIPE_MASK)) dut(
  .clk,.rst,.batch_mode(1'b0),.batch_request_valid(1'b0),.batch_request_ready(),
  .batch_request_tag(2'd0),.batch_steps(5'd0),.batch_capture_after(5'd0),.batch_capture_enable(1'b0),
  .batch_leaf(10'd0),.batch_a(8'd0),.batch_b(32'd0),.batch_family(2'd0),.batch_no_seed(1'b0),
  .batch_start(4'd0),.batch_initial_value(256'd0),.batch_fixed_shape(4'd0),.batch_pair(1'b0),.batch_right(256'd0),
  .batch_seed_domain(8'd0),.batch_step_domain(8'd0),.batch_response_valid(),.batch_response_ready(1'b0),
  .batch_response_tag(),.batch_response_digest(),.batch_response_capture(),.batch_read_tag(2'd0),
  .batch_read_digest(),.batch_read_capture(),
`ifndef SYNTHESIS
  .batch_hashes,.batch_permutations,
`endif
  .node_bytes,.request_valid,.request_ready,.request_recipe,.request_step_recipe(step_recipe),
  .request_chain(1'b1),.request_steps(chain_steps),.request_capture_after(capture_after),.request_capture(capture_requested),
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
`ifdef SYNTHESIS
 // Count functional permutation completions independently of removed ports.
 longint unsigned observed_hashes=0,observed_permutations=0;
 assign hashes=observed_hashes;
 assign permutations=observed_permutations;
 assign batch_hashes=0;
 assign batch_permutations=0;
 always @(posedge clk)begin
  if(rst)begin observed_hashes=0;observed_permutations=0;end
  else begin
`ifdef MHBS_SHA2
   if(dut.hash_complete_event)observed_hashes++;
   if(dut.compression_complete_event)observed_permutations++;
`else
   if(dut.permutation_complete)begin
    observed_permutations++;
    if(dut.running_last)observed_hashes++;
   end
   if(dut.batch_perm_done)begin observed_hashes++;observed_permutations++;end
`endif
  end
 end
`endif

 logic [575:0] vectors[0:2047];logic [19:0] leaf;
 string vector_file;integer count,timeout;
 longint unsigned baseline_hashes,baseline_perms,cycles;
 task automatic tick;@(posedge clk);#1;cycles++;endtask
 initial begin
  cycles=0;
  for(integer k=0;k<32;k++)begin
   secret_seed[k*8+:8]=8'(k+1);secret_prf[k*8+:8]=8'(k+33);public_seed[k*8+:8]=8'(k+65);
   root[k*8+:8]=8'(k+97);randomizer[k*8+:8]=8'(k+129);left[k*8+:8]=8'(k+161);right[k*8+:8]=8'(k+193);
  end
  for(integer k=0;k<16;k++)identifier[k*8+:8]=8'(k+225);
  message_buffer=0;message_length=1;capture_requested=1;
  if(!$value$plusargs("VECTOR=%s",vector_file) || !$value$plusargs("COUNT=%d",count))$fatal(1,"VECTOR/COUNT");
  $readmemh(vector_file,vectors);
  for(integer c=0;c<count;c++)begin
   request_valid=0;response_ready=0;
   if(c%2==0)begin rst=1;tick();tick();rst=0;end
   baseline_hashes=hashes;baseline_perms=permutations;
   chain_steps=vectors[c][516:512];capture_after=vectors[c][521:517];
   node_bytes=vectors[c][527:522];leaf=vectors[c][555:536];
   request_recipe={4'd0,4'd1,8'h83,8'd1,10'd0,6'd63,24'd0};
   step_recipe={4'd0,4'd2,vectors[c][535:528],8'd1,10'd0,6'd63,24'd0};
   tick();request_valid=1;tick();request_valid=0;timeout=0;
   while(!response_valid)begin tick();timeout++;if(timeout>10000 || error)$fatal(1,"case %0d timeout/error",c);end
   if(response_value[391:256]!==0 || response_value[255:0]!==vectors[c][255:0] || response_capture!==vectors[c][511:256])
    $fatal(1,"case %0d chain output/capture mismatch n=%0d steps=%0d cap=%0d leaf=%0d got=%h exp=%h capgot=%h capexp=%h",c,node_bytes,chain_steps,capture_after,leaf,response_value[255:0],vectors[c][255:0],response_capture,vectors[c][511:256]);
   if(hashes-baseline_hashes!=chain_steps+1 || permutations-baseline_perms!=chain_steps+1)$fatal(1,"chain count mismatch");
   repeat(1+c%5)begin tick();if(!response_valid || response_value[255:0]!==vectors[c][255:0])$fatal(1,"response hold");end
   response_ready=1;tick();response_ready=0;tick();
  end
  $display("SCALAR_CHAIN_PASS cases=%0d total_test_cycles=%0d",count,cycles);$finish;
 end
endmodule
`default_nettype wire
