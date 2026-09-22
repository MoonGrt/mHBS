`timescale 1ns/1ps
`default_nettype none

// Tiny event scoreboard for an offline-scheduled program.  An event is
// either free, pending in a lane, or completed and waiting to be consumed.
// There is deliberately no ready-task window, associative tag search, or
// dynamic priority logic in this block.
module uhbs_event_scoreboard #(
    parameter integer EVENTS = 8
) (
    input  wire              clk,
    input  wire              rst_n,
    input  wire              clear,
    input  wire              allocate_valid,
    input  wire [EVENTS-1:0] allocate_mask,
    input  wire              complete_valid,
    input  wire [EVENTS-1:0] complete_mask,
    input  wire              consume_valid,
    input  wire [EVENTS-1:0] consume_mask,
    input  wire [EVENTS-1:0] wait_mask,
    output wire              wait_ready,
    output logic [EVENTS-1:0] pending,
    output logic [EVENTS-1:0] completed,
    output logic             error,
    output logic [2:0]       error_code
);
    localparam logic [2:0] ERR_NONE       = 3'd0;
    localparam logic [2:0] ERR_ALLOC_BUSY = 3'd1;
    localparam logic [2:0] ERR_COMPLETE   = 3'd2;
    localparam logic [2:0] ERR_CONSUME    = 3'd3;
    localparam logic [2:0] ERR_OVERLAP    = 3'd4;

    wire [EVENTS-1:0] consumed = consume_valid ? consume_mask : '0;
    wire [EVENTS-1:0] allocated = allocate_valid ? allocate_mask : '0;
    wire [EVENTS-1:0] completed_now = complete_valid ? complete_mask : '0;
    wire [EVENTS-1:0] effective_completed = completed | completed_now;
    wire [EVENTS-1:0] retained_completed
        = effective_completed & ~consumed;
    wire [EVENTS-1:0] retained_pending = pending & ~completed_now;
    wire alloc_busy = |(allocated
        & (retained_pending | retained_completed));
    wire bad_complete = |(completed_now & ~pending);
    wire bad_consume = |(consumed & ~effective_completed);
    wire bad_overlap = |(allocated & completed_now & ~consumed);

    // Completion bypass lets the next statically scheduled word launch as
    // soon as both lanes expose done/ready, without a scoreboard bubble.
    assign wait_ready = (effective_completed & wait_mask) == wait_mask;

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            pending <= '0;
            completed <= '0;
            error <= 1'b0;
            error_code <= ERR_NONE;
        end else if (clear) begin
            pending <= '0;
            completed <= '0;
            error <= 1'b0;
            error_code <= ERR_NONE;
        end else if (!error) begin
            if (alloc_busy) begin
                error <= 1'b1;
                error_code <= ERR_ALLOC_BUSY;
            end else if (bad_complete) begin
                error <= 1'b1;
                error_code <= ERR_COMPLETE;
            end else if (bad_consume) begin
                error <= 1'b1;
                error_code <= ERR_CONSUME;
            end else if (bad_overlap) begin
                error <= 1'b1;
                error_code <= ERR_OVERLAP;
            end else begin
                pending <= retained_pending | allocated;
                completed <= retained_completed;
            end
        end
    end
endmodule

`default_nettype wire
