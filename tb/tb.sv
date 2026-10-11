`timescale 1ns/1ps
// Runtime Job/ROM common-core harness, including the production signature store.
module tb;
 parameter integer UNROLL=1,PIPELINE=1;
`ifdef SYNTHESIS
 localparam bit DEBUG_STATS=0;
`else
 localparam bit DEBUG_STATS=1;
`endif
 logic clk=0,rst=1;always #5 clk=~clk;
 reg [63:0] pm[0:15],tm[0:15],dm[0:31];
 wire [3:0] program_address,template_address;wire [9:0] descriptor_addresses;
 wire [63:0] program_data=pm[program_address],template_data=tm[template_address];
 wire [127:0] descriptor_data={dm[descriptor_addresses[9:5]],dm[descriptor_addresses[4:0]]};
 reg [255:0] cfg[0:8],nodes_mem[0:1557];reg [63:0] meta[0:4];
 reg [7:0] msg[0:86],expected[0:65535];
 wire [255:0] job_secret_seed=cfg[0],job_secret_prf=cfg[1],job_public_seed=cfg[2],job_randomizer=cfg[3],job_public_root=cfg[4];
 wire [127:0] job_identifier=cfg[5][127:0];wire [31:0] job_index=cfg[6][31:0];wire [1:0] job_operation=cfg[7][1:0];
 wire [6:0] message_length=job_operation==0 ? 0 : cfg[8][6:0];
 logic [63:0] message_data=0;logic message_valid=0;wire message_ready;
 logic verify_valid=0;logic [255:0] verify_data=0;wire verify_ready,verify_pass;
 wire out_valid;wire [255:0] out_data;wire [5:0] out_bytes;wire [1:0] result_kind;
 wire busy,done,keygen_done,error;wire [15:0] error_code;
 wire [63:0] boot_cycles,keygen_cycles,sign_cycles,hash_count,permutation_count;
 common #(.UNROLL(UNROLL),.PIPELINE(PIPELINE)) dut(.*);
`ifdef SYNTHESIS
 // Harness-only placeholders; these ports do not exist on the synthesized RTL.
 assign error_code=0;
 assign boot_cycles=0;
 assign keygen_cycles=0;
 assign sign_cycles=0;
 assign hash_count=0;
 assign permutation_count=0;
`endif
 logic read_enable=0;logic [10:0] read_address=0;
 wire read_valid,complete,store_error;wire [255:0] read_data;wire [5:0] read_bytes,node_bytes;wire [10:0] nodes;wire [15:0] length;
 signature cache(.clk,.rst,.finish(done),.abort(error),.write_valid(out_valid&&job_operation==1),.write_data(out_data),.write_bytes(out_bytes),.read_enable,.read_address,.read_valid,.read_data,.read_bytes,.node_bytes,.complete,.error(store_error),.nodes,.length);
 longint unsigned cycles=0,compute=0;
 integer cursor=0,sent=0,accepted=0,stall=0,replays=1,interrupt_run=0,invalid=0,tamper=0,fault=0,cut=0,invalid_profile=-1;
 longint unsigned hashes[0:1],perms[0:1];longint unsigned computed,elapsed,hcount,pcount;
 logic override_q_valid=0;logic [31:0] override_q=0;
 longint unsigned timeout_cycles=64'd100000000000;
 reg [31:0] rng=32'h51c0ffee;string vector;
 integer batch_live=0,batch_max_live=0,batch_requests=0,batch_returns=0;
 logic [PIPELINE-1:0] batch_tags=0;
 logic [3:0] fors_positions=0;
 integer ltree_odd=0,rolling_reuse=0;
 always @(posedge clk)begin
  if(dut.core.execution_rst)begin batch_live=0;batch_max_live=0;batch_requests=0;batch_returns=0;batch_tags=0;fors_positions=0;ltree_odd=0;rolling_reuse=0;end
  else begin
   begin
    if(dut.core.state==58 && dut.core.fors_target_wave)fors_positions[dut.core.target[1:0]]=1;
    if(dut.core.state==46 && dut.core.lt_count[0])ltree_odd++;
    if(dut.core.pipe_rolling && dut.core.pipe_selected && dut.core.pipe_ready && dut.core.pipe_valid
      && dut.core.lane.batch_request_tag==dut.core.pipe_tag)rolling_reuse++;
    if(dut.core.state==55 && dut.core.endpoint_write)$fatal(1,"L-tree writes before batch inputs accepted");
   end
   // Retire before allocation: a slot may be reused on the same edge.
   if(dut.core.pipe_valid&&dut.core.lane.batch_response_ready)begin
    if(!batch_tags[dut.core.pipe_tag])$fatal(1,"unallocated batch return");
    batch_tags[dut.core.pipe_tag]=0;batch_live--;batch_returns++;
   end
   if(dut.core.pipe_selected&&dut.core.pipe_ready)begin
    if(batch_tags[dut.core.lane.batch_request_tag])$fatal(1,"live tag overwritten");
    batch_tags[dut.core.lane.batch_request_tag]=1;batch_live++;batch_requests++;
   end
   if(batch_live>batch_max_live)batch_max_live=batch_live;
   if(batch_live>PIPELINE)$fatal(1,"too many live batch contexts");
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
   if(cycles>timeout_cycles)$fatal(1,"timeout state=%0d",dut.core.state);
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
  if($value$plusargs("Q=%d",override_q))begin override_q_valid=1;end
  if($value$plusargs("PROFILE=%d",invalid_profile))begin invalid=1;end
  if($value$plusargs("TIMEOUT=%d",timeout_cycles))begin end
  $readmemh({vector,"/program.mem"},pm);$readmemh({vector,"/template.mem"},tm);$readmemh({vector,"/descriptor.mem"},dm);
  $readmemh({vector,"/job.mem"},cfg);$readmemh({vector,"/meta.mem"},meta);$readmemh({vector,"/message.mem"},msg);
  $readmemh({vector,"/expected.mem"},expected);$readmemh({vector,"/nodes.mem"},nodes_mem);
  if(override_q_valid)cfg[6]={224'd0,override_q};
  if(invalid_profile>=0)dm[1]=64'(invalid_profile);
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
    if(fault==3)force dut.core.state=type(dut.core.state)'(7'd127);
    else force dut.core.lane.error=1;
    while(!error)tick();
`ifndef SYNTHESIS
    if(error_code!=(fault==3 ? 16'h3006 : 16'h3007))$fatal(1,"fault code %h",error_code);
`endif
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
   if(invalid)begin
    if(!error)$fatal(1,"index rejection");
`ifndef SYNTHESIS
    if(error_code!=(invalid_profile>=0 ? 16'h3009 : 16'h3008))$fatal(1,"index rejection code");
`endif
   end
   else begin
    if(PIPELINE>1 && dut.core.stateful && (batch_max_live<2 || batch_live!=0 || batch_requests!=batch_returns))
     $fatal(1,"stateful batch overlap/drain %0d/%0d max %0d",batch_requests,batch_returns,batch_max_live);
    $display("BATCH_OBSERVED requests=%0d returns=%0d max_live=%0d",batch_requests,batch_returns,batch_max_live);
     $display("P4_COVERAGE fors_positions=%h ltree_odd=%0d rolling_reuse=%0d",fors_positions,ltree_odd,rolling_reuse);
    if(cursor!=meta[0])$fatal(1,"length %0d expected %0d",cursor,meta[0]);
    if(job_operation==2)begin
     if(accepted!=meta[3]||verify_pass!==(tamper==0))$fatal(1,"verify %0d nodes %0d",verify_pass,accepted);
    end
    if(!tamper)begin
     if(hcount!=meta[1]||pcount!=meta[2])$fatal(1,"counts %0d/%0d expected %0d/%0d",hcount,pcount,meta[1],meta[2]);
    end
    if(DEBUG_STATS)begin
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
endmodule
