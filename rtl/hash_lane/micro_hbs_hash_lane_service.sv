`timescale 1ns/1ps
`default_nettype none

// Algorithm-neutral SHAKE lane service used by the horizontal scheduler.
// A job carries only sponge/repeat policy and an event tag; message assembly,
// destination routing, and tree semantics remain outside the lane.  Two
// instances of this module are therefore physically and functionally equal.
module micro_hbs_hash_lane_service #(
    parameter integer UNROLL = 2,
    parameter integer EVENT_BITS = 3
) (
    input  wire                  clk,
    input  wire                  rst_n,
    input  wire                  job_valid,
    output wire                  job_ready,
    input  wire [EVENT_BITS-1:0] job_event,
    input  wire                  repeat_enable,
    input  wire                  repeat_prefix,
    input  wire                  repeat_prefix_preserve_counter,
    input  wire [2:0]            repeat_prefix_domain,
    input  wire [7:0]            repeat_count,
    input  wire [7:0]            repeat_counter_offset,
    input  wire [7:0]            repeat_feedback_offset,
    input  wire [5:0]            repeat_feedback_bytes,
    input  wire [31:0]           repeat_counter_start,
    input  wire                  capture_enable,
    input  wire [7:0]            capture_after,
    input  wire                  block_valid,
    output wire                  block_ready,
    input  wire [1087:0]         block_data,
    input  wire [7:0]            block_bytes,
    input  wire                  block_last,
    output wire                  response_valid,
    output wire [EVENT_BITS-1:0] response_event,
    output wire [255:0]          response_digest,
    output wire [1087:0]         response_rate,
    output wire [255:0]          capture_digest,
    output wire                  capture_valid,
    output wire                  error,
    output wire                  busy
);
    wire hash_ready;
    wire digest_valid;
    logic [EVENT_BITS-1:0] saved_event;
    wire job_accept = job_valid && job_ready;

    assign job_ready = hash_ready;
    assign response_valid = digest_valid;
    assign response_event = saved_event;
    assign busy = !hash_ready;

    micro_hbs_shake256_stream #(.UNROLL(UNROLL)) stream (
        .clk, .rst_n, .hash_start(job_accept), .hash_ready,
        .block_valid(block_valid && (busy || job_accept)), .block_ready,
        .block_data, .block_bytes, .block_last,
        .repeat_enable, .repeat_prefix,
        .repeat_prefix_preserve_counter, .repeat_prefix_domain,
        .repeat_count, .repeat_counter_offset, .repeat_feedback_offset,
        .repeat_feedback_bytes, .repeat_counter_start,
        .capture_enable, .capture_after,
        .digest(response_digest), .rate_output(response_rate),
        .digest_valid, .capture_digest, .capture_valid, .error
    );

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n)
            saved_event <= '0;
        else if (job_accept)
            saved_event <= job_event;
    end
endmodule

`default_nettype wire
