`timescale 1ns/1ps
`default_nettype none
// Four tags with mixed lengths, response stalls, capture retention and reuse.
module tb_pipeline;
 logic clk=0;always #5 clk=~clk;
 logic rst=1,valid=0,ready_response=0;
 wire ready,response_valid;
 logic [1:0] tag=0,family;
 wire [1:0] response_tag;
 logic [4:0] steps=0,capture_after=0;
 logic no_seed=0;
 logic [7:0] a=0;
 logic [255:0] initial_value=0,secret_seed,public_seed;
 logic [127:0] identifier;
 wire [255:0] digest,capture;
 wire [63:0] hashes,permutations;
 recipe #(.N(32),.DIGEST_BYTES(49),.INDEX_BITS(8),.PIPELINE(4),.UNROLL(1),.SHARED_STATE(1'b1)) dut(
  .clk,.rst,.batch_mode(1'b1),.batch_request_valid(valid),.batch_request_ready(ready),
  .batch_request_tag(tag),.batch_steps(steps),.batch_capture_after(capture_after),.batch_capture_enable(1'b1),
  .batch_leaf(leaf),.batch_a(a),.batch_b(32'd0),.batch_family(family),.batch_no_seed(no_seed),
  .batch_start(4'd0),.batch_initial_value(initial_value),.batch_fixed_shape(4'd0),.batch_pair(1'b0),.batch_right(256'd0),
  .batch_seed_domain(8'h83),.batch_step_domain(8'h83),.batch_response_valid(response_valid),.batch_response_ready(ready_response),
  .batch_response_tag(response_tag),.batch_response_digest(),.batch_response_capture(),.batch_read_tag(response_tag),
  .batch_read_digest(digest),.batch_read_capture(capture),
`ifndef SYNTHESIS
  .batch_hashes(hashes),.batch_permutations(permutations),
`endif
  .node_bytes(6'd32),.request_valid(1'b0),.request_ready(),.request_recipe(64'd0),.request_step_recipe(64'd0),
  .request_chain(1'b0),.request_steps(5'd0),.request_capture_after(5'd0),.request_capture(1'b0),
  .secret_seed,.secret_prf(256'd0),.public_seed,.root(256'd0),.randomizer(256'd0),.identifier,
  .message_buffer(696'd0),.message_length(7'd0),.request_layer(5'd3),.request_tree(64'h0123456789abcdef),
  .request_leaf(20'd0),.request_a(8'd0),.request_b(32'd0),.request_left(256'd0),.request_right(256'd0),
  .list_index0(),.list_index1(),.list_next_index0(),.list_data0(256'd0),.list_data1(256'd0),
  .response_valid(),.response_ready(1'b0),.response_value(),.response_capture(),.error()
`ifndef SYNTHESIS
  ,.hash_count(),.permutation_count()
`endif
 );
`ifdef SYNTHESIS
 longint unsigned observed_permutations=0;
 assign hashes=observed_permutations;
 assign permutations=observed_permutations;
 always @(posedge clk)begin
  if(rst)observed_permutations=0;
  else if(dut.batch_perm_done)observed_permutations++;
 end
`endif
 logic [778:0] vectors[0:7];
 integer slot_row[0:3];integer expected_hashes,cycles=0,same_edge=0,non_order=0,retired=0;
 logic [19:0] leaf=20'd513;
 string vector_file;integer family_arg;
 task automatic tick;
  @(posedge clk);#1;cycles++;if(cycles>10000)$fatal(1,"timeout");
 endtask
 task automatic select_row(input integer row,input integer slot);
  tag=2'(slot);a=8'(row+1);initial_value=vectors[row][767:512];
  steps=vectors[row][772:768];capture_after=vectors[row][777:773];no_seed=vectors[row][778];
 endtask
 task automatic check_response(input integer row);
  if(digest!==vectors[row][511:256] || capture!==vectors[row][255:0])$fatal(1,"family %0d row %0d digest/capture",family,row);
 endtask
 initial begin
  if(!$value$plusargs("VECTOR=%s",vector_file) || !$value$plusargs("FAMILY=%d",family_arg) || !$value$plusargs("HASHES=%d",expected_hashes))$fatal(1,"arguments");
  if($value$plusargs("LEAF=%d",leaf))begin end
  family=2'(family_arg);$readmemh(vector_file,vectors);
  for(integer k=0;k<32;k++)begin secret_seed[k*8+:8]=8'(k+1);public_seed[k*8+:8]=8'(k+65);end
  for(integer k=0;k<16;k++)identifier[k*8+:8]=8'(k+225);
  tick();tick();rst=0;tick();
  for(integer row=0;row<4;row++)begin
   select_row(row,row);valid=1;
   do begin @(negedge clk);end while(!ready);
   slot_row[row]=row;tick();valid=0;
  end
  // Captures remain readable while every completion is held unconsumed.
  repeat(40)tick();
  while(retired<8)begin
   while(!response_valid)tick();
   begin
    integer slot,row,next_row;logic refill;
    slot=int'(response_tag);row=slot_row[slot];next_row=retired+4;
    if(row!=retired)non_order++;
    check_response(row);
    repeat(3)begin tick();if(response_tag!=2'(slot))$fatal(1,"held tag changed");check_response(row);end
    ready_response=1;refill=retired<4;
    if(refill)begin select_row(next_row,slot);valid=1;end
    @(negedge clk);
    if(refill && ready)begin same_edge++;slot_row[slot]=next_row;refill=0;end
    tick();ready_response=0;
    if(!refill)valid=0;
    else begin
     do begin @(negedge clk);end while(!ready);
     slot_row[slot]=next_row;tick();valid=0;
    end
    retired++;
   end
  end
  repeat(4)tick();
  if(response_valid || !same_edge || !non_order || hashes!=expected_hashes || permutations!=hashes)$fatal(1,"coverage/counts %0d %0d %0d/%0d",same_edge,non_order,hashes,expected_hashes);
  $display("PIPELINE_PASS family=%0d requests=8 returns=8 simultaneous=%0d unordered=%0d hashes=%0d",family,same_edge,non_order,hashes);$finish;
 end
endmodule
`default_nettype wire
