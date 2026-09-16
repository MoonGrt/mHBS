`timescale 1ns/1ps
`default_nettype none

// Executes the first two XMSS Sign hashes directly from the JSON-lowered
// layout/component images: PRF randomizer followed by H_msg.  The host loads
// immutable Job bytes once while IDLE; no Hash/task command enters while BUSY.
module tb_micro_hbs_xmss_sign_prehash_slice;
    logic clk = 1'b0;
    logic rst_n = 1'b0;
    logic program_we = 1'b0;
    logic [8:0] program_addr = '0;
    logic [63:0] program_wdata = '0;
    logic layout_cfg_valid = 1'b0;
    wire layout_cfg_ready;
    logic [15:0] layout_cfg_id = '0;
    logic [127:0] layout_cfg_descriptor = '0;
    wire layout_cfg_error;
    wire [15:0] layout_cfg_error_code;
    logic component_cfg_valid = 1'b0;
    wire component_cfg_ready;
    logic [15:0] component_cfg_index = '0;
    logic [191:0] component_cfg_descriptor = '0;
    wire component_cfg_error;
    wire [15:0] component_cfg_error_code;
    logic scratch_init_valid = 1'b0;
    wire scratch_init_ready;
    logic scratch_init_write = 1'b0;
    logic [15:0] scratch_init_address = '0;
    logic [63:0] scratch_init_write_data = '0;
    wire scratch_init_rsp_valid;
    wire [63:0] scratch_init_rsp_data;
    wire scratch_init_error;
    logic job_valid = 1'b0;
    wire job_ready;
    logic [8:0] job_entry = '0;
    wire busy, done, error;
    wire [15:0] error_code;
    wire [255:0] last_digest;
    wire [31:0] accepted_job_commands;
    wire [31:0] host_control_writes_during_busy;
    wire [31:0] issued_hash_requests, retired_instructions;
    wire [31:0] scratch_reads, scratch_writes, absorbed_blocks;
    wire [31:0] retired_components;

    logic [127:0] layout_image [0:9];
    logic [191:0] component_image [0:90];
    logic [63:0] read_word;
    integer index;
    integer measured_cycles;

    localparam logic [7:0] OP_HASH_LAYOUT = 8'h03;
    localparam logic [7:0] OP_HALT = 8'h0d;

    always #5 clk = ~clk;

    micro_hbs_descriptor_shake_slice #(
        .PROGRAM_WORDS(8), .LAYOUT_COUNT(16), .COMPONENT_WORDS(128),
        .SCRATCH_WORDS(1024), .MAX_MESSAGE_BYTES(4096), .UNROLL(2)
    ) dut (.*);

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

    task automatic configure_layout(input [15:0] id,
                                    input [127:0] value);
        begin
            while (!layout_cfg_ready) @(negedge clk);
            @(negedge clk);
            layout_cfg_id = id;
            layout_cfg_descriptor = value;
            layout_cfg_valid = 1'b1;
            @(posedge clk);
            #1 layout_cfg_valid = 1'b0;
            if (layout_cfg_error)
                $fatal(1, "layout configure failed %h", layout_cfg_error_code);
        end
    endtask

    task automatic configure_component(input [15:0] address,
                                       input [191:0] value);
        begin
            while (!component_cfg_ready) @(negedge clk);
            @(negedge clk);
            component_cfg_index = address;
            component_cfg_descriptor = value;
            component_cfg_valid = 1'b1;
            @(posedge clk);
            #1 component_cfg_valid = 1'b0;
            if (component_cfg_error)
                $fatal(1, "component configure failed %h",
                       component_cfg_error_code);
        end
    endtask

    task automatic scratch_write(input [15:0] address,
                                 input [63:0] value);
        begin
            while (!scratch_init_ready) @(negedge clk);
            @(negedge clk);
            scratch_init_address = address;
            scratch_init_write_data = value;
            scratch_init_write = 1'b1;
            scratch_init_valid = 1'b1;
            @(posedge clk);
            #1 scratch_init_valid = 1'b0;
            scratch_init_write = 1'b0;
            if (scratch_init_error)
                $fatal(1, "scratch write failed at %0d", address);
        end
    endtask

    task automatic scratch_read(input [15:0] address,
                                output [63:0] value);
        begin
            while (!scratch_init_ready) @(negedge clk);
            @(negedge clk);
            scratch_init_address = address;
            scratch_init_write = 1'b0;
            scratch_init_valid = 1'b1;
            @(posedge clk);
            #1 scratch_init_valid = 1'b0;
            while (!scratch_init_rsp_valid && !scratch_init_error) begin
                @(posedge clk);
                #1;
            end
            if (scratch_init_error)
                $fatal(1, "scratch read failed at %0d", address);
            value = scratch_init_rsp_data;
        end
    endtask

    initial begin
        $readmemh(
            "manifests/programs/rtl_images/xmss_xmss_shake256_h10_w4_sign_layouts.hex",
            layout_image);
        $readmemh(
            "manifests/programs/rtl_images/xmss_xmss_shake256_h10_w4_sign_components.hex",
            component_image);
        repeat (3) @(negedge clk);
        rst_n = 1'b1;

        configure_layout(9, layout_image[8]);
        configure_layout(10, layout_image[9]);
        for (index = 81; index <= 90; index = index + 1)
            configure_component(index[15:0], component_image[index]);

        // sk_prf, logical slot 250.
        scratch_write(1000, 64'h2726252423222120);
        scratch_write(1001, 64'h2f2e2d2c2b2a2928);
        scratch_write(1002, 64'h3736353433323130);
        scratch_write(1003, 64'h3f3e3d3c3b3a3938);
        // root, logical slot 251.
        scratch_write(1004, 64'ha636f19ac3bd62ba);
        scratch_write(1005, 64'h23dafc3c9df1663e);
        scratch_write(1006, 64'h221eec5a48cff52c);
        scratch_write(1007, 64'h251451dc9b735dc3);
        // 256-bit big-endian index=5, logical slot 252.
        scratch_write(1008, 64'b0);
        scratch_write(1009, 64'b0);
        scratch_write(1010, 64'b0);
        scratch_write(1011, 64'h0500000000000000);
        // 21-byte message "micro-hbs-xmss-kat-v1", logical slot 253.
        scratch_write(1012, 64'h62682d6f7263696d);
        scratch_write(1013, 64'h6b2d73736d782d73);
        scratch_write(1014, 64'h00000031762d7461);

        write_program(0, enc(OP_HASH_LAYOUT, 8'h01, 0, 0, 9));
        write_program(1, enc(OP_HASH_LAYOUT, 8'h01, 0, 0, 10));
        write_program(2, enc(OP_HALT, 0, 0, 0, 0));

        while (!job_ready) @(negedge clk);
        @(negedge clk);
        job_valid = 1'b1;
        @(negedge clk);
        job_valid = 1'b0;
        measured_cycles = 0;
        while (!done && !error && measured_cycles < 5000) begin
            @(negedge clk);
            measured_cycles = measured_cycles + 1;
        end
        if (!done || error)
            $fatal(1, "XMSS prehash job failed code=%h", error_code);

        if (last_digest !==
            256'h854334908536d49aaeed2e80f54335d3b65f66f0ca1793ba1928bd969a251fc7)
            $fatal(1, "H_msg mismatch %064x", last_digest);
        scratch_read(872, read_word);
        if (read_word !== 64'hf1a9cd73bba4a82d)
            $fatal(1, "randomizer word 0 mismatch %016x", read_word);
        scratch_read(875, read_word);
        if (read_word !== 64'h2db5276272d7e881)
            $fatal(1, "randomizer word 3 mismatch %016x", read_word);
        scratch_read(876, read_word);
        if (read_word !== 64'h1928bd969a251fc7)
            $fatal(1, "message digest word 0 mismatch %016x", read_word);
        scratch_read(879, read_word);
        if (read_word !== 64'h854334908536d49a)
            $fatal(1, "message digest word 3 mismatch %016x", read_word);

        if (accepted_job_commands != 1
            || host_control_writes_during_busy != 0
            || issued_hash_requests != 2 || retired_instructions != 3
            || scratch_reads != 23 || scratch_writes != 8
            || absorbed_blocks != 3 || retired_components != 10)
            $fatal(1, "accounting mismatch jobs=%0d hash=%0d retired=%0d reads=%0d writes=%0d blocks=%0d components=%0d",
                   accepted_job_commands, issued_hash_requests,
                   retired_instructions, scratch_reads, scratch_writes,
                   absorbed_blocks, retired_components);

        $display("PASS JSON-lowered XMSS Sign PRF/H_msg RTL cycles=%0d one Job, no runtime task/hash ingress",
                 measured_cycles);
        $finish;
    end
endmodule

`default_nettype wire
