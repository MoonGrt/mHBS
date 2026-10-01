`timescale 1ns/1ps
module shake_case #(parameter REUSE=0, STREAM=0, U=2)(output reg done=0);
 reg clk=0;always #5 clk=~clk;
 reg rst=1;
 reg [5:0] node_bytes=16;
 reg [511:0] chain_prefix_data=0;
 reg context_valid=0,fast_block_valid=0,chain_enable=0,chain_prefix=0,chain_prefix_preserve_counter=0;
 reg [1087:0] fast_block_data=0;
 reg [2:0] chain_prefix_domain=0;
 reg [4:0] chain_count=1,capture_after=0;
 reg capture_enable=0,block_valid=0,block_last=0;
 reg [127:0] block_data=0;
 wire [1:0] context_ready,fast_block_ready,block_ready,response_valid,chain_feedback_valid,finish_valid,capture_valid,error;
 wire [391:0] response_digest[2],finish_digest[2];
 wire [255:0] capture_digest[2];
 wire [3:0] chain_feedback_counter[2];
 `define CONNECT(I) .clk,.rst,.node_bytes,.chain_prefix_data,.context_valid,.fast_block_valid,.fast_block_data,.chain_enable,.chain_prefix,.chain_prefix_preserve_counter,.chain_prefix_domain,.chain_count,.capture_enable,.capture_after,.block_valid,.block_data,.block_last, .context_ready(context_ready[I]),.fast_block_ready(fast_block_ready[I]),.block_ready(block_ready[I]),.response_valid(response_valid[I]),.response_digest(response_digest[I]),.chain_feedback_valid(chain_feedback_valid[I]),.chain_feedback_counter(chain_feedback_counter[I]),.finish_valid(finish_valid[I]),.finish_digest(finish_digest[I]),.capture_digest(capture_digest[I]),.capture_valid(capture_valid[I]),.error(error[I])
 mhbs_compact_shake_context_lane #(.UNROLL(U),.N(32),.DIGEST_BYTES(49),.STREAM_CHAIN_ENABLE(STREAM),.REUSE_FAST_FEEDBACK(REUSE)) dut (`CONNECT(0));
 mhbs_compact_shake_context_lane_ref #(.UNROLL(U),.N(32),.DIGEST_BYTES(49),.STREAM_CHAIN_ENABLE(STREAM),.REUSE_FAST_FEEDBACK(REUSE)) refdut (`CONNECT(1));
 `undef CONNECT
 reg [31:0] rng=32'hcf012456;
 function automatic [31:0] next_rng(input [31:0] v); next_rng=(v<<1) ^ (v[31]?32'h04c11db7:0); endfunction
 integer i,j,fasts=0,streams=0,feedbacks=0,clears=0,finishes=0,resets=0;
 always @(posedge clk) begin
  if(!rst)begin
   if(dut.take_fast)fasts++;
   if(dut.take_stream)streams++;
   if(dut.take_feedback)feedbacks++;
   if(dut.clear_stream)clears++;
   if(finish_valid[0])finishes++;
  end
  #1;
  if({context_ready[0],fast_block_ready[0],block_ready[0],response_valid[0],chain_feedback_valid[0],finish_valid[0],capture_valid[0],error[0],chain_feedback_counter[0],response_digest[0],finish_digest[0],capture_digest[0]} !==
     {context_ready[1],fast_block_ready[1],block_ready[1],response_valid[1],chain_feedback_valid[1],finish_valid[1],capture_valid[1],error[1],chain_feedback_counter[1],response_digest[1],finish_digest[1],capture_digest[1]})
   $fatal(1,"SHAKE mismatch reuse=%0d stream=%0d U=%0d step=%0d",REUSE,STREAM,U,i);
  if(dut.sponge_state!==refdut.sponge_state)$fatal(1,"state mismatch");
 end
 initial begin
  for(i=0;i<12000;i++)begin
   @(negedge clk);rng=next_rng(rng);
   rst=(i<2 || i%503==0);if(rst)resets++;
   context_valid=context_ready[0] && rng[0];
   fast_block_valid=rng[1] && (context_valid || fast_block_ready[0]);
   block_valid=rng[2];block_last=refdut.append_index==8 || rng[7:4]==0;
   if(context_valid)begin
    case(rng[5:4]) 0:node_bytes=16;1:node_bytes=24;default:node_bytes=32;endcase
    chain_enable=rng[6];chain_count=2+{3'b0,rng[9:8]};chain_prefix=rng[10];
    chain_prefix_preserve_counter=rng[11];chain_prefix_domain=rng[14:12];capture_enable=rng[15];capture_after=1;
    for(j=0;j<16;j++)begin rng=next_rng(rng);chain_prefix_data[32*j+:32]=rng;end
   end
   for(j=0;j<34;j++)begin rng=next_rng(rng);fast_block_data[32*j+:32]=rng;end
   for(j=0;j<4;j++)begin rng=next_rng(rng);block_data[32*j+:32]=rng;end
  end
  @(negedge clk);rst=1;context_valid=0;block_valid=0;fast_block_valid=0;
  if(!fasts || !streams || !feedbacks || !clears || !finishes || resets<3)$fatal(1,"missing coverage %0d %0d %0d %0d %0d",fasts,streams,feedbacks,clears,finishes);
  $display("SHAKE_EQ_PASS reuse=%0d stream=%0d U=%0d fast=%0d stream=%0d feedback=%0d clear=%0d finish=%0d",REUSE,STREAM,U,fasts,streams,feedbacks,clears,finishes);done=1;
 end
endmodule
module tb_shake_equivalence;
 wire [5:0] done;
 for(genvar i=0;i<4;i++) begin
  shake_case #(.REUSE(i%2),.STREAM(i/2)) test_case(done[i]);
 end
 shake_case #(.REUSE(1),.STREAM(0),.U(1)) u1(done[4]);
 shake_case #(.REUSE(1),.STREAM(0),.U(4)) u4(done[5]);
 initial begin wait(&done);$display("SHAKE_EQ_ALL_PASS");$finish;end
 initial begin #130000;$fatal(1,"timeout");end
endmodule
