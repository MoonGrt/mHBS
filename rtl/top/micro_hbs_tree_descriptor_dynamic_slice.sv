`timescale 1ns/1ps
`default_nettype none

// Coarse-grained descriptor-selected dynamic TreeHash slice.
//
// The host initializes the static descriptor image only while IDLE.  One
// start(descriptor_id, target_leaf) causes an internal descriptor lookup and,
// after explicit capability checks, one dynamic-height TreeHash transaction.
// No microsequencer or software-supplied per-level operations are present.
//
// This slice currently implements TREEHASH_MIN storage_mode only.  SUBTREE
// and FULL descriptors are rejected with ERR_UNSUPPORTED_MODE rather than
// being silently treated as MIN.  The datapath is 256 bits, so descriptors
// with node_bytes other than 32 are also rejected explicitly.  The opaque
// parent_layout_id is carried with every accepted parent request.
module micro_hbs_tree_descriptor_dynamic_slice #(
    parameter integer MAX_TREE_HEIGHT = 10,
    parameter integer DESCRIPTOR_COUNT = 16
) (
    input  wire         clk,
    input  wire         rst_n,

    input  wire         cfg_valid,
    output wire         cfg_ready,
    input  wire [15:0]  cfg_descriptor_id,
    input  wire [127:0] cfg_descriptor,
    output wire         cfg_error,
    output wire [15:0]  cfg_error_code,

    input  wire         start_valid,
    output wire         start_ready,
    input  wire [15:0]  start_descriptor_id,
    input  wire [15:0]  start_target_leaf,

    input  wire         leaf_valid,
    output wire         leaf_ready,
    input  wire [15:0]  leaf_index,
    input  wire [255:0] leaf_value,

    output wire         parent_req_valid,
    input  wire         parent_req_ready,
    output wire [7:0]   parent_req_height,
    output wire [15:0]  parent_req_start_leaf,
    output wire [255:0] parent_req_left,
    output wire [255:0] parent_req_right,
    output wire [15:0]  parent_req_layout_id,
    input  wire         parent_rsp_valid,
    input  wire [255:0] parent_rsp_value,
    input  wire         parent_rsp_error,

    output wire         auth_valid,
    output wire [7:0]   auth_level,
    output wire [255:0] auth_node,
    output wire         root_valid,
    output wire [255:0] root,
    output wire         busy,
    output logic        done,
    output logic        error,
    output logic [15:0] error_code,
    output wire [15:0]  accepted_leaves,
    output wire [15:0]  parent_hashes,
    output wire [7:0]   peak_stack_nodes,
    output logic [31:0] accepted_starts,
    output logic [31:0] rejected_starts,
    output wire [31:0]  descriptor_host_writes_busy,
    output wire [31:0]  descriptor_lookup_requests
);
    localparam logic [7:0] MODE_TREEHASH_MIN = 8'd0;
    localparam logic [15:0] ERR_UNSUPPORTED_MODE = 16'h0a01;
    localparam logic [15:0] ERR_UNSUPPORTED_NODE_BYTES = 16'h0a02;

    typedef enum logic [2:0] {
        S_IDLE, S_DESCRIPTOR_REQ, S_DESCRIPTOR_WAIT,
        S_START_TREE, S_RUN_TREE
    } state_t;
    state_t state;

    logic [15:0] descriptor_id_latched;
    logic [15:0] target_leaf_latched;
    logic [7:0] selected_tree_height;
    logic [15:0] selected_parent_layout_id;

    wire descriptor_lookup_valid;
    wire descriptor_lookup_ready;
    wire [15:0] descriptor_lookup_id;
    wire descriptor_rsp_valid;
    wire descriptor_rsp_ready;
    wire descriptor_rsp_error;
    wire [15:0] descriptor_rsp_error_code;
    wire [127:0] descriptor_value;
    wire [7:0] descriptor_format_version;
    wire [7:0] descriptor_tree_height;
    wire [15:0] descriptor_node_bytes;
    wire [15:0] descriptor_parent_layout_id;
    wire [7:0] descriptor_storage_mode;
    wire [7:0] descriptor_subtree_height;
    wire [7:0] descriptor_window_height;
    wire [55:0] descriptor_reserved;

    wire dynamic_start;
    wire dynamic_ready;
    wire dynamic_busy;
    wire dynamic_error;
    wire [15:0] dynamic_error_code;
    wire dynamic_auth_valid;
    wire [7:0] dynamic_auth_level;
    wire [255:0] dynamic_auth_node;
    wire dynamic_root_valid;
    wire [255:0] dynamic_root;
    wire dynamic_parent_req_valid;
    wire [7:0] dynamic_parent_req_height;
    wire [15:0] dynamic_parent_req_start_leaf;
    wire [255:0] dynamic_parent_req_left;
    wire [255:0] dynamic_parent_req_right;

    assign busy = state != S_IDLE;
    assign start_ready = rst_n && state == S_IDLE && !cfg_valid;
    assign descriptor_lookup_valid = state == S_DESCRIPTOR_REQ;
    assign descriptor_lookup_id = descriptor_id_latched;
    assign descriptor_rsp_ready = state == S_DESCRIPTOR_WAIT;
    assign dynamic_start = state == S_START_TREE;

    // Mask inactive payloads so a rejected descriptor cannot expose data left
    // by an earlier successful transaction.
    assign parent_req_valid = dynamic_parent_req_valid;
    assign parent_req_height = parent_req_valid
        ? dynamic_parent_req_height : 8'b0;
    assign parent_req_start_leaf = parent_req_valid
        ? dynamic_parent_req_start_leaf : 16'b0;
    assign parent_req_left = parent_req_valid
        ? dynamic_parent_req_left : 256'b0;
    assign parent_req_right = parent_req_valid
        ? dynamic_parent_req_right : 256'b0;
    assign parent_req_layout_id = parent_req_valid
        ? selected_parent_layout_id : 16'b0;
    assign auth_valid = dynamic_auth_valid;
    assign auth_level = auth_valid ? dynamic_auth_level : 8'b0;
    assign auth_node = auth_valid ? dynamic_auth_node : 256'b0;
    assign root_valid = dynamic_root_valid;
    assign root = root_valid ? dynamic_root : 256'b0;

    micro_hbs_tree_descriptor_store #(
        .DESCRIPTOR_COUNT(DESCRIPTOR_COUNT), .FORMAT_VERSION(8'h01)
    ) descriptor_store (
        .clk, .rst_n, .engine_busy(busy),
        .cfg_valid, .cfg_ready, .cfg_descriptor_id, .cfg_descriptor,
        .cfg_error, .cfg_error_code,
        .lookup_valid(descriptor_lookup_valid),
        .lookup_ready(descriptor_lookup_ready),
        .lookup_descriptor_id(descriptor_lookup_id),
        .lookup_rsp_valid(descriptor_rsp_valid),
        .lookup_rsp_ready(descriptor_rsp_ready),
        .lookup_rsp_error(descriptor_rsp_error),
        .lookup_rsp_error_code(descriptor_rsp_error_code),
        .lookup_descriptor(descriptor_value),
        .descriptor_format_version, .descriptor_tree_height,
        .descriptor_node_bytes, .descriptor_parent_layout_id,
        .descriptor_storage_mode, .descriptor_subtree_height,
        .descriptor_window_height, .descriptor_reserved,
        .image_locked(), .descriptor_capacity(), .configured_count(),
        .accepted_loads(), .rejected_loads(),
        .host_writes_busy(descriptor_host_writes_busy),
        .lookup_requests(descriptor_lookup_requests), .lookup_errors()
    );

    micro_hbs_treehash_min_dynamic #(
        .MAX_TREE_HEIGHT(MAX_TREE_HEIGHT)
    ) dynamic_treehash (
        .clk, .rst_n, .start(dynamic_start), .ready(dynamic_ready),
        .tree_height(selected_tree_height),
        .target_leaf(target_leaf_latched),
        .leaf_valid, .leaf_ready, .leaf_index, .leaf_value,
        .parent_req_valid(dynamic_parent_req_valid), .parent_req_ready,
        .parent_req_height(dynamic_parent_req_height),
        .parent_req_start_leaf(dynamic_parent_req_start_leaf),
        .parent_req_left(dynamic_parent_req_left),
        .parent_req_right(dynamic_parent_req_right),
        .parent_rsp_valid, .parent_rsp_value, .parent_rsp_error,
        .auth_valid(dynamic_auth_valid), .auth_level(dynamic_auth_level),
        .auth_node(dynamic_auth_node), .root_valid(dynamic_root_valid),
        .root(dynamic_root), .busy(dynamic_busy), .error(dynamic_error),
        .error_code(dynamic_error_code), .accepted_leaves,
        .parent_hashes, .peak_stack_nodes
    );

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= S_IDLE;
            descriptor_id_latched <= '0;
            target_leaf_latched <= '0;
            selected_tree_height <= '0;
            selected_parent_layout_id <= '0;
            done <= 1'b0;
            error <= 1'b0;
            error_code <= '0;
            accepted_starts <= '0;
            rejected_starts <= '0;
        end else begin
            done <= 1'b0;
            case (state)
                S_IDLE: begin
                    if (start_valid && start_ready) begin
                        descriptor_id_latched <= start_descriptor_id;
                        target_leaf_latched <= start_target_leaf;
                        error <= 1'b0;
                        error_code <= '0;
                        accepted_starts <= accepted_starts + 1'b1;
                        state <= S_DESCRIPTOR_REQ;
                    end
                end

                S_DESCRIPTOR_REQ: begin
                    if (descriptor_lookup_ready)
                        state <= S_DESCRIPTOR_WAIT;
                end

                S_DESCRIPTOR_WAIT: begin
                    if (descriptor_rsp_valid) begin
                        if (descriptor_rsp_error) begin
                            error <= 1'b1;
                            error_code <= descriptor_rsp_error_code;
                            rejected_starts <= rejected_starts + 1'b1;
                            selected_tree_height <= '0;
                            selected_parent_layout_id <= '0;
                            state <= S_IDLE;
                        end else if (descriptor_storage_mode
                            != MODE_TREEHASH_MIN) begin
                            error <= 1'b1;
                            error_code <= ERR_UNSUPPORTED_MODE;
                            rejected_starts <= rejected_starts + 1'b1;
                            selected_tree_height <= '0;
                            selected_parent_layout_id <= '0;
                            state <= S_IDLE;
                        end else if (descriptor_node_bytes != 16'd32) begin
                            error <= 1'b1;
                            error_code <= ERR_UNSUPPORTED_NODE_BYTES;
                            rejected_starts <= rejected_starts + 1'b1;
                            selected_tree_height <= '0;
                            selected_parent_layout_id <= '0;
                            state <= S_IDLE;
                        end else begin
                            selected_tree_height <= descriptor_tree_height;
                            selected_parent_layout_id
                                <= descriptor_parent_layout_id;
                            state <= S_START_TREE;
                        end
                    end
                end

                S_START_TREE: begin
                    if (dynamic_ready)
                        state <= S_RUN_TREE;
                end

                S_RUN_TREE: begin
                    if (dynamic_error) begin
                        error <= 1'b1;
                        error_code <= dynamic_error_code;
                        rejected_starts <= rejected_starts + 1'b1;
                        selected_tree_height <= '0;
                        selected_parent_layout_id <= '0;
                        state <= S_IDLE;
                    end else if (dynamic_ready && !dynamic_busy) begin
                        done <= 1'b1;
                        state <= S_IDLE;
                    end
                end

                default: begin
                    error <= 1'b1;
                    error_code <= ERR_UNSUPPORTED_MODE;
                    rejected_starts <= rejected_starts + 1'b1;
                    selected_tree_height <= '0;
                    selected_parent_layout_id <= '0;
                    state <= S_IDLE;
                end
            endcase
        end
    end
endmodule

`default_nettype wire
