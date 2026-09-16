`timescale 1ns/1ps
`default_nettype none

// One-Job RFC 8391 XMSS vertical path from HASH_LAYOUT through WOTS+ leaf
// generation, Scratchpad writeback, TREE_PUSH, randomized-H, root/auth output.
// The host supplies only immutable seeds/address context at Job admission.
// TREE_HEIGHT=10 executes the complete XMSS-SHAKE256_10_256 key-generation
// tree. Layout 0x0200 is currently a fused, serial WOTS+ leaf capability; the
// generic descriptor-driven composer remains the next integration boundary.
module micro_hbs_xmss_wots_tree_slice #(
    parameter integer PROGRAM_WORDS = 16,
    parameter integer TREE_HEIGHT = 1,
    parameter integer SCRATCH_WORDS = 64,
    parameter integer UNROLL = 2
) (
    input  wire         clk,
    input  wire         rst_n,
    input  wire         program_we,
    input  wire [8:0]   program_addr,
    input  wire [63:0]  program_wdata,
    input  wire         scratch_init_valid,
    output wire         scratch_init_ready,
    input  wire [15:0]  scratch_init_address,
    input  wire [63:0]  scratch_init_data,
    input  wire         job_valid,
    output wire         job_ready,
    input  wire [8:0]   job_entry,
    input  wire [15:0]  job_target_leaf,
    input  wire [255:0] job_sk_seed,
    input  wire [255:0] job_public_seed,
    input  wire [255:0] job_address_template,
    output wire         busy,
    output wire         done,
    output wire         error,
    output wire [15:0]  error_code,
    output wire         root_valid,
    output wire [255:0] root,
    output wire         auth_valid,
    output wire [7:0]   auth_level,
    output wire [255:0] auth_node,
    output wire [31:0]  accepted_job_commands,
    output wire [31:0]  host_control_writes_during_busy,
    output wire [31:0]  issued_hash_requests,
    output wire [31:0]  issued_tree_requests,
    output wire [31:0]  retired_instructions,
    output wire [15:0]  accepted_leaves,
    output wire [15:0]  parent_hashes,
    output wire [31:0]  leaf_scratch_writes,
    output wire [31:0]  last_leaf_shake_calls,
    output wire [31:0]  scratch_transactions
);
    localparam integer NODE_WORDS = 4;
    localparam logic [15:0] ERR_UNSUPPORTED_PATH = 16'h0104;

    logic [15:0] target_leaf_latched;
    logic [255:0] sk_seed_latched, public_seed_latched;
    logic [255:0] address_template_latched;

    wire hash_req_valid, hash_req_ready;
    wire [15:0] hash_layout_id;
    wire [1:0] hash_lane_mask;
    wire [7:0] hash_dest, hash_index_reg;
    wire [31:0] hash_index_value;
    wire hash_rsp_valid, hash_rsp_error;
    wire [15:0] hash_rsp_error_code;
    wire tree_req_valid, tree_req_ready;
    wire [7:0] tree_req_flags, tree_req_rd, tree_req_rs;
    wire [31:0] tree_req_imm, tree_req_rs_value;
    wire tree_rsp_valid, tree_rsp_error;
    wire [15:0] tree_rsp_error_code;
    wire [31:0] issued_data_requests;

    wire leaf_sp_req_valid, leaf_sp_req_ready, leaf_sp_req_write;
    wire [15:0] leaf_sp_req_address;
    wire [63:0] leaf_sp_req_write_data;
    wire leaf_sp_rsp_valid, leaf_sp_rsp_error;
    wire [63:0] leaf_sp_rsp_data;
    wire [31:0] last_prf_calls, last_chain_steps, last_ltree_parents;

    wire tree_sp_req_valid, tree_sp_req_ready, tree_sp_req_write;
    wire [15:0] tree_sp_req_address;
    wire [63:0] tree_sp_req_write_data;
    wire tree_sp_rsp_valid, tree_sp_rsp_error;
    wire [63:0] tree_sp_rsp_data;
    wire [15:0] tree_node_base_word;

    wire parent_req_valid, parent_req_ready;
    wire [7:0] parent_req_height;
    wire [15:0] parent_req_start_leaf;
    wire [255:0] parent_req_left, parent_req_right;
    wire parent_rsp_valid, parent_rsp_error;
    wire [255:0] parent_rsp_value;

    wire arb_sp_req_valid, arb_sp_req_ready, arb_sp_req_write, arb_busy;
    wire [15:0] arb_sp_req_address;
    wire [63:0] arb_sp_req_write_data;
    wire sp_req_valid, sp_req_ready, sp_req_write;
    wire [15:0] sp_req_address;
    wire [63:0] sp_req_write_data, sp_rsp_data;
    wire sp_rsp_valid, sp_bounds_error;
    wire [31:0] scratch_completed, scratch_errors;

    assign tree_node_base_word = {8'b0, tree_req_rd} * NODE_WORDS;
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
            sk_seed_latched <= '0;
            public_seed_latched <= '0;
            address_template_latched <= '0;
        end else if (job_valid && job_ready) begin
            target_leaf_latched <= job_target_leaf;
            sk_seed_latched <= job_sk_seed;
            public_seed_latched <= job_public_seed;
            address_template_latched <= job_address_template;
        end
    end

    micro_hbs_sequencer #(.PROGRAM_WORDS(PROGRAM_WORDS)) sequencer (
        .clk, .rst_n, .program_we, .program_addr, .program_wdata,
        .job_valid, .job_ready, .job_entry, .busy, .done, .error, .error_code,
        .hash_req_valid, .hash_req_ready, .hash_layout_id, .hash_lane_mask,
        .hash_dest, .hash_index_reg, .hash_index_value, .hash_rsp_valid,
        .hash_rsp_error, .hash_rsp_error_code,
        .dynamic_bound_req(), .dynamic_bound_addr(),
        .dynamic_bound_valid(1'b0), .dynamic_bound_value(8'h00),
        .dynamic_bound_error(1'b0), .dynamic_bound_error_code(16'h0000),
        .data_req_valid(), .data_req_ready(1'b1), .data_req_opcode(),
        .data_req_flags(), .data_req_rd(), .data_req_rs(), .data_req_imm(),
        .data_req_rs_value(), .data_rsp_valid(1'b0), .data_rsp_error(1'b1),
        .data_rsp_error_code(ERR_UNSUPPORTED_PATH),
        .data_rsp_reg_write(1'b0), .data_rsp_reg_index(8'h00),
        .data_rsp_reg_value(32'h00000000),
        .tree_req_valid, .tree_req_ready, .tree_req_flags, .tree_req_rd,
        .tree_req_rs, .tree_req_imm, .tree_req_rs_value,
        .tree_rsp_valid, .tree_rsp_error, .tree_rsp_error_code,
        .accepted_job_commands, .host_control_writes_during_busy,
        .issued_hash_requests, .issued_data_requests, .issued_tree_requests,
        .retired_instructions, .register_snapshot()
    );

    micro_hbs_xmss_wots_leaf_scratch_adapter #(
        .SCRATCH_WORDS(SCRATCH_WORDS), .UNROLL(UNROLL)
    ) leaf_adapter (
        .clk, .rst_n, .req_valid(hash_req_valid), .req_ready(hash_req_ready),
        .layout_id(hash_layout_id), .lane_mask(hash_lane_mask),
        .destination(hash_dest), .index_value(hash_index_value),
        .sk_seed(sk_seed_latched), .pub_seed(public_seed_latched),
        .address_template(address_template_latched),
        .rsp_valid(hash_rsp_valid), .rsp_error(hash_rsp_error),
        .rsp_error_code(hash_rsp_error_code),
        .sp_req_valid(leaf_sp_req_valid), .sp_req_ready(leaf_sp_req_ready),
        .sp_req_write(leaf_sp_req_write),
        .sp_req_address(leaf_sp_req_address),
        .sp_req_write_data(leaf_sp_req_write_data),
        .sp_rsp_valid(leaf_sp_rsp_valid), .sp_rsp_error(leaf_sp_rsp_error),
        .prf_keygen_calls(last_prf_calls), .chain_steps(last_chain_steps),
        .ltree_parents(last_ltree_parents),
        .shake_calls(last_leaf_shake_calls),
        .scratch_writes(leaf_scratch_writes)
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
        // HASH_LAYOUT overwrites one fixed leaf buffer; the public register
        // value remains only the TreeHash leaf identity.
        .cmd_node_index(16'b0),
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
        .peak_stack_nodes()
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
        .alu_request_valid(leaf_sp_req_valid),
        .alu_request_ready(leaf_sp_req_ready),
        .alu_request_write(leaf_sp_req_write),
        .alu_request_address(leaf_sp_req_address),
        .alu_request_write_data(leaf_sp_req_write_data),
        .alu_response_valid(leaf_sp_rsp_valid), .alu_response_ready(1'b1),
        .alu_response_read_data(leaf_sp_rsp_data),
        .alu_response_error(leaf_sp_rsp_error),
        .emit_request_valid(1'b0), .emit_request_ready(),
        .emit_request_write(1'b0), .emit_request_address(16'b0),
        .emit_request_write_data(64'b0), .emit_response_valid(),
        .emit_response_ready(1'b1), .emit_response_read_data(),
        .emit_response_error(),
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
        .outstanding(), .active_owner(), .alu_grants(), .emit_grants(),
        .tree_grants(), .accepted_transactions(scratch_transactions),
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
