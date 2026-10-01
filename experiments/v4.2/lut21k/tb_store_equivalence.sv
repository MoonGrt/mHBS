`timescale 1ns/1ps
module store_case #(parameter FIXED=0, SPLIT=0, SINGLE=0)(output reg done=0);
 reg clk=0; always #5 clk=~clk;
 reg write0=0,write1=0;
 reg [6:0] address0=0,address1=1,read0=0,read1=1;
 reg [255:0] data0=0,data1=0;
 wire [255:0] a0,a1,b0,b1;
 mhbs_value_store #(.WIDTH(256),.DEPTH(68),.ADDRESS_BITS(7),.SINGLE_READ(SINGLE),.FIXED_BANK_WRITES(FIXED),.SPLIT_TAIL(SPLIT)) dut
 (.clk,.write0,.write1,.address0,.address1,.read0,.read1,.data0,.data1,.value0(a0),.value1(a1));
 mhbs_value_store_ref #(.WIDTH(256),.DEPTH(68),.ADDRESS_BITS(7),.SINGLE_READ(SINGLE)) refdut
 (.clk,.write0,.write1,.address0,.address1,.read0,.read1,.data0,.data1,.value0(b0),.value1(b1));
 reg [31:0] rng=32'h374adfed;
 function automatic [31:0] next_rng(input [31:0] v); next_rng=(v<<1) ^ (v[31]?32'h04c11db7:0); endfunction
 integer i,j,tail_reads=0,dual_writes=0;
 task step;
 begin
  @(posedge clk); #1;
  if(a0!==b0 || a1!==b1) $fatal(1,"store mismatch F=%0d T=%0d S=%0d read=%0d,%0d",FIXED,SPLIT,SINGLE,read0,read1);
  if(read0>=64) tail_reads++;
  if(write0 && write1)dual_writes++;
  @(negedge clk);
 end endtask
 initial begin
  @(negedge clk);
  for(i=0;i<34;i++) begin
   write0=1;write1=1;address0=i*2;address1=i*2+1;read0=i*2;read1=i*2+1;
   data0={8{32'h12345678+i}};data1=~data0;step();
  end
  // Single writes model an odd endpoint count and FORS root insertion.
  for(i=0;i<68;i++)begin
   write0=!i[0];write1=i[0];address0={i[6:1],1'b0};address1={i[6:1],1'b1};
   data0={8{32'h98765432+i}};data1=data0;read0=i;read1=i^1;step();
  end
  for(i=0;i<2000;i++)begin
   rng=next_rng(rng);write0=rng[0];write1=rng[3];
   rng=next_rng(rng);address0=(rng%34)*2;
   rng=next_rng(rng);address1=(rng%34)*2+1;
   if(!FIXED) begin address0=address0 | rng[10];address1={address1[6:1],rng[11]};end
   rng=next_rng(rng);read0=rng%68;read1=read0^1;
   for(j=0;j<8;j++)begin rng=next_rng(rng);data0[j*32+:32]=rng;rng=next_rng(rng);data1[j*32+:32]=rng;end
   step();
  end
  write0=0;write1=0;
  for(i=0;i<68;i++) begin read0=i;read1=i^1;step();end
  if(!tail_reads || !dual_writes)$fatal(1,"missing coverage");
  $display("STORE_EQ_PASS fixed=%0d split=%0d single=%0d tail=%0d dual=%0d",FIXED,SPLIT,SINGLE,tail_reads,dual_writes);done=1;
 end
endmodule
module tb_store_equivalence;
 wire [7:0] done;
 for(genvar i=0;i<8;i++) begin
  store_case #(.FIXED(i%2),.SPLIT((i/2)%2),.SINGLE(i/4)) test_case(done[i]);
 end
 initial begin wait(&done);$display("STORE_EQ_ALL_PASS");$finish;end
 initial begin #100000;$fatal(1,"timeout");end
endmodule
