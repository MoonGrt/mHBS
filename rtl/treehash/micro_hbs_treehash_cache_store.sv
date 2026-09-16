`timescale 1ns/1ps
`default_nettype none

// Fixed-capacity TreeHash node cache.  CACHE_MODE is a synthesis-time choice:
//   1: SUBTREE_CACHE, retain nodes whose height is at least SUBTREE_HEIGHT.
//   2: FULL_CACHE, retain every node, including leaves and the root.
//
// Nodes use the same identity as micro_hbs_treehash_min:
// (height, start_leaf).  Legal start_leaf values are aligned to 2**height.
// Invalid stores are discarded and invalid lookups return zero with hit low.
module micro_hbs_treehash_cache_store #(
    parameter integer TREE_HEIGHT = 10,
    parameter integer CACHE_MODE = 1,
    parameter integer SUBTREE_HEIGHT = 4
) (
    input  wire         clk,
    input  wire         rst_n,
    input  wire         clear,

    input  wire         store_valid,
    input  wire [7:0]   store_height,
    input  wire [15:0]  store_start_leaf,
    input  wire [255:0] store_value,

    input  wire         lookup_valid,
    output logic        lookup_ready,
    input  wire [7:0]   lookup_height,
    input  wire [15:0]  lookup_start_leaf,
    output logic        lookup_rsp_valid,
    output logic        lookup_hit,
    output logic [255:0] lookup_value,
    output logic        bounds_error,

    output logic        error,
    output logic [15:0] error_code,
    output logic [31:0] cache_writes,
    output logic [31:0] retained_nodes,
    output wire [31:0]  capacity_nodes
);
    localparam integer MODE_SUBTREE_CACHE = 1;
    localparam integer MODE_FULL_CACHE = 2;
    localparam integer LEAF_COUNT = (1 << TREE_HEIGHT);
    localparam integer FULL_NODE_COUNT = (1 << (TREE_HEIGHT + 1)) - 1;
    localparam integer SUBTREE_NODE_COUNT =
        (1 << (TREE_HEIGHT - SUBTREE_HEIGHT + 1)) - 1;
    localparam integer CACHE_NODE_COUNT =
        (CACHE_MODE == MODE_FULL_CACHE) ? FULL_NODE_COUNT : SUBTREE_NODE_COUNT;
    localparam integer INDEX_WIDTH = (CACHE_NODE_COUNT <= 2)
        ? 1 : $clog2(CACHE_NODE_COUNT);

    localparam logic [15:0] ERR_STORE_IDENTITY = 16'h0211;
    localparam logic [15:0] ERR_LOOKUP_IDENTITY = 16'h0212;

    (* ram_style = "block" *) logic [255:0] node_memory [0:CACHE_NODE_COUNT-1];
    logic [CACHE_NODE_COUNT-1:0] node_valid;
    logic [255:0] memory_read_data;
    wire store_identity_ok;
    wire lookup_identity_ok;
    wire store_commit;
    wire lookup_memory_read;
    wire [INDEX_WIDTH-1:0] store_memory_index;
    wire [INDEX_WIDTH-1:0] lookup_memory_index;
    function automatic logic identity_valid;
        input logic [7:0] height_value;
        input logic [15:0] start_value;
        integer alignment_mask;
        begin
            if (height_value > TREE_HEIGHT) begin
                identity_valid = 1'b0;
            end else begin
                alignment_mask = (1 << height_value) - 1;
                identity_valid = (start_value < LEAF_COUNT)
                    && ((start_value & alignment_mask) == 0);
            end
        end
    endfunction

    function automatic logic retained_by_mode;
        input logic [7:0] height_value;
        begin
            retained_by_mode = (CACHE_MODE == MODE_FULL_CACHE)
                || (height_value >= SUBTREE_HEIGHT);
        end
    endfunction

    function automatic integer cache_index;
        input logic [7:0] height_value;
        input logic [15:0] start_value;
        integer level_offset;
        begin
            if (!identity_valid(height_value, start_value)
                || !retained_by_mode(height_value)) begin
                cache_index = 0;
            end else if (CACHE_MODE == MODE_FULL_CACHE) begin
                level_offset = (1 << (TREE_HEIGHT + 1))
                    - (1 << (TREE_HEIGHT - height_value + 1));
                cache_index = level_offset + (start_value >> height_value);
            end else begin
                level_offset = (1 << (TREE_HEIGHT - SUBTREE_HEIGHT + 1))
                    - (1 << (TREE_HEIGHT - height_value + 1));
                cache_index = level_offset + (start_value >> height_value);
            end
        end
    endfunction

    assign capacity_nodes = CACHE_NODE_COUNT;
    assign lookup_ready = !clear;
    assign store_identity_ok = identity_valid(store_height, store_start_leaf);
    assign lookup_identity_ok = identity_valid(lookup_height, lookup_start_leaf);
    assign store_commit = store_valid && !clear && store_identity_ok
        && retained_by_mode(store_height);
    assign lookup_memory_read = lookup_valid && lookup_ready && lookup_identity_ok
        && retained_by_mode(lookup_height);
    assign store_memory_index = cache_index(store_height, store_start_leaf);
    assign lookup_memory_index = cache_index(lookup_height, lookup_start_leaf);
    assign lookup_value = lookup_hit ? memory_read_data : 256'b0;

    initial begin
        if (TREE_HEIGHT < 1 || TREE_HEIGHT > 15)
            $error("TREE_HEIGHT must be in 1..15");
        if (CACHE_MODE != MODE_SUBTREE_CACHE && CACHE_MODE != MODE_FULL_CACHE)
            $error("CACHE_MODE must be SUBTREE_CACHE(1) or FULL_CACHE(2)");
        if (SUBTREE_HEIGHT < 1 || SUBTREE_HEIGHT > TREE_HEIGHT)
            $error("SUBTREE_HEIGHT must be in 1..TREE_HEIGHT");
    end

    // The node array intentionally has no reset so it can infer block RAM.
    // node_valid masks every unread or cleared word from the external port.
    always_ff @(posedge clk) begin
        if (store_commit)
            node_memory[store_memory_index] <= store_value;
        if (lookup_memory_read)
            memory_read_data <= node_memory[lookup_memory_index];
    end

    always_ff @(posedge clk or negedge rst_n) begin : cache_process
        if (!rst_n) begin
            node_valid <= '0;
            lookup_rsp_valid <= 1'b0;
            lookup_hit <= 1'b0;
            bounds_error <= 1'b0;
            error <= 1'b0;
            error_code <= '0;
            cache_writes <= '0;
            retained_nodes <= '0;
        end else begin
            lookup_rsp_valid <= 1'b0;
            bounds_error <= 1'b0;

            if (clear) begin
                node_valid <= '0;
                lookup_hit <= 1'b0;
                error <= 1'b0;
                error_code <= '0;
                cache_writes <= '0;
                retained_nodes <= '0;
            end else begin
                if (store_valid) begin
                    if (!store_identity_ok) begin
                        // Fail closed: never index memory with an invalid identity.
                        error <= 1'b1;
                        if (!error)
                            error_code <= ERR_STORE_IDENTITY;
                    end else if (retained_by_mode(store_height)) begin
                        node_valid[store_memory_index] <= 1'b1;
                        cache_writes <= cache_writes + 1'b1;
                        if (!node_valid[store_memory_index])
                            retained_nodes <= retained_nodes + 1'b1;
                    end
                end

                if (lookup_valid && lookup_ready) begin
                    lookup_rsp_valid <= 1'b1;
                    if (!lookup_identity_ok) begin
                        // An invalid query cannot expose a stale or aliased node.
                        lookup_hit <= 1'b0;
                        bounds_error <= 1'b1;
                        error <= 1'b1;
                        if (!error)
                            error_code <= ERR_LOOKUP_IDENTITY;
                    end else if (!retained_by_mode(lookup_height)) begin
                        // A legal node outside the selected policy is a clean miss.
                        lookup_hit <= 1'b0;
                    end else begin
                        lookup_hit <= node_valid[lookup_memory_index];
                    end
                end
            end
        end
    end
endmodule

`default_nettype wire
