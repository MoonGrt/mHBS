`timescale 1ns/1ps
module tb_ku_store;
 logic clk=0;
 always #5 clk=~clk;
 logic [3:0] write_enable;
 logic [6:0] base_address;
 logic [31:0] base_data;
 wire [6:0] write_address [0:3];
 wire [255:0] write_data [0:3];
 for(genvar lane=0;lane<4;lane++)begin: inputs
  assign write_address[lane]=base_address+lane;
  assign write_data[lane]=256'(base_data+lane);
 end
 logic [6:0] read0,read1;
 wire [255:0] value0,value1;
 mhbs_ku_store #(.WIDTH(256),.DEPTH(68),.ADDRESS_BITS(7),.LANES(4)) dut(.*);
 initial begin
  write_enable=0;base_address=0;base_data=32'h10203040;read0=0;read1=0;
  @(negedge clk);write_enable=4'b1111;
  @(negedge clk);write_enable=0;
  for(int i=0;i<4;i++)begin read0=i;read1=3-i;#1;
   if(value0!==256'(32'h10203040+i) || value1!==256'(32'h10203040+3-i))$fatal(1,"first four-way mismatch %0d",i);
  end
  base_address=4;base_data=32'h50607080;
  @(negedge clk);write_enable=4'b1111;
  @(negedge clk);write_enable=0;
  for(int i=0;i<4;i++)begin read0=i+4;read1=7-i;#1;
   if(value0!==256'(32'h50607080+i) || value1!==256'(32'h50607080+3-i))$fatal(1,"second four-way mismatch %0d got=%h",i,value0);
  end
  $display("KU_STORE_FOUR_WAY_PASS");$finish;
 end
endmodule
