`timescale 1ns/1ps
`default_nettype none

// Compressed horizontal-control boundary.  A future context materializer
// turns each 48-bit command into its padded state and chain parameters.
module micro_hbs_horizontal_token_hash_core #(
    parameter integer PROGRAM_TOKENS = 256,
    parameter integer ADDRESS_WIDTH = 8,
    parameter integer UNROLL = 2
) (
    input  wire                     clk,
    input  wire                     rst_n,
    input  wire                     token_we,
    input  wire [ADDRESS_WIDTH-1:0] token_addr,
    input  wire [63:0]              token_wdata,
    input  wire                     template_we,
    input  wire [5:0]               template_addr,
    input  wire [127:0]             template_wdata,
    input  wire                     job_valid,
    output wire                     job_ready,
    input  wire [ADDRESS_WIDTH-1:0] job_entry,
    output wire                     done,
    output wire                     busy,
    output wire                     error,
    output wire [7:0]               error_code,
    output wire [47:0]              lane0_command,
    input  wire [1599:0]            lane0_state,
    output wire [47:0]              lane1_command,
    input  wire [1599:0]            lane1_state,
    input  wire [1:0]               chain_enable,
    input  wire [1:0]               chain_prefix,
    input  wire [1:0]               chain_prefix_preserve_counter,
    input  wire [5:0]               chain_prefix_domain,
    input  wire [15:0]              chain_count,
    input  wire [63:0]              chain_counter_start,
    input  wire [1:0]               capture_enable,
    input  wire [15:0]              capture_after,
    output wire [1:0]               response_valid,
    output wire [1599:0]            lane0_response_state,
    output wire [1599:0]            lane1_response_state,
    output wire [7:0]               pending_events,
    output wire [7:0]               completed_events
);
    wire lane0_valid, lane1_valid;
    wire lane0_ready, lane1_ready;
    wire [2:0] lane0_event, lane1_event;
    wire [2:0] lane0_response_event, lane1_response_event;

    micro_hbs_horizontal_token_sequencer #(
        .PROGRAM_TOKENS(PROGRAM_TOKENS), .ADDRESS_WIDTH(ADDRESS_WIDTH)
    ) sequencer (
        .clk, .rst_n, .token_we, .token_addr, .token_wdata,
        .template_we, .template_addr, .template_wdata,
        .job_valid, .job_ready, .job_entry, .done, .busy, .error,
        .error_code, .lane0_valid, .lane0_ready, .lane0_command,
        .lane0_event, .lane1_valid, .lane1_ready, .lane1_command,
        .lane1_event, .lane0_done_valid(response_valid[0]),
        .lane0_done_event(lane0_response_event),
        .lane1_done_valid(response_valid[1]),
        .lane1_done_event(lane1_response_event), .program_counter(),
        .pending_events, .completed_events, .retired_words(),
        .retired_tokens(), .issued_lane0(), .issued_lane1(), .wait_cycles()
    );

    micro_hbs_horizontal_keccak_lane #(.UNROLL(UNROLL)) lane0 (
        .clk, .rst_n, .request_valid(lane0_valid),
        .request_ready(lane0_ready), .request_event(lane0_event),
        .request_state(lane0_state), .chain_enable(chain_enable[0]),
        .chain_prefix(chain_prefix[0]),
        .chain_prefix_preserve_counter(chain_prefix_preserve_counter[0]),
        .chain_prefix_domain(chain_prefix_domain[2:0]),
        .chain_count(chain_count[7:0]), .chain_counter_offset(8'd44),
        .chain_feedback_offset(8'd48), .chain_feedback_bytes(6'd16),
        .chain_counter_start(chain_counter_start[31:0]),
        .capture_enable(capture_enable[0]),
        .capture_after(capture_after[7:0]),
        .response_valid(response_valid[0]),
        .response_event(lane0_response_event),
        .response_state(lane0_response_state), .capture_digest(),
        .capture_valid(), .rounds_executed()
    );

    micro_hbs_horizontal_keccak_lane #(.UNROLL(UNROLL)) lane1 (
        .clk, .rst_n, .request_valid(lane1_valid),
        .request_ready(lane1_ready), .request_event(lane1_event),
        .request_state(lane1_state), .chain_enable(chain_enable[1]),
        .chain_prefix(chain_prefix[1]),
        .chain_prefix_preserve_counter(chain_prefix_preserve_counter[1]),
        .chain_prefix_domain(chain_prefix_domain[5:3]),
        .chain_count(chain_count[15:8]), .chain_counter_offset(8'd44),
        .chain_feedback_offset(8'd48), .chain_feedback_bytes(6'd16),
        .chain_counter_start(chain_counter_start[63:32]),
        .capture_enable(capture_enable[1]),
        .capture_after(capture_after[15:8]),
        .response_valid(response_valid[1]),
        .response_event(lane1_response_event),
        .response_state(lane1_response_state), .capture_digest(),
        .capture_valid(), .rounds_executed()
    );
endmodule

`default_nettype wire
