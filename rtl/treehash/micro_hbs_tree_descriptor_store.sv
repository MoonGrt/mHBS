`timescale 1ns/1ps
`default_nettype none

// Algorithm-independent, versioned static TreeHash descriptor table.
//
// Fixed 128-bit descriptor format:
//   [127:120] format_version
//   [119:112] tree_height       (1..15, matching the generic TreeHash core)
//   [111:96]  node_bytes        (8, 16, 24, or 32)
//   [95:80]   parent_layout_id  (opaque layout-table reference)
//   [79:72]   storage_mode      (0 MIN, 1 SUBTREE, 2 FULL)
//   [71:64]   subtree_height
//   [63:56]   window_height
//   [55:0]    reserved          (must be zero)
//
// MIN and FULL do not consume subtree/window parameters and require both to
// be zero.  SUBTREE requires subtree_height in 1..tree_height.  A zero
// window_height selects an upper-only subtree cache; a nonzero value selects
// an active lower window and must not exceed subtree_height.  These are
// storage capabilities, not LMS/XMSS/SLH or task identifiers.
//
// The host may load or overwrite descriptors only while the engine is IDLE.
// Runtime logic can only issue bounded lookups.  The single response register
// holds its complete tuple stable under backpressure and masks every error or
// uninitialized entry to zero.
module micro_hbs_tree_descriptor_store #(
    parameter integer DESCRIPTOR_COUNT = 16,
    parameter logic [7:0] FORMAT_VERSION = 8'h01
) (
    input  wire          clk,
    input  wire          rst_n,
    input  wire          engine_busy,

    input  wire          cfg_valid,
    output wire          cfg_ready,
    input  wire [15:0]   cfg_descriptor_id,
    input  wire [127:0]  cfg_descriptor,
    output logic         cfg_error,
    output logic [15:0]  cfg_error_code,

    input  wire          lookup_valid,
    output wire          lookup_ready,
    input  wire [15:0]   lookup_descriptor_id,
    output logic         lookup_rsp_valid,
    input  wire          lookup_rsp_ready,
    output logic         lookup_rsp_error,
    output logic [15:0]  lookup_rsp_error_code,
    output logic [127:0] lookup_descriptor,

    output wire [7:0]    descriptor_format_version,
    output wire [7:0]    descriptor_tree_height,
    output wire [15:0]   descriptor_node_bytes,
    output wire [15:0]   descriptor_parent_layout_id,
    output wire [7:0]    descriptor_storage_mode,
    output wire [7:0]    descriptor_subtree_height,
    output wire [7:0]    descriptor_window_height,
    output wire [55:0]   descriptor_reserved,

    output wire          image_locked,
    output wire [31:0]   descriptor_capacity,
    output logic [31:0]  configured_count,
    output logic [31:0]  accepted_loads,
    output logic [31:0]  rejected_loads,
    output logic [31:0]  host_writes_busy,
    output logic [31:0]  lookup_requests,
    output logic [31:0]  lookup_errors
);
    localparam integer INDEX_WIDTH = (DESCRIPTOR_COUNT <= 2)
        ? 1 : $clog2(DESCRIPTOR_COUNT);
    localparam logic [16:0] DESCRIPTOR_COUNT_EXT = 17'(DESCRIPTOR_COUNT);

    localparam logic [7:0] MODE_TREEHASH_MIN = 8'd0;
    localparam logic [7:0] MODE_SUBTREE_CACHE = 8'd1;
    localparam logic [7:0] MODE_FULL_CACHE = 8'd2;

    localparam logic [15:0] ERR_CFG_BUSY          = 16'h0901;
    localparam logic [15:0] ERR_CFG_BOUNDS        = 16'h0902;
    localparam logic [15:0] ERR_CFG_CONFLICT      = 16'h0903;
    localparam logic [15:0] ERR_FORMAT_VERSION    = 16'h0904;
    localparam logic [15:0] ERR_TREE_HEIGHT       = 16'h0905;
    localparam logic [15:0] ERR_NODE_BYTES        = 16'h0906;
    localparam logic [15:0] ERR_STORAGE_MODE      = 16'h0907;
    localparam logic [15:0] ERR_MODE_COMBINATION  = 16'h0908;
    localparam logic [15:0] ERR_RESERVED          = 16'h0909;
    localparam logic [15:0] ERR_LOOKUP_BOUNDS     = 16'h090a;
    localparam logic [15:0] ERR_UNINITIALIZED     = 16'h090b;

    (* ram_style = "distributed" *) logic [127:0]
        descriptor_memory [0:DESCRIPTOR_COUNT-1];
    logic [DESCRIPTOR_COUNT-1:0] descriptor_configured;

    wire cfg_id_in_range;
    wire lookup_id_in_range;
    wire cfg_tree_height_valid;
    wire cfg_node_bytes_valid;
    wire cfg_storage_mode_valid;
    logic cfg_mode_combination_valid;
    wire cfg_descriptor_valid;
    wire cfg_write_commit;
    wire lookup_commit;
    wire [INDEX_WIDTH-1:0] cfg_memory_index;
    wire [INDEX_WIDTH-1:0] lookup_memory_index;

    wire [7:0] cfg_tree_height;
    wire [15:0] cfg_node_bytes;
    wire [7:0] cfg_storage_mode;
    wire [7:0] cfg_subtree_height;
    wire [7:0] cfg_window_height;
    wire [55:0] cfg_reserved;

    assign cfg_tree_height = cfg_descriptor[119:112];
    assign cfg_node_bytes = cfg_descriptor[111:96];
    assign cfg_storage_mode = cfg_descriptor[79:72];
    assign cfg_subtree_height = cfg_descriptor[71:64];
    assign cfg_window_height = cfg_descriptor[63:56];
    assign cfg_reserved = cfg_descriptor[55:0];

    assign image_locked = engine_busy;
    assign descriptor_capacity = DESCRIPTOR_COUNT;

    // A lookup request has priority over an IDLE host write.  A pending
    // response blocks another lookup until its consumer accepts it.
    assign cfg_ready = rst_n && !engine_busy && !lookup_valid;
    assign lookup_ready = rst_n
        && (!lookup_rsp_valid || lookup_rsp_ready);

    assign cfg_id_in_range = ({1'b0, cfg_descriptor_id}
        < DESCRIPTOR_COUNT_EXT);
    assign lookup_id_in_range = ({1'b0, lookup_descriptor_id}
        < DESCRIPTOR_COUNT_EXT);
    assign cfg_memory_index = cfg_descriptor_id[INDEX_WIDTH-1:0];
    assign lookup_memory_index = lookup_descriptor_id[INDEX_WIDTH-1:0];

    assign cfg_tree_height_valid = cfg_tree_height >= 1
        && cfg_tree_height <= 15;
    assign cfg_node_bytes_valid = cfg_node_bytes == 8
        || cfg_node_bytes == 16 || cfg_node_bytes == 24
        || cfg_node_bytes == 32;
    assign cfg_storage_mode_valid = cfg_storage_mode == MODE_TREEHASH_MIN
        || cfg_storage_mode == MODE_SUBTREE_CACHE
        || cfg_storage_mode == MODE_FULL_CACHE;

    always_comb begin
        cfg_mode_combination_valid = 1'b0;
        case (cfg_storage_mode)
            MODE_TREEHASH_MIN, MODE_FULL_CACHE: begin
                cfg_mode_combination_valid = cfg_subtree_height == 0
                    && cfg_window_height == 0;
            end
            MODE_SUBTREE_CACHE: begin
                cfg_mode_combination_valid = cfg_subtree_height >= 1
                    && cfg_subtree_height <= cfg_tree_height
                    && (cfg_window_height == 0
                        || (cfg_window_height >= 1
                            && cfg_window_height <= cfg_subtree_height));
            end
            default: cfg_mode_combination_valid = 1'b0;
        endcase
    end

    assign cfg_descriptor_valid = cfg_descriptor[127:120] == FORMAT_VERSION
        && cfg_tree_height_valid && cfg_node_bytes_valid
        && cfg_storage_mode_valid && cfg_mode_combination_valid
        && cfg_reserved == 0;
    assign cfg_write_commit = cfg_valid && cfg_ready && cfg_id_in_range
        && cfg_descriptor_valid;
    assign lookup_commit = lookup_valid && lookup_ready;

    assign descriptor_format_version = lookup_descriptor[127:120];
    assign descriptor_tree_height = lookup_descriptor[119:112];
    assign descriptor_node_bytes = lookup_descriptor[111:96];
    assign descriptor_parent_layout_id = lookup_descriptor[95:80];
    assign descriptor_storage_mode = lookup_descriptor[79:72];
    assign descriptor_subtree_height = lookup_descriptor[71:64];
    assign descriptor_window_height = lookup_descriptor[63:56];
    assign descriptor_reserved = lookup_descriptor[55:0];

    initial begin
        if (DESCRIPTOR_COUNT < 1 || DESCRIPTOR_COUNT > 65536)
            $error("DESCRIPTOR_COUNT must be in 1..65536");
    end

    // Reset only validity metadata so the data array remains RAM-inferable.
    // Stale physical contents cannot be exposed without a configured bit.
    always_ff @(posedge clk) begin
        if (cfg_write_commit)
            descriptor_memory[cfg_memory_index] <= cfg_descriptor;
    end

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            descriptor_configured <= '0;
            cfg_error <= 1'b0;
            cfg_error_code <= '0;
            lookup_rsp_valid <= 1'b0;
            lookup_rsp_error <= 1'b0;
            lookup_rsp_error_code <= '0;
            lookup_descriptor <= '0;
            configured_count <= '0;
            accepted_loads <= '0;
            rejected_loads <= '0;
            host_writes_busy <= '0;
            lookup_requests <= '0;
            lookup_errors <= '0;
        end else begin
            cfg_error <= 1'b0;
            cfg_error_code <= '0;

            if (lookup_rsp_valid && lookup_rsp_ready) begin
                lookup_rsp_valid <= 1'b0;
                lookup_rsp_error <= 1'b0;
                lookup_rsp_error_code <= '0;
                lookup_descriptor <= '0;
            end

            if (cfg_valid) begin
                if (engine_busy) begin
                    cfg_error <= 1'b1;
                    cfg_error_code <= ERR_CFG_BUSY;
                    rejected_loads <= rejected_loads + 1'b1;
                    host_writes_busy <= host_writes_busy + 1'b1;
                end else if (lookup_valid) begin
                    cfg_error <= 1'b1;
                    cfg_error_code <= ERR_CFG_CONFLICT;
                    rejected_loads <= rejected_loads + 1'b1;
                end else if (!cfg_id_in_range) begin
                    cfg_error <= 1'b1;
                    cfg_error_code <= ERR_CFG_BOUNDS;
                    rejected_loads <= rejected_loads + 1'b1;
                end else if (cfg_descriptor[127:120] != FORMAT_VERSION) begin
                    cfg_error <= 1'b1;
                    cfg_error_code <= ERR_FORMAT_VERSION;
                    rejected_loads <= rejected_loads + 1'b1;
                end else if (!cfg_tree_height_valid) begin
                    cfg_error <= 1'b1;
                    cfg_error_code <= ERR_TREE_HEIGHT;
                    rejected_loads <= rejected_loads + 1'b1;
                end else if (!cfg_node_bytes_valid) begin
                    cfg_error <= 1'b1;
                    cfg_error_code <= ERR_NODE_BYTES;
                    rejected_loads <= rejected_loads + 1'b1;
                end else if (!cfg_storage_mode_valid) begin
                    cfg_error <= 1'b1;
                    cfg_error_code <= ERR_STORAGE_MODE;
                    rejected_loads <= rejected_loads + 1'b1;
                end else if (!cfg_mode_combination_valid) begin
                    cfg_error <= 1'b1;
                    cfg_error_code <= ERR_MODE_COMBINATION;
                    rejected_loads <= rejected_loads + 1'b1;
                end else if (cfg_reserved != 0) begin
                    cfg_error <= 1'b1;
                    cfg_error_code <= ERR_RESERVED;
                    rejected_loads <= rejected_loads + 1'b1;
                end else begin
                    descriptor_configured[cfg_memory_index] <= 1'b1;
                    accepted_loads <= accepted_loads + 1'b1;
                    if (!descriptor_configured[cfg_memory_index])
                        configured_count <= configured_count + 1'b1;
                end
            end

            if (lookup_commit) begin
                lookup_rsp_valid <= 1'b1;
                lookup_requests <= lookup_requests + 1'b1;
                if (!lookup_id_in_range) begin
                    lookup_rsp_error <= 1'b1;
                    lookup_rsp_error_code <= ERR_LOOKUP_BOUNDS;
                    lookup_descriptor <= '0;
                    lookup_errors <= lookup_errors + 1'b1;
                end else if (!descriptor_configured[lookup_memory_index]) begin
                    lookup_rsp_error <= 1'b1;
                    lookup_rsp_error_code <= ERR_UNINITIALIZED;
                    lookup_descriptor <= '0;
                    lookup_errors <= lookup_errors + 1'b1;
                end else begin
                    lookup_rsp_error <= 1'b0;
                    lookup_rsp_error_code <= '0;
                    lookup_descriptor
                        <= descriptor_memory[lookup_memory_index];
                end
            end
        end
    end
endmodule

`default_nettype wire
