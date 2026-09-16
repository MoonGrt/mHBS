`timescale 1ns/1ps
`default_nettype none

module micro_hbs_shake_chain_slice #(
    parameter integer PROGRAM_WORDS = 512,
    parameter integer UNROLL = 2
) (
    input  wire         clk,
    input  wire         rst_n,
    input  wire         program_we,
    input  wire  [8:0]  program_addr,
    input  wire  [63:0] program_wdata,
    input  wire         job_valid,
    output logic        job_ready,
    input  wire  [8:0]  job_entry,
    input  wire [255:0] job_initial_value,
    output logic        busy,
    output logic        done,
    output logic        error,
    output logic [15:0] error_code,
    output logic [255:0] result,
    output logic [31:0] accepted_job_commands,
    output logic [31:0] host_control_writes_during_busy,
    output logic [31:0] issued_hash_requests,
    output logic [31:0] retired_instructions
);
    logic hash_req_valid;
    logic hash_req_ready;
    logic [15:0] hash_layout_id;
    logic [1:0] hash_lane_mask;
    logic [7:0] hash_dest;
    logic [7:0] hash_index_reg;
    logic [31:0] hash_index_value;
    logic hash_rsp_valid;
    logic hash_rsp_error;
    logic [15:0] hash_rsp_error_code;

    micro_hbs_sequencer #(.PROGRAM_WORDS(PROGRAM_WORDS)) sequencer (
        .clk, .rst_n, .program_we, .program_addr, .program_wdata,
        .job_valid, .job_ready, .job_entry, .busy, .done, .error, .error_code,
        .hash_req_valid, .hash_req_ready, .hash_layout_id, .hash_lane_mask,
        .hash_dest, .hash_index_reg, .hash_index_value, .hash_rsp_valid, .hash_rsp_error,
        .hash_rsp_error_code, .dynamic_bound_req(), .dynamic_bound_addr(),
        .dynamic_bound_valid(1'b0), .dynamic_bound_value(8'h00),
        .dynamic_bound_error(1'b0), .dynamic_bound_error_code(16'h0000),
        .data_req_valid(), .data_req_ready(1'b1), .data_req_opcode(),
        .data_req_flags(), .data_req_rd(), .data_req_rs(), .data_req_imm(),
        .data_req_rs_value(), .data_rsp_valid(1'b0), .data_rsp_error(1'b1),
        .data_rsp_error_code(16'h0104),
        .data_rsp_reg_write(1'b0), .data_rsp_reg_index(8'h00),
        .data_rsp_reg_value(32'h00000000),
        .tree_req_valid(), .tree_req_ready(1'b1), .tree_req_flags(),
        .tree_req_rd(), .tree_req_rs(), .tree_req_imm(), .tree_req_rs_value(),
        .tree_rsp_valid(1'b0), .tree_rsp_error(1'b1),
        .tree_rsp_error_code(16'h0104),
        .accepted_job_commands,
        .host_control_writes_during_busy, .issued_hash_requests,
        .issued_data_requests(),
        .issued_tree_requests(),
        .retired_instructions
    );

    micro_hbs_shake_chain_adapter #(.UNROLL(UNROLL)) composer_and_lane (
        .clk,
        .rst_n,
        .load_initial_value(job_valid && job_ready),
        .initial_value(job_initial_value),
        .req_valid(hash_req_valid),
        .req_ready(hash_req_ready),
        .layout_id(hash_layout_id),
        .rsp_valid(hash_rsp_valid),
        .rsp_error(hash_rsp_error),
        .rsp_error_code(hash_rsp_error_code),
        .chain_value(result)
    );
endmodule

`default_nettype wire
