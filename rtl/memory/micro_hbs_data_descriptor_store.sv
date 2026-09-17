`timescale 1ns/1ps
`default_nettype none

// Algorithm-independent, versioned data-descriptor store.
//
// Fixed 128-bit descriptor format:
//   [127:120] format_version (FORMAT_VERSION)
//   [119:104] flags          ([0] DATA_LOAD, [1] DATA_MOVE, [2] reserved,
//                             [3] OUTPUT;
//                             [15:4] generic modifiers/reserved)
//   [103:88]  source_a       (64-bit Scratchpad word address)
//   [87:72]   source_b       (64-bit Scratchpad word address)
//   [71:56]   destination    (64-bit Scratchpad word address)
//   [55:40]   word_count
//   [39:36]   last_bytes     (consumer interprets 1..8 for OUTPUT)
//   [35:32]   address_mode   (reserved for generic indexed addressing)
//   [31:0]    reserved
//
// The store deliberately does not attach algorithm or opcode semantics to
// these fields.  Software loads a static image while the engine is IDLE;
// engine_busy locks all configuration writes.  Runtime microcode can only
// perform bounded lookups.  One response register supplies arbitrary response
// backpressure without changing, duplicating, or dropping a descriptor.
module micro_hbs_data_descriptor_store #(
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

    output wire [15:0]   descriptor_flags,
    output wire [15:0]   descriptor_source_a,
    output wire [15:0]   descriptor_source_b,
    output wire [15:0]   descriptor_destination,
    output wire [15:0]   descriptor_word_count,
    output wire [3:0]    descriptor_last_bytes,
    output wire [3:0]    descriptor_address_mode,
    output wire [7:0]    descriptor_format_version,
    output wire [31:0]   descriptor_reserved,

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

    localparam logic [15:0] ERR_CFG_BUSY          = 16'h0601;
    localparam logic [15:0] ERR_CFG_BOUNDS        = 16'h0602;
    localparam logic [15:0] ERR_CFG_CONFLICT      = 16'h0603;
    localparam logic [15:0] ERR_FORMAT_VERSION    = 16'h0604;
    localparam logic [15:0] ERR_LOOKUP_BOUNDS     = 16'h0605;
    localparam logic [15:0] ERR_UNINITIALIZED     = 16'h0606;

    (* ram_style = "distributed" *) logic [127:0]
        descriptor_memory [0:DESCRIPTOR_COUNT-1];
    logic [DESCRIPTOR_COUNT-1:0] descriptor_configured;

    wire cfg_id_in_range;
    wire lookup_id_in_range;
    wire cfg_write_commit;
    wire lookup_commit;
    wire [INDEX_WIDTH-1:0] cfg_memory_index;
    wire [INDEX_WIDTH-1:0] lookup_memory_index;

    assign image_locked = engine_busy;
    assign descriptor_capacity = DESCRIPTOR_COUNT;

    // A pending lookup has priority over an IDLE configuration write.  This
    // also prevents a stalled lookup request from observing a later overwrite.
    assign cfg_ready = rst_n && !engine_busy && !lookup_valid;
    assign lookup_ready = rst_n
        && (!lookup_rsp_valid || lookup_rsp_ready);

    assign cfg_id_in_range = ({1'b0, cfg_descriptor_id}
        < DESCRIPTOR_COUNT_EXT);
    assign lookup_id_in_range = ({1'b0, lookup_descriptor_id}
        < DESCRIPTOR_COUNT_EXT);
    assign cfg_memory_index = cfg_descriptor_id[INDEX_WIDTH-1:0];
    assign lookup_memory_index = lookup_descriptor_id[INDEX_WIDTH-1:0];
    assign cfg_write_commit = cfg_valid && cfg_ready && cfg_id_in_range
        && (cfg_descriptor[127:120] == FORMAT_VERSION);
    assign lookup_commit = lookup_valid && lookup_ready;

    assign descriptor_flags = lookup_descriptor[119:104];
    assign descriptor_source_a = lookup_descriptor[103:88];
    assign descriptor_source_b = lookup_descriptor[87:72];
    assign descriptor_destination = lookup_descriptor[71:56];
    assign descriptor_word_count = lookup_descriptor[55:40];
    assign descriptor_last_bytes = lookup_descriptor[39:36];
    assign descriptor_address_mode = lookup_descriptor[35:32];
    assign descriptor_format_version = lookup_descriptor[127:120];
    assign descriptor_reserved = lookup_descriptor[31:0];

    initial begin
        if (DESCRIPTOR_COUNT < 1 || DESCRIPTOR_COUNT > 65536)
            $error("DESCRIPTOR_COUNT must be in 1..65536");
    end

    // Reset only the validity map, not the data RAM.  Stale physical words can
    // therefore never become observable after reset or before initialization.
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
