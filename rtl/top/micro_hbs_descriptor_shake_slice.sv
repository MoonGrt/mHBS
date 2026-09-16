`timescale 1ns/1ps
`default_nettype none

// One-Job vertical path proving that HASH_LAYOUT is consumed through a
// versioned descriptor rather than a hard-coded layout ID case statement.
module micro_hbs_descriptor_shake_slice #(
    parameter integer PROGRAM_WORDS = 32,
    parameter integer LAYOUT_COUNT = 16,
    parameter integer COMPONENT_WORDS = 256,
    parameter integer SCRATCH_WORDS = 512,
    parameter integer MAX_MESSAGE_BYTES = 1088,
    parameter integer UNROLL = 2
) (
    input  wire         clk,
    input  wire         rst_n,
    input  wire         program_we,
    input  wire [8:0]   program_addr,
    input  wire [63:0]  program_wdata,
    input  wire         layout_cfg_valid,
    output wire         layout_cfg_ready,
    input  wire [15:0]  layout_cfg_id,
    input  wire [127:0] layout_cfg_descriptor,
    output wire         layout_cfg_error,
    output wire [15:0]  layout_cfg_error_code,
    input  wire         component_cfg_valid,
    output wire         component_cfg_ready,
    input  wire [15:0]  component_cfg_index,
    input  wire [191:0] component_cfg_descriptor,
    output wire         component_cfg_error,
    output wire [15:0]  component_cfg_error_code,
    input  wire         scratch_init_valid,
    output wire         scratch_init_ready,
    input  wire         scratch_init_write,
    input  wire [15:0]  scratch_init_address,
    input  wire [63:0]  scratch_init_write_data,
    output wire         scratch_init_rsp_valid,
    output wire [63:0]  scratch_init_rsp_data,
    output wire         scratch_init_error,
    input  wire         job_valid,
    output wire         job_ready,
    input  wire [8:0]   job_entry,
    output wire         busy,
    output wire         done,
    output wire         error,
    output wire [15:0]  error_code,
    output wire [255:0] last_digest,
    output wire [31:0]  accepted_job_commands,
    output wire [31:0]  host_control_writes_during_busy,
    output wire [31:0]  issued_hash_requests,
    output wire [31:0]  retired_instructions,
    output wire [31:0]  scratch_reads,
    output wire [31:0]  scratch_writes,
    output wire [31:0]  absorbed_blocks,
    output wire [31:0]  retired_components
);
    localparam logic [15:0] ERR_UNSUPPORTED_PATH = 16'h0104;

    wire hash_req_valid, hash_req_ready;
    wire [15:0] hash_layout_id;
    wire [1:0] hash_lane_mask;
    wire [7:0] hash_dest, hash_index_reg;
    wire [31:0] hash_index_value;
    wire hash_rsp_valid, hash_rsp_error;
    wire [15:0] hash_rsp_error_code;
    wire [31:0] issued_data_requests, issued_tree_requests;
    wire [255:0] register_snapshot;

    wire composer_sp_req_valid, composer_sp_req_ready, composer_sp_req_write;
    wire [15:0] composer_sp_req_address;
    wire [63:0] composer_sp_req_write_data;
    wire composer_sp_rsp_valid, composer_sp_rsp_error;

    wire sp_req_valid, sp_req_ready, sp_req_write;
    wire [15:0] sp_req_address;
    wire [63:0] sp_req_write_data;
    wire sp_rsp_valid, sp_bounds_error;
    wire [63:0] sp_rsp_data;

    assign scratch_init_ready = !busy && sp_req_ready;
    assign sp_req_valid = busy ? composer_sp_req_valid : scratch_init_valid;
    assign sp_req_write = busy ? composer_sp_req_write : scratch_init_write;
    assign sp_req_address = busy ? composer_sp_req_address
        : scratch_init_address;
    assign sp_req_write_data = busy ? composer_sp_req_write_data
        : scratch_init_write_data;
    assign composer_sp_req_ready = busy && sp_req_ready;
    assign composer_sp_rsp_valid = busy && sp_rsp_valid;
    assign composer_sp_rsp_error = busy && sp_bounds_error;
    assign scratch_init_rsp_valid = !busy && sp_rsp_valid;
    assign scratch_init_rsp_data = sp_rsp_data;
    assign scratch_init_error = !busy && sp_bounds_error;

    micro_hbs_sequencer #(.PROGRAM_WORDS(PROGRAM_WORDS)) sequencer (
        .clk, .rst_n, .program_we, .program_addr, .program_wdata,
        .job_valid, .job_ready, .job_entry, .busy, .done, .error, .error_code,
        .hash_req_valid, .hash_req_ready, .hash_layout_id, .hash_lane_mask,
        .hash_dest, .hash_index_reg, .hash_index_value, .hash_rsp_valid,
        .hash_rsp_error, .hash_rsp_error_code,
        .dynamic_bound_req(), .dynamic_bound_addr(),
        .dynamic_bound_valid(1'b0), .dynamic_bound_value(8'b0),
        .dynamic_bound_error(1'b0), .dynamic_bound_error_code(16'b0),
        .data_req_valid(), .data_req_ready(1'b1), .data_req_opcode(),
        .data_req_flags(), .data_req_rd(), .data_req_rs(), .data_req_imm(),
        .data_req_rs_value(), .data_rsp_valid(1'b0), .data_rsp_error(1'b1),
        .data_rsp_error_code(ERR_UNSUPPORTED_PATH),
        .data_rsp_reg_write(1'b0), .data_rsp_reg_index(8'b0),
        .data_rsp_reg_value(32'b0),
        .tree_req_valid(), .tree_req_ready(1'b1), .tree_req_flags(),
        .tree_req_rd(), .tree_req_rs(), .tree_req_imm(), .tree_req_rs_value(),
        .tree_rsp_valid(1'b0), .tree_rsp_error(1'b1),
        .tree_rsp_error_code(ERR_UNSUPPORTED_PATH),
        .accepted_job_commands, .host_control_writes_during_busy,
        .issued_hash_requests, .issued_data_requests, .issued_tree_requests,
        .retired_instructions, .register_snapshot
    );

    micro_hbs_descriptor_shake_composer #(
        .LAYOUT_COUNT(LAYOUT_COUNT), .COMPONENT_WORDS(COMPONENT_WORDS),
        .SCRATCH_WORDS(SCRATCH_WORDS),
        .MAX_MESSAGE_BYTES(MAX_MESSAGE_BYTES), .UNROLL(UNROLL)
    ) composer (
        .clk, .rst_n, .engine_busy(busy),
        .cfg_valid(layout_cfg_valid), .cfg_ready(layout_cfg_ready),
        .cfg_layout_id(layout_cfg_id),
        .cfg_descriptor(layout_cfg_descriptor),
        .cfg_error(layout_cfg_error),
        .cfg_error_code(layout_cfg_error_code),
        .component_cfg_valid, .component_cfg_ready, .component_cfg_index,
        .component_cfg_descriptor, .component_cfg_error,
        .component_cfg_error_code,
        .req_valid(hash_req_valid), .req_ready(hash_req_ready),
        .layout_id(hash_layout_id), .lane_mask(hash_lane_mask),
        .destination(hash_dest), .index_value(hash_index_value),
        .register_snapshot,
        .rsp_valid(hash_rsp_valid), .rsp_error(hash_rsp_error),
        .rsp_error_code(hash_rsp_error_code),
        .sp_req_valid(composer_sp_req_valid),
        .sp_req_ready(composer_sp_req_ready),
        .sp_req_write(composer_sp_req_write),
        .sp_req_address(composer_sp_req_address),
        .sp_req_write_data(composer_sp_req_write_data),
        .sp_rsp_valid(composer_sp_rsp_valid),
        .sp_rsp_read_data(sp_rsp_data), .sp_rsp_error(composer_sp_rsp_error),
        .busy(), .last_digest, .scratch_reads, .scratch_writes,
        .absorbed_blocks, .retired_components
    );

    micro_hbs_scratchpad64 #(
        .WORDS(SCRATCH_WORDS), .ADDRESS_WIDTH(16)
    ) scratchpad (
        .clk, .rst_n, .request_valid(sp_req_valid),
        .request_ready(sp_req_ready), .request_write(sp_req_write),
        .request_address(sp_req_address),
        .request_write_data(sp_req_write_data),
        .response_valid(sp_rsp_valid), .response_read_data(sp_rsp_data),
        .bounds_error(sp_bounds_error), .scrub_start(1'b0),
        .scrub_busy(), .scrub_done()
    );
endmodule

`default_nettype wire
