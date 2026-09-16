`timescale 1ns/1ps
`default_nettype none

module tb_micro_hbs_descriptor_shake_slice;
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

    localparam logic [7:0] OP_HASH_LAYOUT = 8'h03;
    localparam logic [7:0] OP_HALT = 8'h0d;
    integer word_index;
    integer byte_index;
    logic [63:0] data_word;
    logic [63:0] read_word;

    always #5 clk = ~clk;

    micro_hbs_descriptor_shake_slice #(
        .PROGRAM_WORDS(16), .LAYOUT_COUNT(4), .COMPONENT_WORDS(16),
        .SCRATCH_WORDS(256),
        .MAX_MESSAGE_BYTES(272), .UNROLL(2)
    ) dut (.*);

    function automatic [63:0] enc(input [7:0] opcode,
        input [7:0] flags, input [7:0] rd, input [7:0] rs,
        input [31:0] imm);
        enc = {opcode, flags, rd, rs, imm};
    endfunction

    function automatic [127:0] descriptor(
        input [7:0] output_bytes_value,
        input [15:0] message_bytes_value,
        input [15:0] source_base_word,
        input [15:0] source_span_words);
        descriptor = {
            8'h01, 8'h01, 8'h01, 8'h01,
            {8'b0, output_bytes_value}, message_bytes_value,
            16'b0, 8'b0, 8'd1, source_base_word, source_span_words
        };
    endfunction

    function automatic [127:0] component_layout(
        input [7:0] output_bytes_value,
        input [15:0] message_bytes_value,
        input [15:0] component_pc_value,
        input [7:0] component_count_value,
        input [7:0] destination_base,
        input [2:0] destination_base_reg,
        input destination_use_base_reg,
        input [2:0] destination_index_reg,
        input destination_use_index_reg,
        input [7:0] destination_stride);
        component_layout = {
            8'h01, 8'h01, 8'h02, 8'h01,
            {8'b0, output_bytes_value}, message_bytes_value,
            component_pc_value, component_count_value,
            component_count_value,
            destination_base, destination_base_reg,
            destination_use_base_reg, destination_index_reg,
            destination_use_index_reg, destination_stride, 8'b0
        };
    endfunction

    function automatic [191:0] component(
        input [7:0] kind,
        input [7:0] byte_count,
        input [7:0] address_flags,
        input [15:0] a_base,
        input [2:0] a_reg0,
        input [15:0] a_scale0,
        input [2:0] a_reg1,
        input [15:0] a_scale1,
        input [15:0] b_base,
        input [2:0] b_reg0,
        input [15:0] b_scale0,
        input [2:0] b_reg1,
        input [15:0] b_scale1,
        input [31:0] immediate);
        component = {
            8'h01, kind, byte_count, address_flags,
            a_base, 1'b0, a_reg0, a_scale0, 1'b0, a_reg1, a_scale1,
            b_base, 1'b0, b_reg0, b_scale0, 1'b0, b_reg1, b_scale1,
            immediate, 16'b0
        };
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

    task automatic configure_component(input [15:0] index,
                                       input [191:0] value);
        begin
            while (!component_cfg_ready) @(negedge clk);
            @(negedge clk);
            component_cfg_index = index;
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

    task automatic start_and_wait;
        integer timeout;
        begin
            while (!job_ready) @(negedge clk);
            @(negedge clk);
            job_valid = 1'b1;
            @(negedge clk);
            job_valid = 1'b0;
            timeout = 0;
            while (!done && !error && timeout < 10000) begin
                @(negedge clk);
                timeout = timeout + 1;
            end
            if (!done || error)
                $fatal(1, "descriptor SHAKE job failed code=%h", error_code);
        end
    endtask

    initial begin
        repeat (3) @(negedge clk);
        rst_n = 1'b1;

        // Layout 0 hashes 200 contiguous bytes and writes all 32 digest bytes
        // to logical slot 32 (physical words 128..131).
        configure_layout(0, descriptor(8'd32, 16'd200, 16'd0, 16'd25));
        // Layout 1 hashes 80 bytes and writes only 16 digest bytes to slot 40.
        configure_layout(1, descriptor(8'd16, 16'd80, 16'd32, 16'd10));

        // Layout 2 is a true component program.  It concatenates literal,
        // zero, register, affine Scratchpad, and affine Scratchpad-XOR data.
        // Its output slot is also selected by an affine register binding.
        configure_layout(2, component_layout(
            8'd32, 16'd35, 16'd0, 8'd5,
            8'd48, 3'd1, 1'b1, 3'd0, 1'b0, 8'd0));
        configure_component(0, component(
            8'h01, 8'd4, 8'h00, 0, 0, 0, 0, 0,
            0, 0, 0, 0, 0, 32'hdeadbeef));
        configure_component(1, component(
            8'h02, 8'd3, 8'h00, 0, 0, 0, 0, 0,
            0, 0, 0, 0, 0, 0));
        configure_component(2, component(
            8'h03, 8'd4, 8'h00, 0, 0, 0, 0, 0,
            0, 0, 0, 0, 0, 0));
        // A = slot 17 + R2*2 + R3 = slot 20.
        configure_component(3, component(
            8'h04, 8'd13, 8'h03, 16'd17, 3'd2, 16'd2,
            3'd3, 16'd1, 0, 0, 0, 0, 0, 0));
        // A = slot 21 + R2*2 + R3 = 24; B = slot 27 + R2 = 28.
        configure_component(4, component(
            8'h05, 8'd11, 8'h07, 16'd21, 3'd2, 16'd2,
            3'd3, 16'd1, 16'd27, 3'd2, 16'd1,
            3'd0, 16'd0, 0));
        // Layout 3 crosses the 136-byte SHAKE rate boundary two bytes into
        // its Scratchpad component and must resume that component internally.
        configure_layout(3, component_layout(
            8'd32, 16'd151, 16'd5, 8'd4,
            8'd60, 3'd0, 1'b0, 3'd0, 1'b0, 8'd0));
        configure_component(5, component(
            8'h01, 8'd4, 8'h00, 0, 0, 0, 0, 0,
            0, 0, 0, 0, 0, 32'ha1b2c3d4));
        configure_component(6, component(
            8'h02, 8'd130, 8'h00, 0, 0, 0, 0, 0,
            0, 0, 0, 0, 0, 0));
        configure_component(7, component(
            8'h04, 8'd13, 8'h00, 16'd30, 0, 0, 0, 0,
            0, 0, 0, 0, 0, 0));
        configure_component(8, component(
            8'h03, 8'd4, 8'h00, 0, 0, 0, 0, 0,
            0, 0, 0, 0, 0, 4));

        for (word_index = 0; word_index < 25; word_index = word_index + 1) begin
            data_word = '0;
            for (byte_index = 0; byte_index < 8; byte_index = byte_index + 1)
                data_word[8*byte_index +: 8] = 8'(8*word_index + byte_index);
            scratch_write(word_index[15:0], data_word);
        end
        for (word_index = 0; word_index < 10; word_index = word_index + 1) begin
            data_word = '0;
            for (byte_index = 0; byte_index < 8; byte_index = byte_index + 1)
                data_word[8*byte_index +: 8] = 8'(8*word_index + byte_index);
            scratch_write(16'd32 + word_index[15:0], data_word);
        end
        scratch_write(16'd162, 64'hfeedfacecafebeef);
        for (word_index = 0; word_index < 2; word_index = word_index + 1) begin
            data_word = '0;
            for (byte_index = 0; byte_index < 8; byte_index = byte_index + 1)
                if (8*word_index + byte_index < 13)
                    data_word[8*byte_index +: 8]
                        = 8'h20 + 8'(8*word_index + byte_index);
            scratch_write(16'd80 + word_index[15:0], data_word);
        end
        for (word_index = 0; word_index < 2; word_index = word_index + 1) begin
            data_word = '0;
            for (byte_index = 0; byte_index < 8; byte_index = byte_index + 1)
                if (8*word_index + byte_index < 11)
                    data_word[8*byte_index +: 8]
                        = 8'h40 + 8'(8*word_index + byte_index);
            scratch_write(16'd96 + word_index[15:0], data_word);
            data_word = '0;
            for (byte_index = 0; byte_index < 8; byte_index = byte_index + 1)
                if (8*word_index + byte_index < 11)
                    data_word[8*byte_index +: 8]
                        = 8'h80 + 8'(8*word_index + byte_index);
            scratch_write(16'd112 + word_index[15:0], data_word);
        end
        scratch_write(16'd192, 64'h0123456789abcdef);
        for (word_index = 0; word_index < 2; word_index = word_index + 1) begin
            data_word = '0;
            for (byte_index = 0; byte_index < 8; byte_index = byte_index + 1)
                if (8*word_index + byte_index < 13)
                    data_word[8*byte_index +: 8]
                        = 8'h55 + 8'(8*word_index + byte_index);
            scratch_write(16'd120 + word_index[15:0], data_word);
        end

        write_program(0, enc(OP_HASH_LAYOUT, 8'h01, 8'd32, 0, 0));
        write_program(1, enc(OP_HALT, 0, 0, 0, 0));
        start_and_wait();
        if (last_digest !==
            256'h5e7ab0afb59c9ebab18739bbe4c59f3b827f969ac7e1b1bfd3052b2703cae14e)
            $fatal(1, "200-byte digest mismatch %064x", last_digest);

        write_program(0, enc(OP_HASH_LAYOUT, 8'h01, 8'd40, 0, 1));
        start_and_wait();
        if (last_digest !==
            256'h505a0dbfe6c4ad6ef0c80baa2d07e154d67d1eda14bb51626dc83b51261aa1c2)
            $fatal(1, "80-byte digest mismatch %064x", last_digest);
        scratch_read(16'd162, read_word);
        if (read_word !== 64'hfeedfacecafebeef)
            $fatal(1, "16-byte output overwrote third word %016x", read_word);

        write_program(0, enc(8'h01, 0, 8'd0, 0, 32'h01020304));
        write_program(1, enc(8'h01, 0, 8'd1, 0, 1));
        write_program(2, enc(8'h01, 0, 8'd2, 0, 1));
        write_program(3, enc(8'h01, 0, 8'd3, 0, 1));
        write_program(4, enc(OP_HASH_LAYOUT, 8'h01, 0, 0, 2));
        write_program(5, enc(OP_HALT, 0, 0, 0, 0));
        start_and_wait();
        if (last_digest !==
            256'h17f0641acdefdc80493c36b9281bd7c205147618c4d169a8164be4b435612aff)
            $fatal(1, "component-program digest mismatch %064x",
                   last_digest);
        scratch_read(16'd192, read_word);
        if (read_word !== 64'h0123456789abcdef)
            $fatal(1, "affine destination ignored R1 binding");

        write_program(0, enc(8'h01, 0, 8'd4, 0, 32'h11223344));
        write_program(1, enc(OP_HASH_LAYOUT, 8'h01, 0, 0, 3));
        write_program(2, enc(OP_HALT, 0, 0, 0, 0));
        start_and_wait();
        if (last_digest !==
            256'hb260021af9b17ad4afd8cc3effae30a43f2e9653e49ce135c1138ee6dbcafbfd)
            $fatal(1, "cross-rate component digest mismatch %064x",
                   last_digest);

        if (accepted_job_commands != 4
            || host_control_writes_during_busy != 0
            || issued_hash_requests != 4 || retired_instructions != 13
            || scratch_reads != 43 || scratch_writes != 14
            || absorbed_blocks != 6 || retired_components != 9)
            $fatal(1, "accounting mismatch jobs=%0d hash=%0d retired=%0d reads=%0d writes=%0d blocks=%0d components=%0d",
                   accepted_job_commands, issued_hash_requests,
                   retired_instructions, scratch_reads, scratch_writes,
                   absorbed_blocks, retired_components);

        $display("PASS descriptor-driven HASH_LAYOUT SHAKE: five component kinds, affine binding, XOR and cross-rate autonomous resume");
        $finish;
    end
endmodule

`default_nettype wire
