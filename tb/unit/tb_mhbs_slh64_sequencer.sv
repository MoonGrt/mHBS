`timescale 1ns/1ps
module tb_mhbs_slh64_sequencer;
 logic clk=0,rst=1,start=0,command_ready=0,command_done=0;
 wire ready,done,command_valid;
 wire [5:0] program_address;wire [3:0] template_address;wire [47:0] command;
 logic [63:0] prog[0:63],tpl[0:15];
 wire [63:0] program_data=prog[program_address],template_data=tpl[template_address];
 mhbs_program_sequencer dut(.clk,.rst,.start,.entry(5'd0),.ready,.done,.program_address,.program_data,
  .template_address,.template_data,.command_valid,.command_ready,.command_done,.command);
 always #5 clk=~clk;
 integer count=0,delay_count=0,cycles=0;
 task tick;begin @(posedge clk);#1;end endtask
 always @(posedge clk)if(!rst)begin
  cycles=cycles+1;if(cycles>1000)$fatal(1,"timeout");
  if(command_valid && command_ready)begin
   if(delay_count || command[23:13]!==11'((count/2)*64+count%2))$fatal(1,"nested coordinate/order %0d %h",count,command);
   count=count+1;delay_count=5;
  end
 end
 always @(negedge clk)begin
  command_ready<=cycles%3!=0;command_done<=0;
  if(delay_count>0)begin delay_count=delay_count-1;if(delay_count==0)command_done<=1;end
 end
 initial begin
  for(integer i=0;i<64;i=i+1)prog[i]=0;
  for(integer i=0;i<16;i=i+1)tpl[i]=0;
  tpl[0]=64'd9;
  prog[0]=0;
  prog[1]=(64'd2<<62)|(64'd1<<51)|(64'd1<<40);
  prog[2]=(64'd2<<62)|(64'd1<<57)|(64'd2<<51)|(64'd64<<40);
  prog[3]=64'd3<<62;
  repeat(3)tick();rst=0;tick();start=1;tick();start=0;
  while(!done)tick();
  if(count!=6 || delay_count!=0)$fatal(1,"macro completion count");
  repeat(10)tick();if(!ready || command_valid)$fatal(1,"halt");
  $display("SLH64_SEQUENCER_PASS nested_loop delayed_ready delayed_completion halt");$finish;
 end
endmodule
