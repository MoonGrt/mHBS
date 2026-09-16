`timescale 1ns/1ps
`default_nettype none

module tb_micro_hbs_xmss_wots_tree_slice;
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
    logic [15:0] job_target_leaf = 0;
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

    localparam logic [7:0] OP_MOVI = 8'h01;
    localparam logic [7:0] OP_HASH_LAYOUT = 8'h03;
    localparam logic [7:0] OP_LOOP_SETUP = 8'h04;
    localparam logic [7:0] OP_LOOP_END = 8'h05;
    localparam logic [7:0] OP_TREE_PUSH = 8'h0b;
    localparam logic [7:0] OP_HALT = 8'h0d;
    localparam logic [255:0] EXPECTED_ROOT =
        256'hf37079a672a8cdb3db910be2eaba5de2772f31dcc1c9984df28719cb8d241b23;
    localparam logic [255:0] EXPECTED_AUTH =
        256'hc3d718baf73c8d78d5b59d60b6e7f0ef36e3f784644c6b8e78639a83629bd8b1;
    logic [255:0] captured_root, captured_auth;
    integer byte_index, timeout;

    always #5 clk = ~clk;
    micro_hbs_xmss_wots_tree_slice #(
        .PROGRAM_WORDS(16), .TREE_HEIGHT(1), .SCRATCH_WORDS(64), .UNROLL(2)
    ) dut (.*);

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            captured_root <= '0;
            captured_auth <= '0;
        end else begin
            if (root_valid) captured_root <= root;
            if (auth_valid) begin
                if (auth_level != 0) $fatal(1, "unexpected auth level");
                captured_auth <= auth_node;
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
            @(negedge clk); program_addr = address; program_wdata = word;
            program_we = 1'b1;
            @(negedge clk); program_we = 1'b0;
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
        write_program(1, enc(OP_LOOP_SETUP, 0, 0, 0, 2));
        // Layout 0x0200 reuses logical node slot 8; R0 is the leaf identity.
        write_program(2, enc(OP_HASH_LAYOUT, 1, 8, 0, 16'h0200));
        write_program(3, enc(OP_TREE_PUSH, 0, 8, 0, 16'h0200));
        write_program(4, enc(OP_LOOP_END, 0, 0, 0, 0));
        write_program(5, enc(OP_HALT, 0, 0, 0, 0));

        @(negedge clk); job_valid = 1'b1;
        @(negedge clk); job_valid = 1'b0;
        timeout = 0;
        while (!done && !error && timeout < 150000) begin
            @(negedge clk); timeout = timeout + 1;
        end
        if (!done || error || captured_root !== EXPECTED_ROOT)
            $fatal(1, "WOTS->TreeHash Job failed code=%h root=%064x",
                   error_code, captured_root);
        if (captured_auth !== EXPECTED_AUTH)
            $fatal(1, "authentication node mismatch got=%064x", captured_auth);
        if (accepted_job_commands != 1
            || host_control_writes_during_busy != 0
            || issued_hash_requests != 2 || issued_tree_requests != 2
            || accepted_leaves != 2 || parent_hashes != 1
            || leaf_scratch_writes != 8 || last_leaf_shake_calls != 3346
            || scratch_transactions != 16 || retired_instructions != 9)
            $fatal(1, "autonomy/accounting mismatch job=%0d hash=%0d tree=%0d leaf=%0d parent=%0d writes=%0d scratch=%0d retired=%0d",
                   accepted_job_commands, issued_hash_requests,
                   issued_tree_requests, accepted_leaves, parent_hashes,
                   leaf_scratch_writes, scratch_transactions,
                   retired_instructions);
        $display("PASS one-Job HASH_LAYOUT->RFC8391 WOTS+ leaf->Scratchpad->TREE_PUSH->XMSS root/auth");
        $finish;
    end
endmodule

`default_nettype wire
