`timescale 1ns/1ps
`default_nettype none

// Event-tagged SHAKE context lane for horizontal microcode.
//
// The materializer supplies one already-delimited 1088-bit SHAKE rate block
// at a time.  The lane retains the 1600-bit sponge state across blocks and
// therefore supports the 576/608-byte T_l preimages used by SLH-DSA.  A
// one-block request may alternatively enable the lane-local WOTS chain path;
// this reuses the same Keccak datapath and never round-trips chain feedback
// through the scratchpad.
module micro_hbs_horizontal_shake_context_lane #(
    parameter integer UNROLL = 2,
    parameter integer EVENT_BITS = 3
) (
    input  wire                  clk,
    input  wire                  rst_n,

    input  wire                  context_valid,
    output wire                  context_ready,
    input  wire [EVENT_BITS-1:0] context_event,
    input  wire                  chain_enable,
    input  wire                  chain_prefix,
    input  wire                  chain_prefix_preserve_counter,
    input  wire [2:0]            chain_prefix_domain,
    input  wire [7:0]            chain_count,
    input  wire [31:0]           chain_counter_start,
    input  wire                  capture_enable,
    input  wire [7:0]            capture_after,

    input  wire                  block_valid,
    output wire                  block_ready,
    // Only the low 1088 bits are absorbed.  Capacity bits are deliberately
    // absent from the interface so a descriptor cannot corrupt sponge state.
    input  wire [1087:0]         block_data,
    input  wire                  block_last,

    output logic                 response_valid,
    output logic [EVENT_BITS-1:0] response_event,
    output logic [1599:0]        response_state,
    output logic [255:0]         capture_digest,
    output logic                 capture_valid,
    output logic                 error
);
    localparam logic [1:0] IDLE = 2'd0;
    localparam logic [1:0] WAIT_BLOCK = 2'd1;
    localparam logic [1:0] RUN = 2'd2;

    logic [1:0] state;
    logic [EVENT_BITS-1:0] saved_event;
    logic saved_chain_enable;
    logic saved_chain_prefix;
    logic saved_chain_prefix_preserve_counter;
    logic [2:0] saved_chain_prefix_domain;
    logic [7:0] saved_chain_count;
    logic [31:0] saved_chain_counter_start;
    logic saved_capture_enable;
    logic [7:0] saved_capture_after;
    logic first_block;
    logic running_last;

    wire permutation_ready;
    wire permutation_done;
    wire [1599:0] permutation_state;
    wire [255:0] permutation_capture_digest;
    wire permutation_capture_valid;
    wire start = block_valid && block_ready;
    wire [1599:0] rate_block = {{512{1'b0}}, block_data};
    wire [1599:0] permutation_input = first_block
        ? rate_block
        : (permutation_state ^ rate_block);

    assign context_ready = state == IDLE;
    assign block_ready = state == WAIT_BLOCK && permutation_ready;

    micro_hbs_keccak_f1600 #(.UNROLL(UNROLL)) permutation (
        .clk, .rst_n, .start, .ready(permutation_ready),
        .state_in(permutation_input),
        .chain_enable(saved_chain_enable),
        .chain_prefix(saved_chain_prefix),
        .chain_prefix_preserve_counter(
            saved_chain_prefix_preserve_counter),
        .chain_prefix_domain(saved_chain_prefix_domain),
        .chain_count(saved_chain_count),
        .chain_counter_offset(8'd44),
        .chain_feedback_offset(8'd48),
        .chain_feedback_bytes(6'd16),
        .chain_counter_start(saved_chain_counter_start),
        .capture_enable(saved_capture_enable),
        .capture_after(saved_capture_after),
        .state_out(permutation_state), .done(permutation_done),
        .capture_digest(permutation_capture_digest),
        .capture_valid(permutation_capture_valid), .rounds_executed()
    );

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= IDLE;
            saved_event <= '0;
            saved_chain_enable <= 1'b0;
            saved_chain_prefix <= 1'b0;
            saved_chain_prefix_preserve_counter <= 1'b0;
            saved_chain_prefix_domain <= '0;
            saved_chain_count <= '0;
            saved_chain_counter_start <= '0;
            saved_capture_enable <= 1'b0;
            saved_capture_after <= '0;
            first_block <= 1'b1;
            running_last <= 1'b0;
            response_valid <= 1'b0;
            response_event <= '0;
            response_state <= '0;
            capture_digest <= '0;
            capture_valid <= 1'b0;
            error <= 1'b0;
        end else begin
            response_valid <= 1'b0;
            capture_valid <= 1'b0;
            error <= 1'b0;
            case (state)
                IDLE: if (context_valid) begin
                    saved_event <= context_event;
                    saved_chain_enable <= chain_enable;
                    saved_chain_prefix <= chain_prefix;
                    saved_chain_prefix_preserve_counter
                        <= chain_prefix_preserve_counter;
                    saved_chain_prefix_domain <= chain_prefix_domain;
                    saved_chain_count <= chain_count;
                    saved_chain_counter_start <= chain_counter_start;
                    saved_capture_enable <= capture_enable;
                    saved_capture_after <= capture_after;
                    first_block <= 1'b1;
                    state <= WAIT_BLOCK;
                end
                WAIT_BLOCK: if (start) begin
                    running_last <= block_last;
                    // Repeat chains are defined over one complete F preimage.
                    // Rejecting a chained multi-block request prevents an
                    // ambiguous reset/feedback interpretation.
                    if (saved_chain_enable && !block_last) begin
                        error <= 1'b1;
                        state <= IDLE;
                    end else begin
                        state <= RUN;
                    end
                end
                RUN: if (permutation_done) begin
                    if (running_last) begin
                        response_valid <= 1'b1;
                        response_event <= saved_event;
                        response_state <= permutation_state;
                        capture_digest <= permutation_capture_digest;
                        capture_valid <= permutation_capture_valid;
                        state <= IDLE;
                    end else begin
                        first_block <= 1'b0;
                        state <= WAIT_BLOCK;
                    end
                end
                default: state <= IDLE;
            endcase
        end
    end
endmodule

`default_nettype wire
