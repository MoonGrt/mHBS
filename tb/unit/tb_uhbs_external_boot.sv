`timescale 1ns/1ps
module tb_uhbs_external_boot;
 logic clk=0,rst=1,message_valid=0;
 logic [63:0] message_data=0;
 logic [6:0] message_length=7'd9;
 logic [6:0] kg_message_length=7'd0;
 wire message_ready,kg_ready,done,kg_done,error,busy;
 wire [31:0] boot_cycles,keygen_cycles,sign_cycles;
 `define JOB .SECRET_SEED(256'h1122),.SECRET_PRF(256'h3344),.PUBLIC_SEED(256'h5566),.RANDOMIZER(256'h7788),.PUBLIC_ROOT(256'h99aa)
 uhbs_top #(`JOB,.OPERATION(1)) dut(.clk,.rst,.message_length,.message_data,.message_valid,.message_ready,.done,.error,.busy,.boot_cycles,.keygen_cycles,.sign_cycles);
 uhbs_top #(`JOB,.OPERATION(0)) kg(.clk,.rst,.message_length(kg_message_length),.message_data,.message_valid,.message_ready(kg_ready),.done(kg_done));
 always #5 clk=~clk;
 task tick;begin @(posedge clk);#1;end endtask
 task reset;begin rst=1;message_valid=0;message_length=9;kg_message_length=0;repeat(3)tick();rst=0;end endtask
 task send(input [63:0] word);begin
  @(negedge clk);message_data=word;message_valid=1;
  do begin @(posedge clk);end while(!message_ready);
  #1;@(negedge clk);message_valid=0;
 end endtask
 always @(posedge clk)if(!rst && kg_ready)$fatal(1,"Keygen message_ready");
 initial begin
  reset();repeat(7)tick();send(64'h0807060504030201);
  // Interrupt a partially received message; the next reset starts from byte 0.
  reset();repeat(7)tick();
  for(integer run=0;run<2;run=run+1)begin
   repeat(3)tick();send(64'h1817161514131211);message_length=0;repeat(4)tick();send(64'hffeeddccbbaa9919);
   while(!done || !kg_done)tick();
   if(error || busy || boot_cycles!=2 || keygen_cycles!=0 || sign_cycles==0)$fatal(1,"status/cycles");
   if(dut.core.starts!=1 || kg.core.starts!=1)$fatal(1,"restarted");
   if(dut.core.received!=16 || dut.core.first_word!=64'h1817161514131211 || dut.core.last_word!=64'hffeeddccbbaa9919)$fatal(1,"message beats");
   message_valid=1;repeat(20)begin tick();if(message_ready || !done || busy)$fatal(1,"halt");end
   // A pulse entirely between clock edges cannot reset synchronous state.
   @(negedge clk);#1;rst=1;#1;
   if(!done || busy)$fatal(1,"unexpected asynchronous reset");
   rst=0;tick();if(!done || busy)$fatal(1,"short reset pulse sampled");
   if(run==0)reset();
  end
  reset();message_length=0;repeat(9)tick();
  if(!error || done || busy || message_ready || dut.error_code!=16'h3002)$fatal(1,"invalid sign length");
  reset();message_length=88;repeat(9)tick();
  if(!error || done || busy || message_ready || dut.error_code!=16'h3002)$fatal(1,"overlong sign length");
  reset();kg_message_length=1;repeat(9)tick();
  if(!kg.error || kg_done || kg_ready || kg.error_code!=16'h3002)$fatal(1,"invalid keygen length");
  $display("EXTERNAL_BOOT_UNIT_PASS");$finish;
 end
 initial begin #100000;$fatal(1,"timeout");end
endmodule
