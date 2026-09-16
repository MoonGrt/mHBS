`timescale 1ns/1ps
`default_nettype none

// Control replay of the checked-in, verifier-produced LMOTS program image.
// Hash and data services acknowledge internal requests without computing the
// digest; cryptographic equality remains covered by the independent model/KAT.
module tb_micro_hbs_lmots_program_image;
    logic clk = 1'b0;
    logic rst_n = 1'b0;
    logic job_valid = 1'b0;
    wire job_ready;
    wire busy;
    wire done;
    wire error;
    wire [15:0] error_code;

    wire hash_req_valid;
    logic hash_rsp_valid = 1'b0;
    wire data_req_valid;
    logic data_rsp_valid = 1'b0;
    wire [7:0] data_req_opcode;
    wire [31:0] accepted_job_commands;
    wire [31:0] host_control_writes_during_busy;
    wire [31:0] issued_hash_requests;
    wire [31:0] issued_data_requests;
    wire [31:0] retired_instructions;
    integer timeout;

    localparam integer EXPECTED_HASH_REQUESTS = 1073;
    localparam integer EXPECTED_RETIRED = 2215;

    always #5 clk = ~clk;

    // Each service response is deliberately one cycle after request
    // acceptance, exercising the sequencer request/wait boundary.
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            hash_rsp_valid <= 1'b0;
            data_rsp_valid <= 1'b0;
        end else begin
            hash_rsp_valid <= hash_req_valid;
            data_rsp_valid <= data_req_valid;
        end
    end

    micro_hbs_sequencer #(
        .PROGRAM_WORDS(512),
        .PROGRAM_INIT_FILE(
            "manifests/programs/rtl_images/lms_lmots_public_w4.hex"
        ),
        .PROGRAM_INIT_WORDS(9)
    ) dut (
        .clk,
        .rst_n,
        .program_we(1'b0),
        .program_addr(9'b0),
        .program_wdata(64'b0),
        .job_valid,
        .job_ready,
        .job_entry(9'b0),
        .busy,
        .done,
        .error,
        .error_code,
        .hash_req_valid,
        .hash_req_ready(1'b1),
        .hash_layout_id(),
        .hash_lane_mask(),
        .hash_dest(),
        .hash_index_reg(),
        .hash_index_value(),
        .hash_rsp_valid,
        .hash_rsp_error(1'b0),
        .hash_rsp_error_code(16'b0),
        .dynamic_bound_req(),
        .dynamic_bound_addr(),
        .dynamic_bound_valid(1'b0),
        .dynamic_bound_value(8'b0),
        .dynamic_bound_error(1'b0),
        .dynamic_bound_error_code(16'b0),
        .data_req_valid,
        .data_req_ready(1'b1),
        .data_req_opcode,
        .data_req_flags(),
        .data_req_rd(),
        .data_req_rs(),
        .data_req_imm(),
        .data_req_rs_value(),
        .data_rsp_valid,
        .data_rsp_error(1'b0),
        .data_rsp_error_code(16'b0),
        .data_rsp_reg_write(1'b0),
        .data_rsp_reg_index(8'b0),
        .data_rsp_reg_value(32'b0),
        .tree_req_valid(),
        .tree_req_ready(1'b1),
        .tree_req_flags(),
        .tree_req_rd(),
        .tree_req_rs(),
        .tree_req_imm(),
        .tree_req_rs_value(),
        .tree_rsp_valid(1'b0),
        .tree_rsp_error(1'b1),
        .tree_rsp_error_code(16'h0104),
        .accepted_job_commands,
        .host_control_writes_during_busy,
        .issued_hash_requests,
        .issued_data_requests,
        .issued_tree_requests(),
        .retired_instructions
    );

    initial begin
        repeat (3) @(negedge clk);
        rst_n = 1'b1;
        @(negedge clk);
        if (!job_ready)
            $fatal(1, "initialized sequencer not ready");
        job_valid = 1'b1;
        @(negedge clk);
        job_valid = 1'b0;

        for (timeout = 0; timeout < 20000; timeout = timeout + 1) begin
            @(posedge clk);
            if (done) begin
                if (error)
                    $fatal(1, "LMOTS image control replay error %h", error_code);
                if (accepted_job_commands != 1
                    || host_control_writes_during_busy != 0)
                    $fatal(1, "autonomy counters jobs=%0d writes=%0d",
                           accepted_job_commands,
                           host_control_writes_during_busy);
                if (issued_hash_requests != EXPECTED_HASH_REQUESTS)
                    $fatal(1, "hash requests %0d expected %0d",
                           issued_hash_requests, EXPECTED_HASH_REQUESTS);
                if (issued_data_requests != 1 || data_req_opcode != 8'h0c)
                    $fatal(1, "EMIT request count/opcode %0d/%h",
                           issued_data_requests, data_req_opcode);
                if (retired_instructions != EXPECTED_RETIRED)
                    $fatal(1, "retired %0d expected %0d",
                           retired_instructions, EXPECTED_RETIRED);
                $display("PASS verified LMOTS readmemh control replay jobs=1 hashes=%0d data=%0d retired=%0d",
                         issued_hash_requests, issued_data_requests,
                         retired_instructions);
                $finish;
            end
            if (error)
                $fatal(1, "LMOTS image control replay fault %h", error_code);
        end
        $fatal(1, "timeout waiting for LMOTS image replay");
    end
endmodule

`default_nettype wire
