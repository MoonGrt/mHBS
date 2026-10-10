`timescale 1ns/1ps
`default_nettype none
// Independent byte-serialization vectors, including rate and node boundaries.
module tb_recipe #(parameter integer PIPELINE=4,UNROLL=1);
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
 wire [63:0] hashes,permutations,batch_hashes,batch_permutations;
 recipe #(.N(32),.DIGEST_BYTES(49),.INDEX_BITS(8),.PIPELINE(PIPELINE),.UNROLL(UNROLL)) dut(
  .clk,.rst,.batch_mode(1'b0),.batch_request_valid(1'b0),.batch_request_ready(),
  .batch_request_tag(2'd0),.batch_steps(5'd0),.batch_capture_after(5'd0),.batch_capture_enable(1'b0),
  .batch_leaf(10'd0),.batch_a(8'd0),.batch_b(32'd0),.batch_family(2'd0),.batch_no_seed(1'b0),
  .batch_start(4'd0),.batch_initial_value(256'd0),.batch_fixed_shape(4'd0),.batch_pair(1'b0),.batch_right(256'd0),
  .batch_seed_domain(8'd0),.batch_step_domain(8'd0),.batch_response_valid(),.batch_response_ready(1'b0),
  .batch_response_tag(),.batch_response_digest(),.batch_response_capture(),.batch_read_tag(2'd0),
  .batch_read_digest(),.batch_read_capture(),.batch_hashes,.batch_permutations,
  .node_bytes,.request_valid,.request_ready,.request_recipe,.request_step_recipe(64'd0),
  .request_chain(1'b0),.request_steps(5'd0),.request_capture_after(5'd0),.request_capture(1'b0),
  .secret_seed,.secret_prf,.public_seed,.root,.randomizer,.identifier,.message_buffer,.message_length,
  .request_layer(5'd3),.request_tree(64'h0123456789abcdef),.request_leaf(leaf),
  .request_a(8'd67),.request_b(32'h12345678),.request_left(left),.request_right(right),
  .list_index0,.list_index1,.list_next_index0,
  .list_data0(list_index0<136 ? nodes[list_index0] : 256'd0),
  .list_data1(list_index1<136 ? nodes[list_index1] : 256'd0),
  .response_valid,.response_ready,.response_value,.response_capture(),.error,
  .hash_count(hashes),.permutation_count(permutations)
 );
 logic [451:0] vectors[0:2047];
 logic [19:0] leaf;
 string vector_file;integer count,timeout;
 task automatic tick;@(posedge clk);#1;endtask
 initial begin
  for(integer k=0;k<32;k++)begin
   secret_seed[k*8+:8]=8'(k+1);secret_prf[k*8+:8]=8'(k+33);public_seed[k*8+:8]=8'(k+65);
   root[k*8+:8]=8'(k+97);randomizer[k*8+:8]=8'(k+129);left[k*8+:8]=8'(k+161);right[k*8+:8]=8'(k+193);
  end
  for(integer k=0;k<16;k++)identifier[k*8+:8]=8'(k+225);
  for(integer k=0;k<87;k++)message_buffer[k*8+:8]=8'(17+3*k);
  for(integer j=0;j<136;j++)for(integer k=0;k<32;k++)nodes[j][k*8+:8]=8'(13*j+k);
  if(!$value$plusargs("VECTOR=%s",vector_file) || !$value$plusargs("COUNT=%d",count))$fatal(1,"VECTOR/COUNT");
  $readmemh(vector_file,vectors);
  for(integer c=0;c<count;c++)begin
   rst=1;request_valid=0;response_ready=0;tick();tick();rst=0;
   leaf=vectors[c][451:432];
   node_bytes=vectors[c][397:392];message_length=vectors[c][404:398];
   request_recipe={4'd0,vectors[c][408:405],8'h83,vectors[c][416:409],10'd0,6'd63,24'd0};
   tick();request_valid=1;tick();request_valid=0;
   timeout=0;
   while(!response_valid)begin tick();timeout++;if(timeout>10000 || error)$fatal(1,"case %0d timeout/error",c);end
   if(response_value!==vectors[c][391:0])$fatal(1,"case %0d n=%0d shape=%0d arity=%0d len=%0d got=%h expected=%h",c,node_bytes,request_recipe[59:56],request_recipe[47:40],message_length,response_value,vectors[c][391:0]);
   if(hashes+batch_hashes!=vectors[c][420:417] || permutations+batch_permutations!=vectors[c][431:421])$fatal(1,"case %0d counts %0d/%0d",c,hashes+batch_hashes,permutations+batch_permutations);
   repeat(3)begin tick();if(!response_valid || response_value!==vectors[c][391:0])$fatal(1,"response hold");end
   response_ready=1;tick();response_ready=0;tick();
  end
  $display("RECIPE_PASS cases=%0d",count);$finish;
 end
endmodule
`default_nettype wire
