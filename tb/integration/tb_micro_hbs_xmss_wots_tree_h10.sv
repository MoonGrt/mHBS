`timescale 1ns/1ps
`default_nettype none

// Complete RFC 8391 XMSS-SHAKE256_10_256 key-generation tree replay.
// Six static microinstructions expand 1,024 HASH_LAYOUT/TREE_PUSH pairs;
// leaves are generated in RTL and are never supplied by the host.
module tb_micro_hbs_xmss_wots_tree_h10;
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
    logic [15:0] job_target_leaf = 16'd5;
    logic [255:0] job_sk_seed = '0;
    logic [255:0] job_public_seed = '0;
    logic [255:0] job_address_template = '0;
    wire busy, done, error, root_valid, auth_valid;
    wire [15:0] error_code;
    wire [255:0] root, auth_node;
    wire [7:0] auth_level;
    wire [31:0] accepted_job_commands;
    wire [31:0] host_control_writes_during_busy;
    wire [31:0] issued_hash_requests, issued_tree_requests;
    wire [31:0] retired_instructions;
    wire [15:0] accepted_leaves, parent_hashes;
    wire [31:0] leaf_scratch_writes, last_leaf_shake_calls;
    wire [31:0] scratch_transactions;

    logic [255:0] captured_root;
    logic [255:0] captured_auth [0:9];
    logic [9:0] captured_auth_mask;
    logic [63:0] operation_cycles;
    integer byte_index;
    integer level;
    integer timeout;

    localparam logic [7:0] OP_MOVI = 8'h01;
    localparam logic [7:0] OP_HASH_LAYOUT = 8'h03;
    localparam logic [7:0] OP_LOOP_SETUP = 8'h04;
    localparam logic [7:0] OP_LOOP_END = 8'h05;
    localparam logic [7:0] OP_TREE_PUSH = 8'h0b;
    localparam logic [7:0] OP_HALT = 8'h0d;

    // Byte zero is stored in bits [7:0], hence these packed constants are the
    // byte reverse of the conventional hexadecimal RFC/Python presentation.
    localparam logic [255:0] EXPECTED_ROOT =
        256'h251451dc9b735dc3221eec5a48cff52c23dafc3c9df1663ea636f19ac3bd62ba;

    function automatic [255:0] expected_auth(input integer auth_index);
        begin
            case (auth_index)
                0: expected_auth = 256'had26933c91a6b104602213e06344ed8ec29d2a0d7bba15baf968f4cecbbe2da6;
                1: expected_auth = 256'h0a5afd093798fc8709cd37a3168079322aa29ca2a4dfe7ac8660b6c0c9e790b1;
                2: expected_auth = 256'hf9475994eae032b3e5ce9bce7754e4bb9eef436292d454b676433fd517bec637;
                3: expected_auth = 256'hfb52ed6351e9119ba79e4902e984a58ac42e7f346c6e6f8eb535cbb266462d13;
                4: expected_auth = 256'h2d4ac857c402cac5d1b5f7a0230c7bf94c78955796f266c13c829e9b9c7e50b3;
                5: expected_auth = 256'h9fb36cd4cee69c9aea7e86f47dc00d46be46df3a0bbaf263f872480ce5c4a2bd;
                6: expected_auth = 256'h83b56c93008b82b3e882ed14497e54b3ee4d3c507a0b670ee0cf9f70a7d8d045;
                7: expected_auth = 256'h7a693117e3e1b10dd0487aed3f43293b2fc8b30373c9bfae82bf17afd9af0cf0;
                8: expected_auth = 256'h3ff9979004ac5c74815b6515f5aaf578cae96472705edc1adca805944d24ba91;
                9: expected_auth = 256'h4b92e8b546a94dc58b07dc1a1094ba51cd5cbf98ef199157de1cede275b370b7;
                default: expected_auth = 'x;
            endcase
        end
    endfunction

    always #5 clk = ~clk;

    micro_hbs_xmss_wots_tree_slice #(
        .PROGRAM_WORDS(16), .TREE_HEIGHT(10), .SCRATCH_WORDS(64), .UNROLL(2)
    ) dut (.*);

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            captured_root <= '0;
            captured_auth_mask <= '0;
            operation_cycles <= '0;
            for (level = 0; level < 10; level = level + 1)
                captured_auth[level] <= '0;
        end else begin
            if (job_valid && job_ready)
                operation_cycles <= 64'd1;
            else if (busy)
                operation_cycles <= operation_cycles + 1'b1;
            if (root_valid)
                captured_root <= root;
            if (auth_valid) begin
                if (auth_level >= 10)
                    $fatal(1, "authentication level out of range %0d", auth_level);
                captured_auth[auth_level] <= auth_node;
                captured_auth_mask[auth_level] <= 1'b1;
            end
        end
    end

    function automatic [63:0] enc(input [7:0] opcode,
        input [7:0] flags, input [7:0] rd, input [7:0] rs,
        input [31:0] imm);
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

    initial begin
        for (byte_index = 0; byte_index < 32; byte_index = byte_index + 1) begin
            job_sk_seed[8*byte_index +: 8] = byte_index[7:0];
            job_public_seed[8*byte_index +: 8] = 8'h40 + byte_index[7:0];
        end

        repeat (3) @(negedge clk);
        rst_n = 1'b1;
        write_program(0, enc(OP_MOVI, 0, 0, 0, 0));
        write_program(1, enc(OP_LOOP_SETUP, 0, 0, 0, 1024));
        write_program(2, enc(OP_HASH_LAYOUT, 1, 8, 0, 16'h0200));
        write_program(3, enc(OP_TREE_PUSH, 0, 8, 0, 16'h0200));
        write_program(4, enc(OP_LOOP_END, 0, 0, 0, 0));
        write_program(5, enc(OP_HALT, 0, 0, 0, 0));

        @(negedge clk);
        if (!job_ready)
            $fatal(1, "sequencer not ready");
        job_valid = 1'b1;
        @(negedge clk);
        job_valid = 1'b0;

        timeout = 0;
        while (!done && !error && timeout < 100000000) begin
            @(negedge clk);
            timeout = timeout + 1;
        end

        if (!done || error)
            $fatal(1, "XMSS h10 Job failed/timeout code=%h cycle=%0d",
                   error_code, timeout);
        if (captured_root !== EXPECTED_ROOT)
            $fatal(1, "XMSS h10 root mismatch got=%064x", captured_root);
        if (captured_auth_mask !== 10'h3ff)
            $fatal(1, "XMSS h10 auth mask mismatch %03x", captured_auth_mask);
        for (level = 0; level < 10; level = level + 1)
            if (captured_auth[level] !== expected_auth(level))
                $fatal(1, "auth[%0d] mismatch got=%064x",
                       level, captured_auth[level]);

        if (accepted_job_commands != 1
            || host_control_writes_during_busy != 0
            || issued_hash_requests != 1024
            || issued_tree_requests != 1024
            || accepted_leaves != 1024
            || parent_hashes != 1023
            || leaf_scratch_writes != 4096
            || last_leaf_shake_calls != 3346
            || scratch_transactions != 8192
            || retired_instructions != 3075)
            $fatal(1, "accounting mismatch jobs=%0d hashes=%0d tree=%0d leaves=%0d parents=%0d writes=%0d scratch=%0d retired=%0d",
                   accepted_job_commands, issued_hash_requests,
                   issued_tree_requests, accepted_leaves, parent_hashes,
                   leaf_scratch_writes, scratch_transactions,
                   retired_instructions);

        $display("PASS microcoded XMSS h10 RTL root/auth cycles=%0d leaves=%0d parents=%0d",
                 operation_cycles, accepted_leaves, parent_hashes);
        $finish;
    end
endmodule

`default_nettype wire
