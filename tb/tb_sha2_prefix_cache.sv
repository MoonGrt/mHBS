`timescale 1ns/1ps
`default_nettype none
// Cache acceptance is checked from raw compression transactions, independently
// of internal valid/hit signals. Expected digests come from full hashlib hashes.
module tb_sha2_prefix_cache #(parameter integer PIPELINE=4,UNROLL=1,
 localparam integer TAG_BITS=PIPELINE>1 ? $clog2(PIPELINE) : 1);
 logic clk=0;always #5 clk=~clk;
 logic rst=1,batch_mode=0,request_valid=0,response_ready=0;
 logic batch_valid=0,batch_response_ready=0;
 wire request_ready,response_valid,batch_ready,batch_response_valid,error;
 logic [TAG_BITS-1:0] tag=0;
 wire [TAG_BITS-1:0] response_tag;
 logic [4:0] steps=0,capture_after=0;
 logic [1:0] family=0;
 logic [7:0] address_a=0;
 logic [5:0] node_bytes=16;
 logic [63:0] request_recipe=0;
 logic [6:0] message_length=1;
 logic [255:0] secret_seed,secret_prf,public_seed,root,randomizer,left,right;
 logic [127:0] identifier;
 logic [695:0] message_buffer;
 wire [7:0] list_index0,list_index1,list_next_index0;
 logic [255:0] nodes[0:135];
 wire [391:0] response_value;
 wire [255:0] response_capture,batch_digest,batch_capture;
 recipe #(.N(32),.DIGEST_BYTES(49),.INDEX_BITS(8),.PIPELINE(PIPELINE),.UNROLL(UNROLL),.SHARED_STATE(1'b1)) dut(
  .clk,.rst,.batch_mode,.batch_request_valid(batch_valid),.batch_request_ready(batch_ready),
  .batch_request_tag(tag),.batch_steps(steps),.batch_capture_after(capture_after),.batch_capture_enable(1'b1),
  .batch_leaf(20'd65536),.batch_a(address_a),.batch_b(32'd0),.batch_family(family),.batch_no_seed(1'b0),
  .batch_start(4'd0),.batch_initial_value(256'd0),.batch_fixed_shape(4'd0),.batch_pair(1'b0),.batch_right(256'd0),
  .batch_seed_domain(8'h83),.batch_step_domain(8'h83),.batch_response_valid,.batch_response_ready,
  .batch_response_tag(response_tag),.batch_response_digest(batch_digest),.batch_response_capture(batch_capture),
  .batch_read_tag(response_tag),.batch_read_digest(),.batch_read_capture(),
`ifndef SYNTHESIS
  .batch_hashes(),.batch_permutations(),.hash_count(),.permutation_count(),
`endif
  .node_bytes,.request_valid,.request_ready,.request_recipe,.request_step_recipe(64'd0),
  .request_chain(1'b0),.request_steps(5'd0),.request_capture_after(5'd0),.request_capture(1'b0),
  .secret_seed,.secret_prf,.public_seed,.root,.randomizer,.identifier,.message_buffer,.message_length,
  .request_layer(5'd3),.request_tree(64'h0123456789abcdef),.request_leaf(20'd65536),
  .request_a(8'd67),.request_b(32'h12345678),.request_left(left),.request_right(right),
  .list_index0,.list_index1,.list_next_index0,
  .list_data0(list_index0<136 ? nodes[list_index0] : 256'd0),
  .list_data1(list_index1<136 ? nodes[list_index1] : 256'd0),
  .response_valid,.response_ready,.response_value,.response_capture,.error
 );
 localparam [255:0] IV=256'h6a09e667bb67ae853c6ef372a54ff53a510e527f9b05688c1f83d9ab5be0cd19;
 logic [511:0] expected_prefix;
 always_comb begin
  expected_prefix=0;
  if(node_bytes==16)begin
   for(integer k=0;k<16;k++)expected_prefix[511-k*8-:8]=public_seed[k*8+:8];
  end else begin
   expected_prefix[263:256]=8'd3;
   for(integer k=0;k<32;k++)expected_prefix[255-k*8-:8]=public_seed[k*8+:8];
  end
 end
 longint unsigned observed_hashes=0,observed_blocks=0,observed_prefix=0;
 always @(posedge clk)begin
  if(rst)begin observed_hashes=0;observed_blocks=0;observed_prefix=0;end
  else begin
   if(dut.hash_complete_event)observed_hashes++;
   if(dut.compression_complete_event)observed_blocks++;
   if(dut.block_ready && dut.compression_ready && dut.format_cv==IV && dut.block_buffer==expected_prefix)
    observed_prefix++;
  end
 end
 logic [1218:0] scalar_vectors[0:63];
 logic [809:0] batch_vectors[0:6*PIPELINE-1];
 logic [PIPELINE-1:0] seen;
 string scalar_file,batch_file;
 integer count,cycles=0;
 longint unsigned base_hashes,base_blocks,base_prefix;
 integer expected_hashes,logical_blocks,prefix_hashes,prefix_misses,physical_blocks;
 task automatic tick;
  @(posedge clk);#1;cycles++;if(cycles>1000000)$fatal(1,"timeout");
 endtask
 task automatic reset_lane;
  request_valid=0;batch_valid=0;response_ready=0;batch_response_ready=0;
  rst=1;tick();tick();rst=0;tick();
 endtask
 task automatic snapshot;
  base_hashes=observed_hashes;base_blocks=observed_blocks;base_prefix=observed_prefix;
 endtask
 task automatic check_counts(input integer index);
  physical_blocks=logical_blocks-prefix_hashes+prefix_misses;
  if(observed_hashes-base_hashes!=expected_hashes || observed_blocks-base_blocks!=physical_blocks ||
     observed_prefix-base_prefix!=prefix_misses)
   $fatal(1,"case %0d counts hashes=%0d/%0d blocks=%0d/%0d prefixes=%0d/%0d",index,
    observed_hashes-base_hashes,expected_hashes,observed_blocks-base_blocks,physical_blocks,
    observed_prefix-base_prefix,prefix_misses);
 endtask
 initial begin
  if(!$value$plusargs("SCALAR=%s",scalar_file) || !$value$plusargs("BATCH=%s",batch_file) ||
     !$value$plusargs("COUNT=%d",count))$fatal(1,"arguments");
  $readmemh(scalar_file,scalar_vectors);$readmemh(batch_file,batch_vectors);
  for(integer k=0;k<32;k++)begin
   secret_seed[k*8+:8]=8'(k+1);secret_prf[k*8+:8]=8'(k+33);
   root[k*8+:8]=8'(k+97);randomizer[k*8+:8]=8'(k+129);
  end
  for(integer k=0;k<16;k++)identifier[k*8+:8]=8'(k+225);
  for(integer k=0;k<87;k++)message_buffer[k*8+:8]=8'(17+3*k);
  for(integer j=0;j<136;j++)for(integer k=0;k<32;k++)nodes[j][k*8+:8]=8'(13*j+k);
  reset_lane();
  for(integer c=0;c<count;c++)begin
   if(scalar_vectors[c][1217])reset_lane();
   public_seed=scalar_vectors[c][647:392];left=scalar_vectors[c][903:648];right=scalar_vectors[c][1159:904];
   request_recipe=0;request_recipe[59:56]=scalar_vectors[c][1163:1160];request_recipe[55:48]=8'h83;
   request_recipe[47:40]=scalar_vectors[c][1171:1164];request_recipe[29:24]=63;
   request_recipe[37:32]=scalar_vectors[c][1184:1179];message_length=scalar_vectors[c][1178:1172];
   node_bytes=request_recipe[59:56] inside {1,2,3,4,12} ? 16 : 32;
   expected_hashes=int'(scalar_vectors[c][1192:1185]);logical_blocks=int'(scalar_vectors[c][1200:1193]);
   prefix_hashes=int'(scalar_vectors[c][1208:1201]);prefix_misses=int'(scalar_vectors[c][1216:1209]);
   snapshot();request_valid=1;
   do begin @(negedge clk);end while(!request_ready);
   tick();request_valid=0;
   if(scalar_vectors[c][1218])begin
    while(observed_prefix==base_prefix)tick();
    repeat(3)tick();reset_lane();snapshot();request_valid=1;
    do begin @(negedge clk);end while(!request_ready);
    tick();request_valid=0;
   end
   while(!response_valid)begin tick();if(error)$fatal(1,"scalar %0d error",c);end
   if(response_value!==scalar_vectors[c][391:0])$fatal(1,"scalar %0d digest mismatch",c);
   check_counts(c);
   repeat(5)begin
    tick();if(!response_valid || response_value!==scalar_vectors[c][391:0])$fatal(1,"scalar held response");
    check_counts(c);
   end
   response_ready=1;tick();response_ready=0;tick();
  end
  // All P contexts can arrive before the first prefix returns. Exactly one
  // cold compression is permitted; later warm waves execute no prefix block.
  batch_mode=1;reset_lane();
  for(integer group_index=0;group_index<6;group_index++)begin
   family=group_index==3 ? 1 : group_index==4 ? 2 : 0;node_bytes=family==0 ? 16 : 32;
   for(integer k=0;k<32;k++)public_seed[k*8+:8]=8'(k+65)^(group_index>=2 ? 8'ha5 : 8'd0);
   expected_hashes=0;logical_blocks=0;prefix_hashes=0;
   prefix_misses=(group_index==0 || group_index==2 || group_index==3 || group_index==5) ? 1 : 0;
   for(integer k=0;k<PIPELINE;k++)begin
    expected_hashes+=int'(batch_vectors[group_index*PIPELINE+k][793:778]);
    logical_blocks+=int'(batch_vectors[group_index*PIPELINE+k][809:794]);
   end
   if(family==0)prefix_hashes=expected_hashes;
   else if(family==1)begin
    for(integer k=0;k<PIPELINE;k++)prefix_hashes+=2*int'(batch_vectors[group_index*PIPELINE+k][772:768]);
   end
   snapshot();seen=0;
   for(integer k=0;k<PIPELINE;k++)begin
    tag=TAG_BITS'(k);address_a=8'(k+1);
    steps=batch_vectors[group_index*PIPELINE+k][772:768];
    capture_after=batch_vectors[group_index*PIPELINE+k][777:773];batch_valid=1;
    do begin @(negedge clk);end while(!batch_ready);
    tick();batch_valid=0;
   end
   repeat(20)tick();
   for(integer k=0;k<PIPELINE;k++)begin
    while(!batch_response_valid)begin tick();if(error)$fatal(1,"batch error");end
    begin
     integer index;logic [TAG_BITS-1:0] held;
     held=response_tag;index=group_index*PIPELINE+int'(held);
     if(seen[held])$fatal(1,"duplicate batch response");seen[held]=1;
     repeat(5)begin
      if(!batch_response_valid || response_tag!==held || batch_digest!==batch_vectors[index][511:256] ||
         batch_capture!==batch_vectors[index][255:0])$fatal(1,"batch group %0d tag %0d digest/capture/hold",group_index,held);
      tick();
     end
     batch_response_ready=1;tick();batch_response_ready=0;tick();
    end
   end
   check_counts(100+group_index);
  end
  $display("SHA2_PREFIX_CACHE_PASS P%0dU%0d scalar_cases=%0d batch_groups=6 contexts=%0d reset_replay=1",PIPELINE,UNROLL,count,PIPELINE);
  $finish;
 end
endmodule
`default_nettype wire
