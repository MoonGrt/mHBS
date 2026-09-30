`timescale 1ns/1ps
module tb_mhbs_slh_fixed_block;
 parameter [15:0] MASK=16'h101e;
 logic [5:0] node_bytes;
 logic [63:0] request_recipe,request_step_recipe,request_tree;
 logic request_chain;
 logic [255:0] secret_seed,secret_prf,public_seed,root,randomizer;
 logic [255:0] request_left,request_right;
 logic [127:0] identifier;
 logic [4:0] request_layer;
 logic [9:0] request_leaf;
 logic [6:0] request_a;
 logic [31:0] request_b;
 reg feedback;
 reg [391:0] retained_digest,final_digest;
 integer checked=0,feedback_checked=0,stream_skipped=0,parents=0;
 mhbs_recipe_lane #(.N(32),.DIGEST_BYTES(49),.RECIPE_MASK(MASK)) dut(
  .clk(1'b0),.rst(1'b0),.node_bytes,.request_recipe,.request_step_recipe,
  .request_chain,.secret_seed,.secret_prf,.public_seed,.root,.randomizer,
  .identifier,.request_layer,.request_tree,.request_leaf,.request_a,.request_b,
  .request_left,.request_right,.request_valid(1'b0),.response_ready(1'b0),
  .request_steps(5'd15),.request_capture_after(5'd7),.request_capture(1'b1),
  .message_buffer(696'd0),.message_length(7'd0),
  .list_data0(256'd0),.list_data1(256'd0));
 mhbs_recipe_lane_value_narrow_ref #(.N(32),.DIGEST_BYTES(49),.RECIPE_MASK(MASK)) reference_lane(
  .clk(1'b0),.rst(1'b0),.node_bytes,.request_recipe,.request_step_recipe,
  .request_chain,.secret_seed,.secret_prf,.public_seed,.root,.randomizer,
  .identifier,.request_layer,.request_tree,.request_leaf,.request_a,.request_b,
  .request_left,.request_right,.request_valid(1'b0),.response_ready(1'b0),
  .request_steps(5'd15),.request_capture_after(5'd7),.request_capture(1'b1),
  .message_buffer(696'd0),.message_length(7'd0),
  .list_data0(256'd0),.list_data1(256'd0));
 function automatic [391:0] pattern(input integer kind);
  for(integer j=0;j<49;j=j+1)
   pattern[j*8 +:8]=kind==0 ? 0 : kind==1 ? 255 : $random;
 endfunction
 initial begin
  // Isolate the combinational constructor. Sequential request/capture/stall
  // behavior is exercised by the existing SHAKE-vector and integration tests.
  force dut.chain_feedback_valid=feedback;
  force reference_lane.chain_feedback_valid=feedback;
  force dut.chain_feedback_counter=4'd13;
  force reference_lane.chain_feedback_counter=4'd13;
  force dut.digest=retained_digest;
  force reference_lane.digest=retained_digest;
  force dut.finish_digest=final_digest;
  force reference_lane.finish_digest=final_digest;
  for(integer n=0;n<3;n=n+1)begin
   node_bytes=16+8*n;
   for(integer shape=1;shape<16;shape=shape+1)if(MASK[shape])
   for(integer count=0;count<4;count=count+1)
   for(integer mode=0;mode<8;mode=mode+1)
   for(integer t=0;t<6;t=t+1)begin
    secret_seed=pattern(t);secret_prf=pattern(t);public_seed=pattern(t);
    root=pattern(t);randomizer=pattern(t);identifier=pattern(t);
    request_left=pattern(t);request_right=pattern(t);
    retained_digest=pattern(t);final_digest=pattern(t);
    request_layer=pattern(t);request_tree=pattern(t);request_leaf=pattern(t);
    request_a=pattern(t);request_b=pattern(t);
    request_recipe=0;request_recipe[59:56]=4'(shape);
    request_recipe[55:48]=t[0] ? 8'd6 : 8'd0;
    request_recipe[47:40]=count==3 ? 8'd255 : 8'(count);
    request_step_recipe=64'h0200010000000000;
    request_step_recipe[55:48]=t[0] ? 8'd3 : 8'd0;
    request_chain=mode[0];feedback=mode[2];
    dut.seed_phase=mode[1];reference_lane.seed_phase=mode[1];
    dut.iteration=5'd7;reference_lane.iteration=5'd7;
    dut.compound=2'(t);reference_lane.compound=2'(t);
    dut.seed_shapes=(16'b1<<shape)&MASK;reference_lane.seed_shapes=(16'b1<<shape)&MASK;
    dut.step_shapes=16'h0004&MASK;reference_lane.step_shapes=16'h0004&MASK;
    dut.legacy_value=pattern(t);reference_lane.legacy_value=dut.legacy_value;
    dut.temporary_key=pattern(t);reference_lane.temporary_key=dut.temporary_key;
    dut.mask0=pattern(t);reference_lane.mask0=dut.mask0;
    dut.mask1=pattern(t);reference_lane.mask1=dut.mask1;
    #1;
    if(dut.fixed_block!==reference_lane.fixed_block)$fatal(1,"fixed-block classification changed");
    // STREAM does not consume fast_block. Its arbitrary data may differ in
    // the specialized path; compare every bit whenever the block is used.
    if(dut.fixed_block)begin
     if(dut.fast_block!==reference_lane.fast_block)
      $fatal(1,"fixed-block mismatch mask=%h n=%0d shape=%0d arity=%0d mode=%0d pattern=%0d",MASK,node_bytes,shape,count,mode,t);
     if(dut.fast_block[1087]!==1'b1)$fatal(1,"missing final SHAKE padding bit");
     checked=checked+1;
     if(feedback)feedback_checked=feedback_checked+1;
     if(dut.shapes[2] && dut.arity==2 && !feedback)parents=parents+1;
    end else stream_skipped=stream_skipped+1;
   end
  end
  if(checked==0 || feedback_checked==0 || parents==0)$fatal(1,"missing fixed-block coverage");
  if(MASK==16'h101e && stream_skipped==0)$fatal(1,"missing stream exclusion coverage");
  $display("SLH_FIXED_BLOCK_EQ_PASS mask=%h blocks=%0d feedback=%0d parents=%0d stream_skipped=%0d",MASK,checked,feedback_checked,parents,stream_skipped);
  $finish;
 end
endmodule
