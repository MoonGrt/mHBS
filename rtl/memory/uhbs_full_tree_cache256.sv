`timescale 1ns/1ps
`default_nettype none

// Complete height-10 Merkle tree cache.  Tree identities are lowered by the
// compiler to level-order addresses 0..2046.  A four-entry write collector
// turns simultaneous results from two equal hash lanes into the single BRAM
// write used by the cache.  The other port remains available for prefetch.
//
// The array is intentionally neither reset nor cleared.  A single committed
// bit makes stale words unreachable and avoids a 2047-bit validity vector.
module uhbs_full_tree_cache256 #(
    parameter integer TREE_NODES = 2047
) (
    input  wire          clk,
    input  wire          rst_n,

    input  wire          build_start,
    output wire          build_ready,
    input  wire          build_abort,
    input  wire          build_commit,
    output logic         cache_valid,
    output logic         build_active,

    input  wire          store0_valid,
    input  wire          store0_tree_node,
    input  wire [10:0]   store0_address,
    input  wire [255:0]  store0_data,
    input  wire          store1_valid,
    input  wire          store1_tree_node,
    input  wire [10:0]   store1_address,
    input  wire [255:0]  store1_data,
    output wire          store_ready,

    input  wire          lookup_valid,
    output wire          lookup_ready,
    input  wire [10:0]   lookup_address,
    input  wire          lookup_allow_uncommitted,
    output logic         lookup_rsp_valid,
    output logic         lookup_hit,
    output logic [255:0] lookup_data,

    output logic         error,
    output logic [15:0]  error_code,
    output logic [11:0]  tree_writes,
    output wire [2:0]    queued_writes
);
    localparam logic [15:0] ERR_STORE_RANGE  = 16'h2401;
    localparam logic [15:0] ERR_LOOKUP_RANGE = 16'h2402;
    localparam logic [15:0] ERR_QUEUE_FULL   = 16'h2403;
    localparam logic [15:0] ERR_COMMIT_EARLY = 16'h2404;
    localparam logic [15:0] ERR_BUILD_BUSY   = 16'h2405;

    (* ram_style = "block" *) logic [255:0] node_memory [0:TREE_NODES-1];

    logic [10:0]  fifo_address [0:3];
    logic [255:0] fifo_data [0:3];
    logic         fifo_tree [0:3];
    logic [1:0]   fifo_head, fifo_tail;
    logic [2:0]   fifo_count;
    logic         read_pending;
    logic         read_authorized;
    logic [255:0] memory_read_data;

    wire store0_in_range = store0_address < TREE_NODES;
    wire store1_in_range = store1_address < TREE_NODES;
    wire lookup_in_range = lookup_address < TREE_NODES;
    wire dequeue = fifo_count != 0;
    wire stores_requested = store0_valid || store1_valid;
    wire lookup_accept = lookup_valid && lookup_ready;

    assign build_ready = !build_active && fifo_count == 0 && !read_pending;
    // Four entries plus one dequeue per cycle.  The conservative threshold
    // accepts any possible two-lane completion without partial acceptance.
    // Ready is an advance reservation for a possible two-result completion.
    // It therefore must not depend on valid, which is asserted one cycle after
    // the producer observes ready.
    assign store_ready = build_active && fifo_count <= 2;
    assign lookup_ready = !read_pending;
    assign queued_writes = fifo_count;

    initial begin
        if (TREE_NODES != 2047)
            $error("full stateful tree cache requires 2047 nodes");
    end

    // One memory write and one independent synchronous read infer a simple
    // dual-port block RAM.  Wide data registers are deliberately not reset.
    always_ff @(posedge clk) begin
        if (dequeue)
            node_memory[fifo_address[fifo_head]] <= fifo_data[fifo_head];
        if (lookup_accept && lookup_in_range)
            memory_read_data <= node_memory[lookup_address];
    end

    always_ff @(posedge clk or negedge rst_n) begin : control
        logic [2:0] next_count;
        logic [1:0] next_tail;
        if (!rst_n) begin
            cache_valid <= 1'b0;
            build_active <= 1'b0;
            fifo_head <= '0;
            fifo_tail <= '0;
            fifo_count <= '0;
            read_pending <= 1'b0;
            read_authorized <= 1'b0;
            lookup_rsp_valid <= 1'b0;
            lookup_hit <= 1'b0;
            lookup_data <= '0;
            error <= 1'b0;
            error_code <= '0;
            tree_writes <= '0;
        end else begin
            lookup_rsp_valid <= 1'b0;

            if (read_pending) begin
                lookup_rsp_valid <= 1'b1;
                lookup_hit <= read_authorized;
                lookup_data <= read_authorized ? memory_read_data : 256'b0;
                read_pending <= 1'b0;
            end

            if (lookup_accept) begin
                read_pending <= 1'b1;
                read_authorized <= lookup_in_range
                    && (cache_valid || (build_active
                        && lookup_allow_uncommitted));
                if (!lookup_in_range) begin
                    error <= 1'b1;
                    if (!error)
                        error_code <= ERR_LOOKUP_RANGE;
                end
            end

            if (build_abort) begin
                cache_valid <= 1'b0;
                build_active <= 1'b0;
                fifo_head <= '0;
                fifo_tail <= '0;
                fifo_count <= '0;
                tree_writes <= '0;
                read_pending <= 1'b0;
            end else begin
                if (build_start) begin
                    if (!build_ready) begin
                        error <= 1'b1;
                        if (!error)
                            error_code <= ERR_BUILD_BUSY;
                    end else begin
                        cache_valid <= 1'b0;
                        build_active <= 1'b1;
                        tree_writes <= '0;
                        error <= 1'b0;
                        error_code <= '0;
                    end
                end

                next_count = fifo_count;
                next_tail = fifo_tail;
                if (dequeue) begin
                    fifo_head <= fifo_head + 1'b1;
                    next_count = next_count - 1'b1;
                    if (fifo_tree[fifo_head])
                        tree_writes <= tree_writes + 1'b1;
                end

                if (stores_requested) begin
                    if (!store_ready) begin
                        error <= 1'b1;
                        if (!error)
                            error_code <= ERR_QUEUE_FULL;
                    end else begin
                        if (store0_valid) begin
                            if (!store0_in_range) begin
                                error <= 1'b1;
                                if (!error)
                                    error_code <= ERR_STORE_RANGE;
                            end else begin
                                fifo_address[next_tail] <= store0_address;
                                fifo_data[next_tail] <= store0_data;
                                fifo_tree[next_tail] <= store0_tree_node;
                                next_tail = next_tail + 1'b1;
                                next_count = next_count + 1'b1;
                            end
                        end
                        if (store1_valid) begin
                            if (!store1_in_range) begin
                                error <= 1'b1;
                                if (!error)
                                    error_code <= ERR_STORE_RANGE;
                            end else begin
                                fifo_address[next_tail] <= store1_address;
                                fifo_data[next_tail] <= store1_data;
                                fifo_tree[next_tail] <= store1_tree_node;
                                next_tail = next_tail + 1'b1;
                                next_count = next_count + 1'b1;
                            end
                        end
                        fifo_tail <= next_tail;
                    end
                end
                fifo_count <= next_count;

                if (build_commit) begin
                    if (build_active && fifo_count == 0
                        && tree_writes == TREE_NODES) begin
                        cache_valid <= 1'b1;
                        build_active <= 1'b0;
                    end else begin
                        cache_valid <= 1'b0;
                        error <= 1'b1;
                        if (!error)
                            error_code <= ERR_COMMIT_EARLY;
                    end
                end
            end
        end
    end
endmodule

`default_nettype wire
