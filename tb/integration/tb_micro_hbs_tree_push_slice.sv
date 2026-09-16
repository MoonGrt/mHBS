`timescale 1ns/1ps
`default_nettype none

module tb_micro_hbs_tree_push_slice;
    logic clk = 1'b0;
    logic rst_n = 1'b0;
    logic program_we = 1'b0;
    logic [8:0] program_addr = '0;
    logic [63:0] program_wdata = '0;
    logic scratch_init_valid = 1'b0;
    wire scratch_init_ready;
    logic [15:0] scratch_init_address = '0;
    logic [63:0] scratch_init_data = '0;
    logic job_valid = 1'b0;
    wire job_ready;
    logic [8:0] job_entry = '0;
    logic [15:0] job_target_leaf = 16'd2;
    wire busy, done, error;
    wire [15:0] error_code;
    wire root_valid;
    wire [255:0] root;
    wire auth_valid;
    wire [7:0] auth_level;
    wire [255:0] auth_node;
    wire [31:0] accepted_job_commands, host_control_writes_during_busy;
    wire [31:0] issued_tree_requests, retired_instructions;
    wire [15:0] accepted_leaves, parent_hashes;
    wire [7:0] peak_stack_nodes;

    logic [255:0] captured_root;
    logic [1:0] auth_mask;
    logic [255:0] auth_nodes [0:1];
    integer leaf_index;
    integer word_index;
    integer timeout;

    localparam logic [7:0] OP_MOVI = 8'h01;
    localparam logic [7:0] OP_LOOP_SETUP = 8'h04;
    localparam logic [7:0] OP_LOOP_END = 8'h05;
    localparam logic [7:0] OP_TREE_PUSH = 8'h0b;
    localparam logic [7:0] OP_HALT = 8'h0d;
    // hashlib.shake_256 tree root bytes are
    // 313dce54...4d24769c.  The streaming SHAKE RTL stores byte zero in
    // root[7:0], hence its vector-literal display is byte-reversed.
    localparam logic [255:0] EXPECTED_ROOT =
        256'h9c76244d9eae66584ddaf7df47f84479f3005c6f450e1bdc01ce7b3c54ce3d31;

    always #5 clk = ~clk;

    micro_hbs_tree_push_slice #(
        .PROGRAM_WORDS(16), .TREE_HEIGHT(2), .NODE_BYTES(32),
        .SCRATCH_WORDS(64), .UNROLL(2)
    ) dut (.*);

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            captured_root <= '0;
            auth_mask <= '0;
            auth_nodes[0] <= '0;
            auth_nodes[1] <= '0;
        end else begin
            if (root_valid)
                captured_root <= root;
            if (auth_valid) begin
                if (auth_level >= 2) $fatal(1, "invalid auth level");
                auth_mask[auth_level] <= 1'b1;
                auth_nodes[auth_level] <= auth_node;
            end
        end
    end

    function automatic [63:0] enc(
        input [7:0] opcode,
        input [7:0] flags,
        input [7:0] rd,
        input [7:0] rs,
        input [31:0] imm
    );
        enc = {opcode, flags, rd, rs, imm};
    endfunction

    task automatic write_program(input [8:0] address, input [63:0] word);
        begin
            @(negedge clk);
            program_addr = address;
            program_wdata = word;
            program_we = 1'b1;
            @(negedge clk);
            program_we = 1'b0;
        end
    endtask

    task automatic write_scratch(input [15:0] address, input [63:0] word);
        begin
            @(negedge clk);
            if (!scratch_init_ready) $fatal(1, "scratch init not ready");
            scratch_init_address = address;
            scratch_init_data = word;
            scratch_init_valid = 1'b1;
            @(negedge clk);
            scratch_init_valid = 1'b0;
        end
    endtask

    initial begin
        repeat (3) @(negedge clk);
        rst_n = 1'b1;

        // R0 is the loop counter and therefore the TREE_PUSH leaf index.
        write_program(0, enc(OP_MOVI, 0, 0, 0, 0));
        write_program(1, enc(OP_LOOP_SETUP, 0, 0, 0, 4));
        write_program(2, enc(OP_TREE_PUSH, 0, 0, 0, 16'h0042));
        write_program(3, enc(OP_LOOP_END, 0, 0, 0, 0));
        write_program(4, enc(OP_HALT, 0, 0, 0, 0));

        // Four leaves, each 32 bytes of its leaf index.  The scratch word
        // ordering matches the adapter's documented [63:0]-first assembly.
        for (leaf_index = 0; leaf_index < 4; leaf_index = leaf_index + 1)
            for (word_index = 0; word_index < 4; word_index = word_index + 1)
                write_scratch(leaf_index*4 + word_index,
                    {8{leaf_index[7:0]}});

        @(negedge clk);
        job_valid = 1'b1;
        @(negedge clk);
        job_valid = 1'b0;

        timeout = 0;
        while (!done && !error && timeout < 2000) begin
            @(negedge clk);
            timeout = timeout + 1;
        end
        if (!done || error)
            $fatal(1, "tree Job failed/timeout error=%h", error_code);
        if (captured_root !== EXPECTED_ROOT)
            $fatal(1, "root mismatch got=%064x", captured_root);
        if (auth_mask != 2'b11)
            $fatal(1, "auth path incomplete mask=%b", auth_mask);
        if (accepted_job_commands != 1 || host_control_writes_during_busy != 0
            || issued_tree_requests != 4 || accepted_leaves != 4
            || parent_hashes != 3 || retired_instructions != 11
            || peak_stack_nodes == 0)
            $fatal(1, "accounting jobs=%0d host=%0d tree=%0d leaves=%0d parents=%0d retired=%0d peak=%0d",
                   accepted_job_commands, host_control_writes_during_busy,
                   issued_tree_requests, accepted_leaves, parent_hashes,
                   retired_instructions, peak_stack_nodes);

        $display("PASS one-Job microcode TREE_PUSH -> Scratchpad -> real TreeHash/SHAKE root/auth");
        $finish;
    end
endmodule

`default_nettype wire
