`timescale 1ns/1ps
`default_nettype none

module tb_micro_hbs_dynamic_loop;
    logic clk = 1'b0;
    logic rst_n = 1'b0;
    logic program_we = 1'b0;
    logic [8:0] program_addr = '0;
    logic [63:0] program_wdata = '0;
    logic job_valid = 1'b0;
    logic job_ready;
    logic [8:0] job_entry = '0;
    logic busy, done, error;
    logic [15:0] error_code;
    logic hash_req_valid;
    logic dynamic_bound_req;
    logic [15:0] dynamic_bound_addr;
    logic [7:0] supplied_bound = 0;
    logic [31:0] accepted_job_commands;
    logic [31:0] host_control_writes_during_busy;
    logic [31:0] issued_hash_requests;
    logic [31:0] retired_instructions;

    always #5 clk = ~clk;

    micro_hbs_sequencer dut (
        .clk, .rst_n, .program_we, .program_addr, .program_wdata,
        .job_valid, .job_ready, .job_entry, .busy, .done, .error, .error_code,
        .hash_req_valid, .hash_req_ready(1'b1), .hash_layout_id(),
        .hash_lane_mask(), .hash_dest(), .hash_index_reg(), .hash_index_value(),
        .hash_rsp_valid(1'b0), .hash_rsp_error(1'b0),
        .hash_rsp_error_code(16'h0000), .dynamic_bound_req,
        .dynamic_bound_addr, .dynamic_bound_valid(dynamic_bound_req),
        .dynamic_bound_value(supplied_bound), .dynamic_bound_error(1'b0),
        .dynamic_bound_error_code(16'h0000),
        .data_req_valid(), .data_req_ready(1'b1), .data_req_opcode(),
        .data_req_flags(), .data_req_rd(), .data_req_rs(), .data_req_imm(),
        .data_req_rs_value(), .data_rsp_valid(1'b0), .data_rsp_error(1'b1),
        .data_rsp_error_code(16'h0104), .data_rsp_reg_write(1'b0),
        .data_rsp_reg_index(8'h00), .data_rsp_reg_value(32'h00000000),
        .tree_req_valid(), .tree_req_ready(1'b1), .tree_req_flags(),
        .tree_req_rd(), .tree_req_rs(), .tree_req_imm(), .tree_req_rs_value(),
        .tree_rsp_valid(1'b0), .tree_rsp_error(1'b1),
        .tree_rsp_error_code(16'h0104), .accepted_job_commands,
        .host_control_writes_during_busy, .issued_hash_requests,
        .issued_data_requests(), .issued_tree_requests(),
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

    task automatic run_and_check(input [7:0] bound, input [31:0] expected_retired);
        integer timeout;
        begin
            supplied_bound = bound;
            @(negedge clk);
            job_valid = 1'b1;
            @(negedge clk);
            job_valid = 1'b0;
            timeout = 0;
            while (!done && timeout < 100) begin
                @(posedge clk);
                timeout = timeout + 1;
                if (dynamic_bound_req && dynamic_bound_addr != 16'd5)
                    $fatal(1, "dynamic bound address %0d", dynamic_bound_addr);
            end
            if (!done || error) $fatal(1, "dynamic loop failed error=%h", error_code);
            if (retired_instructions != expected_retired)
                $fatal(1, "bound=%0d retired=%0d expected=%0d",
                       bound, retired_instructions, expected_retired);
        end
    endtask

    task automatic reject_removed_opcode(input [7:0] removed_opcode);
        integer timeout;
        begin
            @(negedge clk);
            rst_n = 1'b0;
            repeat (2) @(posedge clk);
            @(negedge clk);
            rst_n = 1'b1;
            write_program(0, enc(removed_opcode, 0, 0, 0, 0));
            @(negedge clk);
            if (!job_ready) $fatal(1, "sequencer not ready for removed opcode");
            job_valid = 1'b1;
            @(negedge clk);
            job_valid = 1'b0;
            timeout = 0;
            while (!error && timeout < 10) begin
                @(posedge clk);
                timeout = timeout + 1;
            end
            if (!error || done || busy || error_code != 16'h0003)
                $fatal(1, "removed opcode %h was not rejected error=%h",
                       removed_opcode, error_code);
        end
    endtask

    initial begin
        repeat (3) @(posedge clk);
        rst_n = 1'b1;

        // R1=5; dynamic loop bound from Scratchpad[R1], zero exits to pc=4.
        write_program(0, enc(8'h01, 0, 1, 0, 32'd5));
        write_program(1, enc(8'h04, 1, 1, 2, 32'd4));
        // SET_REG R0,0 is an observable-safe loop body; NOP was removed in v0.2.
        write_program(2, enc(8'h01, 0, 0, 0, 0));
        write_program(3, enc(8'h05, 0, 0, 0, 0));
        write_program(4, enc(8'h0d, 0, 0, 0, 0));

        run_and_check(0, 3);

        @(negedge clk);
        rst_n = 1'b0;
        repeat (2) @(posedge clk);
        rst_n = 1'b1;
        run_and_check(3, 9);

        if (issued_hash_requests != 0) $fatal(1, "unexpected hash request");
        reject_removed_opcode(8'h00);
        reject_removed_opcode(8'h0a);
        reject_removed_opcode(8'h0e);
        reject_removed_opcode(8'h0f);
        reject_removed_opcode(8'h10);
        reject_removed_opcode(8'h11);

        $display("PASS dynamic bounded loop and removed-opcode rejection");
        $finish;
    end
endmodule

`default_nettype wire
