`timescale 1ns/1ps
`default_nettype none

// One-Job vertical slice for descriptor-driven LOAD/STORE/XOR/EMIT.
// Program/data descriptor images and initial data are accepted only while the
// engine is idle.  During BUSY every data operation is derived from the
// executing microinstruction and the locked descriptor image; there is no
// external task or per-operation command ingress.
module micro_hbs_data_slice #(
    parameter integer PROGRAM_WORDS = 32,
    parameter integer DESCRIPTOR_COUNT = 16,
    parameter integer SCRATCH_WORDS = 64,
    parameter integer ADDRESS_WIDTH = 6
) (
    input  wire                         clk,
    input  wire                         rst_n,

    input  wire                         program_we,
    input  wire [8:0]                   program_addr,
    input  wire [63:0]                  program_wdata,

    input  wire                         descriptor_cfg_valid,
    output wire                         descriptor_cfg_ready,
    input  wire [15:0]                  descriptor_cfg_id,
    input  wire [127:0]                 descriptor_cfg_data,
    output wire                         descriptor_cfg_error,
    output wire [15:0]                  descriptor_cfg_error_code,

    input  wire                         scratch_init_valid,
    output wire                         scratch_init_ready,
    input  wire [ADDRESS_WIDTH-1:0]     scratch_init_address,
    input  wire [63:0]                  scratch_init_data,

    input  wire                         job_valid,
    output wire                         job_ready,
    input  wire [8:0]                   job_entry,

    output wire                         out_valid,
    input  wire                         out_ready,
    output wire [63:0]                  out_data,
    output wire [7:0]                   out_keep,
    output wire                         out_last,

    output wire                         busy,
    output wire                         done,
    output wire                         error,
    output wire [15:0]                  error_code,
    output wire [31:0]                  accepted_job_commands,
    output wire [31:0]                  host_control_writes_during_busy,
    output wire [31:0]                  issued_data_requests,
    output wire [31:0]                  retired_instructions,
    output wire [31:0]                  external_task_descriptors,
    output wire [31:0]                  external_hash_descriptors
);
    localparam logic [15:0] ERR_UNSUPPORTED_PATH = 16'h0104;

    wire data_req_valid, data_req_ready;
    wire [7:0] data_req_opcode, data_req_flags, data_req_rd, data_req_rs;
    wire [31:0] data_req_imm, data_req_rs_value;
    wire [255:0] register_snapshot;
    wire data_rsp_valid, data_rsp_error, data_rsp_reg_write;
    wire [15:0] data_rsp_error_code;
    wire [7:0] data_rsp_reg_index;
    wire [31:0] data_rsp_reg_value;

    wire desc_lookup_valid, desc_lookup_ready, desc_rsp_valid, desc_rsp_ready;
    wire [15:0] desc_lookup_id, desc_rsp_error_code;
    wire desc_rsp_error;
    wire [127:0] desc_value;
    wire [15:0] desc_flags, desc_source_a, desc_source_b, desc_destination;
    wire [15:0] desc_word_count;
    wire [3:0] desc_last_bytes, desc_address_mode;
    wire [7:0] desc_format_version;
    wire [31:0] desc_reserved;

    wire data_sp_req_valid, data_sp_req_ready, data_sp_req_write;
    wire [ADDRESS_WIDTH-1:0] data_sp_req_address;
    wire [63:0] data_sp_req_write_data;
    wire data_sp_rsp_valid, data_sp_rsp_error;
    wire [63:0] data_sp_rsp_data;
    wire emit_sp_req_valid, emit_sp_req_ready, emit_sp_req_write;
    wire [ADDRESS_WIDTH-1:0] emit_sp_req_address;
    wire [63:0] emit_sp_req_write_data;
    wire emit_sp_rsp_valid, emit_sp_rsp_ready, emit_sp_rsp_error;
    wire [63:0] emit_sp_rsp_data;

    wire arb_sp_req_valid, arb_sp_req_ready, arb_sp_req_write;
    wire [ADDRESS_WIDTH-1:0] arb_sp_req_address;
    wire [63:0] arb_sp_req_write_data;
    wire sp_req_valid, sp_req_ready, sp_req_write;
    wire [ADDRESS_WIDTH-1:0] sp_req_address;
    wire [63:0] sp_req_write_data;
    wire sp_rsp_valid, sp_bounds_error;
    wire [63:0] sp_rsp_data;
    wire arb_busy;

    wire [31:0] issued_hash_requests, issued_tree_requests;

    assign external_task_descriptors = 32'b0;
    assign external_hash_descriptors = 32'b0;

    assign scratch_init_ready = !busy && !arb_busy && sp_req_ready;
    assign sp_req_valid = busy ? arb_sp_req_valid : scratch_init_valid;
    assign sp_req_write = busy ? arb_sp_req_write : 1'b1;
    assign sp_req_address = busy ? arb_sp_req_address : scratch_init_address;
    assign sp_req_write_data = busy ? arb_sp_req_write_data
        : scratch_init_data;
    assign arb_sp_req_ready = busy && sp_req_ready;

    micro_hbs_sequencer #(.PROGRAM_WORDS(PROGRAM_WORDS)) sequencer (
        .clk, .rst_n, .program_we, .program_addr, .program_wdata,
        .job_valid, .job_ready, .job_entry, .busy, .done, .error,
        .error_code,
        .hash_req_valid(), .hash_req_ready(1'b1), .hash_layout_id(),
        .hash_lane_mask(), .hash_dest(), .hash_index_reg(),
        .hash_index_value(), .hash_rsp_valid(1'b0),
        .hash_rsp_error(1'b1),
        .hash_rsp_error_code(ERR_UNSUPPORTED_PATH),
        .dynamic_bound_req(), .dynamic_bound_addr(),
        .dynamic_bound_valid(1'b0), .dynamic_bound_value(8'b0),
        .dynamic_bound_error(1'b0), .dynamic_bound_error_code(16'b0),
        .data_req_valid, .data_req_ready, .data_req_opcode,
        .data_req_flags, .data_req_rd, .data_req_rs, .data_req_imm,
        .data_req_rs_value, .data_rsp_valid, .data_rsp_error,
        .data_rsp_error_code, .data_rsp_reg_write, .data_rsp_reg_index,
        .data_rsp_reg_value,
        .tree_req_valid(), .tree_req_ready(1'b1), .tree_req_flags(),
        .tree_req_rd(), .tree_req_rs(), .tree_req_imm(),
        .tree_req_rs_value(), .tree_rsp_valid(1'b0),
        .tree_rsp_error(1'b1),
        .tree_rsp_error_code(ERR_UNSUPPORTED_PATH),
        .accepted_job_commands, .host_control_writes_during_busy,
        .issued_hash_requests, .issued_data_requests,
        .issued_tree_requests, .retired_instructions, .register_snapshot
    );

    micro_hbs_data_descriptor_store #(
        .DESCRIPTOR_COUNT(DESCRIPTOR_COUNT)
    ) descriptors (
        .clk, .rst_n, .engine_busy(busy),
        .cfg_valid(descriptor_cfg_valid),
        .cfg_ready(descriptor_cfg_ready),
        .cfg_descriptor_id(descriptor_cfg_id),
        .cfg_descriptor(descriptor_cfg_data),
        .cfg_error(descriptor_cfg_error),
        .cfg_error_code(descriptor_cfg_error_code),
        .lookup_valid(desc_lookup_valid), .lookup_ready(desc_lookup_ready),
        .lookup_descriptor_id(desc_lookup_id),
        .lookup_rsp_valid(desc_rsp_valid),
        .lookup_rsp_ready(desc_rsp_ready),
        .lookup_rsp_error(desc_rsp_error),
        .lookup_rsp_error_code(desc_rsp_error_code),
        .lookup_descriptor(desc_value), .descriptor_flags(desc_flags),
        .descriptor_source_a(desc_source_a),
        .descriptor_source_b(desc_source_b),
        .descriptor_destination(desc_destination),
        .descriptor_word_count(desc_word_count),
        .descriptor_last_bytes(desc_last_bytes),
        .descriptor_address_mode(desc_address_mode),
        .descriptor_format_version(desc_format_version),
        .descriptor_reserved(desc_reserved),
        .image_locked(), .descriptor_capacity(), .configured_count(),
        .accepted_loads(), .rejected_loads(), .host_writes_busy(),
        .lookup_requests(), .lookup_errors()
    );

    micro_hbs_data_engine #(
        .SCRATCH_WORDS(SCRATCH_WORDS), .ADDRESS_WIDTH(ADDRESS_WIDTH)
    ) data_engine (
        .clk, .rst_n, .cmd_valid(data_req_valid),
        .cmd_ready(data_req_ready), .cmd_opcode(data_req_opcode),
        .cmd_flags(data_req_flags), .cmd_rd(data_req_rd),
        .cmd_rs(data_req_rs), .cmd_imm(data_req_imm),
        .cmd_rs_value(data_req_rs_value), .cmd_registers(register_snapshot),
        .rsp_valid(data_rsp_valid),
        .rsp_error(data_rsp_error), .rsp_error_code(data_rsp_error_code),
        .rsp_reg_write(data_rsp_reg_write),
        .rsp_reg_index(data_rsp_reg_index),
        .rsp_reg_value(data_rsp_reg_value),
        .descriptor_lookup_valid(desc_lookup_valid),
        .descriptor_lookup_ready(desc_lookup_ready),
        .descriptor_lookup_id(desc_lookup_id),
        .descriptor_rsp_valid(desc_rsp_valid),
        .descriptor_rsp_ready(desc_rsp_ready),
        .descriptor_rsp_error(desc_rsp_error),
        .descriptor_rsp_error_code(desc_rsp_error_code),
        .descriptor_flags(desc_flags), .descriptor_source_a(desc_source_a),
        .descriptor_source_b(desc_source_b),
        .descriptor_destination(desc_destination),
        .descriptor_word_count(desc_word_count),
        .descriptor_last_bytes(desc_last_bytes),
        .descriptor_address_mode(desc_address_mode),
        .descriptor_format_version(desc_format_version),
        .descriptor_reserved(desc_reserved),
        .binding_lookup_valid(), .binding_lookup_ready(1'b1),
        .binding_lookup_id(), .binding_rsp_valid(1'b0),
        .binding_rsp_ready(), .binding_rsp_error(1'b1),
        .binding_rsp_error_code(16'h0705), .binding_operand(2'b0),
        .binding_use_base_reg(1'b0), .binding_base_reg(3'b0),
        .binding_use_index_reg(1'b0), .binding_index_reg(3'b0),
        .binding_base_scale_words(16'b0),
        .binding_index_stride_words(16'b0),
        .data_scratch_request_valid(data_sp_req_valid),
        .data_scratch_request_ready(data_sp_req_ready),
        .data_scratch_request_write(data_sp_req_write),
        .data_scratch_request_address(data_sp_req_address),
        .data_scratch_request_write_data(data_sp_req_write_data),
        .data_scratch_response_valid(data_sp_rsp_valid),
        .data_scratch_response_data(data_sp_rsp_data),
        .data_scratch_response_error(data_sp_rsp_error),
        .emit_scratch_request_valid(emit_sp_req_valid),
        .emit_scratch_request_ready(emit_sp_req_ready),
        .emit_scratch_request_write(emit_sp_req_write),
        .emit_scratch_request_address(emit_sp_req_address),
        .emit_scratch_request_write_data(emit_sp_req_write_data),
        .emit_scratch_response_valid(emit_sp_rsp_valid),
        .emit_scratch_response_ready(emit_sp_rsp_ready),
        .emit_scratch_response_data(emit_sp_rsp_data),
        .emit_scratch_response_error(emit_sp_rsp_error),
        .out_valid, .out_ready, .out_data, .out_keep, .out_last,
        .accepted_commands(), .completed_commands(), .error_commands()
    );

    micro_hbs_scratch_arbiter #(.ADDRESS_WIDTH(ADDRESS_WIDTH)) arbiter (
        .clk, .rst_n,
        .alu_request_valid(data_sp_req_valid),
        .alu_request_ready(data_sp_req_ready),
        .alu_request_write(data_sp_req_write),
        .alu_request_address(data_sp_req_address),
        .alu_request_write_data(data_sp_req_write_data),
        .alu_response_valid(data_sp_rsp_valid),
        .alu_response_ready(1'b1),
        .alu_response_read_data(data_sp_rsp_data),
        .alu_response_error(data_sp_rsp_error),
        .emit_request_valid(emit_sp_req_valid),
        .emit_request_ready(emit_sp_req_ready),
        .emit_request_write(emit_sp_req_write),
        .emit_request_address(emit_sp_req_address),
        .emit_request_write_data(emit_sp_req_write_data),
        .emit_response_valid(emit_sp_rsp_valid),
        .emit_response_ready(emit_sp_rsp_ready),
        .emit_response_read_data(emit_sp_rsp_data),
        .emit_response_error(emit_sp_rsp_error),
        .tree_request_valid(1'b0), .tree_request_ready(),
        .tree_request_write(1'b0), .tree_request_address('0),
        .tree_request_write_data(64'b0), .tree_response_valid(),
        .tree_response_ready(1'b1), .tree_response_read_data(),
        .tree_response_error(), .scratch_request_valid(arb_sp_req_valid),
        .scratch_request_ready(arb_sp_req_ready),
        .scratch_request_write(arb_sp_req_write),
        .scratch_request_address(arb_sp_req_address),
        .scratch_request_write_data(arb_sp_req_write_data),
        .scratch_response_valid(sp_rsp_valid),
        .scratch_response_read_data(sp_rsp_data),
        .scratch_bounds_error(sp_bounds_error), .busy(arb_busy),
        .outstanding(), .active_owner(), .alu_grants(), .emit_grants(),
        .tree_grants(), .accepted_transactions(),
        .completed_transactions(), .error_transactions()
    );

    micro_hbs_scratchpad64 #(
        .WORDS(SCRATCH_WORDS), .ADDRESS_WIDTH(ADDRESS_WIDTH)
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
