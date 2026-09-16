`timescale 1ns/1ps
`default_nettype none

module micro_hbs_control_slice #(
    parameter int PROGRAM_WORDS = 512
) (
    input  wire         clk,
    input  wire         rst_n,
    input  wire         program_we,
    input  wire  [8:0]  program_addr,
    input  wire  [63:0] program_wdata,
    input  wire         job_valid,
    output logic        job_ready,
    input  wire  [8:0]  job_entry,
    input  wire  [7:0]  job_operation,
    input  wire  [15:0] job_parameter_set,
    input  wire  [31:0] job_message_base,
    input  wire  [31:0] job_message_length,
    input  wire  [31:0] job_secret_key_base,
    input  wire  [31:0] job_public_key_base,
    input  wire  [31:0] job_output_base,
    input  wire  [31:0] job_state_handle,
    input  wire  [15:0] job_flags,
    output logic        busy,
    output logic        done,
    output logic        error,
    output logic [15:0] error_code,
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
    logic [7:0] latched_operation;
    logic [15:0] latched_parameter_set;
    logic [31:0] latched_message_base;
    logic [31:0] latched_message_length;
    logic [31:0] latched_secret_key_base;
    logic [31:0] latched_public_key_base;
    logic [31:0] latched_output_base;
    logic [31:0] latched_state_handle;
    logic [15:0] latched_flags;

    micro_hbs_job_latch job_latch (
        .clk,
        .rst_n,
        .accept(job_valid && job_ready),
        .in_operation(job_operation),
        .in_parameter_set(job_parameter_set),
        .in_message_base(job_message_base),
        .in_message_length(job_message_length),
        .in_secret_key_base(job_secret_key_base),
        .in_public_key_base(job_public_key_base),
        .in_output_base(job_output_base),
        .in_state_handle(job_state_handle),
        .in_flags(job_flags),
        .operation(latched_operation),
        .parameter_set(latched_parameter_set),
        .message_base(latched_message_base),
        .message_length(latched_message_length),
        .secret_key_base(latched_secret_key_base),
        .public_key_base(latched_public_key_base),
        .output_base(latched_output_base),
        .state_handle(latched_state_handle),
        .flags(latched_flags)
    );

    micro_hbs_sequencer #(.PROGRAM_WORDS(PROGRAM_WORDS)) sequencer (
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
        .hash_req_valid,
        .hash_req_ready,
        .hash_layout_id,
        .hash_lane_mask,
        .hash_dest,
        .hash_index_reg,
        .hash_index_value,
        .hash_rsp_valid,
        .hash_rsp_error(1'b0),
        .hash_rsp_error_code(16'h0000),
        .dynamic_bound_req(),
        .dynamic_bound_addr(),
        .dynamic_bound_valid(1'b0),
        .dynamic_bound_value(8'h00),
        .dynamic_bound_error(1'b0),
        .dynamic_bound_error_code(16'h0000),
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
        .host_control_writes_during_busy,
        .issued_hash_requests,
        .issued_data_requests(),
        .issued_tree_requests(),
        .retired_instructions
    );

    // This bounded placeholder is an internal test dependency, not an
    // external Hash descriptor ingress. The production cryptographic lane
    // replaces it without changing the Job interface.
    micro_hbs_hash_latency_stub #(.LATENCY(3)) hash_lane_stub (
        .clk,
        .rst_n,
        .req_valid(hash_req_valid),
        .req_ready(hash_req_ready),
        .layout_id(hash_layout_id),
        .lane_mask(hash_lane_mask),
        .dest(hash_dest),
        .index_reg(hash_index_reg),
        .rsp_valid(hash_rsp_valid)
    );
endmodule

`default_nettype wire
