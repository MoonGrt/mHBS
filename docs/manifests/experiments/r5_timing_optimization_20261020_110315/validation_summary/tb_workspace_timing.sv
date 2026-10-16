`timescale 1ns/1ps
module tb_workspace_timing;
    parameter integer PIPELINE=4;
    logic clk=0,rst=1;
    always #5 clk=~clk;
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
    task tick; begin @(posedge clk); #1; end endtask
    task reset_core; begin
        @(negedge clk); rst=1; repeat(3)tick(); @(negedge clk);rst=0;tick();
    end endtask
    initial begin
        reset_core();
        // Exercise the guard slot directly, without generating a full tree or
        // changing the frozen RTL. Both addresses must be prepared on one edge.
        @(negedge clk);force dut.read_addresses.next_address=8'd126;tick();
        if(dut.endpoint_read0!==8'd126 || dut.endpoint_read1!==8'd127)$fatal(1,"126/127 pair");
        @(negedge clk);force dut.read_addresses.next_address=8'd127;tick();
        if(dut.endpoint_read0!==8'd127 || dut.endpoint_read1!==8'd126)$fatal(1,"127/126 guard pair");
        @(negedge clk);force dut.read_addresses.next_address=8'd0;tick();
        if(dut.endpoint_read0!==8'd0 || dut.endpoint_read1!==8'd1)$fatal(1,"0/1 pair");
        release dut.read_addresses.next_address;
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
        @(negedge clk);force dut.read_addresses.next_address=8'd88;tick();
        if(dut.endpoint_value0!==PATTERN)$fatal(1,"authentication node not committed");
        @(negedge clk);force dut.read_addresses.next_address=8'd68;tick();
        if(dut.endpoint_value0!==PATTERN)$fatal(1,"deferred stack node not committed");
        release dut.read_addresses.next_address;
        $display("WORKSPACE_TIMING_PASS P%0dU1 read126_127=1 read127_126=1 auth_priority=1 deferred_stack=1",PIPELINE);
        $finish;
    end
endmodule
