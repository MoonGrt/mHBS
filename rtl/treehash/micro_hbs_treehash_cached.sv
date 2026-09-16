`timescale 1ns/1ps
`default_nettype none

// micro_hbs_treehash_min plus a passive, synthesis-time-selected node cache.
// The cache observes accepted leaves and successful parent responses, so it
// cannot change the TreeHash issue order or parent-hash latency.
module micro_hbs_treehash_cached #(
    parameter integer TREE_HEIGHT = 10,
    parameter integer CACHE_MODE = 1,
    parameter integer SUBTREE_HEIGHT = 4
) (
    input  wire         clk,
    input  wire         rst_n,
    input  wire         start,
    output wire         ready,
    input  wire [15:0]  target_leaf,
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
    input  wire         parent_rsp_valid,
    input  wire [255:0] parent_rsp_value,
    input  wire         parent_rsp_error,
    output wire         auth_valid,
    output wire [7:0]   auth_level,
    output wire [255:0] auth_node,
    output wire         root_valid,
    output wire [255:0] root,
    output wire         busy,
    output wire         error,
    output wire [15:0]  error_code,
    output wire [15:0]  accepted_leaves,
    output wire [15:0]  parent_hashes,
    output wire [7:0]   peak_stack_nodes,

    input  wire         cache_clear,
    input  wire         cache_lookup_valid,
    output wire         cache_lookup_ready,
    input  wire [7:0]   cache_lookup_height,
    input  wire [15:0]  cache_lookup_start_leaf,
    output wire         cache_rsp_valid,
    output wire         cache_hit,
    output wire [255:0] cache_value,
    output wire         cache_bounds_error,
    output wire         cache_error,
    output wire [15:0]  cache_error_code,
    output wire [31:0]  cache_writes,
    output wire [31:0]  cache_retained_nodes,
    output wire [31:0]  cache_capacity_nodes
);
    logic [7:0] pending_parent_height;
    logic [15:0] pending_parent_start_leaf;
    logic pending_parent_valid;
    wire cache_store_leaf;
    wire cache_store_parent;
    wire tree_error;
    wire [15:0] tree_error_code;

    assign cache_store_leaf = leaf_valid && leaf_ready;
    assign cache_store_parent = parent_rsp_valid && !parent_rsp_error
        && pending_parent_valid;
    assign error = tree_error || cache_error;
    assign error_code = tree_error ? tree_error_code : cache_error_code;

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            pending_parent_height <= '0;
            pending_parent_start_leaf <= '0;
            pending_parent_valid <= 1'b0;
        end else begin
            if (parent_req_valid && parent_req_ready) begin
                pending_parent_height <= parent_req_height;
                pending_parent_start_leaf <= parent_req_start_leaf;
                pending_parent_valid <= 1'b1;
            end
            if (parent_rsp_valid || parent_rsp_error)
                pending_parent_valid <= 1'b0;
        end
    end

    micro_hbs_treehash_min #(.TREE_HEIGHT(TREE_HEIGHT)) treehash_min (
        .clk,
        .rst_n,
        .start,
        .ready,
        .target_leaf,
        .leaf_valid,
        .leaf_ready,
        .leaf_index,
        .leaf_value,
        .parent_req_valid,
        .parent_req_ready,
        .parent_req_height,
        .parent_req_start_leaf,
        .parent_req_left,
        .parent_req_right,
        .parent_rsp_valid,
        .parent_rsp_value,
        .parent_rsp_error,
        .auth_valid,
        .auth_level,
        .auth_node,
        .root_valid,
        .root,
        .busy,
        .error(tree_error),
        .error_code(tree_error_code),
        .accepted_leaves,
        .parent_hashes,
        .peak_stack_nodes
    );

    micro_hbs_treehash_cache_store #(
        .TREE_HEIGHT(TREE_HEIGHT),
        .CACHE_MODE(CACHE_MODE),
        .SUBTREE_HEIGHT(SUBTREE_HEIGHT)
    ) cache_store (
        .clk,
        .rst_n,
        .clear(cache_clear),
        .store_valid(cache_store_leaf || cache_store_parent),
        .store_height(cache_store_leaf ? 8'd0 : pending_parent_height),
        .store_start_leaf(cache_store_leaf ? leaf_index : pending_parent_start_leaf),
        .store_value(cache_store_leaf ? leaf_value : parent_rsp_value),
        .lookup_valid(cache_lookup_valid),
        .lookup_ready(cache_lookup_ready),
        .lookup_height(cache_lookup_height),
        .lookup_start_leaf(cache_lookup_start_leaf),
        .lookup_rsp_valid(cache_rsp_valid),
        .lookup_hit(cache_hit),
        .lookup_value(cache_value),
        .bounds_error(cache_bounds_error),
        .error(cache_error),
        .error_code(cache_error_code),
        .cache_writes,
        .retained_nodes(cache_retained_nodes),
        .capacity_nodes(cache_capacity_nodes)
    );
endmodule

`default_nettype wire
