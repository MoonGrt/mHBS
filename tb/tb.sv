`timescale 1ns/1ps
// A single executable loads all six profiles and three entrypoints at runtime.
module tb;
    `include "rtl/executor/instructions.svh"
    import "DPI-C" function void micro_trace_reset();
    import "DPI-C" function void micro_trace_sample(input longint unsigned recipe,
        input int unsigned layer,input longint unsigned tree,
        input int unsigned leaf,input int unsigned a,input int unsigned b,input bit [391:0] result);
    import "DPI-C" function string micro_trace_digest();
    import "DPI-C" function int unsigned micro_trace_samples();
    parameter bit SWAP=0,PROFILE_ENABLE=1;
    logic clk=0,rst=1;
    always #5 clk=~clk;
    logic [63:0] program_memory[0:511],descriptor_memory[0:31];
    wire [8:0] program_address;logic [63:0] program_data;
    wire [4:0] descriptor_address;wire [63:0] descriptor_data=descriptor_memory[descriptor_address];
    always @(posedge clk)program_data<=program_memory[program_address];
    reg [255:0] job[0:7];
    wire [255:0] job_secret_seed=job[0],job_secret_prf=job[1],job_public_seed=job[2],
        job_randomizer=job[3],job_public_root=job[4];
    wire [1:0] job_operation=job[5][1:0];
    wire [6:0] message_length=job[6][6:0];
    wire [5:0] node_bytes=job[7][5:0];
    logic message_valid=0,verify_valid=0;
    logic [63:0] message_data=0;logic [255:0] verify_data=0;
    wire message_ready,verify_ready,verify_pass,busy,done,keygen_done,error,out_valid;
    wire [1:0] result_kind;wire [15:0] error_code;
    wire [31:0] boot_cycles,keygen_cycles,sign_cycles,hash_count,permutation_count;
    wire [255:0] out_data;wire [5:0] out_bytes;
    common #(.SWAP_PHYSICAL_LANES(SWAP),.PROFILE_ENABLE(PROFILE_ENABLE)) dut(.*);
    reg [7:0] message_bytes[0:86],expected_bytes[0:65535];
    reg [255:0] signature[0:2047];reg [31:0] metadata[0:5];
    integer sent=0,node_sent=0,cursor=0,cycles=0,waits=0,stall=0,replay=0,cut=0;
    integer flip=-1,bad_message=0,expected=1,interrupt_run=0,chain_interrupt=0,fault=0,watchdog=500000000;
    integer root_bit=-1,root_noise=0,node_noise=0,tail_noise=0,bad_length=-1,bad_operation=-1;
    integer retired=0,hash_waits=0,overlap=0,round_cycles[0:1];
    integer observed_hashes=0,observed_permutations=0,operation_cycles=0,entry_pc=0;
    wire [1:0] round_active,round_end,hash_end,context_start;
    integer issue_credit[0:1],authorized_hashes=0,started_hashes=0;
    logic outstanding_issue=0,snapshot_valid=0,macro_owned=0;
    integer observed_macros=0,observed_macro_cycles=0,observed_macro_hashes=0,completed_macros=0;
    integer macro_budget=0,macro_starts=0,macro_responses=0,macro_mode_snapshot=0;
    logic macro_slot_snapshot=0;
    logic [3:0] macro_digit_snapshot=0;
    logic [4:0] macro_layer_snapshot=0;
    logic [63:0] macro_tree_snapshot=0;
    logic [9:0] macro_leaf_snapshot=0;
    logic [6:0] macro_chain_snapshot=0;
    logic [63:0] macro_prf_recipe=0,macro_f_recipe=0;
    logic [232:0] request_snapshot;
    wire [232:0] request_context={dut.core.group_recipe,dut.core.group_tree,dut.core.group_layer,
        dut.core.group_leaf[0],dut.core.group_leaf[1],dut.core.group_a[0],dut.core.group_a[1],
        dut.core.group_b[0],dut.core.group_b[1],dut.core.group_mask};
    wire [232:0] launch_context={dut.core.physical_recipe,dut.core.group_tree,dut.core.group_layer,
        dut.core.group_leaf[0],dut.core.group_leaf[1],dut.core.group_a[0],dut.core.group_a[1],
        dut.core.physical_b_value,dut.core.physical_b_value,dut.core.group_mask};
    // One physical Hash lane serves two logical result slots. A normal ISSUE
    // authorizes one Hash; a CHAIN instance authorizes only its bounded recipe
    // sequence. Both paths independently account every accepted Hash start.
    wire physical_start=dut.core.lanes[0].lane.sponge.context_valid
        && dut.core.lanes[0].lane.sponge.context_ready;
    wire active_logical=dut.core.group_mask[1];
    assign context_start={physical_start && active_logical,physical_start && !active_logical};
    always @(posedge clk)if(!rst && !error && physical_start)begin
        if(dut.core.group_mask!=1 && dut.core.group_mask!=2)
            $fatal(1,"physical Hash start requires one-hot image authorization");
        if({dut.core.lanes[0].lane.request_recipe,dut.core.lanes[0].lane.request_tree,
            dut.core.lanes[0].lane.request_layer,dut.core.lanes[0].lane.request_leaf,
            dut.core.lanes[0].lane.request_a,dut.core.lanes[0].lane.request_b}
            !=={dut.core.physical_recipe,dut.core.group_tree,dut.core.group_layer,
                dut.core.group_leaf[active_logical],dut.core.group_a[active_logical],
                dut.core.physical_b_value})
            $fatal(1,"Hash launch context differs from issue snapshot logical=%0d",active_logical);
    end
    // The message store has one dedicated word port. Check accepted payload
    // bytes independently of its storage representation; padding may replace
    // the remaining bytes in the last word. No issue can modify the store.
    always @(posedge clk) begin : message_word_monitor
        integer source_word,source_byte;
        if(!rst && !error) begin
            if(dut.core.group_valid && dut.core.message_write)
                $fatal(1,"message RAM write during outstanding Hash");
            source_word=integer'(dut.core.lanes[0].lane.position[12:3])
                -integer'(dut.core.lanes[0].lane.message_prefix_words);
            if(dut.core.lanes[0].lane.state==1
                && (dut.core.group_recipe[59:56]==3 || dut.core.group_recipe[59:56]==4)
                && source_word>=0 && source_word*8<message_length) begin
                if(integer'(dut.core.message_word_address)!=source_word)
                    $fatal(1,"message word address differs from recipe offset");
                for(integer byte_index=0;byte_index<8;byte_index=byte_index+1) begin
                    source_byte=source_word*8+byte_index;
                    if(source_byte<message_length
                        && dut.core.message_word_data[byte_index*8+:8]!==message_bytes[source_byte])
                        $fatal(1,"message word payload changed byte=%0d",source_byte);
                end
            end
        end
    end
    assign round_active={1'b0,dut.core.lanes[0].lane.sponge.state==2};
    assign round_end={1'b0,round_active[0]
        && dut.core.lanes[0].lane.sponge.round_index+1>=24};
    assign hash_end={1'b0,round_end[0] && dut.core.lanes[0].lane.sponge.running_last};
    reg [31:0] rng=32'h15c0ffee;
    string image_dir,vector_dir,trace_path;integer trace_file=0;
    logic signature_read_enable=0;logic [10:0] signature_read_address=0;
    wire signature_read_valid,signature_valid,signature_error;
    wire [255:0] signature_read_data;wire [5:0] signature_node_bytes;
    wire [10:0] signature_nodes;wire [15:0] signature_length;
    signature storage (
        .clk,.rst,.finish(done && job_operation==1),.abort(error),
        .write_valid(out_valid && job_operation==1),.write_data(out_data),.write_bytes(out_bytes),
        .read_enable(signature_read_enable),.read_address(signature_read_address),
        .read_valid(signature_read_valid),.read_data(signature_read_data),
        .node_bytes(signature_node_bytes),.complete(signature_valid),.error(signature_error),
        .nodes(signature_nodes),.length(signature_length)
    );
    task tick;begin @(posedge clk);#1;end endtask
    always @(negedge clk) begin
        if(rst)begin message_valid=0;verify_valid=0;rng=32'h15c0ffee;end
        else begin
            rng={rng[30:0],rng[31]^rng[21]^rng[1]^rng[0]};
            if(!(message_valid && !message_ready))begin
                message_valid=sent<message_length && (!stall || rng[2:0]!=0);
                message_data=tail_noise ? 64'ha5a5a5a5a5a5a5a5 : 0;
                for(integer b=0;b<8;b=b+1)
                    if(sent+b<message_length)message_data[8*b+:8]=message_bytes[sent+b];
            end
            if(!(verify_valid && !verify_ready))begin
                verify_valid=job_operation==2 && node_sent<metadata[5]
                    && (!cut || node_sent<cut) && (!stall || rng[1:0]!=0);
                verify_data=signature[node_sent];
                if(node_noise)for(integer b=0;b<32;b=b+1)if(b>=node_bytes)verify_data[b*8+:8]=8'ha5;
            end
        end
    end
    always @(posedge clk)begin
        if(rst)begin
            sent=0;node_sent=0;cursor=0;cycles=0;waits=0;micro_trace_reset();
            retired=0;hash_waits=0;overlap=0;round_cycles[0]=0;round_cycles[1]=0;
            observed_hashes=0;observed_permutations=0;
            issue_credit[0]=0;issue_credit[1]=0;authorized_hashes=0;started_hashes=0;
            outstanding_issue=0;snapshot_valid=0;request_snapshot=0;macro_owned=0;
            observed_macros=0;observed_macro_cycles=0;observed_macro_hashes=0;completed_macros=0;
            macro_budget=0;macro_starts=0;macro_responses=0;
        end
        else begin
            if(error)begin
                if(physical_start || (|dut.core.trace_hash_valid) || dut.core.chain_issue)
                    $fatal(1,"Hash work continued after architectural fault");
                issue_credit[0]=0;issue_credit[1]=0;outstanding_issue=0;snapshot_valid=0;macro_owned=0;
            end else begin
                if(dut.core.chain_active)observed_macro_cycles=observed_macro_cycles+1;
                if(dut.core.retire && dut.core.opcode==OP_HASH)begin
                    if(outstanding_issue || macro_owned)$fatal(1,"nested Hash authorization");
                    if(dut.core.issue_mask!=1 && dut.core.issue_mask!=2)
                        $fatal(1,"K1U1 image retired a non-one-hot ISSUE");
                    outstanding_issue=1;
                    for(integer lane=0;lane<2;lane=lane+1)if(dut.core.issue_mask[lane])begin
                        if(issue_credit[lane])$fatal(1,"unconsumed Hash authorization lane=%0d",lane);
                        issue_credit[lane]=1;authorized_hashes=authorized_hashes+1;
                    end
                end
                if(dut.core.chain_start)begin
                    if(outstanding_issue || macro_owned || issue_credit[0] || issue_credit[1])
                        $fatal(1,"CHAIN overlaps another authorization");
                    macro_owned=1;observed_macros=observed_macros+1;
                    macro_mode_snapshot=integer'(dut.core.chain_mode);
                    macro_slot_snapshot=dut.core.chain_slot;
                    macro_digit_snapshot=dut.core.chain_digit;
                    macro_layer_snapshot=dut.core.ctx_layer;macro_tree_snapshot=dut.core.ctx_tree;
                    macro_leaf_snapshot=dut.core.b==1 ? dut.core.ctx_leaf : dut.core.ctx_cursor[9:0];
                    macro_chain_snapshot=dut.core.ctx_chain+7'(macro_slot_snapshot);
                    macro_prf_recipe=descriptor_memory[7];macro_f_recipe=descriptor_memory[8];
                    macro_budget=macro_mode_snapshot==3 ? 15-integer'(macro_digit_snapshot)
                        : macro_mode_snapshot==2 ? 1+integer'(macro_digit_snapshot) : 16;
                    if(integer'(dut.core.chain_expected_hashes)!=macro_budget)
                        $fatal(1,"CHAIN claimed budget differs from mode/digit");
                    if(macro_slot_snapshot!==(dut.core.a==2 ? 1'b1 : dut.core.a==1 ? 1'b0 : dut.core.ctx_mask[1]))
                        $fatal(1,"CHAIN logical slot differs from instruction selector");
                    macro_starts=0;macro_responses=0;
                end
                if(snapshot_valid && request_context!==request_snapshot)
                    $fatal(1,"single-Hash request snapshot changed while outstanding");
                if(dut.core.group_valid && !outstanding_issue && !macro_owned && !dut.core.chain_active)
                    $fatal(1,"Hash group without explicit instruction ownership");
                if(dut.core.chain_issue && (!macro_owned || !physical_start))
                    $fatal(1,"CHAIN issue signal without owned physical Hash start");
                // Drain the owned response before accepting its successor on
                // the same edge. The old snapshot and trace remain intact.
                for(integer lane=0;lane<2;lane=lane+1)if(dut.core.trace_hash_valid[lane])begin
                    if(!snapshot_valid)$fatal(1,"Hash trace without a unique outstanding physical request");
                    if(macro_owned)begin
                        if(lane!=integer'(macro_slot_snapshot) || macro_responses>=macro_starts)
                            $fatal(1,"CHAIN response has no matching owned request");
                        macro_responses=macro_responses+1;
                    end
                    snapshot_valid=0;
                end
                for(integer lane=0;lane<2;lane=lane+1)if(context_start[lane])begin
                    if(snapshot_valid)$fatal(1,"another physical Hash before its predecessor completed");
                    if(macro_owned)begin
                        if(!dut.core.chain_issue || lane!=integer'(macro_slot_snapshot) || macro_starts>=macro_budget)
                            $fatal(1,"CHAIN physical Hash exceeds owner/slot/budget");
                        if(dut.core.group_layer!==macro_layer_snapshot || dut.core.group_tree!==macro_tree_snapshot
                            || dut.core.group_leaf[lane]!==macro_leaf_snapshot || dut.core.group_a[lane]!==macro_chain_snapshot)
                            $fatal(1,"CHAIN Hash escaped its captured HBS address");
                        if(macro_mode_snapshot!=3 && macro_starts==0)begin
                            if(dut.core.chain_hash_stage || dut.core.chain_reissue
                                || dut.core.physical_recipe!==macro_prf_recipe || dut.core.physical_b_value!=0)
                                $fatal(1,"CHAIN must begin with exactly one address PRF");
                        end else begin
                            if(!(dut.core.chain_hash_stage || dut.core.chain_reissue)
                                || dut.core.physical_recipe!==macro_f_recipe
                                || integer'(dut.core.physical_b_value)!=(macro_mode_snapshot==3
                                    ? integer'(macro_digit_snapshot)+macro_starts : macro_starts-1))
                                $fatal(1,"CHAIN F step/recipe differs from bounded owner sequence");
                        end
                        macro_starts=macro_starts+1;observed_macro_hashes=observed_macro_hashes+1;
                        authorized_hashes=authorized_hashes+1;
                    end else begin
                        if(!outstanding_issue || issue_credit[lane]!=1)
                            $fatal(1,"Hash start without image authorization lane=%0d",lane);
                        issue_credit[lane]=0;
                    end
                    started_hashes=started_hashes+1;
                    request_snapshot=launch_context;snapshot_valid=1;
                end
                if(dut.core.chain_complete)begin
                    if(!macro_owned || macro_starts!=macro_budget || macro_responses!=macro_budget || snapshot_valid)
                        $fatal(1,"CHAIN retired without its exact bounded Hash sequence");
                    if(!dut.core.retire || dut.core.opcode!=OP_CHAIN)
                        $fatal(1,"CHAIN completion did not retire its owning instruction");
                    macro_owned=0;completed_macros=completed_macros+1;
                end
                if(dut.core.retire && dut.core.opcode==OP_WAIT)begin
                    if(!outstanding_issue || issue_credit[0] || issue_credit[1] || snapshot_valid)
                        $fatal(1,"WAIT without exactly one completed Hash per active lane");
                    outstanding_issue=0;
                end
            end
            if(dut.core.retire)retired=retired+1;
            if(dut.core.ir_valid && dut.core.opcode==OP_WAIT && !dut.core.group_complete)hash_waits=hash_waits+1;
            if(dut.core.group_valid && dut.core.retire && typed_metadata(dut.core.opcode))overlap=overlap+1;
            for(integer lane=0;lane<2;lane=lane+1)begin
                if(round_active[lane])round_cycles[lane]=round_cycles[lane]+1;
                if(round_end[lane])observed_permutations=observed_permutations+1;
                if(hash_end[lane])observed_hashes=observed_hashes+1;
            end
            for(integer lane=0;lane<2;lane=lane+1)if(dut.core.trace_hash_valid[lane])
                micro_trace_sample(dut.core.trace_recipe,int'(dut.core.trace_layer),dut.core.trace_tree,
                    int'(dut.core.trace_leaf[lane]),int'(dut.core.trace_a[lane]),
                    dut.core.trace_b[lane],dut.core.trace_result[lane]);
            cycles=cycles+1;
            if(message_valid && message_ready)sent=sent+8;
            if(verify_valid && verify_ready)node_sent=node_sent+1;
            if((message_ready&&!message_valid)||(verify_ready&&!verify_valid))waits=waits+1;
            if(cycles>watchdog)$fatal(1,"micro timeout");
            if(error && !fault)$fatal(1,"micro error=%h cycles=%0d",error_code,cycles);
            if(out_valid)begin
                if(job_operation==2 || result_kind!=job_operation || out_bytes!=node_bytes)
                    $fatal(1,"unexpected output/width");
                for(integer b=0;b<32;b=b+1)if(b<out_bytes)begin
                    if(cursor>=metadata[0] || out_data[b*8+:8]!==expected_bytes[cursor])
                        $fatal(1,"micro output byte=%0d actual=%h expected=%h",cursor,out_data[b*8+:8],expected_bytes[cursor]);
                    cursor=cursor+1;
                end
            end
        end
    end
    initial begin
        if(!$value$plusargs("IMAGE=%s",image_dir))$fatal(1,"IMAGE required");
        if(!$value$plusargs("VECTOR=%s",vector_dir))$fatal(1,"VECTOR required");
        if($value$plusargs("STALL=%d",stall))begin end
        if($value$plusargs("REPLAY=%d",replay))begin end
        if($value$plusargs("CUT=%d",cut))begin end
        if($value$plusargs("FLIP=%d",flip))begin end
        if($value$plusargs("BAD_MESSAGE=%d",bad_message))begin end
        if($value$plusargs("EXPECT=%d",expected))begin end
        if($value$plusargs("INTERRUPT=%d",interrupt_run))begin end
        if($value$plusargs("CHAIN_INTERRUPT=%d",chain_interrupt))begin end
        if($value$plusargs("FAULT=%d",fault))begin end
        if($value$plusargs("ROOT_BIT=%d",root_bit))begin end
        if($value$plusargs("ROOT_NOISE=%d",root_noise))begin end
        if($value$plusargs("NOISE=%d",node_noise))begin end
        if($value$plusargs("TAIL_NOISE=%d",tail_noise))begin end
        if($value$plusargs("BAD_LENGTH=%d",bad_length))begin end
        if($value$plusargs("BAD_OPERATION=%d",bad_operation))begin end
        if($value$plusargs("WATCHDOG=%d",watchdog))begin end
        $readmemh({image_dir,"/program.mem"},program_memory);
        $readmemh({image_dir,"/descriptor.mem"},descriptor_memory);
        $readmemh({vector_dir,"/job.mem"},job);
        $readmemh({vector_dir,"/metadata.mem"},metadata);
        // Read the just-loaded array directly: continuous aliases settle in a
        // later delta cycle and cannot select files in this initial block.
        if(job[5]!=2)$readmemh({vector_dir,"/expected.mem"},expected_bytes,0,metadata[0]-1);
        if(job[6])$readmemh({vector_dir,"/message.mem"},message_bytes,0,int'(job[6])-1);
        if(job[5]==2)$readmemh({vector_dir,"/nodes.mem"},signature,0,metadata[5]-1);
        if(flip>=0)signature[flip][0]=~signature[flip][0];
        if(bad_message)message_bytes[0]=message_bytes[0]^bad_message[7:0];
        if(root_bit>=0)job[4][root_bit]=~job[4][root_bit];
        if(root_noise)for(integer b=0;b<32;b=b+1)if(b>=job[7])job[4][b*8+:8]=8'ha5;
        if(bad_length>=0)job[6]=256'(bad_length);
        if(bad_operation>=0)job[5]=256'(bad_operation);
        entry_pc=job[5]==0 ? descriptor_memory[0][26:18]
            : job[5]==1 ? descriptor_memory[0][17:9] : descriptor_memory[0][8:0];
        if(fault==1)program_memory[entry_pc]=0;
        if(fault==4)descriptor_memory[0][31:27]=5'd1;
        if(fault==9)descriptor_memory[0][31:27]=5'd2;
        if(fault==10)descriptor_memory[0][31:27]=5'd4;
        if(fault==11)descriptor_memory[0][31:27]=5'd5;
        // Known opcodes with malformed private operands must fault before writeback.
        if(fault==5)program_memory[entry_pc]={OP_GROUP_INIT,8'd0,8'd1,8'd0,32'd0};
        if(fault==6)program_memory[entry_pc]={OP_LOAD,8'd0,8'd1,IDX_CHAIN0,32'd0};
        if(fault==7)begin
            program_memory[entry_pc+0]={OP_HEIGHT,8'd2,8'd0,8'd0,32'd1};
            program_memory[entry_pc+1]={OP_CURSOR_INIT,56'd0};
            program_memory[entry_pc+2]={OP_CURSOR_NEXT,24'd0,32'd2};
            program_memory[entry_pc+3]={OP_CURSOR_NEXT,24'd0,32'd1};
        end
        if(fault==8)begin
            program_memory[entry_pc+0]={OP_MASK,24'd0,32'd3};
            program_memory[entry_pc+1]={OP_HASH,8'd2,48'd0};
        end
        repeat(4)tick();rst=0;
        if(interrupt_run)begin repeat(1000)tick();rst=1;repeat(4)tick();rst=0;end
        if(chain_interrupt)begin
            while(!(dut.core.chain_active && round_active[0]
                && dut.core.lanes[0].lane.sponge.round_index>=3))tick();
            rst=1;repeat(4)tick();rst=0;
        end
        if(cut)begin
            while(node_sent<cut)tick();repeat(3000)tick();
            if(done || error || !busy || !verify_ready || verify_pass)$fatal(1,"truncated input completed");
            rst=1;repeat(4)tick();cut=0;rst=0;
        end
        if(fault)begin
            if(fault==2)begin
                while(!( |(dut.core.lane_valid & dut.core.response_pending)))tick();
                force dut.core.lanes[0].lane.error=1;
            end
            while(!error)tick();
            if(fault==2 && error_code!=16'h3007)$fatal(1,"lane error propagation");
            if(fault==3 && error_code!=16'h3002)$fatal(1,"invalid job input");
            if((fault==4 || fault==9 || fault==10 || fault==11) && error_code!=16'h3101)$fatal(1,"old ABI accepted");
            if(fault>=5 && fault!=9 && fault!=10 && fault!=11 && error_code!=16'h3006)$fatal(1,"typed operand/range fault");
            if(fault==8 && (authorized_hashes || started_hashes || observed_hashes))
                $fatal(1,"paired ISSUE caused a physical Hash start before its fault");
            repeat(30)begin tick();if(out_valid || busy || done)$fatal(1,"fault did not halt");end
            $display("MICRO_FAULT_PASS code=%h",error_code);$finish;
        end
        for(integer run=0;run<=replay;run=run+1)begin
            while(!done)tick();
            operation_cycles=cycles;
            if(outstanding_issue || macro_owned || snapshot_valid || issue_credit[0] || issue_credit[1]
                || completed_macros!=observed_macros || micro_trace_samples()!=observed_hashes
                || authorized_hashes!=started_hashes || started_hashes!=observed_hashes)
                $fatal(1,"Hash authorization/start/completion counts differ");
            if(cursor!=metadata[0] || error)$fatal(1,"micro output length");
            if(job_operation==2 && (verify_pass!==expected[0] || node_sent!=metadata[5]))
                $fatal(1,"verify pass=%0d expected=%0d input=%0d/%0d",verify_pass,expected,node_sent,metadata[5]);
            if(flip<0 && !bad_message && root_bit<0 &&
                (observed_hashes!=metadata[1] || observed_permutations!=metadata[2]))
                $fatal(1,"observed hash/permutation counts");
            if(PROFILE_ENABLE &&
                (hash_count!=observed_hashes || permutation_count!=observed_permutations))
                $fatal(1,"micro hash counts %0d/%0d expected %0d/%0d",hash_count,permutation_count,metadata[1],metadata[2]);
            if(PROFILE_ENABLE && (dut.core.macro_count!=observed_macros
                || dut.core.macro_busy_cycles!=observed_macro_cycles || dut.core.macro_hashes!=observed_macro_hashes))
                $fatal(1,"macro profile counters differ from independent ownership monitor");
            if(!PROFILE_ENABLE && {boot_cycles,keygen_cycles,sign_cycles,hash_count,permutation_count,
                dut.core.macro_count,dut.core.macro_busy_cycles,dut.core.macro_hashes}!==256'd0)
                $fatal(1,"statistics not pruned");
            if(job_operation==1)begin
                if(!signature_valid || signature_error || signature_length!=metadata[0])$fatal(1,"signature metadata");
                for(integer i=0;i<signature_nodes;i=i+1)begin
                    signature_read_enable=1;signature_read_address=11'(i);tick();
                    if(!signature_read_valid)$fatal(1,"signature read latency");
                    for(integer b=0;b<32;b=b+1)if(b<node_bytes)
                        if(signature_read_data[8*b+:8]!==expected_bytes[i*int'(node_bytes)+b])
                            $fatal(1,"signature read data");
                end
                signature_read_enable=0;
            end
            $display("MICRO_RTL_PASS operation=%0d n=%0d bytes=%0d nodes=%0d hashes=%0d permutations=%0d cycles=%0d waits=%0d swap=%0d stats=%0d",job_operation,node_bytes,cursor,node_sent,hash_count,permutation_count,operation_cycles,waits,SWAP,PROFILE_ENABLE);
            $display("MICRO_METRICS instructions=%0d hash_waits=%0d overlap=%0d lane0_round_cycles=%0d lane1_round_cycles=%0d",retired,hash_waits,overlap,round_cycles[0],round_cycles[1]);
            $display("MICRO_MACRO_METRICS macro_count=%0d macro_busy_cycles=%0d macro_hashes=%0d",
                dut.core.macro_count,dut.core.macro_busy_cycles,dut.core.macro_hashes);
            $display("MICRO_HASH_TRACE %s",micro_trace_digest());
            repeat(30)begin tick();if(!done || busy || out_valid || message_ready || verify_ready)$fatal(1,"completion halt");end
            if(run<replay)begin rst=1;repeat(4)tick();rst=0;end
        end
        $finish;
    end
endmodule
