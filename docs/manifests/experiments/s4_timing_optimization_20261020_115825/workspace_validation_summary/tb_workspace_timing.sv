`timescale 1ns/1ps
module tb_workspace_timing;
    parameter integer PIPELINE=4;
    logic clk=0,rst=1,clock_enable=1;
    always #5 if(clock_enable)clk=~clk;
    integer address_checks=0, logical_read_checks=0, physical_read_checks=0;
    integer forward0_checks=0, forward1_checks=0, reset_flush_checks=0;
    logic [255:0] logical_mem[0:127], physical_mem[0:127];
    logic [127:0] logical_valid='0, physical_valid='0;
    logic injected_write=0, injection_active=0;
    logic [7:0] injected_address=0, injected_read0=0, injected_read1=1;
    logic [255:0] injected_data=0;
    // Independent scoreboards model the two distinct moments: logical
    // capture and next-edge physical RAM commit. The pending item still
    // commits when rst is asserted, because the actual value RAM has no reset.
    always @(posedge clk) begin : commit_scoreboard
        if (dut.workspace_commit_valid) begin
            physical_mem[dut.workspace_commit_address] = dut.workspace_commit_data;
            physical_valid[dut.workspace_commit_address] = 1;
            if (rst) reset_flush_checks++;
        end
        if (!rst && dut.endpoint_write) begin
            logical_mem[dut.endpoint_address] = dut.endpoint_data;
            logical_valid[dut.endpoint_address] = 1;
        end
        #1;
        if (logical_valid[dut.endpoint_read0]) begin
            if (dut.endpoint_value0 !== logical_mem[dut.endpoint_read0])
                $fatal(1,"logical read0 differs addr=%0d expected=%h actual=%h pending_valid=%b pending_addr=%0d pending_data=%h write=%b waddr=%0d wdata=%h",dut.endpoint_read0,logical_mem[dut.endpoint_read0],dut.endpoint_value0,dut.workspace_commit_valid,dut.workspace_commit_address,dut.workspace_commit_data,dut.endpoint_write,dut.endpoint_address,dut.endpoint_data);
            logical_read_checks++;
        end
        if (logical_valid[dut.endpoint_read1]) begin
            if (dut.endpoint_value1 !== logical_mem[dut.endpoint_read1])
                $fatal(1,"logical read1 differs at %0d",dut.endpoint_read1);
            logical_read_checks++;
        end
        if (physical_valid[dut.endpoint_read0]) begin
            if (dut.endpoint_ram_value0 !== physical_mem[dut.endpoint_read0])
                $fatal(1,"physical RAM read0 differs at %0d",dut.endpoint_read0);
            physical_read_checks++;
        end
        if (physical_valid[dut.endpoint_read1]) begin
            if (dut.endpoint_ram_value1 !== physical_mem[dut.endpoint_read1])
                $fatal(1,"physical RAM read1 differs at %0d",dut.endpoint_read1);
            physical_read_checks++;
        end
        if (dut.workspace_commit_valid && dut.workspace_commit_address == dut.endpoint_read0)
            forward0_checks++;
        if (dut.workspace_commit_valid && dut.workspace_commit_address == dut.endpoint_read1)
            forward1_checks++;
    end
    executor #(.PIPELINE(PIPELINE),.UNROLL(1)) dut (
        .clk,.rst,.job_valid(1'b0),.image_header(64'd0),.profile_descriptor(64'd0),
        .program_data(64'd0),.template_data(64'd0),.descriptor_data(128'd0),
        .job_entry(4'd0),.job_operation(2'd1),.job_message_length(7'd1),
        .job_index(32'd0),.job_identifier(128'd0),
        .job_secret_seed(256'd0),.job_secret_prf(256'd0),.job_public_seed(256'd0),
        .job_public_root(256'd0),.job_randomizer(256'd0),
        .message_valid(1'b0),.message_data(64'd0),.verify_valid(1'b0),.verify_data(256'd0)
    );
    localparam [255:0] PATTERN=256'hfedcba98765432100123456789abcdef5566778899aabbccddeeff0011223344;
    task drive_injected_port; begin
        // Reissue force for every beat: Verilator 5.008 samples a procedural
        // force RHS when executed, rather than following later RHS changes.
        force dut.endpoint_write=injected_write;
        force dut.endpoint_address=injected_address;
        force dut.endpoint_data=injected_data;
        // Drive the existing address registers before the edge. Forcing
        // an aliased output net is inconsistent after Verilator's inlining;
        // the actual registered read selector remains the source of truth.
        dut.read_addresses.address=injected_read0;
        dut.read_addresses.adjacent_address=injected_read1;
    end endtask
    task tick; begin
        if(injection_active)drive_injected_port();
        @(posedge clk); #1;
    end endtask
    task reset_core; begin
        @(negedge clk); rst=1; repeat(3)tick(); @(negedge clk);rst=0;tick();
    end endtask
    task check_next(input integer expected,input string description); begin
        #1;
        if(dut.read_addresses.next_address!==8'(expected) ||
            dut.read_addresses.next_adjacent_address!==(expected==127 ? 8'd126 : 8'(expected+1)))
            $fatal(1,"address decoder %s main=%0d adjacent=%0d expected=%0d",description,
                dut.read_addresses.next_address,dut.read_addresses.next_adjacent_address,expected);
        address_checks++;
    end endtask
    initial begin
        reset_core();
        // Inject one producer into the actual frozen executor write network;
        // the commit registers, both forwarding selectors and the actual
        // odd/even RAM banks remain unchanged and are checked above.
        @(negedge clk);
        injection_active=1;injected_write=1;
        for(integer a=0;a<128;a++) begin
            injected_address=8'(a); injected_data=PATTERN ^ 256'(a);
            injected_read0=8'(a&~1);injected_read1=8'((a&~1)+1);
            tick(); @(negedge clk);
        end
        // Back-to-back writes overwrite one address and alternate parity.
        // The first read after capture must observe forwarding, while raw
        // RAM still holds the immediately preceding committed version.
        for(integer a=0;a<64;a++) begin
            injected_address=8'(a%4); injected_data=PATTERN ^ (256'(a+1024)<<16);
            injected_read0=8'((a%4)&~1);injected_read1=injected_read0+1;
            tick(); @(negedge clk);
        end
        // Repeat a single address, forwarding the new version every edge.
        for(integer a=0;a<16;a++) begin
            injected_address=8'd37;injected_data=PATTERN ^ (256'(a+2048)<<32);
            injected_read0=8'd36;injected_read1=8'd37;
            tick(); @(negedge clk);
        end
        // Read0 may itself be odd (including the 127/126 guard pair).
        for(integer a=0;a<16;a++) begin
            injected_address=(a[0] ? 8'd126 : 8'd127);
            injected_read0=8'd127;injected_read1=8'd126;
            injected_data=PATTERN ^ (256'(a+4096)<<48);
            tick(); @(negedge clk);
        end
        // The old pending word must physically land on the reset edge;
        // rst clears only the next commit-valid bit, never the RAM write.
        injected_address=8'd99;injected_read0=8'd98;injected_read1=8'd99;
        injected_data=PATTERN ^ 256'h1234;tick();
        if(!dut.workspace_commit_valid || dut.endpoint_value1!==injected_data)
            $fatal(1,"reset test did not prepare a forwarded pending write");
        @(negedge clk);rst=1;injected_write=0;tick();
        if(dut.workspace_commit_valid)
            $fatal(1,"reset did not clear the pending valid bit");
        // Reset also returns the registered read pair to 0/1. Select the
        // tested location again after the edge, then inspect physical RAM
        // with forwarding disabled by the cleared valid bit.
        dut.read_addresses.address=8'd98;
        dut.read_addresses.adjacent_address=8'd99;
        #1;
        if(dut.endpoint_ram_value1!==injected_data || dut.endpoint_value1!==injected_data)
            $fatal(1,"pending write was lost instead of physically committed on reset");
        @(negedge clk);rst=0;injection_active=0;
        release dut.endpoint_write;release dut.endpoint_address;release dut.endpoint_data;

        reset_core();
        // Exercise the guard slot directly, without generating a full tree or
        // changing the frozen RTL. Both addresses must be prepared on one edge.
        @(negedge clk);dut.state=type(dut.state)'(7'd23);force dut.lane_list_next=8'd126;tick();
        if(dut.endpoint_read0!==8'd126 || dut.endpoint_read1!==8'd127)$fatal(1,"126/127 pair");
        @(negedge clk);force dut.lane_list_next=8'd127;tick();
        if(dut.endpoint_read0!==8'd127 || dut.endpoint_read1!==8'd126)$fatal(1,"127/126 guard pair");
        @(negedge clk);force dut.lane_list_next=8'd0;tick();
        if(dut.endpoint_read0!==8'd0 || dut.endpoint_read1!==8'd1)$fatal(1,"0/1 pair");
        release dut.lane_list_next;
        // Stop clock edges while checking the address combinational decoder
        // independently of the unrelated state-control protocol. The complete
        // functional regressions separately run every RTL assertion normally.
        @(negedge clk);clock_enable=0;dut.state=type(dut.state)'(0);
        check_next(0,"default hold");
        dut.state=type(dut.state)'(15);check_next(0,"REDUCE_SETUP");
        dut.state=type(dut.state)'(6);check_next(0,"TREE_INIT");
        dut.state=type(dut.state)'(46);check_next(0,"LT_COPY");
        dut.state=type(dut.state)'(17);dut.node_level=3;dut.tree_height=10;check_next(71,"PUSH_NODE stack");
        dut.node_level=10;check_next(88,"PUSH_NODE root");
        dut.state=type(dut.state)'(20);dut.auth_level=19;check_next(108,"AUTH_OUTPUT height20");
        dut.state=type(dut.state)'(22);force dut.lane_list_next=8'd126;check_next(126,"HASH_ISSUE");
        dut.state=type(dut.state)'(23);force dut.lane_list_next=8'd127;check_next(127,"HASH_WAIT guard");
        release dut.lane_list_next;
        dut.state=type(dut.state)'(54);dut.lt_cursor=5;check_next(4,"LT_PIPE_INIT aligned");
        dut.state=type(dut.state)'(47);check_next(0,"LT_NEXT holds for P>1");
        dut.state=type(dut.state)'(55);force dut.pipe_ready=0;check_next(0,"LT_PIPE_ISSUE stalled");
        force dut.pipe_ready=1;dut.lt_cursor=0;dut.pipe_issue_slot=0;check_next(2,"LT_PIPE_ISSUE first");
        dut.pipe_issue_slot=PIPELINE-1;check_next(2*PIPELINE,"LT_PIPE_ISSUE last");
        dut.state=type(dut.state)'(56);force dut.lt_batch_complete=0;check_next(0,"LT_PIPE_WAIT incomplete");
        force dut.lt_batch_complete=1;dut.lt_cursor=0;dut.lt_count=67;check_next(2*PIPELINE,"LT_PIPE_WAIT next wave");
        dut.lt_cursor=66;check_next(66,"LT_PIPE_WAIT odd tail 67");
        dut.lt_count=66;check_next(0,"LT_PIPE_WAIT even finish");
        release dut.lt_batch_complete;
        dut.state=type(dut.state)'(68);dut.fors_total=8;dut.fors_target_delta=20;check_next(36,"FORS_LEAF_NEXT other group");
        dut.fors_target_delta=7;check_next(42,"FORS_LEAF_NEXT target group");
        dut.state=type(dut.state)'(59);check_next(36,"FORS_AUTH0");
        dut.state=type(dut.state)'(60);check_next(36,"FORS_BEGIN");
        dut.state=type(dut.state)'(66);check_next(36,"FORS_AUTH1");
        dut.state=type(dut.state)'(65);check_next(36,"FORS_LEVEL");
        dut.state=type(dut.state)'(63);force dut.pipe_ready=0;check_next(0,"FORS_ISSUE stalled");
        force dut.pipe_ready=1;dut.pipe_issue_slot=PIPELINE-1;check_next(36,"FORS_ISSUE final slot");
        dut.pipe_issue_slot=0;dut.pipe_expected_mask=0;check_next(36,"FORS_ISSUE empty remainder");
        dut.pipe_expected_mask='1;dut.fors_offset=0;check_next(38,"FORS_ISSUE next input");
        release dut.pipe_ready;
        dut.state=type(dut.state)'(64);dut.fors_offset=0;force dut.fors_outputs=5'(PIPELINE+1);
        check_next(36+2*PIPELINE,"FORS_WAIT structural continuation branch");
        release dut.fors_outputs;dut.fors_total=4;dut.fors_level=1;check_next(36,"FORS_WAIT upper level");
        dut.fors_level=0;dut.fors_total=8;dut.fors_target_delta=6;check_next(38,"FORS_WAIT target auth");
        dut.fors_target_delta=20;check_next(36,"FORS_WAIT other group");
        dut.state=type(dut.state)'(69);dut.fors_root_cursor=11;check_next(48,"FORS_ROOT_NEXT");
        dut.state=type(dut.state)'(0);clock_enable=1;
        reset_core();
        // Construct a legal shared-write collision: leaf zero is the target
        // leaf one's authentication node and is also an even tree-stack node.
        @(negedge clk);
        dut.operation=2'd1;dut.node_level=0;dut.tree_height=10;
        dut.target=1;dut.target_at_level=1;dut.node_index=0;
        dut.auth_node_match=1;dut.node_below_root=1;
        dut.macro_flags=8'h02;dut.node_value=PATTERN;
        dut.state=type(dut.state)'(7'd17);
        #1;
        if(!dut.auth_write || !dut.stack_write || !dut.endpoint_write || dut.endpoint_address!==8'd88)
            $fatal(1,"authentication write must win shared port");
        tick();
        if(dut.state!==type(dut.state)'(7'd70) || dut.auth_write || !dut.stack_write ||
            !dut.endpoint_write || dut.endpoint_address!==8'd68)
            $fatal(1,"deferred stack write must own next cycle");
        tick();
        reset_core();
        @(negedge clk);dut.state=type(dut.state)'(7'd23);force dut.lane_list_next=8'd88;tick();
        if(dut.endpoint_value0!==PATTERN)$fatal(1,"authentication node not committed");
        @(negedge clk);force dut.lane_list_next=8'd68;tick();
        if(dut.endpoint_value0!==PATTERN)$fatal(1,"deferred stack node not committed");
        release dut.lane_list_next;
        if(forward0_checks==0 || forward1_checks==0 || reset_flush_checks==0 || physical_read_checks<200)
            $fatal(1,"workspace coverage incomplete");
        $display("WORKSPACE_TIMING_PASS P%0dU1 read126_127=1 read127_126=1 auth_priority=1 deferred_stack=1 address_decoder_checks=%0d logical_reads=%0d physical_RAM_reads=%0d forward0=%0d forward1=%0d reset_pending_flush=%0d back_to_back=1 repeated_same_address=1",PIPELINE,address_checks,logical_read_checks,physical_read_checks,forward0_checks,forward1_checks,reset_flush_checks);
        $finish;
    end
endmodule
