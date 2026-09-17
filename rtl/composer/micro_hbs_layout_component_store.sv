`timescale 1ns/1ps
`default_nettype none

// Static component program for descriptor-driven HASH composition.
//
// Each 192-bit word is algorithm-independent:
//   [191:184] format_version
//   [183:176] kind (literal/zero/register/scratch/scratch-xor)
//   [175:168] byte_count
//   [167:160] address flags
//   [159:104] source-A affine logical-slot expression
//   [103:48]  source-B affine logical-slot expression
//   [47:16]   immediate/register selector
//   [15:0]    reserved
//
// A source expression is base + R[reg0]*scale0 + R[reg1]*scale1.  The
// composer converts logical 32-byte slots to physical 64-bit Scratchpad
// words.  The table is configured only while the engine is idle.
module micro_hbs_layout_component_store #(
    parameter integer COMPONENT_WORDS = 256,
    parameter logic [7:0] FORMAT_VERSION = 8'h01
) (
    input  wire         clk,
    input  wire         rst_n,
    input  wire         engine_busy,

    input  wire         cfg_valid,
    output wire         cfg_ready,
    input  wire [15:0]  cfg_index,
    input  wire [191:0] cfg_component,
    output logic        cfg_error,
    output logic [15:0] cfg_error_code,

    input  wire         lookup_valid,
    output wire         lookup_ready,
    input  wire [15:0]  lookup_index,
    output logic        lookup_rsp_valid,
    output logic        lookup_rsp_error,
    output logic [15:0] lookup_rsp_error_code,
    output wire [191:0] lookup_component,

    output logic [31:0] configured_count,
    output logic [31:0] accepted_loads,
    output logic [31:0] rejected_loads,
    output logic [31:0] host_writes_busy,
    output logic [31:0] lookup_requests,
    output logic [31:0] lookup_errors
);
    localparam integer INDEX_WIDTH = (COMPONENT_WORDS <= 2)
        ? 1 : $clog2(COMPONENT_WORDS);
    localparam logic [16:0] COMPONENT_WORDS_EXT = 17'(COMPONENT_WORDS);

    localparam logic [15:0] ERR_CFG_BUSY       = 16'h0c01;
    localparam logic [15:0] ERR_CFG_BOUNDS     = 16'h0c02;
    localparam logic [15:0] ERR_CFG_CONFLICT   = 16'h0c03;
    localparam logic [15:0] ERR_FORMAT_VERSION = 16'h0c04;
    localparam logic [15:0] ERR_LOOKUP_BOUNDS  = 16'h0c05;
    localparam logic [15:0] ERR_UNINITIALIZED  = 16'h0c06;

    (* ram_style = "distributed" *) logic [191:0]
        component_memory [0:COMPONENT_WORDS-1];
    logic [COMPONENT_WORDS-1:0] component_configured;
    logic [191:0] component_read_data;
    logic lookup_success;

    wire cfg_in_range = ({1'b0, cfg_index} < COMPONENT_WORDS_EXT);
    wire lookup_in_range = ({1'b0, lookup_index} < COMPONENT_WORDS_EXT);
    wire [INDEX_WIDTH-1:0] cfg_memory_index = cfg_index[INDEX_WIDTH-1:0];
    wire [INDEX_WIDTH-1:0] lookup_memory_index
        = lookup_index[INDEX_WIDTH-1:0];
    wire cfg_commit = cfg_valid && cfg_ready && cfg_in_range
        && cfg_component[191:184] == FORMAT_VERSION;
    wire lookup_commit = lookup_valid && lookup_ready && lookup_in_range
        && component_configured[lookup_memory_index];

    assign cfg_ready = rst_n && !engine_busy && !lookup_valid;
    assign lookup_ready = rst_n;
    assign lookup_component = lookup_success ? component_read_data : 192'b0;

    initial begin
        if (COMPONENT_WORDS < 1 || COMPONENT_WORDS > 65536)
            $error("COMPONENT_WORDS must be in 1..65536");
    end

    always_ff @(posedge clk) begin
        if (cfg_commit)
            component_memory[cfg_memory_index] <= cfg_component;
        if (lookup_commit)
            component_read_data <= component_memory[lookup_memory_index];
    end

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            component_configured <= '0;
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
                end else if (!cfg_in_range) begin
                    cfg_error <= 1'b1;
                    cfg_error_code <= ERR_CFG_BOUNDS;
                    rejected_loads <= rejected_loads + 1'b1;
                end else if (cfg_component[191:184] != FORMAT_VERSION) begin
                    cfg_error <= 1'b1;
                    cfg_error_code <= ERR_FORMAT_VERSION;
                    rejected_loads <= rejected_loads + 1'b1;
                end else begin
                    component_configured[cfg_memory_index] <= 1'b1;
                    accepted_loads <= accepted_loads + 1'b1;
                    if (!component_configured[cfg_memory_index])
                        configured_count <= configured_count + 1'b1;
                end
            end

            if (lookup_valid && lookup_ready) begin
                lookup_rsp_valid <= 1'b1;
                lookup_requests <= lookup_requests + 1'b1;
                if (!lookup_in_range) begin
                    lookup_success <= 1'b0;
                    lookup_rsp_error <= 1'b1;
                    lookup_rsp_error_code <= ERR_LOOKUP_BOUNDS;
                    lookup_errors <= lookup_errors + 1'b1;
                end else if (!component_configured[lookup_memory_index]) begin
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
