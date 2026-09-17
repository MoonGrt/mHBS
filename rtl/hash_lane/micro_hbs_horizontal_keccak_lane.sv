`timescale 1ns/1ps
`default_nettype none

// Minimal event-tagged permutation service.  This follows the efficient
// sphincslet-style contract (load complete state, iterate, return complete
// state) while retaining μHBS's two-round-per-cycle Keccak implementation.
// Message padding and layout composition are intentionally outside the lane.
module micro_hbs_horizontal_keccak_lane #(
    parameter integer UNROLL = 2,
    parameter integer EVENT_BITS = 3
) (
    input  wire                  clk,
    input  wire                  rst_n,
    input  wire                  request_valid,
    output wire                  request_ready,
    input  wire [EVENT_BITS-1:0] request_event,
    input  wire [1599:0]         request_state,
    input  wire                  chain_enable,
    input  wire                  chain_prefix,
    input  wire                  chain_prefix_preserve_counter,
    input  wire [2:0]            chain_prefix_domain,
    input  wire [7:0]            chain_count,
    input  wire [7:0]            chain_counter_offset,
    input  wire [7:0]            chain_feedback_offset,
    input  wire [5:0]            chain_feedback_bytes,
    input  wire [31:0]           chain_counter_start,
    input  wire                  capture_enable,
    input  wire [7:0]            capture_after,
    output wire                  response_valid,
    output wire [EVENT_BITS-1:0] response_event,
    output wire [1599:0]         response_state,
    output wire [255:0]          capture_digest,
    output wire                  capture_valid,
    output wire [5:0]            rounds_executed
);
    wire start = request_valid && request_ready;
    wire done;
    logic [EVENT_BITS-1:0] saved_event;

    micro_hbs_keccak_f1600 #(.UNROLL(UNROLL)) permutation (
        .clk, .rst_n, .start, .ready(request_ready),
        .state_in(request_state), .chain_enable, .chain_prefix,
        .chain_prefix_preserve_counter, .chain_prefix_domain,
        .chain_count, .chain_counter_offset, .chain_feedback_offset,
        .chain_feedback_bytes, .chain_counter_start,
        .capture_enable, .capture_after, .state_out(response_state),
        .done, .capture_digest, .capture_valid, .rounds_executed
    );

    assign response_valid = done;
    assign response_event = saved_event;

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n)
            saved_event <= '0;
        else if (start)
            saved_event <= request_event;
    end
endmodule

`default_nettype wire
