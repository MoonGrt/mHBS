`timescale 1ns/1ps
`default_nettype none

// Warm active-subtree TreeHash cache.
//
// The permanent upper region stores every node at height >= WINDOW_HEIGHT.
// The active region stores nodes below WINDOW_HEIGHT only for one aligned
// 2**WINDOW_HEIGHT-leaf window.  The window root is in the upper region, so it
// is not duplicated.  For TREE_HEIGHT=10/WINDOW_HEIGHT=4 this is exactly
// 127 upper + 30 active nodes = 157 nodes = 5,024 logical bytes.
//
// activate(target_leaf) is the only window-level control operation.  The
// aligned base is derived internally and activation is accepted only while the
// owning job is idle and no lookup response is in flight.
// store_* is intended to be driven by internal TreeHash node-generation events,
// not by software as a per-level task interface.
module micro_hbs_treehash_warm_active_cache #(
    parameter integer TREE_HEIGHT = 10,
    parameter integer WINDOW_HEIGHT = 4
) (
    input  wire         clk,
    input  wire         rst_n,
    input  wire         clear_all,
    input  wire         job_busy,

    input  wire         activate_valid,
    output wire         activate_ready,
    input  wire [15:0]  activate_target_leaf,
    output logic        active_window_valid,
    output logic [15:0] active_window_base,

    input  wire         store_valid,
    input  wire [7:0]   store_height,
    input  wire [15:0]  store_start_leaf,
    input  wire [255:0] store_value,

    input  wire         lookup_valid,
    output wire         lookup_ready,
    input  wire [7:0]   lookup_height,
    input  wire [15:0]  lookup_start_leaf,
    output logic        lookup_rsp_valid,
    output logic        lookup_hit,
    output wire [255:0] lookup_value,
    output logic        bounds_error,

    output wire         busy,
    output logic        error,
    output logic [15:0] error_code,
    output logic [31:0] upper_writes,
    output logic [31:0] lower_writes,
    output logic [31:0] upper_retained_nodes,
    output logic [31:0] lower_retained_nodes,
    output logic [31:0] lookup_requests,
    output logic [31:0] cache_hits,
    output logic [31:0] cache_misses,
    output logic [31:0] window_switches,
    output wire [31:0]  upper_capacity_nodes,
    output wire [31:0]  lower_capacity_nodes,
    output wire [31:0]  total_capacity_nodes,
    output wire [31:0]  logical_capacity_bytes
);
    localparam integer LEAF_COUNT = (1 << TREE_HEIGHT);
    localparam integer WINDOW_LEAVES = (1 << WINDOW_HEIGHT);
    localparam logic [15:0] WINDOW_MASK = 16'(WINDOW_LEAVES - 1);
    localparam integer UPPER_NODE_COUNT =
        (1 << (TREE_HEIGHT - WINDOW_HEIGHT + 1)) - 1;
    localparam integer LOWER_NODE_COUNT = (1 << (WINDOW_HEIGHT + 1)) - 2;
    localparam integer TOTAL_NODE_COUNT = UPPER_NODE_COUNT + LOWER_NODE_COUNT;
    localparam integer UPPER_INDEX_WIDTH = (UPPER_NODE_COUNT <= 2)
        ? 1 : $clog2(UPPER_NODE_COUNT);
    localparam integer LOWER_INDEX_WIDTH = (LOWER_NODE_COUNT <= 2)
        ? 1 : $clog2(LOWER_NODE_COUNT);

    localparam logic [15:0] ERR_ACTIVATE_TARGET = 16'h0231;
    localparam logic [15:0] ERR_ACTIVATE_BUSY = 16'h0232;
    localparam logic [15:0] ERR_STORE_IDENTITY = 16'h0233;
    localparam logic [15:0] ERR_LOOKUP_IDENTITY = 16'h0234;

    (* ram_style = "block" *) logic [255:0] upper_memory [0:UPPER_NODE_COUNT-1];
    // Thirty 256-bit words are normally more efficient as distributed RAM.
    (* ram_style = "distributed" *) logic [255:0] lower_memory [0:LOWER_NODE_COUNT-1];
    logic [UPPER_NODE_COUNT-1:0] upper_valid;
    logic [LOWER_NODE_COUNT-1:0] lower_valid;
    logic [255:0] upper_read_data;
    logic [255:0] lower_read_data;
    logic lookup_response_upper;
    logic lookup_inflight;

    wire store_identity_ok;
    wire lookup_identity_ok;
    wire store_is_upper;
    wire store_is_active_lower;
    wire lookup_is_upper;
    wire lookup_is_active_lower;
    wire upper_store_commit;
    wire lower_store_commit;
    wire upper_lookup_read;
    wire lower_lookup_read;
    wire [UPPER_INDEX_WIDTH-1:0] upper_store_index;
    wire [UPPER_INDEX_WIDTH-1:0] upper_lookup_index;
    wire [LOWER_INDEX_WIDTH-1:0] lower_store_index;
    wire [LOWER_INDEX_WIDTH-1:0] lower_lookup_index;
    wire [15:0] activation_window_base;

    function automatic logic node_identity_valid;
        input logic [7:0] height_value;
        input logic [15:0] start_value;
        integer alignment_mask;
        begin
            if (height_value > TREE_HEIGHT) begin
                node_identity_valid = 1'b0;
            end else begin
                alignment_mask = (1 << height_value) - 1;
                node_identity_valid = (start_value < LEAF_COUNT)
                    && ((start_value & alignment_mask) == 0);
            end
        end
    endfunction

    function automatic logic activation_target_valid;
        input logic [15:0] target_value;
        begin
            activation_target_valid = (target_value < LEAF_COUNT);
        end
    endfunction

    function automatic logic inside_active_window;
        input logic [15:0] start_value;
        begin
            inside_active_window = active_window_valid
                && (start_value >= active_window_base)
                && ({1'b0, start_value}
                    < ({1'b0, active_window_base} + WINDOW_LEAVES));
        end
    endfunction

    function automatic integer upper_index_fn;
        input logic [7:0] height_value;
        input logic [15:0] start_value;
        integer level_offset;
        begin
            if (!node_identity_valid(height_value, start_value)
                || height_value < WINDOW_HEIGHT) begin
                upper_index_fn = 0;
            end else begin
                level_offset = (1 << (TREE_HEIGHT - WINDOW_HEIGHT + 1))
                    - (1 << (TREE_HEIGHT - height_value + 1));
                upper_index_fn = level_offset + (start_value >> height_value);
            end
        end
    endfunction

    function automatic integer lower_index_fn;
        input logic [7:0] height_value;
        input logic [15:0] start_value;
        integer level_offset;
        begin
            if (!node_identity_valid(height_value, start_value)
                || height_value >= WINDOW_HEIGHT
                || !inside_active_window(start_value)) begin
                lower_index_fn = 0;
            end else begin
                level_offset = (1 << (WINDOW_HEIGHT + 1))
                    - (1 << (WINDOW_HEIGHT - height_value + 1));
                lower_index_fn = level_offset
                    + ((start_value - active_window_base) >> height_value);
            end
        end
    endfunction

    assign upper_capacity_nodes = UPPER_NODE_COUNT;
    assign lower_capacity_nodes = LOWER_NODE_COUNT;
    assign total_capacity_nodes = TOTAL_NODE_COUNT;
    assign logical_capacity_bytes = TOTAL_NODE_COUNT * 32;
    assign busy = job_busy || lookup_inflight;

    // Activation has priority over a new lookup, but never over an
    // already accepted lookup response or an internal node store.
    assign activate_ready = !clear_all && !job_busy && !lookup_inflight
        && !store_valid;
    assign lookup_ready = !clear_all && !activate_valid;
    assign activation_window_base = activate_target_leaf & ~WINDOW_MASK;

    assign store_identity_ok = node_identity_valid(store_height, store_start_leaf);
    assign lookup_identity_ok = node_identity_valid(lookup_height, lookup_start_leaf);
    assign store_is_upper = store_identity_ok && (store_height >= WINDOW_HEIGHT);
    assign store_is_active_lower = store_identity_ok
        && (store_height < WINDOW_HEIGHT) && inside_active_window(store_start_leaf);
    assign lookup_is_upper = lookup_identity_ok && (lookup_height >= WINDOW_HEIGHT);
    assign lookup_is_active_lower = lookup_identity_ok
        && (lookup_height < WINDOW_HEIGHT) && inside_active_window(lookup_start_leaf);

    assign upper_store_index = upper_index_fn(store_height, store_start_leaf);
    assign upper_lookup_index = upper_index_fn(lookup_height, lookup_start_leaf);
    assign lower_store_index = lower_index_fn(store_height, store_start_leaf);
    assign lower_lookup_index = lower_index_fn(lookup_height, lookup_start_leaf);

    assign upper_store_commit = store_valid && !clear_all && store_is_upper;
    assign lower_store_commit = store_valid && !clear_all && store_is_active_lower;
    assign upper_lookup_read = lookup_valid && lookup_ready && lookup_is_upper;
    assign lower_lookup_read = lookup_valid && lookup_ready && lookup_is_active_lower;
    assign lookup_value = lookup_hit
        ? (lookup_response_upper ? upper_read_data : lower_read_data) : 256'b0;

    initial begin
        if (TREE_HEIGHT < 1 || TREE_HEIGHT > 15)
            $error("TREE_HEIGHT must be in 1..15");
        if (WINDOW_HEIGHT < 1 || WINDOW_HEIGHT > TREE_HEIGHT)
            $error("WINDOW_HEIGHT must be in 1..TREE_HEIGHT");
    end

    // Reset-free data arrays retain BRAM/LUTRAM inference.  Valid metadata is
    // the sole authority for whether a physical word may be exposed.
    always_ff @(posedge clk) begin
        if (upper_store_commit)
            upper_memory[upper_store_index] <= store_value;
        if (lower_store_commit)
            lower_memory[lower_store_index] <= store_value;
        if (upper_lookup_read)
            upper_read_data <= upper_memory[upper_lookup_index];
        if (lower_lookup_read)
            lower_read_data <= lower_memory[lower_lookup_index];
    end

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            upper_valid <= '0;
            lower_valid <= '0;
            active_window_valid <= 1'b0;
            active_window_base <= '0;
            lookup_rsp_valid <= 1'b0;
            lookup_hit <= 1'b0;
            lookup_response_upper <= 1'b0;
            lookup_inflight <= 1'b0;
            bounds_error <= 1'b0;
            error <= 1'b0;
            error_code <= '0;
            upper_writes <= '0;
            lower_writes <= '0;
            upper_retained_nodes <= '0;
            lower_retained_nodes <= '0;
            lookup_requests <= '0;
            cache_hits <= '0;
            cache_misses <= '0;
            window_switches <= '0;
        end else begin
            lookup_rsp_valid <= 1'b0;
            lookup_inflight <= lookup_valid && lookup_ready;
            bounds_error <= 1'b0;

            if (clear_all) begin
                upper_valid <= '0;
                lower_valid <= '0;
                active_window_valid <= 1'b0;
                active_window_base <= '0;
                lookup_hit <= 1'b0;
                lookup_inflight <= 1'b0;
                error <= 1'b0;
                error_code <= '0;
                upper_writes <= '0;
                lower_writes <= '0;
                upper_retained_nodes <= '0;
                lower_retained_nodes <= '0;
                lookup_requests <= '0;
                cache_hits <= '0;
                cache_misses <= '0;
                window_switches <= '0;
            end else begin
                if (activate_valid) begin
                    if (!activate_ready) begin
                        error <= 1'b1;
                        if (!error)
                            error_code <= ERR_ACTIVATE_BUSY;
                    end else if (!activation_target_valid(activate_target_leaf)) begin
                        error <= 1'b1;
                        if (!error)
                            error_code <= ERR_ACTIVATE_TARGET;
                    end else begin
                        active_window_valid <= 1'b1;
                        active_window_base <= activation_window_base;
                        lower_valid <= '0;
                        lower_retained_nodes <= '0;
                        window_switches <= window_switches + 1'b1;
                        // A valid idle selection is also an explicit recovery
                        // boundary for prior configuration/protocol errors.
                        error <= 1'b0;
                        error_code <= '0;
                    end
                end

                if (store_valid) begin
                    if (!store_identity_ok) begin
                        error <= 1'b1;
                        if (!error)
                            error_code <= ERR_STORE_IDENTITY;
                    end else if (store_is_upper) begin
                        upper_valid[upper_store_index] <= 1'b1;
                        upper_writes <= upper_writes + 1'b1;
                        if (!upper_valid[upper_store_index])
                            upper_retained_nodes <= upper_retained_nodes + 1'b1;
                    end else if (store_is_active_lower) begin
                        lower_valid[lower_store_index] <= 1'b1;
                        lower_writes <= lower_writes + 1'b1;
                        if (!lower_valid[lower_store_index])
                            lower_retained_nodes <= lower_retained_nodes + 1'b1;
                    end
                    // A valid lower node outside the active window is ignored.
                end

                if (lookup_valid && lookup_ready) begin
                    lookup_rsp_valid <= 1'b1;
                    lookup_requests <= lookup_requests + 1'b1;
                    if (!lookup_identity_ok) begin
                        lookup_hit <= 1'b0;
                        lookup_response_upper <= 1'b0;
                        bounds_error <= 1'b1;
                        error <= 1'b1;
                        if (!error)
                            error_code <= ERR_LOOKUP_IDENTITY;
                    end else if (lookup_is_upper) begin
                        lookup_response_upper <= 1'b1;
                        lookup_hit <= upper_valid[upper_lookup_index];
                        if (upper_valid[upper_lookup_index])
                            cache_hits <= cache_hits + 1'b1;
                        else
                            cache_misses <= cache_misses + 1'b1;
                    end else if (lookup_is_active_lower) begin
                        lookup_response_upper <= 1'b0;
                        lookup_hit <= lower_valid[lower_lookup_index];
                        if (lower_valid[lower_lookup_index])
                            cache_hits <= cache_hits + 1'b1;
                        else
                            cache_misses <= cache_misses + 1'b1;
                    end else begin
                        lookup_response_upper <= 1'b0;
                        lookup_hit <= 1'b0;
                        cache_misses <= cache_misses + 1'b1;
                    end
                end
            end
        end
    end
endmodule

`default_nettype wire
