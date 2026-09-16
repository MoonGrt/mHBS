`timescale 1ns/1ps
`default_nettype none

module tb_micro_hbs_tree_push;
    logic clk = 1'b0;
    logic rst_n = 1'b0;
    logic program_we = 1'b0;
    logic [8:0] program_addr = '0;
    logic [63:0] program_wdata = '0;
    logic job_valid = 1'b0;
    wire job_ready;
    logic [8:0] job_entry = '0;
    wire busy, done, error;
    wire [15:0] error_code;

    wire tree_req_valid;
    logic tree_req_ready = 1'b0;
    wire [7:0] tree_req_flags, tree_req_rd, tree_req_rs;
    wire [31:0] tree_req_imm, tree_req_rs_value;
    logic tree_rsp_valid = 1'b0;
    logic tree_rsp_error = 1'b0;
    logic [15:0] tree_rsp_error_code = '0;

    wire [31:0] accepted_job_commands;
    wire [31:0] host_control_writes_during_busy;
    wire [31:0] issued_hash_requests;
    wire [31:0] issued_data_requests;
    wire [31:0] issued_tree_requests;
    wire [31:0] retired_instructions;
    integer timeout;

    localparam logic [7:0] OP_MOVI      = 8'h01;
    localparam logic [7:0] OP_TREE_PUSH = 8'h0b;
    localparam logic [7:0] OP_HALT      = 8'h0d;

    always #5 clk = ~clk;

    micro_hbs_sequencer #(.PROGRAM_WORDS(16)) dut (
        .clk, .rst_n, .program_we, .program_addr, .program_wdata,
        .job_valid, .job_ready, .job_entry, .busy, .done, .error, .error_code,
        .hash_req_valid(), .hash_req_ready(1'b0), .hash_layout_id(),
        .hash_lane_mask(), .hash_dest(), .hash_index_reg(), .hash_index_value(),
        .hash_rsp_valid(1'b0), .hash_rsp_error(1'b0), .hash_rsp_error_code(16'h0000),
        .dynamic_bound_req(), .dynamic_bound_addr(), .dynamic_bound_valid(1'b0),
        .dynamic_bound_value(8'h00), .dynamic_bound_error(1'b0),
        .dynamic_bound_error_code(16'h0000),
        .data_req_valid(), .data_req_ready(1'b0), .data_req_opcode(),
        .data_req_flags(), .data_req_rd(), .data_req_rs(), .data_req_imm(),
        .data_req_rs_value(), .data_rsp_valid(1'b0), .data_rsp_error(1'b0),
        .data_rsp_error_code(16'h0000), .data_rsp_reg_write(1'b0),
        .data_rsp_reg_index(8'h00), .data_rsp_reg_value(32'h00000000),
        .tree_req_valid, .tree_req_ready, .tree_req_flags, .tree_req_rd,
        .tree_req_rs, .tree_req_imm, .tree_req_rs_value, .tree_rsp_valid,
        .tree_rsp_error, .tree_rsp_error_code,
        .accepted_job_commands, .host_control_writes_during_busy,
        .issued_hash_requests, .issued_data_requests, .issued_tree_requests,
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

    task automatic submit_job(input [8:0] entry);
        begin
            @(negedge clk);
            if (!job_ready) $fatal(1, "sequencer not ready for Job");
            job_entry = entry;
            job_valid = 1'b1;
            @(negedge clk);
            job_valid = 1'b0;
        end
    endtask

    task automatic reset_sequencer;
        begin
            @(negedge clk);
            rst_n = 1'b0;
            tree_req_ready = 1'b0;
            tree_rsp_valid = 1'b0;
            tree_rsp_error = 1'b0;
            program_we = 1'b0;
            repeat (2) @(posedge clk);
            @(negedge clk);
            rst_n = 1'b1;
        end
    endtask

    task automatic await_tree_request;
        begin
            timeout = 0;
            while (!tree_req_valid && timeout < 40) begin
                @(negedge clk);
                timeout = timeout + 1;
            end
            if (!tree_req_valid) $fatal(1, "TREE_PUSH request timeout");
            if (tree_req_flags !== 0 || tree_req_rd !== 8'he1 ||
                tree_req_rs !== 8'd3 || tree_req_imm !== 32'h10203040 ||
                tree_req_rs_value !== 32'h55667788)
                $fatal(1, "TREE_PUSH payload mismatch flags=%h rd=%h rs=%h imm=%h value=%h",
                       tree_req_flags, tree_req_rd, tree_req_rs,
                       tree_req_imm, tree_req_rs_value);
            repeat (3) begin
                @(posedge clk);
                #1;
                if (!tree_req_valid || tree_req_rd !== 8'he1 ||
                    tree_req_rs_value !== 32'h55667788)
                    $fatal(1, "TREE_PUSH request changed under backpressure");
            end
        end
    endtask

    initial begin
        repeat (3) @(posedge clk);
        rst_n = 1'b1;

        // rd is an unrestricted 8-bit tree object/destination identifier.
        write_program(0, enc(OP_MOVI, 0, 3, 0, 32'h55667788));
        write_program(1, enc(OP_TREE_PUSH, 0, 8'he1, 3, 32'h10203040));
        write_program(2, enc(OP_HALT, 0, 0, 0, 0));
        write_program(3, enc(OP_MOVI, 0, 3, 0, 32'h55667788));
        write_program(4, enc(OP_TREE_PUSH, 0, 8'he1, 3, 32'h10203040));
        write_program(6, enc(OP_TREE_PUSH, 1, 8'he1, 3, 32'h10203040));
        write_program(8, enc(OP_TREE_PUSH, 0, 8'he1, 8, 32'h10203040));

        submit_job(0);
        await_tree_request();
        if (issued_tree_requests != 0)
            $fatal(1, "backpressured request incremented tree counter");
        @(negedge clk);
        tree_req_ready = 1'b1;
        @(posedge clk);
        #1;
        if (tree_req_valid || issued_tree_requests != 1)
            $fatal(1, "TREE_PUSH acceptance/counter mismatch issued=%0d",
                   issued_tree_requests);
        @(negedge clk);
        tree_req_ready = 1'b0;
        repeat (2) begin
            @(posedge clk);
            #1;
            if (done || error || tree_req_valid)
                $fatal(1, "TREE_PUSH did not wait for response");
        end
        @(negedge clk);
        tree_rsp_valid = 1'b1;
        @(negedge clk);
        tree_rsp_valid = 1'b0;
        timeout = 0;
        while (!done && timeout < 30) begin
            @(negedge clk);
            timeout = timeout + 1;
        end
        if (!done || error || accepted_job_commands != 1 ||
            issued_tree_requests != 1 || issued_data_requests != 0 ||
            issued_hash_requests != 0 || retired_instructions != 3)
            $fatal(1, "normal TREE_PUSH path/counters failed error=%h tree=%0d retired=%0d",
                   error_code, issued_tree_requests, retired_instructions);

        // A tree response error fails closed and is not retired.
        reset_sequencer();
        submit_job(3);
        await_tree_request();
        @(negedge clk);
        tree_req_ready = 1'b1;
        @(negedge clk);
        tree_req_ready = 1'b0;
        tree_rsp_error_code = 16'h6789;
        tree_rsp_error = 1'b1;
        @(negedge clk);
        tree_rsp_error = 1'b0;
        if (!error || busy || done || error_code != 16'h6789 ||
            issued_tree_requests != 1 || retired_instructions != 1)
            $fatal(1, "TREE_PUSH response error did not fail closed code=%h", error_code);

        // The existing BUSY image lock also dominates a simultaneous tree
        // request acceptance, so no in-flight Job can alter its own program.
        reset_sequencer();
        submit_job(3);
        await_tree_request();
        @(negedge clk);
        program_addr = 4;
        program_wdata = enc(OP_HALT, 0, 0, 0, 0);
        program_we = 1'b1;
        tree_req_ready = 1'b1;
        @(negedge clk);
        program_we = 1'b0;
        tree_req_ready = 1'b0;
        if (!error || busy || done || error_code != 16'h0001 ||
            host_control_writes_during_busy != 1 || issued_tree_requests != 0)
            $fatal(1, "TREE_PUSH BUSY image lock failed code=%h host=%0d tree=%0d",
                   error_code, host_control_writes_during_busy,
                   issued_tree_requests);

        // Verifier semantics: flags must be zero, rs must be a register, while
        // rd above proved that an arbitrary 8-bit object identifier is legal.
        reset_sequencer();
        submit_job(6);
        repeat (5) @(negedge clk);
        if (!error || error_code != 16'h0004 || issued_tree_requests != 0)
            $fatal(1, "TREE_PUSH nonzero flags accepted code=%h", error_code);

        reset_sequencer();
        submit_job(8);
        repeat (5) @(negedge clk);
        if (!error || error_code != 16'h0004 || issued_tree_requests != 0)
            $fatal(1, "TREE_PUSH invalid rs accepted code=%h", error_code);

        $display("PASS TREE_PUSH request/response, backpressure, counter, error, and operands");
        $finish;
    end
endmodule

`default_nettype wire
