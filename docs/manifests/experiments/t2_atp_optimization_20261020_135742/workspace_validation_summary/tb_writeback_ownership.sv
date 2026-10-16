`timescale 1ns/1ps
module tb_writeback_ownership;
    parameter integer PIPELINE=4;
    logic clk=0,rst=1;
    always #5 clk=~clk;
    logic [255:0] memory[0:127], generic_memory[0:135];
    logic [127:0] valid='0;
    logic [135:0] generic_valid='0;
    logic expected_write=0;
    logic [7:0] expected_address=0;
    logic [255:0] expected_data=0;
    integer writes=0,reads=0,auth_collisions=0,odd_copies=0,owners=0,reset_checks=0;
    integer generic_reads=0,generic_writes=0;
    logic [127:0] descriptor_bus=0;
    logic response_valid=0;
    localparam TAG_BITS=PIPELINE>1 ? $clog2(PIPELINE) : 1;
    logic [TAG_BITS-1:0] response_tag=0;
    logic [255:0] response_data=0;
    logic generic_we=0;
    logic [7:0] generic_wa=0,generic_r0=0,generic_r1=1;
    logic [255:0] generic_wd=0;
    wire [255:0] generic_v0,generic_v1;
    value #(.DEPTH(136)) generic_value(.clk,.write_enable(generic_we),.write_address(generic_wa),.write_data(generic_wd),.read0(generic_r0),.read1(generic_r1),.value0(generic_v0),.value1(generic_v1));
    executor #(.PIPELINE(PIPELINE),.UNROLL(1)) dut (
        .clk,.rst,.job_valid(1'b0),.image_header(64'd0),.profile_descriptor(64'd0),
        .program_data(64'd0),.template_data(64'd0),.descriptor_data(descriptor_bus),
        .job_entry(4'd0),.job_operation(2'd1),.job_message_length(7'd1),
        .job_index(32'd0),.job_identifier(128'd0),
        .job_secret_seed(256'd0),.job_secret_prf(256'd0),.job_public_seed(256'd0),
        .job_public_root(256'd0),.job_randomizer(256'd0),
        .message_valid(1'b0),.message_data(64'd0),.verify_valid(1'b0),.verify_data(256'd0)
    );
    localparam [255:0] PATTERN=256'hfedcba98765432100123456789abcdef5566778899aabbccddeeff0011223344;
    always @(posedge clk) begin : independent_scoreboard
        if (dut.endpoint_write !== expected_write ||
            (expected_write && (dut.endpoint_address !== expected_address || dut.endpoint_data !== expected_data)))
            $fatal(1,"write owner mismatch P%0d state=%0d expected_we=%b actual_we=%b expected_addr=%0d actual_addr=%0d expected_data=%h actual_data=%h",PIPELINE,dut.state,expected_write,dut.endpoint_write,expected_address,dut.endpoint_address,expected_data,dut.endpoint_data);
        if(expected_write)begin
            if(expected_address>=128)$fatal(1,"executor scoreboard out of range");
            memory[expected_address]=expected_data;valid[expected_address]=1;writes++;
        end
        if(generic_we)begin
            generic_memory[generic_wa]=generic_wd;generic_valid[generic_wa]=1;generic_writes++;
        end
        #1;
        if(valid[dut.endpoint_read0])begin
            if(dut.endpoint_value0!==memory[dut.endpoint_read0])$fatal(1,"executor read0 addr=%0d",dut.endpoint_read0);
            reads++;
        end
        if(valid[dut.endpoint_read1])begin
            if(dut.endpoint_value1!==memory[dut.endpoint_read1])$fatal(1,"executor read1 addr=%0d",dut.endpoint_read1);
            reads++;
        end
        if(generic_valid[generic_r0])begin
            if(generic_v0!==generic_memory[generic_r0])$fatal(1,"generic136 read0 addr=%0d",generic_r0);
            generic_reads++;
        end
        if(generic_valid[generic_r1])begin
            if(generic_v1!==generic_memory[generic_r1])$fatal(1,"generic136 read1 addr=%0d",generic_r1);
            generic_reads++;
        end
    end
    if(PIPELINE>1)begin : context_driver
        task inject(input bit active,input integer tag,input logic[255:0] data);begin
            // Construct a legal published-response snapshot rather than forcing
            // the output port, keeping recipe ownership assertions active.
            dut.lane.scheduled_execution.fixed_context.pending_valid=0;
            dut.lane.scheduled_execution.fixed_context.busy=active ? (PIPELINE'(1)<<tag) : '0;
            dut.lane.scheduled_execution.fixed_context.complete=active ? (PIPELINE'(1)<<tag) : '0;
            dut.lane.scheduled_execution.fixed_context.awaiting_response=0;
            dut.lane.scheduled_execution.fixed_context.response_held=active;
            dut.lane.scheduled_execution.fixed_context.held_tag=TAG_BITS'(tag);
            dut.lane.scheduled_execution.fixed_context.held_digest=data;
            dut.lane.scheduled_execution.fixed_context.held_capture=0;
            dut.lane.scheduled_execution.fixed_context.initial_pending=0;
            dut.lane.scheduled_execution.fixed_context.captured_valid=0;
            dut.lane.scheduled_execution.fixed_context.digest[tag]=data;
        end endtask
    end else begin : context_driver
        task inject(input bit active,input integer tag,input logic[255:0] data);begin end endtask
    end
    task tick;begin @(posedge clk);#2;end endtask
    task select_pair(input integer a);begin
        dut.read_addresses.address=8'(a);
        dut.read_addresses.adjacent_address=8'(a==127 ? 126 : a+1);
    end endtask
    task phase(input integer code);begin
        dut.state=type(dut.state)'(code);
        dut.lane_request_active=code==22;
        dut.batch_issue_phase=PIPELINE>1 && (code==38 || code==55 || code==63);
        dut.batch_verify_phase=PIPELINE>1 && code==53;
        dut.pipe_response_accept=PIPELINE>1 && (code==38 || code==39 || code==53 || code==56 || code==64);
        dut.pipe_mode=PIPELINE>1 && (code==38 || code==39 || code==53 || code==55 || code==56 || code==61 || code==63 || code==64);
        dut.fors_pipe=PIPELINE>1 && (code==61 || code==63 || code==64);
        dut.lt_pipe=PIPELINE>1 && (code==55 || code==56);
        dut.fors_leaves=PIPELINE>1 && dut.indexing==1 && dut.operation!=2 && (code==38 || code==39);
        #1;
        dut.direct_writeback_phase=PIPELINE>1 && dut.pipe_direct && (code==38 || code==39 || code==53);
    end endtask
    task begin_case;begin
        @(negedge clk);expected_write=0;response_valid=0;
        context_driver.inject(0,0,0);
        force dut.pipe_selected=0;descriptor_bus=0;
        dut.operation=1;dut.stateful=0;dut.xmss=0;dut.indexing=0;dut.standalone_chain=0;
        dut.macro_flags=0;dut.macro_route=0;dut.pipe_rolling=0;
        dut.pipe_done_mask=0;dut.pipe_expected_mask='1;dut.pipe_completed=0;dut.endpoint_count=67;
        phase(0);
    end endtask
    task plan_write(input integer a,input logic[255:0] data);begin
        expected_write=1;expected_address=8'(a);expected_data=data;
    end endtask
    task response(input integer tag,input logic[255:0] data);begin
        response_valid=1;response_tag=TAG_BITS'(tag);response_data=data;
        context_driver.inject(1,tag,data);
    end endtask
    initial begin
        repeat(3)tick();@(negedge clk);rst=0;tick();
        for(integer a=0;a<128;a++)begin
            begin_case();dut.chain_cursor=8'(a);dut.result={136'd0,PATTERN^256'(a)};
            select_pair(a&~1);phase(8);plan_write(a,PATTERN^256'(a));tick();
        end
        owners++;
        // Actual consecutive PUSH_NODE and PUSH_STACK edges, independent data.
        begin_case();dut.node_level=0;dut.tree_height=10;dut.target=1;dut.target_at_level=1;
        dut.node_index=0;dut.auth_node_match=1;dut.node_below_root=1;dut.macro_flags=2;
        dut.node_value=PATTERN^256'hface;select_pair(88);phase(17);
        plan_write(88,PATTERN^256'hface);tick();
        if(dut.state!==type(dut.state)'(70))$fatal(1,"auth collision did not defer stack");
        expected_address=68;tick();auth_collisions++;owners+=2;
        for(integer a=0;a<2;a++)begin
            begin_case();dut.macro_flags=2;select_pair(36+2*a);phase(a==0 ? 59 : 66);
            plan_write(88+a,memory[36+2*a]);tick();
        end
        owners++;
        if(PIPELINE>1)begin
            for(integer t=0;t<PIPELINE;t++)begin
                begin_case();dut.indexing=1;dut.fors_offset=0;select_pair(36+(t&~1));phase(38);
                response(t,PATTERN^(256'(t+512)<<24));plan_write(36+t,PATTERN^(256'(t+512)<<24));tick();
                begin_case();dut.indexing=1;dut.fors_offset=0;select_pair(36+(t&~1));phase(64);
                response(t,PATTERN^(256'(t+768)<<24));plan_write(36+t,PATTERN^(256'(t+768)<<24));tick();
                begin_case();dut.lt_cursor=24;select_pair(12+(t&~1));phase(56);
                response(t,PATTERN^(256'(t+1024)<<24));plan_write(12+t,PATTERN^(256'(t+1024)<<24));tick();
                begin_case();dut.chain_cursor=24;select_pair(24+(t&~1));phase(38);
                response(t,PATTERN^(256'(t+1280)<<24));plan_write(24+t,PATTERN^(256'(t+1280)<<24));tick();
                begin_case();dut.pipe_rolling=1;dut.pipe_chain_index[t]=8'(65-t);select_pair((65-t)&~1);phase(38);
                response(t,PATTERN^(256'(t+1536)<<24));plan_write(65-t,PATTERN^(256'(t+1536)<<24));tick();
            end
            owners+=5;
        end else begin
            begin_case();dut.lt_cursor=8;dut.result={136'd0,PATTERN^256'hfeed};select_pair(4);phase(45);
            plan_write(4,PATTERN^256'hfeed);tick();owners++;
            begin_case();phase(0);#1;
            if(dut.direct_writeback_phase || dut.batch_issue_phase || dut.pipe_mode)$fatal(1,"P1 enabled parallel controls");
            tick();
        end
        begin_case();dut.macro_route=1;dut.group_index=33;dut.route_source=1;dut.node_value=PATTERN^256'hbead;
        descriptor_bus[127:64]=64'h0020000000000000;select_pair(32);phase(25);
        plan_write(33,PATTERN^256'hbead);tick();owners++;
        // Emulate only arithmetic payloads: all actual in-place RAM writes and
        // odd-tail copies go through the frozen mux. Inputs for a wave are
        // snapshotted before writes; full Sign separately checks real hashes.
        begin : reduction
            integer count,base,n;
            logic[255:0] output_wave[0:PIPELINE-1];
            count=67;
            while(count>1)begin
                base=0;
                while(base<count/2)begin
                    n=(count/2-base)<PIPELINE ? count/2-base : PIPELINE;
                    for(integer t=0;t<n;t++)output_wave[t]=memory[2*(base+t)]^memory[2*(base+t)+1]^256'(count);
                    for(integer t=0;t<n;t++)begin
                        begin_case();dut.lt_cursor=8'(2*base);dut.lt_count=8'(count);select_pair(2*(base+t));
                        if(PIPELINE>1)begin phase(56);response(t,output_wave[t]);end
                        else begin dut.lt_cursor=8'(2*(base+t));dut.result={136'd0,output_wave[t]};phase(45);end
                        plan_write(base+t,output_wave[t]);tick();
                    end
                    base+=n;
                end
                if(count[0])begin
                    begin_case();dut.lt_cursor=8'(count-1);dut.lt_count=8'(count);select_pair(count-1);phase(46);
                    plan_write(count/2,memory[count-1]);tick();odd_copies++;
                end
                count=(count+1)/2;
            end
        end
        owners++;
        // Current executor's highest legal pair is127/126, never135/134.
        begin_case();select_pair(127);phase(0);tick();
        if(dut.endpoint_value0!==memory[127] || dut.endpoint_value1!==memory[126])$fatal(1,"127/126 guard");
        // Reset during an actual write: value RAM is intentionally unreset,
        // so that edge commits; the following edge has no owner or stale phase.
        begin_case();dut.chain_cursor=99;dut.result={136'd0,PATTERN^256'habcd};select_pair(98);phase(8);
        plan_write(99,PATTERN^256'habcd);rst=1;tick();reset_checks++;
        expected_write=0;tick();
        if(dut.direct_writeback_phase || dut.pipe_mode)$fatal(1,"reset retained writeback phase");
        @(negedge clk);rst=0;select_pair(98);phase(0);tick();
        if(dut.endpoint_value1!==memory[99])$fatal(1,"reset lost RAM data");reset_checks++;
        // The same frozen generic value implementation still supports136
        // entries. Check its compact tail, both odd/even135/134 orientations.
        for(integer a=0;a<136;a++)begin
            begin_case();generic_we=1;generic_wa=8'(a);generic_wd=PATTERN^(256'(a+2048)<<16);
            generic_r0=8'(a&~1);generic_r1=generic_r0+1;tick();
        end
        for(integer a=0;a<32;a++)begin
            begin_case();generic_we=1;generic_wa=a[0] ? 134 : 135;generic_wd=PATTERN^(256'(a+4096)<<32);
            generic_r0=a[1] ? 134 : 135;generic_r1=a[1] ? 135 : 134;tick();
        end
        for(integer a=0;a<136;a++)begin
            begin_case();generic_we=0;generic_r0=8'(a);generic_r1=8'(a==135 ? 134 : a+1);tick();
        end
        if(writes<200 || reads<400 || odd_copies!=5 || auth_collisions!=1 || reset_checks!=2 || generic_reads<300)
            $fatal(1,"coverage incomplete writes=%0d reads=%0d odd=%0d generic=%0d",writes,reads,odd_copies,generic_reads);
        $display("WRITEBACK_OWNERSHIP_PASS P%0dU1 writes=%0d reads=%0d owner_categories=%0d auth_collision=%0d odd67_copies=%0d reset_checks=%0d executor127_126=1 generic136_writes=%0d generic136_reads=%0d generic135_134=1 p1_scalar=%0d",PIPELINE,writes,reads,owners,auth_collisions,odd_copies,reset_checks,generic_writes,generic_reads,PIPELINE==1);
        $finish;
    end
endmodule
