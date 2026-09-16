`timescale 1ns/1ps
`default_nettype none

module tb_micro_hbs_data_tree_slice;
    logic clk = 1'b0;
    logic rst_n = 1'b0;
    logic program_we = 1'b0;
    logic [8:0] program_addr = '0;
    logic [63:0] program_wdata = '0;
    logic descriptor_cfg_valid = 1'b0;
    wire descriptor_cfg_ready;
    logic [15:0] descriptor_cfg_id = '0;
    logic [127:0] descriptor_cfg_data = '0;
    wire descriptor_cfg_error;
    wire [15:0] descriptor_cfg_error_code;
    logic scratch_init_valid = 1'b0;
    wire scratch_init_ready;
    logic [15:0] scratch_init_address = '0;
    logic [63:0] scratch_init_data = '0;
    logic job_valid = 1'b0;
    wire job_ready;
    logic [8:0] job_entry = '0;
    logic [15:0] job_target_leaf = 16'd2;
    logic [255:0] job_public_seed = '0;
    logic [255:0] job_address_template = '0;
    wire out_valid;
    logic out_ready = 1'b0;
    wire [63:0] out_data;
    wire [7:0] out_keep;
    wire out_last;
    wire root_valid, auth_valid, busy, done, error;
    wire [255:0] root, auth_node;
    wire [7:0] auth_level;
    wire [15:0] error_code;
    wire [31:0] accepted_job_commands, host_control_writes_during_busy;
    wire [31:0] issued_data_requests, issued_tree_requests;
    wire [31:0] retired_instructions;
    wire [15:0] accepted_leaves, parent_hashes;
    wire [31:0] data_scratch_grants, emit_scratch_grants;
    wire [31:0] tree_scratch_grants, scratch_transactions;

    localparam logic [7:0] OP_MOVI = 8'h01;
    localparam logic [7:0] OP_LOOP_SETUP = 8'h04;
    localparam logic [7:0] OP_LOOP_END = 8'h05;
    localparam logic [7:0] OP_STORE = 8'h09;
    localparam logic [7:0] OP_TREE_PUSH = 8'h0b;
    localparam logic [7:0] OP_EMIT = 8'h0c;
    localparam logic [7:0] OP_HALT = 8'h0d;
    localparam logic [255:0] EXPECTED_ROOT =
        256'h8b3ab1a3257bef6845f6c66f3b0f2c564037d0b292090bb20b4a964f80976960;
    localparam logic [255:0] EXPECTED_AUTH1 =
        256'h3679c3520a5c65af4889281d2e32c911bd2a0a4bc9da266d4ab2a169979c5aff;

    logic [255:0] captured_root;
    logic [1:0] auth_mask;
    logic [255:0] auth_nodes [0:1];
    integer output_words;
    integer leaf_index, word_index, byte_index, timeout;

    always #5 clk = ~clk;

    micro_hbs_data_tree_slice #(
        .PROGRAM_WORDS(16), .DESCRIPTOR_COUNT(4), .SCRATCH_WORDS(64),
        .TREE_HEIGHT(2), .UNROLL(2)
    ) dut (.*);

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            captured_root <= '0;
            auth_mask <= '0;
            auth_nodes[0] <= '0;
            auth_nodes[1] <= '0;
            output_words <= 0;
        end else begin
            if (root_valid) captured_root <= root;
            if (auth_valid) begin
                if (auth_level >= 2) $fatal(1, "invalid auth level");
                auth_mask[auth_level] <= 1'b1;
                auth_nodes[auth_level] <= auth_node;
            end
            if (out_valid && out_ready) begin
                if (out_data !== {8{8'h01}} || out_keep != 8'hff
                    || !out_last)
                    $fatal(1, "EMIT output mismatch");
                output_words <= output_words + 1;
            end
        end
    end

    function automatic [63:0] enc(input [7:0] opcode,
        input [7:0] flags, input [7:0] rd, input [7:0] rs,
        input [31:0] imm);
        enc = {opcode, flags, rd, rs, imm};
    endfunction

    function automatic [127:0] desc(input [15:0] flags,
        input [15:0] source_a, input [15:0] source_b,
        input [15:0] destination, input [15:0] word_count,
        input [3:0] last_bytes, input [3:0] address_mode);
        desc = {8'h01, flags, source_a, source_b, destination,
                word_count, last_bytes, address_mode, 32'b0};
    endfunction

    task automatic write_program(input [8:0] address, input [63:0] word);
        begin
            @(negedge clk); program_addr = address; program_wdata = word;
            program_we = 1'b1;
            @(negedge clk); program_we = 1'b0;
        end
    endtask

    task automatic write_descriptor(input [15:0] id,
                                    input [127:0] value);
        begin
            @(negedge clk);
            if (!descriptor_cfg_ready) $fatal(1, "descriptor not ready");
            descriptor_cfg_id = id; descriptor_cfg_data = value;
            descriptor_cfg_valid = 1'b1;
            @(negedge clk); descriptor_cfg_valid = 1'b0;
            if (descriptor_cfg_error)
                $fatal(1, "descriptor config error %h",
                       descriptor_cfg_error_code);
        end
    endtask

    task automatic write_scratch(input [15:0] address, input [63:0] word);
        begin
            @(negedge clk);
            if (!scratch_init_ready) $fatal(1, "scratch init not ready");
            scratch_init_address = address; scratch_init_data = word;
            scratch_init_valid = 1'b1;
            @(negedge clk); scratch_init_valid = 1'b0;
        end
    endtask

    initial begin
        for (byte_index = 0; byte_index < 32; byte_index = byte_index + 1)
            job_public_seed[8*byte_index +: 8] = 8'h40 + byte_index;

        repeat (3) @(negedge clk);
        rst_n = 1'b1;
        // Copy 4 leaves into the TreeHash region, then run the tree and emit
        // one source word.  All three clients traverse the same arbiter.
        write_program(0, enc(OP_STORE, 0, 0, 0, 0));
        write_program(1, enc(OP_MOVI, 0, 0, 0, 0));
        write_program(2, enc(OP_LOOP_SETUP, 0, 0, 0, 4));
        write_program(3, enc(OP_TREE_PUSH, 0, 0, 0, 16'h0082));
        write_program(4, enc(OP_LOOP_END, 0, 0, 0, 0));
        write_program(5, enc(OP_EMIT, 0, 0, 0, 32'h0001_0000));
        write_program(6, enc(OP_HALT, 0, 0, 0, 0));

        write_descriptor(0, desc(16'h0002, 16, 0, 0, 16, 0, 0));
        write_descriptor(1, desc(16'h0008, 20, 0, 0, 1, 8, 0));

        for (leaf_index = 0; leaf_index < 4; leaf_index = leaf_index + 1)
            for (word_index = 0; word_index < 4; word_index = word_index + 1)
                write_scratch(16 + leaf_index*4 + word_index,
                              {8{leaf_index[7:0]}});

        @(negedge clk); job_valid = 1'b1;
        @(negedge clk); job_valid = 1'b0;
        out_ready = 1'b1;
        timeout = 0;
        while (!done && !error && timeout < 10000) begin
            @(negedge clk); timeout = timeout + 1;
        end
        out_ready = 1'b0;
        if (!done || error || captured_root !== EXPECTED_ROOT)
            $fatal(1, "combined Job failed code=%h root=%064x",
                   error_code, captured_root);
        if (auth_mask != 2'b11
            || auth_nodes[0] !== {32{8'h03}}
            || auth_nodes[1] !== EXPECTED_AUTH1)
            $fatal(1, "combined auth mismatch");
        if (output_words != 1 || accepted_job_commands != 1
            || host_control_writes_during_busy != 0
            || issued_data_requests != 2 || issued_tree_requests != 4
            || retired_instructions != 13 || accepted_leaves != 4
            || parent_hashes != 3 || data_scratch_grants != 32
            || emit_scratch_grants != 1 || tree_scratch_grants != 16
            || scratch_transactions != 49)
            $fatal(1, "combined accounting data=%0d emit=%0d tree=%0d tx=%0d retired=%0d",
                   data_scratch_grants, emit_scratch_grants,
                   tree_scratch_grants, scratch_transactions,
                   retired_instructions);

        $display("PASS combined one-Job data+TreeHash slice: 49 shared Scratchpad transactions, RFC8391 root/auth, EMIT");
        $finish;
    end
endmodule

`default_nettype wire
