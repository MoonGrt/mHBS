`timescale 1ns/1ps
`default_nettype none

// One-Job TreeHash slice using the RFC 8391 XMSS-SHAKE256/n=32 randomized-H
// parent layout.  public_seed and the upper ADRS template are coarse immutable
// Job fields captured once at admission; tree height/index are derived from
// TreeHash merge context in hardware.
module micro_hbs_xmss_tree_push_slice #(
    parameter integer PROGRAM_WORDS = 16,
    parameter integer TREE_HEIGHT = 2,
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
    output wire [31:0]  issued_tree_requests,
    output wire [31:0]  retired_instructions,
    output wire [15:0]  accepted_leaves,
    output wire [15:0]  parent_hashes,
    output wire [7:0]   peak_stack_nodes
);
    localparam integer NODE_WORDS = 4;
    localparam logic [15:0] ERR_UNSUPPORTED_PATH = 16'h0104;

    wire tree_req_valid, tree_req_ready;
    wire [7:0] tree_req_flags, tree_req_rd, tree_req_rs;
    wire [31:0] tree_req_imm, tree_req_rs_value;
    wire tree_rsp_valid, tree_rsp_error;
    wire [15:0] tree_rsp_error_code;
    logic [15:0] target_leaf_latched;
    logic [255:0] public_seed_latched, address_template_latched;

    wire adapter_sp_req_valid, adapter_sp_req_ready, adapter_sp_req_write;
    wire [15:0] adapter_sp_req_address;
    wire [63:0] adapter_sp_req_write_data;
    wire sp_response_valid, sp_bounds_error;
    wire [63:0] sp_response_read_data;
    wire parent_req_valid, parent_req_ready;
    wire [7:0] parent_req_height;
    wire [15:0] parent_req_start_leaf;
    wire [255:0] parent_req_left, parent_req_right;
    wire parent_rsp_valid, parent_rsp_error;
    wire [255:0] parent_rsp_value;
    wire scratch_request_valid, scratch_request_ready, scratch_request_write;
    wire [15:0] scratch_request_address;
    wire [63:0] scratch_request_write_data;
    wire [31:0] issued_hash_requests, issued_data_requests;
    wire [15:0] tree_node_base_word;

    assign scratch_init_ready = !busy && scratch_request_ready;
    assign scratch_request_valid = busy ? adapter_sp_req_valid
        : scratch_init_valid;
    assign scratch_request_write = busy ? adapter_sp_req_write : 1'b1;
    assign scratch_request_address = busy ? adapter_sp_req_address
        : scratch_init_address;
    assign scratch_request_write_data = busy ? adapter_sp_req_write_data
        : scratch_init_data;
    assign adapter_sp_req_ready = busy && scratch_request_ready;
    assign tree_node_base_word = {8'b0, tree_req_rd} * NODE_WORDS;

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
        .retired_instructions
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
        .rsp_layout_id(), .sp_req_valid(adapter_sp_req_valid),
        .sp_req_ready(adapter_sp_req_ready),
        .sp_req_write(adapter_sp_req_write),
        .sp_req_address(adapter_sp_req_address),
        .sp_req_write_data(adapter_sp_req_write_data),
        .sp_rsp_valid(sp_response_valid),
        .sp_rsp_read_data(sp_response_read_data),
        .sp_rsp_error(sp_bounds_error), .sp_rsp_error_code(16'h0402),
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

    micro_hbs_scratchpad64 #(
        .WORDS(SCRATCH_WORDS), .ADDRESS_WIDTH(16)
    ) scratchpad (
        .clk, .rst_n, .request_valid(scratch_request_valid),
        .request_ready(scratch_request_ready),
        .request_write(scratch_request_write),
        .request_address(scratch_request_address),
        .request_write_data(scratch_request_write_data),
        .response_valid(sp_response_valid),
        .response_read_data(sp_response_read_data),
        .bounds_error(sp_bounds_error), .scrub_start(1'b0),
        .scrub_busy(), .scrub_done()
    );
endmodule

`default_nettype wire
