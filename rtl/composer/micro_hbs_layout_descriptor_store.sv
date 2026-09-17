`timescale 1ns/1ps
`default_nettype none

// Algorithm-independent, versioned layout-descriptor table.
//
// Fixed 128-bit descriptor format (interpretation belongs to the composer):
//   [127:120] format_version
//   [119:112] capability
//   [111:104] input_mode
//   [103:96]  output_mode
//   [95:80]   flags
//   [79:64]   message_bytes
//   [63:48]   expression_pc
//   [47:40]   expression_tokens
//   [39:32]   source_count
//   [31:16]   scratch_base_word
//   [15:0]    scratch_span_words
//
// capability/input/output values describe generic datapath features; this
// store does not recognize LMS, XMSS, SLH-DSA, or any other algorithm ID.
// Configuration is an initialization operation.  engine_busy locks the image;
// runtime HASH traffic can only perform bounded read lookups.
module micro_hbs_layout_descriptor_store #(
    parameter integer LAYOUT_COUNT = 16,
    parameter logic [7:0] FORMAT_VERSION = 8'h01
) (
    input  wire         clk,
    input  wire         rst_n,
    input  wire         engine_busy,

    input  wire         cfg_valid,
    output wire         cfg_ready,
    input  wire [15:0]  cfg_layout_id,
    input  wire [127:0] cfg_descriptor,
    output logic        cfg_error,
    output logic [15:0] cfg_error_code,

    input  wire         lookup_valid,
    output wire         lookup_ready,
    input  wire [15:0]  lookup_layout_id,
    output logic        lookup_rsp_valid,
    output logic        lookup_rsp_error,
    output logic [15:0] lookup_rsp_error_code,
    output wire [127:0] lookup_descriptor,

    output wire         image_locked,
    output wire [31:0]  layout_capacity,
    output logic [31:0] configured_count,
    output logic [31:0] accepted_loads,
    output logic [31:0] rejected_loads,
    output logic [31:0] host_writes_busy,
    output logic [31:0] lookup_requests,
    output logic [31:0] lookup_errors
);
    localparam integer INDEX_WIDTH = (LAYOUT_COUNT <= 2)
        ? 1 : $clog2(LAYOUT_COUNT);
    localparam logic [16:0] LAYOUT_COUNT_EXT = 17'(LAYOUT_COUNT);

    localparam logic [15:0] ERR_CFG_BUSY = 16'h0102;
    localparam logic [15:0] ERR_CFG_BOUNDS = 16'h0209;
    localparam logic [15:0] ERR_CFG_CONFLICT = 16'h020a;
    localparam logic [15:0] ERR_LOOKUP_BOUNDS = 16'h020b;
    localparam logic [15:0] ERR_UNINITIALIZED = 16'h020c;
    localparam logic [15:0] ERR_FORMAT_VERSION = 16'h020d;

    (* ram_style = "distributed" *) logic [127:0] descriptor_memory [0:LAYOUT_COUNT-1];
    logic [LAYOUT_COUNT-1:0] descriptor_configured;
    logic [127:0] descriptor_read_data;
    logic lookup_success;

    wire cfg_id_in_range;
    wire lookup_id_in_range;
    wire cfg_write_commit;
    wire lookup_read_commit;
    wire [INDEX_WIDTH-1:0] cfg_memory_index;
    wire [INDEX_WIDTH-1:0] lookup_memory_index;

    assign image_locked = engine_busy;
    assign layout_capacity = LAYOUT_COUNT;
    // A runtime lookup has priority over an idle configuration write.  This
    // removes read-during-write ambiguity without adding a request queue.
    assign lookup_ready = rst_n;
    assign cfg_ready = rst_n && !engine_busy && !lookup_valid;
    assign cfg_id_in_range = ({1'b0, cfg_layout_id} < LAYOUT_COUNT_EXT);
    assign lookup_id_in_range = ({1'b0, lookup_layout_id} < LAYOUT_COUNT_EXT);
    assign cfg_memory_index = cfg_layout_id[INDEX_WIDTH-1:0];
    assign lookup_memory_index = lookup_layout_id[INDEX_WIDTH-1:0];
    assign cfg_write_commit = cfg_valid && cfg_ready && cfg_id_in_range
        && (cfg_descriptor[127:120] == FORMAT_VERSION);
    assign lookup_read_commit = lookup_valid && lookup_ready
        && lookup_id_in_range && descriptor_configured[lookup_memory_index];
    // Error and uninitialized responses can never expose an old RAM word.
    assign lookup_descriptor = lookup_success ? descriptor_read_data : 128'b0;

    initial begin
        if (LAYOUT_COUNT < 1 || LAYOUT_COUNT > 65536)
            $error("LAYOUT_COUNT must be in 1..65536");
    end

    // The data RAM has no reset; the reset valid map is the authority for
    // visibility and keeps fail-closed initialization synthesizable as LUTRAM.
    always_ff @(posedge clk) begin
        if (cfg_write_commit)
            descriptor_memory[cfg_memory_index] <= cfg_descriptor;
        if (lookup_read_commit)
            descriptor_read_data <= descriptor_memory[lookup_memory_index];
    end

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            descriptor_configured <= '0;
            lookup_success <= 1'b0;
            cfg_error <= 1'b0;
            cfg_error_code <= '0;
            lookup_rsp_valid <= 1'b0;
            lookup_rsp_error <= 1'b0;
            lookup_rsp_error_code <= '0;
            configured_count <= '0;
            accepted_loads <= '0;
            rejected_loads <= '0;
            host_writes_busy <= '0;
            lookup_requests <= '0;
            lookup_errors <= '0;
        end else begin
            cfg_error <= 1'b0;
            cfg_error_code <= '0;
            lookup_rsp_valid <= 1'b0;
            lookup_rsp_error <= 1'b0;
            lookup_rsp_error_code <= '0;

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
                end else begin
                    descriptor_configured[cfg_memory_index] <= 1'b1;
                    accepted_loads <= accepted_loads + 1'b1;
                    if (!descriptor_configured[cfg_memory_index])
                        configured_count <= configured_count + 1'b1;
                end
            end

            if (lookup_valid && lookup_ready) begin
                lookup_rsp_valid <= 1'b1;
                lookup_requests <= lookup_requests + 1'b1;
                if (!lookup_id_in_range) begin
                    lookup_success <= 1'b0;
                    lookup_rsp_error <= 1'b1;
                    lookup_rsp_error_code <= ERR_LOOKUP_BOUNDS;
                    lookup_errors <= lookup_errors + 1'b1;
                end else if (!descriptor_configured[lookup_memory_index]) begin
                    lookup_success <= 1'b0;
                    lookup_rsp_error <= 1'b1;
                    lookup_rsp_error_code <= ERR_UNINITIALIZED;
                    lookup_errors <= lookup_errors + 1'b1;
                end else begin
                    lookup_success <= 1'b1;
                end
            end else begin
                lookup_success <= 1'b0;
            end
        end
    end
endmodule

`default_nettype wire
