`timescale 1ns/1ps
`default_nettype none

module tb_micro_hbs_data_ops;
    logic clk = 1'b0;
    logic rst_n = 1'b0;
    logic program_we = 1'b0;
    logic [8:0] program_addr = '0;
    logic [63:0] program_wdata = '0;
    logic job_valid = 1'b0;
    wire job_ready;
    logic [8:0] job_entry = '0;
    wire busy;
    wire done;
    wire error;
    wire [15:0] error_code;

    wire data_req_valid;
    logic data_req_ready = 1'b0;
    wire [7:0] data_req_opcode;
    wire [7:0] data_req_flags;
    wire [7:0] data_req_rd;
    wire [7:0] data_req_rs;
    wire [31:0] data_req_imm;
    wire [31:0] data_req_rs_value;
    logic data_rsp_valid = 1'b0;
    logic data_rsp_error = 1'b0;
    logic [15:0] data_rsp_error_code = '0;
    logic data_rsp_reg_write = 1'b0;
    logic [7:0] data_rsp_reg_index = '0;
    logic [31:0] data_rsp_reg_value = '0;

    wire [31:0] accepted_job_commands;
    wire [31:0] host_control_writes_during_busy;
    wire [31:0] issued_hash_requests;
    wire [31:0] issued_data_requests;
    wire [31:0] retired_instructions;
    integer timeout;

    localparam logic [7:0] OP_SET_REG  = 8'h01;
    localparam logic [7:0] OP_DATA_LOAD  = 8'h08;
    localparam logic [7:0] OP_DATA_MOVE = 8'h09;
    localparam logic [7:0] OP_OUTPUT  = 8'h0c;
    localparam logic [7:0] OP_HALT  = 8'h0d;

    always #5 clk = ~clk;

    micro_hbs_sequencer #(.PROGRAM_WORDS(16)) dut (
        .clk,
        .rst_n,
        .program_we,
        .program_addr,
        .program_wdata,
        .job_valid,
        .job_ready,
        .job_entry,
        .busy,
        .done,
        .error,
        .error_code,
        .hash_req_valid(),
        .hash_req_ready(1'b0),
        .hash_layout_id(),
        .hash_lane_mask(),
        .hash_dest(),
        .hash_index_reg(),
        .hash_index_value(),
        .hash_rsp_valid(1'b0),
        .hash_rsp_error(1'b0),
        .hash_rsp_error_code(16'h0000),
        .dynamic_bound_req(),
        .dynamic_bound_addr(),
        .dynamic_bound_valid(1'b0),
        .dynamic_bound_value(8'h00),
        .dynamic_bound_error(1'b0),
        .dynamic_bound_error_code(16'h0000),
        .data_req_valid,
        .data_req_ready,
        .data_req_opcode,
        .data_req_flags,
        .data_req_rd,
        .data_req_rs,
        .data_req_imm,
        .data_req_rs_value,
        .data_rsp_valid,
        .data_rsp_error,
        .data_rsp_error_code,
        .data_rsp_reg_write,
        .data_rsp_reg_index,
        .data_rsp_reg_value,
        .tree_req_valid(),
        .tree_req_ready(1'b0),
        .tree_req_flags(),
        .tree_req_rd(),
        .tree_req_rs(),
        .tree_req_imm(),
        .tree_req_rs_value(),
        .tree_rsp_valid(1'b0),
        .tree_rsp_error(1'b0),
        .tree_rsp_error_code(16'h0000),
        .accepted_job_commands,
        .host_control_writes_during_busy,
        .issued_hash_requests,
        .issued_data_requests,
        .issued_tree_requests(),
        .retired_instructions
    );

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

    task automatic submit_job;
        begin
            @(negedge clk);
            if (!job_ready) $fatal(1, "sequencer not ready for Job");
            job_valid = 1'b1;
            @(negedge clk);
            job_valid = 1'b0;
        end
    endtask

    task automatic await_request(
        input [7:0] expected_opcode,
        input [7:0] expected_flags,
        input [7:0] expected_rd,
        input [7:0] expected_rs,
        input [31:0] expected_imm,
        input [31:0] expected_rs_value
    );
        begin
            timeout = 0;
            while (!data_req_valid && timeout < 40) begin
                @(negedge clk);
                timeout = timeout + 1;
            end
            if (!data_req_valid) $fatal(1, "data request timeout");
            if (data_req_opcode !== expected_opcode ||
                data_req_flags !== expected_flags ||
                data_req_rd !== expected_rd ||
                data_req_rs !== expected_rs ||
                data_req_imm !== expected_imm ||
                data_req_rs_value !== expected_rs_value)
                $fatal(1, "request payload mismatch op=%h flags=%h rd=%0d rs=%0d imm=%h value=%h",
                       data_req_opcode, data_req_flags, data_req_rd, data_req_rs,
                       data_req_imm, data_req_rs_value);

            // Backpressure must not duplicate the request or change payload.
            repeat (2) begin
                @(posedge clk);
                #1;
                if (!data_req_valid ||
                    data_req_opcode !== expected_opcode ||
                    data_req_flags !== expected_flags ||
                    data_req_rd !== expected_rd ||
                    data_req_rs !== expected_rs ||
                    data_req_imm !== expected_imm ||
                    data_req_rs_value !== expected_rs_value)
                    $fatal(1, "request changed while backpressured");
            end
        end
    endtask

    task automatic accept_and_respond(
        input logic response_reg_write,
        input logic [7:0] response_reg_index,
        input logic [31:0] response_reg_value
    );
        begin
            @(negedge clk);
            data_req_ready = 1'b1;
            @(posedge clk);
            #1;
            if (data_req_valid) $fatal(1, "request valid did not clear after acceptance");
            @(negedge clk);
            data_req_ready = 1'b0;

            // The instruction must remain pending until the response arrives.
            repeat (2) begin
                @(posedge clk);
                #1;
                if (done || error || data_req_valid)
                    $fatal(1, "data instruction did not wait for its response");
            end
            @(negedge clk);
            data_rsp_reg_write = response_reg_write;
            data_rsp_reg_index = response_reg_index;
            data_rsp_reg_value = response_reg_value;
            data_rsp_valid = 1'b1;
            @(negedge clk);
            data_rsp_valid = 1'b0;
            data_rsp_reg_write = 1'b0;
        end
    endtask

    task automatic reset_sequencer;
        begin
            @(negedge clk);
            rst_n = 1'b0;
            data_req_ready = 1'b0;
            data_rsp_valid = 1'b0;
            data_rsp_error = 1'b0;
            data_rsp_reg_write = 1'b0;
            data_rsp_reg_index = '0;
            data_rsp_reg_value = '0;
            program_we = 1'b0;
            repeat (2) @(posedge clk);
            @(negedge clk);
            rst_n = 1'b1;
        end
    endtask

    initial begin
        repeat (3) @(posedge clk);
        rst_n = 1'b1;

        // R2=9, followed by the three ISA-visible data-plane operations.
        write_program(0, enc(OP_SET_REG,  0, 2, 0, 32'd9));
        write_program(1, enc(OP_DATA_LOAD,  0, 1, 2, 32'h00000100));
        write_program(2, enc(OP_OUTPUT,  1, 5, 1, 32'd7));
        write_program(3, enc(OP_DATA_MOVE, 0, 3, 2, 32'h00000101));
        write_program(4, enc(OP_HALT,  0, 0, 0, 32'd0));

        submit_job();
        await_request(OP_DATA_LOAD, 0, 1, 2, 32'h00000100, 32'd9);
        accept_and_respond(1'b1, 8'd1, 32'hc001d00d);
        await_request(OP_OUTPUT, 1, 5, 1, 32'd7, 32'hc001d00d);
        accept_and_respond(1'b0, 8'd0, 32'd0);
        await_request(OP_DATA_MOVE, 0, 3, 2, 32'h00000101, 32'd9);
        accept_and_respond(1'b0, 8'd0, 32'd0);
        timeout = 0;
        while (!done && timeout < 30) begin
            @(negedge clk);
            timeout = timeout + 1;
        end
        if (!done || error) $fatal(1, "normal data-op program failed error=%h", error_code);
        if (accepted_job_commands != 1 || issued_data_requests != 3 ||
            issued_hash_requests != 0 || retired_instructions != 5)
            $fatal(1, "normal counters job=%0d data=%0d hash=%0d retired=%0d",
                   accepted_job_commands, issued_data_requests,
                   issued_hash_requests, retired_instructions);

        // A data-plane error is fail-closed and preserves the response code.
        reset_sequencer();
        submit_job();
        await_request(OP_DATA_LOAD, 0, 1, 2, 32'h00000100, 32'd9);
        @(negedge clk);
        data_req_ready = 1'b1;
        @(negedge clk);
        data_req_ready = 1'b0;
        data_rsp_error_code = 16'h3456;
        data_rsp_error = 1'b1;
        @(negedge clk);
        data_rsp_error = 1'b0;
        if (!error || busy || done || error_code != 16'h3456)
            $fatal(1, "data response error did not fail closed error=%h", error_code);
        if (issued_data_requests != 1 || retired_instructions != 1)
            $fatal(1, "error-path counters data=%0d retired=%0d",
                   issued_data_requests, retired_instructions);

        // A successful response requesting an out-of-range register write is
        // rejected before either the write or instruction retirement.
        reset_sequencer();
        submit_job();
        await_request(OP_DATA_LOAD, 0, 1, 2, 32'h00000100, 32'd9);
        @(negedge clk);
        data_req_ready = 1'b1;
        @(negedge clk);
        data_req_ready = 1'b0;
        data_rsp_reg_write = 1'b1;
        data_rsp_reg_index = 8;
        data_rsp_reg_value = 32'hdeadbeef;
        data_rsp_valid = 1'b1;
        @(negedge clk);
        data_rsp_valid = 1'b0;
        data_rsp_reg_write = 1'b0;
        if (!error || busy || done || error_code != 16'h0004)
            $fatal(1, "invalid response write index did not fail closed error=%h", error_code);
        if (issued_data_requests != 1 || retired_instructions != 1)
            $fatal(1, "invalid-index counters data=%0d retired=%0d",
                   issued_data_requests, retired_instructions);

        // An image write while a request is backpressured aborts the Job.  The
        // write must not reach program RAM, even if a response also arrives.
        reset_sequencer();
        submit_job();
        await_request(OP_DATA_LOAD, 0, 1, 2, 32'h00000100, 32'd9);
        @(negedge clk);
        program_addr = 1;
        program_wdata = enc(OP_HALT, 0, 0, 0, 0);
        program_we = 1'b1;
        data_req_ready = 1'b1;
        data_rsp_valid = 1'b1;
        @(negedge clk);
        program_we = 1'b0;
        data_req_ready = 1'b0;
        data_rsp_valid = 1'b0;
        if (!error || busy || done || error_code != 16'h0001)
            $fatal(1, "BUSY image write did not take priority error=%h", error_code);
        if (host_control_writes_during_busy != 1 || issued_data_requests != 0)
            $fatal(1, "image-lock counters host=%0d data=%0d",
                   host_control_writes_during_busy, issued_data_requests);

        // Reset and re-read pc=1 to prove the rejected write changed no image.
        reset_sequencer();
        submit_job();
        await_request(OP_DATA_LOAD, 0, 1, 2, 32'h00000100, 32'd9);

        $display("PASS DATA_LOAD/DATA_MOVE/OUTPUT request-response, backpressure, error, and image lock");
        $finish;
    end
endmodule

`default_nettype wire
