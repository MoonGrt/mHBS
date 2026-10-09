`timescale 1ns/1ps
// Runtime Job/ROM common-core harness, including the production signature store.
module tb;
 parameter integer UNROLL=1,PIPELINE=1,PROFILE_ENABLE=1;
 logic clk=0,rst=1;always #5 clk=~clk;
 reg [63:0] pm[0:15],tm[0:15],dm[0:31];
 wire [3:0] program_address,template_address;wire [9:0] descriptor_addresses;
 wire [63:0] program_data=pm[program_address],template_data=tm[template_address];
 wire [127:0] descriptor_data={dm[descriptor_addresses[9:5]],dm[descriptor_addresses[4:0]]};
 reg [255:0] cfg[0:8],nodes_mem[0:1557];reg [31:0] meta[0:4];
 reg [7:0] msg[0:86],expected[0:65535];
 wire [255:0] job_secret_seed=cfg[0],job_secret_prf=cfg[1],job_public_seed=cfg[2],job_randomizer=cfg[3],job_public_root=cfg[4];
 wire [127:0] job_identifier=cfg[5][127:0];wire [31:0] job_index=cfg[6][31:0];wire [1:0] job_operation=cfg[7][1:0];
 wire [6:0] message_length=job_operation==0 ? 0 : cfg[8][6:0];
 logic [63:0] message_data=0;logic message_valid=0;wire message_ready;
 logic verify_valid=0;logic [255:0] verify_data=0;wire verify_ready,verify_pass;
 wire out_valid;wire [255:0] out_data;wire [5:0] out_bytes;wire [1:0] result_kind;
 wire busy,done,keygen_done,error;wire [15:0] error_code;
 wire [31:0] boot_cycles,keygen_cycles,sign_cycles,hash_count,permutation_count;
 common #(.UNROLL(UNROLL),.PIPELINE(PIPELINE),.PROFILE_ENABLE(PROFILE_ENABLE)) dut(.*);
 logic read_enable=0;logic [10:0] read_address=0;
 wire read_valid,complete,store_error;wire [255:0] read_data;wire [5:0] read_bytes,node_bytes;wire [10:0] nodes;wire [15:0] length;
 signature cache(.clk,.rst,.finish(done),.abort(error),.write_valid(out_valid&&job_operation==1),.write_data(out_data),.write_bytes(out_bytes),.read_enable,.read_address,.read_valid,.read_data,.read_bytes,.node_bytes,.complete,.error(store_error),.nodes,.length);
 integer cycles=0,compute=0,cursor=0,sent=0,accepted=0,stall=0,replays=1,interrupt_run=0,invalid=0,tamper=0,override_q=-1,fault=0,cut=0;
 integer hashes[0:1],perms[0:1];integer computed,elapsed,hcount,pcount;
 reg [31:0] rng=32'h51c0ffee;string vector;
 integer batch_live=0,batch_max_live=0,batch_requests=0,batch_returns=0;
 always @(posedge clk)begin
  if(dut.core.execution_rst)begin batch_live=0;batch_max_live=0;batch_requests=0;batch_returns=0;end
  else begin
   if(dut.core.pipe_selected&&dut.core.pipe_ready)begin batch_live++;batch_requests++;end
   if(batch_live>batch_max_live)batch_max_live=batch_live;
   if(dut.core.pipe_mode&&dut.core.pipe_valid)begin batch_live--;batch_returns++;end
   if(batch_live<0)$fatal(1,"duplicate batch return");
  end
 end
 always @(posedge clk)begin
  if(dut.core.execution_rst)begin hashes[0]=0;perms[0]=0;end
  else begin
   if(dut.core.lane.permutation_complete)begin
    perms[0]++;if(dut.core.lane.running_last)hashes[0]++;
   end
   if(dut.core.lane.batch_perm_done)begin perms[0]++;hashes[0]++;end
  end
 end
 initial begin hashes[1]=0;perms[1]=0;end
 always @(posedge clk)begin
  if(dut.core.rst)compute=0;
  else if(dut.core.state==0&&dut.core.job_valid)compute=0;
  else if(dut.core.state!=0&&dut.core.state!=32)compute++;
  if(rst)begin cycles=0;cursor=0;sent=0;accepted=0;end
  else begin
   cycles++;
   if(cycles>400000000)$fatal(1,"timeout state=%0d",dut.core.state);
   if(error&&!invalid&&!fault)$fatal(1,"error %h state=%0d",error_code,dut.core.state);
   if(message_valid&&message_ready)sent+=8;
   if(verify_valid&&verify_ready)accepted++;
   if(out_valid)begin
    if(out_bytes!=4&&out_bytes!=16&&out_bytes!=24&&out_bytes!=32)$fatal(1,"width %0d",out_bytes);
    for(integer i=0;i<32;i++)if(i<out_bytes)begin
     if(cursor>=meta[0]||out_data[i*8+:8]!==expected[cursor])$fatal(1,"byte %0d got %h expected %h state %0d",cursor,out_data[i*8+:8],expected[cursor],dut.core.state);
     cursor++;
    end
   end
  end
 end
 always @(negedge clk)begin
  if(rst)begin message_valid=0;verify_valid=0;rng=32'h51c0ffee;end
  else begin
   rng={rng[30:0],rng[31]^rng[21]^rng[1]^rng[0]};
   if(!(message_valid&&!message_ready))begin
    message_valid=job_operation!=0&&sent<message_length&&(!stall||rng[1:0]!=0);
    message_data=64'hfefdfcfbfaf9f8f7;
    for(integer i=0;i<8;i++)if(sent+i<message_length)message_data[i*8+:8]=msg[sent+i];
   end
   if(!(verify_valid&&!verify_ready))begin
    verify_valid=job_operation==2&&accepted<meta[3]&&(!cut||accepted<cut)&&(!stall||rng[3:0]==0);
    verify_data=accepted<meta[3]?nodes_mem[accepted]:0;
   end
  end
 end
 task tick;begin @(posedge clk);#1;end endtask
 initial begin
  if(!$value$plusargs("VECTOR=%s",vector))$fatal(1,"VECTOR");
  if($value$plusargs("FAULT=%d",fault))begin end
  if($value$plusargs("CUT=%d",cut))begin end
  if($value$plusargs("STALL=%d",stall))begin end
  if($value$plusargs("REPLAYS=%d",replays))begin end
  if($value$plusargs("INTERRUPT=%d",interrupt_run))begin end
  if($value$plusargs("INVALID=%d",invalid))begin end
  if($value$plusargs("TAMPER=%d",tamper))begin end
  if($value$plusargs("Q=%d",override_q))begin end
  $readmemh({vector,"/program.mem"},pm);$readmemh({vector,"/template.mem"},tm);$readmemh({vector,"/descriptor.mem"},dm);
  $readmemh({vector,"/job.mem"},cfg);$readmemh({vector,"/meta.mem"},meta);$readmemh({vector,"/message.mem"},msg);
  $readmemh({vector,"/expected.mem"},expected);$readmemh({vector,"/nodes.mem"},nodes_mem);
  if(override_q>=0)cfg[6]=override_q;
  case(tamper)
   1:msg[0]^=1;
   2:nodes_mem[1]^=1;
   3:nodes_mem[meta[3]-1]^=1;
   4:cfg[4]^=1;
   5:nodes_mem[0]^=1;
  endcase
  for(integer r=0;r<replays;r++)begin
   rst=1;read_enable=0;repeat(5)tick();rst=0;
   if(interrupt_run&&r==0)begin repeat(1000)tick();rst=1;repeat(5)tick();rst=0;end
   if(fault)begin
    if(fault==2)begin while(!dut.core.pipe_mode || !dut.core.lane.stage_valid)tick();end
    else begin while(dut.core.state!=23)tick();end
    force dut.core.lane.error=1;
       while(!error)tick();
    if(error_code!=16'h3007)$fatal(1,"fault code");
    repeat(40)begin tick();if(out_valid||busy||done||verify_ready||verify_pass)$fatal(1,"fault halt");end
    $display("STATEFUL_FAULT_PASS");$finish;tick();
   end
   if(cut)begin
    while(accepted<cut)tick();while(!verify_ready)tick();repeat(1000)tick();
    if(done||error||!verify_ready)$fatal(1,"truncated node wait");
    rst=1;repeat(5)tick();cut=0;rst=0;
   end
   while(!done&&!error)tick();
   computed=compute;elapsed=cycles;hcount=hashes[0]+hashes[1];pcount=perms[0]+perms[1];
   if(invalid)begin if(!error||error_code!=16'h3008)$fatal(1,"index rejection");end
   else begin
    if(PIPELINE>1 && dut.core.stateful && (batch_max_live<2 || batch_live!=0 || batch_requests!=batch_returns))
     $fatal(1,"stateful batch overlap/drain %0d/%0d max %0d",batch_requests,batch_returns,batch_max_live);
    $display("BATCH_OBSERVED requests=%0d returns=%0d max_live=%0d",batch_requests,batch_returns,batch_max_live);
    if(cursor!=meta[0])$fatal(1,"length %0d expected %0d",cursor,meta[0]);
    if(job_operation==2)begin
     if(accepted!=meta[3]||verify_pass!==(tamper==0))$fatal(1,"verify %0d nodes %0d",verify_pass,accepted);
    end
    if(!tamper)begin
     if(hcount!=meta[1]||pcount!=meta[2])$fatal(1,"counts %0d/%0d expected %0d/%0d",hcount,pcount,meta[1],meta[2]);
    end
    if(PROFILE_ENABLE)begin
     if(hash_count!=hcount||permutation_count!=pcount)$fatal(1,"statistics mismatch");
    end else if(hash_count||permutation_count||sign_cycles||keygen_cycles||boot_cycles)$fatal(1,"statistics not disabled");
    if(job_operation==1)begin
     if(!complete||length!=cursor||store_error)$fatal(1,"cache metadata");
     cursor=0;
     for(integer n=0;n<nodes;n++)begin
      read_enable=1;read_address=n;tick();
      if(!read_valid)$fatal(1,"cache read");
      for(integer b=0;b<32;b++)if(b<read_bytes)begin
       if(read_data[b*8+:8]!==expected[cursor])$fatal(1,"cache byte %0d",cursor);
       cursor++;
      end
     end
     read_enable=0;if(cursor!=meta[0])$fatal(1,"cache length");
    end
    $display("STATEFUL_PASS P%0dU%0d op=%0d cycles=%0d total=%0d hashes=%0d permutations=%0d tamper=%0d",PIPELINE,UNROLL,job_operation,computed,elapsed,hcount,pcount,tamper);
   end
  end
  if(invalid)$display("INDEX_REJECT_PASS");
  $finish;
 end

 longint states[0:63], returns[0:63], recipes[0:15];
 longint live[0:4], pipe_cycles, pipe_recycle, pipe_issue, serial_cycles, serial_rounds, stream_wait, stream_prepare;
 initial begin
  for(integer i=0;i<64;i++)begin states[i]=0;returns[i]=0;end
  for(integer i=0;i<16;i++)recipes[i]=0;
  for(integer i=0;i<=4;i++)live[i]=0;
  pipe_cycles=0;pipe_recycle=0;pipe_issue=0;serial_cycles=0;serial_rounds=0;stream_wait=0;stream_prepare=0;
 end
 always @(posedge clk)if(!rst && dut.core.state!=0)begin
  states[dut.core.state]++;
  if(dut.core.state==23)returns[dut.core.hash_return]++;
  if(dut.core.state==23)recipes[dut.core.task_recipe[59:56]]++;
  if(dut.core.pipe_mode)begin
   pipe_cycles++;live[$countones(dut.core.lane.stage_valid)]++;
   if(dut.core.lane.recycle)pipe_recycle++;
   if(dut.core.pipe_selected&&dut.core.pipe_ready)pipe_issue++;
  end else begin
   serial_cycles++;
   if(dut.core.lane.hash_state==2)serial_rounds++;
   if(dut.core.lane.hash_state==1)stream_wait++;
   if(dut.core.lane.state==2)stream_prepare++;
  end
 end
 final begin
  for(integer i=0;i<64;i++)if(states[i])$display("PROFILE_STATE %0d %0d",i,states[i]);
  for(integer i=0;i<64;i++)if(returns[i])$display("PROFILE_RETURN %0d %0d",i,returns[i]);
  for(integer i=0;i<16;i++)if(recipes[i])$display("PROFILE_RECIPE %0d %0d",i,recipes[i]);
  for(integer i=0;i<=4;i++)$display("PROFILE_LIVE %0d %0d",i,live[i]);
  $display("PROFILE_TOTAL pipe=%0d recycle=%0d issue=%0d serial=%0d serial_run=%0d stream_wait=%0d stream_prepare=%0d",pipe_cycles,pipe_recycle,pipe_issue,serial_cycles,serial_rounds,stream_wait,stream_prepare);
 end

endmodule
