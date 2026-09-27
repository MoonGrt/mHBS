`timescale 1ns/1ps
`ifdef MHBS_PARTITIONED
`define HBS_CORE dut.common.core
`else
`define HBS_CORE dut.core
`endif
module tb_mhbs_external;
 parameter [255:0] SECRET_SEED=0,SECRET_PRF=0,PUBLIC_SEED=0,RANDOMIZER=0,PUBLIC_ROOT=0;
 parameter integer OPERATION=1,MESSAGE_BYTES=1;
 parameter integer SWAP=0;
 logic clk=0,rst=1;
 wire busy,done,keygen_done,error,out_valid,out_last,result_kind;
 wire [15:0] error_code;
 wire [31:0] boot_cycles,keygen_cycles,sign_cycles,hash_count,permutation_count;
 wire [63:0] out_data;wire [7:0] out_keep;
 logic [63:0] message_data=0;logic message_valid=0;wire message_ready;
 logic [6:0] message_length=MESSAGE_BYTES[6:0];
 reg [7:0] message_bytes[0:86];
 integer sent=0,wait_cycles=0,stall=0,tail_noise=0;reg [31:0] rng=32'h51c0ffee;
 mhbs_top #(.SECRET_SEED(SECRET_SEED),.SECRET_PRF(SECRET_PRF),.PUBLIC_SEED(PUBLIC_SEED),
 .RANDOMIZER(RANDOMIZER),.PUBLIC_ROOT(PUBLIC_ROOT),.OPERATION(OPERATION),.SWAP_PHYSICAL_LANES(SWAP),.PROGRAM_INIT_FILE(""),.TEMPLATE_INIT_FILE(""),.DESCRIPTOR_INIT_FILE("")) dut(.*);
 always #5 clk=~clk;
 string directory,vector_directory,dump_path,trace_path;
 integer trace_words=0,trace_cursor=0,fault=0;
 reg [47:0] trace_expected[0:2047];
 reg [31:0] metadata[0:5];
 reg [7:0] expected_bytes[0:65535];
 integer cursor=0,cycles=0,replays=1,interrupt_run=0,dump_file=0;
 integer residency[0:63];
 task tick;begin @(posedge clk);#1;end endtask
 always @(negedge clk)begin
  if(rst)begin message_valid=0;message_data=0;rng=32'h51c0ffee;end
  else if(!(message_valid && !message_ready))begin
   rng={rng[30:0],rng[31]^rng[21]^rng[1]^rng[0]};
   message_valid=!stall || (cycles>12 && rng[1:0]!=0);
   message_data=tail_noise ? 64'hd9c8b7a695847362 : 0;
   for(integer j=0;j<8;j=j+1)if(sent+j<MESSAGE_BYTES)message_data[j*8 +:8]=message_bytes[sent+j];
  end
 end
 always @(posedge clk)begin
  if(rst)begin sent=0;wait_cycles=0;cursor=0;cycles=0;trace_cursor=0;for(integer i=0;i<64;i=i+1)residency[i]=0;end
  else begin
   cycles=cycles+1;
   if(!OPERATION && message_ready)$fatal(1,"Keygen accepted a message");
   if(message_valid && message_ready)begin
    if(sent>=MESSAGE_BYTES)$fatal(1,"accepted excess data");sent=sent+8;
   end
   if(`HBS_CORE.state==1 && !message_valid)wait_cycles=wait_cycles+1;
   if(cycles>15000000)$fatal(1,"timeout");
   if(error && !fault)$fatal(1,"V42_ERROR code=%h cycle=%0d",error_code,cycles);
   residency[`HBS_CORE.state]=residency[`HBS_CORE.state]+1;
   if(trace_words && `HBS_CORE.cmd_valid && `HBS_CORE.state==3)begin
    if(trace_cursor>=trace_words || `HBS_CORE.cmd!==trace_expected[trace_cursor])$fatal(1,"macro trace %0d",trace_cursor);
    trace_cursor=trace_cursor+1;
   end
   if(out_valid)begin
    if(result_kind!==metadata[3][0])$fatal(1,"wrong operation");
    for(integer i=0;i<8;i=i+1)if(out_keep[i])begin
     if(cursor>=metadata[0] || out_data[i*8 +:8]!==expected_bytes[cursor])
      $fatal(1,"byte=%0d got=%h expected=%h state=%0d",cursor,out_data[i*8 +:8],expected_bytes[cursor],`HBS_CORE.state);
     if(dump_file)$fwrite(dump_file,"%02x\n",out_data[i*8 +:8]);
     cursor=cursor+1;
    end
    if(out_last!==(cursor==metadata[0]))$fatal(1,"out_last");
   end
  end
 end
 initial begin
  if(!$value$plusargs("IMAGE=%s",directory))$fatal(1,"IMAGE required");
  if(!$value$plusargs("VECTOR=%s",vector_directory))$fatal(1,"VECTOR required");
  if($value$plusargs("STALL=%d",stall))begin end
  if($value$plusargs("TAIL_NOISE=%d",tail_noise))begin end
  if($value$plusargs("REPLAYS=%d",replays))begin end
  if($value$plusargs("INTERRUPT=%d",interrupt_run))begin end
  if($value$plusargs("DUMP=%s",dump_path))dump_file=$fopen(dump_path,"w");
  $readmemh({directory,"/program.mem"},dut.program_memory);
  $readmemh({directory,"/template.mem"},dut.template_memory);
  $readmemh({directory,"/descriptor.mem"},dut.descriptor_memory);
  $readmemh({vector_directory,"/metadata.mem"},metadata);
  $readmemh({vector_directory,"/expected.mem"},expected_bytes,0,metadata[0]-1);
  if(metadata[3]!=OPERATION || metadata[5]!=MESSAGE_BYTES)$fatal(1,"parameter/vector mismatch");
  if(MESSAGE_BYTES>0)$readmemh({vector_directory,"/message.mem"},message_bytes,0,MESSAGE_BYTES-1);
  if($value$plusargs("TRACE=%s",trace_path))begin
   if(!$value$plusargs("TRACE_WORDS=%d",trace_words))$fatal(1,"TRACE_WORDS required");
   $readmemh(trace_path,trace_expected,0,trace_words-1);
  end
  if($value$plusargs("FAULT=%d",fault))begin end
  repeat(4)tick();rst=0;
  if(interrupt_run)begin repeat(1000)tick();rst=1;repeat(4)tick();rst=0;end
  if(fault)begin
   if(fault==2)while(cursor<metadata[4])tick();
   while(!(`HBS_CORE.lane_valid[0] && `HBS_CORE.response_pending[0]))tick();
   force `HBS_CORE.lanes[0].lane.error=1;
   while(!error)tick();
   repeat(40)begin tick();if(out_valid || busy || done)$fatal(1,"fault halt");end
   $display("V42_FAULT_PASS mode=%0d prefix=%0d",fault,cursor);$finish;
  end
  for(integer run=0;run<replays;run=run+1)begin
   while(!done)tick();
   if(cursor!=metadata[0] || hash_count!=metadata[1] || permutation_count!=metadata[2])
    $fatal(1,"counts bytes=%0d hash=%0d perm=%0d expected=%0d/%0d/%0d",cursor,hash_count,permutation_count,metadata[0],metadata[1],metadata[2]);
   if(trace_words && trace_cursor!=trace_words)$fatal(1,"incomplete macro trace");
   if(boot_cycles!=2)$fatal(1,"boot cycles");
   if(metadata[3] ? keygen_cycles!=0 : sign_cycles!=0)$fatal(1,"inactive cycle counter");
   $display("EXTERNAL_PASS boot=%0d keygen=%0d sign=%0d hashes=%0d permutations=%0d swap=%0d run=%0d wait=%0d total=%0d",boot_cycles,keygen_cycles,sign_cycles,hash_count,permutation_count,SWAP,run,wait_cycles,cycles);
   for(integer i=0;i<64;i=i+1)if(residency[i])$display("RESIDENCY state=%0d cycles=%0d",i,residency[i]);
   repeat(40)begin tick();if(!done || busy || out_valid || message_ready)$fatal(1,"completion halt");end
   if(run+1<replays)begin rst=1;repeat(4)tick();rst=0;end
  end
  if(dump_file)$fclose(dump_file);
  $finish;
 end
endmodule

`undef HBS_CORE
