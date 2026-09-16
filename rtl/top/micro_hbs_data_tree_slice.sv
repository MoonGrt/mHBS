`timescale 1ns/1ps
`default_nettype none

// Combined one-Job capability slice.  A single Microsequencer drives the
// descriptor/AGU data engine and TreeHash over one fixed-priority Scratchpad
// arbiter.  The only unsupported execution path is HASH_LAYOUT; no task/hash
// ingress or run-time scheduler exists.
module micro_hbs_data_tree_slice #(
    parameter integer PROGRAM_WORDS = 32,
    parameter integer DESCRIPTOR_COUNT = 16,
    parameter integer SCRATCH_WORDS = 64,
    parameter integer TREE_HEIGHT = 2,
    parameter integer UNROLL = 2
) (
    input  wire         clk,
    input  wire         rst_n,
    input  wire         program_we,
    input  wire [8:0]   program_addr,
    input  wire [63:0]  program_wdata,
    input  wire         descriptor_cfg_valid,
    output wire         descriptor_cfg_ready,
    input  wire [15:0]  descriptor_cfg_id,
    input  wire [127:0] descriptor_cfg_data,
    output wire         descriptor_cfg_error,
    output wire [15:0]  descriptor_cfg_error_code,
    input  wire         scratch_init_valid,
    output wire         scratch_init_ready,
    input  wire [15:0]  scratch_init_address,
    input  wire [63:0]  scratch_init_data,
    input  wire         job_valid,
    output wire         job_ready,
    input  wire [8:0]   job_entry,
    input  wire [15:0]  job_target_leaf,
    input  wire [255:0] job_public_seed,
    input  wire [255:0] job_address_template,
    output wire         out_valid,
    input  wire         out_ready,
    output wire [63:0]  out_data,
    output wire [7:0]   out_keep,
    output wire         out_last,
    output wire         root_valid,
    output wire [255:0] root,
    output wire         auth_valid,
    output wire [7:0]   auth_level,
    output wire [255:0] auth_node,
    output wire         busy,
    output wire         done,
    output wire         error,
    output wire [15:0]  error_code,
    output wire [31:0]  accepted_job_commands,
    output wire [31:0]  host_control_writes_during_busy,
    output wire [31:0]  issued_data_requests,
    output wire [31:0]  issued_tree_requests,
    output wire [31:0]  retired_instructions,
    output wire [15:0]  accepted_leaves,
    output wire [15:0]  parent_hashes,
    output wire [31:0]  data_scratch_grants,
    output wire [31:0]  emit_scratch_grants,
    output wire [31:0]  tree_scratch_grants,
    output wire [31:0]  scratch_transactions
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
    wire tree_req_valid, tree_req_ready;
    wire [7:0] tree_req_flags, tree_req_rd, tree_req_rs;
    wire [31:0] tree_req_imm, tree_req_rs_value;
    wire tree_rsp_valid, tree_rsp_error;
    wire [15:0] tree_rsp_error_code;
    wire [31:0] issued_hash_requests;

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
    wire [15:0] data_sp_req_address;
    wire [63:0] data_sp_req_write_data;
    wire data_sp_rsp_valid, data_sp_rsp_error;
    wire [63:0] data_sp_rsp_data;
    wire emit_sp_req_valid, emit_sp_req_ready, emit_sp_req_write;
    wire [15:0] emit_sp_req_address;
    wire [63:0] emit_sp_req_write_data;
    wire emit_sp_rsp_valid, emit_sp_rsp_ready, emit_sp_rsp_error;
    wire [63:0] emit_sp_rsp_data;
    wire tree_sp_req_valid, tree_sp_req_ready, tree_sp_req_write;
    wire [15:0] tree_sp_req_address;
    wire [63:0] tree_sp_req_write_data;
    wire tree_sp_rsp_valid, tree_sp_rsp_error;
    wire [63:0] tree_sp_rsp_data;

    wire arb_sp_req_valid, arb_sp_req_ready, arb_sp_req_write, arb_busy;
    wire [15:0] arb_sp_req_address;
    wire [63:0] arb_sp_req_write_data;
    wire sp_req_valid, sp_req_ready, sp_req_write;
    wire [15:0] sp_req_address;
    wire [63:0] sp_req_write_data, sp_rsp_data;
    wire sp_rsp_valid, sp_bounds_error;
    wire [31:0] scratch_completed, scratch_errors;

    logic [15:0] target_leaf_latched;
    logic [255:0] public_seed_latched, address_template_latched;
    wire parent_req_valid, parent_req_ready;
    wire [7:0] parent_req_height;
    wire [15:0] parent_req_start_leaf;
    wire [255:0] parent_req_left, parent_req_right;
    wire parent_rsp_valid, parent_rsp_error;
    wire [255:0] parent_rsp_value;
    wire [7:0] peak_stack_nodes;
    wire [15:0] tree_node_base_word = {8'b0, tree_req_rd} * 4;

    assign scratch_init_ready = !busy && !arb_busy && sp_req_ready;
    assign sp_req_valid = busy ? arb_sp_req_valid : scratch_init_valid;
    assign sp_req_write = busy ? arb_sp_req_write : 1'b1;
    assign sp_req_address = busy ? arb_sp_req_address : scratch_init_address;
    assign sp_req_write_data = busy ? arb_sp_req_write_data
        : scratch_init_data;
    assign arb_sp_req_ready = busy && sp_req_ready;

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            target_leaf_latched <= '0;
            public_seed_latched <= '0;
            address_template_latched <= '0;
        end else if (job_valid && job_ready) begin
            target_leaf_latched <= job_target_leaf;
            public_seed_latched <= job_public_seed;
            address_template_latched <= job_address_template;
        end
    end

    micro_hbs_sequencer #(.PROGRAM_WORDS(PROGRAM_WORDS)) sequencer (
        .clk, .rst_n, .program_we, .program_addr, .program_wdata,
        .job_valid, .job_ready, .job_entry, .busy, .done, .error, .error_code,
        .hash_req_valid(), .hash_req_ready(1'b1), .hash_layout_id(),
        .hash_lane_mask(), .hash_dest(), .hash_index_reg(), .hash_index_value(),
        .hash_rsp_valid(1'b0), .hash_rsp_error(1'b1),
        .hash_rsp_error_code(ERR_UNSUPPORTED_PATH),
        .dynamic_bound_req(), .dynamic_bound_addr(),
        .dynamic_bound_valid(1'b0), .dynamic_bound_value(8'b0),
        .dynamic_bound_error(1'b0), .dynamic_bound_error_code(16'b0),
        .data_req_valid, .data_req_ready, .data_req_opcode, .data_req_flags,
        .data_req_rd, .data_req_rs, .data_req_imm, .data_req_rs_value,
        .data_rsp_valid, .data_rsp_error, .data_rsp_error_code,
        .data_rsp_reg_write, .data_rsp_reg_index, .data_rsp_reg_value,
        .tree_req_valid, .tree_req_ready, .tree_req_flags, .tree_req_rd,
        .tree_req_rs, .tree_req_imm, .tree_req_rs_value,
        .tree_rsp_valid, .tree_rsp_error, .tree_rsp_error_code,
        .accepted_job_commands, .host_control_writes_during_busy,
        .issued_hash_requests, .issued_data_requests, .issued_tree_requests,
        .retired_instructions, .register_snapshot
    );

    micro_hbs_data_descriptor_store #(
        .DESCRIPTOR_COUNT(DESCRIPTOR_COUNT)
    ) descriptors (
        .clk, .rst_n, .engine_busy(busy),
        .cfg_valid(descriptor_cfg_valid), .cfg_ready(descriptor_cfg_ready),
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
        .descriptor_reserved(desc_reserved), .image_locked(),
        .descriptor_capacity(), .configured_count(), .accepted_loads(),
        .rejected_loads(), .host_writes_busy(), .lookup_requests(),
        .lookup_errors()
    );

    micro_hbs_data_engine #(
        .SCRATCH_WORDS(SCRATCH_WORDS), .ADDRESS_WIDTH(16)
    ) data_engine (
        .clk, .rst_n, .cmd_valid(data_req_valid), .cmd_ready(data_req_ready),
        .cmd_opcode(data_req_opcode), .cmd_flags(data_req_flags),
        .cmd_rd(data_req_rd), .cmd_rs(data_req_rs), .cmd_imm(data_req_imm),
        .cmd_rs_value(data_req_rs_value), .cmd_registers(register_snapshot),
        .rsp_valid(data_rsp_valid),
        .rsp_error(data_rsp_error), .rsp_error_code(data_rsp_error_code),
        .rsp_reg_write(data_rsp_reg_write),
        .rsp_reg_index(data_rsp_reg_index), .rsp_reg_value(data_rsp_reg_value),
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

    micro_hbs_tree_push_adapter #(
        .TREE_HEIGHT(TREE_HEIGHT), .NODE_BYTES(32),
        .SCRATCH_WORDS(SCRATCH_WORDS)
    ) tree_adapter (
        .clk, .rst_n, .cancel(1'b0),
        .cmd_valid(tree_req_valid), .cmd_ready(tree_req_ready),
        .cmd_descriptor_id(tree_req_imm[15:0]),
        .cmd_layout_id(tree_req_imm[15:0]), .cmd_node_source(8'h00),
        .cmd_node_base_word(tree_node_base_word),
        .cmd_node_index(tree_req_rs_value[15:0]),
        .cmd_leaf_index(tree_req_rs_value[15:0]),
        .cmd_tree_start(tree_req_rs_value == 0),
        .cmd_target_leaf(target_leaf_latched),
        .rsp_valid(tree_rsp_valid), .rsp_error(tree_rsp_error),
        .rsp_error_code(tree_rsp_error_code), .rsp_descriptor_id(),
        .rsp_layout_id(), .sp_req_valid(tree_sp_req_valid),
        .sp_req_ready(tree_sp_req_ready), .sp_req_write(tree_sp_req_write),
        .sp_req_address(tree_sp_req_address),
        .sp_req_write_data(tree_sp_req_write_data),
        .sp_rsp_valid(tree_sp_rsp_valid), .sp_rsp_read_data(tree_sp_rsp_data),
        .sp_rsp_error(tree_sp_rsp_error), .sp_rsp_error_code(16'h0402),
        .parent_req_valid, .parent_req_ready, .parent_req_height,
        .parent_req_start_leaf, .parent_req_left, .parent_req_right,
        .parent_rsp_valid, .parent_rsp_value, .parent_rsp_error,
        .auth_valid, .auth_level, .auth_node, .root_valid, .root,
        .busy(), .poisoned(), .accepted_leaves, .parent_hashes,
        .peak_stack_nodes
    );

    micro_hbs_xmss_tree_parent_context #(.UNROLL(UNROLL)) parent_context (
        .clk, .rst_n, .public_seed(public_seed_latched),
        .address_template(address_template_latched),
        .req_valid(parent_req_valid), .req_ready(parent_req_ready),
        .req_parent_height(parent_req_height),
        .req_start_leaf(parent_req_start_leaf),
        .req_left_node(parent_req_left), .req_right_node(parent_req_right),
        .rsp_valid(parent_rsp_valid), .rsp_parent(parent_rsp_value),
        .rsp_error(parent_rsp_error)
    );

    micro_hbs_scratch_arbiter #(.ADDRESS_WIDTH(16)) scratch_arbiter (
        .clk, .rst_n,
        .alu_request_valid(data_sp_req_valid),
        .alu_request_ready(data_sp_req_ready),
        .alu_request_write(data_sp_req_write),
        .alu_request_address(data_sp_req_address),
        .alu_request_write_data(data_sp_req_write_data),
        .alu_response_valid(data_sp_rsp_valid), .alu_response_ready(1'b1),
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
        .tree_request_valid(tree_sp_req_valid),
        .tree_request_ready(tree_sp_req_ready),
        .tree_request_write(tree_sp_req_write),
        .tree_request_address(tree_sp_req_address),
        .tree_request_write_data(tree_sp_req_write_data),
        .tree_response_valid(tree_sp_rsp_valid), .tree_response_ready(1'b1),
        .tree_response_read_data(tree_sp_rsp_data),
        .tree_response_error(tree_sp_rsp_error),
        .scratch_request_valid(arb_sp_req_valid),
        .scratch_request_ready(arb_sp_req_ready),
        .scratch_request_write(arb_sp_req_write),
        .scratch_request_address(arb_sp_req_address),
        .scratch_request_write_data(arb_sp_req_write_data),
        .scratch_response_valid(sp_rsp_valid),
        .scratch_response_read_data(sp_rsp_data),
        .scratch_bounds_error(sp_bounds_error), .busy(arb_busy),
        .outstanding(), .active_owner(), .alu_grants(data_scratch_grants),
        .emit_grants(emit_scratch_grants),
        .tree_grants(tree_scratch_grants),
        .accepted_transactions(scratch_transactions),
        .completed_transactions(scratch_completed),
        .error_transactions(scratch_errors)
    );

    micro_hbs_scratchpad64 #(
        .WORDS(SCRATCH_WORDS), .ADDRESS_WIDTH(16)
    ) scratchpad (
        .clk, .rst_n, .request_valid(sp_req_valid),
        .request_ready(sp_req_ready), .request_write(sp_req_write),
        .request_address(sp_req_address), .request_write_data(sp_req_write_data),
        .response_valid(sp_rsp_valid), .response_read_data(sp_rsp_data),
        .bounds_error(sp_bounds_error), .scrub_start(1'b0),
        .scrub_busy(), .scrub_done()
    );
endmodule

`default_nettype wire
