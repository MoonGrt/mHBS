`timescale 1ns/1ps
`default_nettype none

module tb_micro_hbs_scratch_bitfield_load;
    logic clk = 0;
    logic rst_n = 0;
    always #5 clk = ~clk;

    logic cmd_valid = 0;
    wire cmd_ready;
    wire busy;
    logic [15:0] cmd_source_address = 16'd480;
    logic [15:0] cmd_input_bytes = 16'd34;
    logic [15:0] cmd_bit_offset = 0;
    logic [6:0] cmd_bit_width = 0;
    logic cmd_destination_is_reg = 0;
    logic [7:0] cmd_destination_reg = 0;
    logic [15:0] cmd_destination_address = 16'd500;
    logic [4:0] cmd_output_bytes = 0;
    wire rsp_valid;
    logic rsp_ready = 1;
    wire rsp_error;
    wire [15:0] rsp_error_code;
    wire rsp_reg_write;
    wire [7:0] rsp_reg_index;
    wire [31:0] rsp_reg_value;
    wire scratch_request_valid, scratch_request_ready;
    wire scratch_request_write;
    wire [15:0] scratch_request_address;
    wire [63:0] scratch_request_write_data;
    wire scratch_response_valid;
    wire [63:0] scratch_response_data;
    wire scratch_response_error;
    wire [31:0] accepted_commands, scratch_reads, scratch_writes;

    micro_hbs_scratch_bitfield_load dut (.*);
    micro_hbs_scratchpad64 #(.WORDS(1024), .ADDRESS_WIDTH(16)) scratch (
        .clk, .rst_n, .request_valid(scratch_request_valid),
        .request_ready(scratch_request_ready),
        .request_write(scratch_request_write),
        .request_address(scratch_request_address),
        .request_write_data(scratch_request_write_data),
        .response_valid(scratch_response_valid),
        .response_read_data(scratch_response_data),
        .bounds_error(scratch_response_error), .scrub_start(1'b0),
        .scrub_busy(), .scrub_done()
    );

    task automatic issue;
        begin
            while (!cmd_ready) @(negedge clk);
            cmd_valid = 1'b1;
            @(negedge clk);
            cmd_valid = 1'b0;
            while (!rsp_valid) @(negedge clk);
            if (rsp_error)
                $fatal(1, "bitfield command failed %h", rsp_error_code);
        end
    endtask

    initial begin
        repeat (3) @(negedge clk);
        rst_n = 1;
        // 9ab84d06f64b5fa06a82b143aef669e56140c5ad7f9e22aa1609d614680b3d52e9fa
        scratch.memory[480] = 64'ha05f4bf6064db89a;
        scratch.memory[481] = 64'he569f6ae43b1826a;
        scratch.memory[482] = 64'haa229e7fadc54061;
        scratch.memory[483] = 64'h523d0b6814d60916;
        scratch.memory[484] = 64'h000000000000fae9;

        // Tree address: skip the 25-byte digest and its masked high bit.
        cmd_bit_offset = 16'd201;
        cmd_bit_width = 7'd63;
        cmd_destination_is_reg = 0;
        cmd_destination_address = 16'd500;
        cmd_output_bytes = 5'd12;
        issue();
        if (scratch.memory[500] !== 64'h6814d60900000000
            || scratch.memory[501] !== 64'h00000000e9523d0b)
            $fatal(1, "tree-address extraction mismatch %h %h",
                   scratch.memory[500], scratch.memory[501]);

        // Leaf index is the low three bits of the final digest byte.
        cmd_bit_offset = 16'd269;
        cmd_bit_width = 7'd3;
        cmd_destination_is_reg = 1;
        cmd_destination_reg = 5;
        cmd_output_bytes = 0;
        issue();
        if (!rsp_reg_write || rsp_reg_index != 5 || rsp_reg_value != 2)
            $fatal(1, "leaf extraction mismatch we=%0d r=%0d v=%0d off=%0d in=%0d w0=%h",
                   rsp_reg_write, rsp_reg_index, rsp_reg_value,
                   dut.bit_in_word, dut.bit_width, dut.word0);

        // FORS index 1: dynamic descriptor adapters use offset = 6*R0.
        cmd_bit_offset = 16'd6;
        cmd_bit_width = 7'd6;
        cmd_destination_reg = 1;
        issue();
        if (!rsp_reg_write || rsp_reg_value != 43)
            $fatal(1, "FORS digit extraction mismatch %0d", rsp_reg_value);

        if (accepted_commands != 3 || scratch_reads != 4
            || scratch_writes != 2)
            $fatal(1, "counter mismatch %0d %0d %0d", accepted_commands,
                   scratch_reads, scratch_writes);
        $display("PASS generic Scratchpad bitfield LOAD tree/leaf/FORS reads=%0d writes=%0d",
                 scratch_reads, scratch_writes);
        $finish;
    end
endmodule

`default_nettype wire
