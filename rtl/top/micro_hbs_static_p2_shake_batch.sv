`timescale 1ns/1ps
`default_nettype none

// Static P=2 SHAKE256 batch capability.
//
// The complete batch is accepted by one batch_start transaction and copied
// into local registers.  There is deliberately no per-hash request port and
// no dynamic scheduler: task 2*k is always assigned to lane 0 and task
// 2*k+1 to lane 1.  An odd final pair uses lane mask 2'b01.
module micro_hbs_static_p2_shake_batch #(
    parameter integer MAX_TASKS = 8,
    parameter integer UNROLL = 2
) (
    input  wire                           clk,
    input  wire                           rst_n,
    input  wire                           batch_start,
    output logic                          batch_ready,
    input  wire [7:0]                     batch_count,
    input  wire [MAX_TASKS*1088-1:0]      batch_messages,
    input  wire [MAX_TASKS*8-1:0]         batch_message_lengths,
    output logic [MAX_TASKS*256-1:0]      batch_digests,
    output logic                          busy,
    output logic                          batch_done,
    output logic                          batch_error,

    // One-cycle observation pulse for each statically assigned pair.
    output logic                          dispatch_valid,
    output logic [1:0]                    dispatch_lane_mask,
    output logic [7:0]                    dispatch_pair_index,

    // Cycles are counted from the cycle after batch acceptance through the
    // completion cycle.  Fixed dispatch bubbles are therefore idle cycles.
    output logic [31:0]                   lane0_active_cycles,
    output logic [31:0]                   lane0_idle_cycles,
    output logic [31:0]                   lane1_active_cycles,
    output logic [31:0]                   lane1_idle_cycles
);
    typedef enum logic [1:0] {S_IDLE, S_DISPATCH, S_WAIT} state_t;
    state_t state;

    logic [MAX_TASKS*1088-1:0] message_bank;
    logic [MAX_TASKS*8-1:0] length_bank;
    logic [7:0] accepted_count;
    logic [7:0] pair_base;
    logic [1:0] pending_mask;
    logic [1:0] active_mask;

    logic lane0_start;
    logic lane1_start;
    logic [1087:0] lane0_message;
    logic [1087:0] lane1_message;
    logic [7:0] lane0_length;
    logic [7:0] lane1_length;
    wire lane0_ready;
    wire lane1_ready;
    wire [255:0] lane0_digest;
    wire [255:0] lane1_digest;
    wire lane0_done;
    wire lane1_done;
    wire lane0_error;
    wire lane1_error;

    logic request_is_valid;
    integer validation_index;
    localparam logic [7:0] MAX_TASKS_U8 = 8'(MAX_TASKS);

    always_comb begin
        request_is_valid = (batch_count != 0) && (batch_count <= MAX_TASKS_U8);
        for (validation_index = 0;
             validation_index < MAX_TASKS;
             validation_index = validation_index + 1) begin
            if ((validation_index < batch_count)
                && (batch_message_lengths[8*validation_index +: 8] > 135))
                request_is_valid = 1'b0;
        end
    end

    micro_hbs_shake256_single_block #(.UNROLL(UNROLL)) lane0 (
        .clk,
        .rst_n,
        .start(lane0_start),
        .ready(lane0_ready),
        .message(lane0_message),
        .message_length(lane0_length),
        .digest(lane0_digest),
        .done(lane0_done),
        .error(lane0_error)
    );

    micro_hbs_shake256_single_block #(.UNROLL(UNROLL)) lane1 (
        .clk,
        .rst_n,
        .start(lane1_start),
        .ready(lane1_ready),
        .message(lane1_message),
        .message_length(lane1_length),
        .digest(lane1_digest),
        .done(lane1_done),
        .error(lane1_error)
    );

    assign busy = (state != S_IDLE);
    assign batch_ready = (state == S_IDLE) && lane0_ready && lane1_ready;

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= S_IDLE;
            message_bank <= '0;
            length_bank <= '0;
            accepted_count <= '0;
            pair_base <= '0;
            pending_mask <= '0;
            active_mask <= '0;
            lane0_start <= 1'b0;
            lane1_start <= 1'b0;
            lane0_message <= '0;
            lane1_message <= '0;
            lane0_length <= '0;
            lane1_length <= '0;
            batch_digests <= '0;
            batch_done <= 1'b0;
            batch_error <= 1'b0;
            dispatch_valid <= 1'b0;
            dispatch_lane_mask <= '0;
            dispatch_pair_index <= '0;
            lane0_active_cycles <= '0;
            lane0_idle_cycles <= '0;
            lane1_active_cycles <= '0;
            lane1_idle_cycles <= '0;
        end else begin
            lane0_start <= 1'b0;
            lane1_start <= 1'b0;
            batch_done <= 1'b0;
            batch_error <= 1'b0;
            dispatch_valid <= 1'b0;

            if (state != S_IDLE) begin
                if (active_mask[0])
                    lane0_active_cycles <= lane0_active_cycles + 1'b1;
                else
                    lane0_idle_cycles <= lane0_idle_cycles + 1'b1;
                if (active_mask[1])
                    lane1_active_cycles <= lane1_active_cycles + 1'b1;
                else
                    lane1_idle_cycles <= lane1_idle_cycles + 1'b1;
            end

            case (state)
                S_IDLE: begin
                    active_mask <= 2'b00;
                    pending_mask <= 2'b00;
                    if (batch_start) begin
                        if (!request_is_valid) begin
                            batch_error <= 1'b1;
                        end else begin
                            message_bank <= batch_messages;
                            length_bank <= batch_message_lengths;
                            accepted_count <= batch_count;
                            pair_base <= 0;
                            batch_digests <= '0;
                            dispatch_lane_mask <= 2'b00;
                            dispatch_pair_index <= 0;
                            lane0_active_cycles <= 0;
                            lane0_idle_cycles <= 0;
                            lane1_active_cycles <= 0;
                            lane1_idle_cycles <= 0;
                            state <= S_DISPATCH;
                        end
                    end
                end

                S_DISPATCH: begin
                    // Lockstep availability preserves static pair assignment;
                    // the controller never chooses among ready lanes.
                    if (lane0_ready && lane1_ready) begin
                        lane0_message <= message_bank[1088*pair_base +: 1088];
                        lane0_length <= length_bank[8*pair_base +: 8];
                        lane0_start <= 1'b1;
                        if ((pair_base + 8'd1) < accepted_count) begin
                            lane1_message <= message_bank[1088*pair_base + 1088 +: 1088];
                            lane1_length <= length_bank[8*pair_base + 8 +: 8];
                            lane1_start <= 1'b1;
                            pending_mask <= 2'b11;
                            active_mask <= 2'b11;
                            dispatch_lane_mask <= 2'b11;
                        end else begin
                            lane1_message <= '0;
                            lane1_length <= '0;
                            pending_mask <= 2'b01;
                            active_mask <= 2'b01;
                            dispatch_lane_mask <= 2'b01;
                        end
                        dispatch_pair_index <= pair_base >> 1;
                        dispatch_valid <= 1'b1;
                        state <= S_WAIT;
                    end
                end

                S_WAIT: begin
                    if ((pending_mask[0] && lane0_error)
                        || (pending_mask[1] && lane1_error)) begin
                        active_mask <= 2'b00;
                        pending_mask <= 2'b00;
                        batch_error <= 1'b1;
                        state <= S_IDLE;
                    end else begin
                        if (pending_mask[0] && lane0_done) begin
                            batch_digests[256*pair_base +: 256] <= lane0_digest;
                            pending_mask[0] <= 1'b0;
                        end
                        if (pending_mask[1] && lane1_done) begin
                            batch_digests[256*pair_base + 256 +: 256] <= lane1_digest;
                            pending_mask[1] <= 1'b0;
                        end

                        if ((pending_mask & ~{lane1_done, lane0_done}) == 2'b00) begin
                            active_mask <= 2'b00;
                            pending_mask <= 2'b00;
                            if ((pair_base + 8'd2) >= accepted_count) begin
                                batch_done <= 1'b1;
                                state <= S_IDLE;
                            end else begin
                                pair_base <= pair_base + 8'd2;
                                state <= S_DISPATCH;
                            end
                        end
                    end
                end

                default: begin
                    active_mask <= 2'b00;
                    pending_mask <= 2'b00;
                    batch_error <= 1'b1;
                    state <= S_IDLE;
                end
            endcase
        end
    end
endmodule

`default_nettype wire
