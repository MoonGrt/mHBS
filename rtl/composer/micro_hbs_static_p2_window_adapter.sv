`timescale 1ns/1ps
`default_nettype none

// Windowed static P=2 adapter for layout R[index].  Each bank record is:
//   word 0      message length in bits [7:0]
//   words 1..17 136 message bytes, little-byte-first as required by SHAKE
// The two records are read in lockstep into bounded 1088-bit windows.  There
// is no task ingress or ready-lane selection in this adapter.
module micro_hbs_static_p2_window_adapter #(
    parameter integer PAIR_CAPACITY = 8,
    parameter integer UNROLL = 2
) (
    input  wire          clk,
    input  wire          rst_n,
    input  wire          job_begin,

    input  wire          req_valid,
    output logic         req_ready,
    input  wire [15:0]   layout_id,
    input  wire [1:0]    lane_mask,
    input  wire [31:0]   index_value,
    output logic         rsp_valid,
    output logic         rsp_error,
    output logic [15:0]  rsp_error_code,

    output logic         bank0_read_valid,
    input  wire          bank0_read_ready,
    output logic [15:0]  bank0_read_address,
    input  wire          bank0_response_valid,
    input  wire [63:0]   bank0_read_data,
    input  wire          bank0_bounds_error,
    output logic         bank1_read_valid,
    input  wire          bank1_read_ready,
    output logic [15:0]  bank1_read_address,
    input  wire          bank1_response_valid,
    input  wire [63:0]   bank1_read_data,
    input  wire          bank1_bounds_error,

    input  wire [15:0]   result_read_pair,
    output logic [255:0] result_lane0,
    output logic [255:0] result_lane1,
    output logic [1:0]   result_lane_mask,

    output logic         composing,
    output logic [1:0]   lane_active_mask,
    output logic         pair_dispatch_valid,
    output logic [1:0]   pair_dispatch_lane_mask,
    output logic [15:0]  pair_dispatch_index
);
    localparam logic [15:0] LAYOUT_STATIC_P2_SHAKE = 16'h0200;
    localparam logic [15:0] ERR_UNSUPPORTED_LAYOUT = 16'h0301;
    localparam logic [15:0] ERR_BAD_LANE_MASK      = 16'h0302;
    localparam logic [15:0] ERR_PAIR_BOUNDS        = 16'h0303;
    localparam logic [15:0] ERR_MESSAGE_LENGTH     = 16'h0304;
    localparam logic [15:0] ERR_BANK_BOUNDS        = 16'h0305;
    localparam integer PAIR_INDEX_WIDTH =
        (PAIR_CAPACITY <= 2) ? 1 : $clog2(PAIR_CAPACITY);
    localparam logic [15:0] PAIR_CAPACITY_U16 = 16'(PAIR_CAPACITY);

    typedef enum logic [2:0] {S_IDLE, S_COMPOSE, S_LAUNCH, S_WAIT} state_t;
    state_t state;

    logic [15:0] pair_index;
    logic [PAIR_INDEX_WIDTH-1:0] pair_slot;
    logic [15:0] record_base;
    logic [1:0] accepted_lane_mask;
    logic [5:0] issue_word;
    logic [5:0] receive_word;
    logic [1087:0] lane0_window;
    logic [1087:0] lane1_window;
    logic [7:0] lane0_length;
    logic [7:0] lane1_length;
    logic [1:0] pending_mask;

    logic lane0_start;
    logic lane1_start;
    wire lane0_ready;
    wire lane1_ready;
    wire [255:0] lane0_digest;
    wire [255:0] lane1_digest;
    wire lane0_done;
    wire lane1_done;
    wire lane0_error;
    wire lane1_error;

    logic [PAIR_CAPACITY*256-1:0] lane0_results;
    logic [PAIR_CAPACITY*256-1:0] lane1_results;
    logic [PAIR_CAPACITY*2-1:0] result_masks;

    wire bank0_read_accept;
    wire bank1_read_accept;
    assign bank0_read_accept = bank0_read_valid && bank0_read_ready;
    assign bank1_read_accept = bank1_read_valid && bank1_read_ready;

    assign req_ready = (state == S_IDLE);
    assign composing = (state == S_COMPOSE);
    assign bank0_read_valid = (state == S_COMPOSE) && (issue_word < 6'd18);
    assign bank1_read_valid = bank0_read_valid && accepted_lane_mask[1];
    assign bank0_read_address = record_base + {{10{1'b0}}, issue_word};
    assign bank1_read_address = record_base + {{10{1'b0}}, issue_word};

    always @(*) begin
        result_lane0 = '0;
        result_lane1 = '0;
        result_lane_mask = '0;
        if (result_read_pair < PAIR_CAPACITY_U16) begin
            result_lane_mask = result_masks[
                2*result_read_pair[PAIR_INDEX_WIDTH-1:0] +: 2];
            if (result_lane_mask[0])
                result_lane0 = lane0_results[
                    256*result_read_pair[PAIR_INDEX_WIDTH-1:0] +: 256];
            if (result_lane_mask[1])
                result_lane1 = lane1_results[
                    256*result_read_pair[PAIR_INDEX_WIDTH-1:0] +: 256];
        end
    end

    micro_hbs_shake256_single_block #(.UNROLL(UNROLL)) lane0 (
        .clk,
        .rst_n,
        .start(lane0_start),
        .ready(lane0_ready),
        .message(lane0_window),
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
        .message(lane1_window),
        .message_length(lane1_length),
        .digest(lane1_digest),
        .done(lane1_done),
        .error(lane1_error)
    );

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= S_IDLE;
            pair_index <= '0;
            pair_slot <= '0;
            record_base <= '0;
            accepted_lane_mask <= '0;
            issue_word <= '0;
            receive_word <= '0;
            lane0_window <= '0;
            lane1_window <= '0;
            lane0_length <= '0;
            lane1_length <= '0;
            pending_mask <= '0;
            lane_active_mask <= '0;
            lane0_start <= 1'b0;
            lane1_start <= 1'b0;
            rsp_valid <= 1'b0;
            rsp_error <= 1'b0;
            rsp_error_code <= '0;
            pair_dispatch_valid <= 1'b0;
            pair_dispatch_lane_mask <= '0;
            pair_dispatch_index <= '0;
            result_masks <= '0;
        end else begin
            lane0_start <= 1'b0;
            lane1_start <= 1'b0;
            rsp_valid <= 1'b0;
            rsp_error <= 1'b0;
            rsp_error_code <= '0;
            pair_dispatch_valid <= 1'b0;

            if (job_begin) begin
                lane_active_mask <= 2'b00;
                pair_dispatch_lane_mask <= 2'b00;
                pair_dispatch_index <= '0;
                result_masks <= '0;
            end

            case (state)
                S_IDLE: begin
                    lane_active_mask <= 2'b00;
                    pending_mask <= 2'b00;
                    if (req_valid) begin
                        if (layout_id != LAYOUT_STATIC_P2_SHAKE) begin
                            rsp_error <= 1'b1;
                            rsp_error_code <= ERR_UNSUPPORTED_LAYOUT;
                        end else if (lane_mask != 2'b01 && lane_mask != 2'b11) begin
                            rsp_error <= 1'b1;
                            rsp_error_code <= ERR_BAD_LANE_MASK;
                        end else if (index_value[31:16] != 0
                            || index_value[15:0] >= PAIR_CAPACITY_U16) begin
                            rsp_error <= 1'b1;
                            rsp_error_code <= ERR_PAIR_BOUNDS;
                        end else begin
                            pair_index <= index_value[15:0];
                            pair_slot <= index_value[PAIR_INDEX_WIDTH-1:0];
                            record_base <= (index_value[15:0] << 4)
                                + (index_value[15:0] << 1);
                            accepted_lane_mask <= lane_mask;
                            issue_word <= 0;
                            receive_word <= 0;
                            lane0_window <= '0;
                            lane1_window <= '0;
                            lane0_length <= '0;
                            lane1_length <= '0;
                            state <= S_COMPOSE;
                        end
                    end
                end

                S_COMPOSE: begin
                    if (bank0_bounds_error
                        || (accepted_lane_mask[1] && bank1_bounds_error)) begin
                        rsp_error <= 1'b1;
                        rsp_error_code <= ERR_BANK_BOUNDS;
                        state <= S_IDLE;
                    end else begin
                        if (bank0_read_accept
                            && (!accepted_lane_mask[1] || bank1_read_accept))
                            issue_word <= issue_word + 1'b1;

                        if (bank0_response_valid
                            && (!accepted_lane_mask[1] || bank1_response_valid)) begin
                            if (receive_word == 0) begin
                                lane0_length <= bank0_read_data[7:0];
                                if (accepted_lane_mask[1])
                                    lane1_length <= bank1_read_data[7:0];
                            end else begin
                                lane0_window[64*(receive_word-1) +: 64]
                                    <= bank0_read_data;
                                if (accepted_lane_mask[1])
                                    lane1_window[64*(receive_word-1) +: 64]
                                        <= bank1_read_data;
                            end

                            if (receive_word == 6'd17) begin
                                if (lane0_length > 135
                                    || (accepted_lane_mask[1]
                                        && lane1_length > 135)) begin
                                    rsp_error <= 1'b1;
                                    rsp_error_code <= ERR_MESSAGE_LENGTH;
                                    state <= S_IDLE;
                                end else begin
                                    state <= S_LAUNCH;
                                end
                            end else begin
                                receive_word <= receive_word + 1'b1;
                            end
                        end
                    end
                end

                S_LAUNCH: begin
                    if (lane0_ready && (!accepted_lane_mask[1] || lane1_ready)) begin
                        lane0_start <= 1'b1;
                        lane1_start <= accepted_lane_mask[1];
                        pending_mask <= accepted_lane_mask;
                        lane_active_mask <= accepted_lane_mask;
                        pair_dispatch_valid <= 1'b1;
                        pair_dispatch_lane_mask <= accepted_lane_mask;
                        pair_dispatch_index <= pair_index;
                        state <= S_WAIT;
                    end
                end

                S_WAIT: begin
                    if ((pending_mask[0] && lane0_error)
                        || (pending_mask[1] && lane1_error)) begin
                        lane_active_mask <= 2'b00;
                        pending_mask <= 2'b00;
                        rsp_error <= 1'b1;
                        rsp_error_code <= ERR_MESSAGE_LENGTH;
                        state <= S_IDLE;
                    end else begin
                        if (pending_mask[0] && lane0_done) begin
                            lane0_results[256*pair_slot +: 256] <= lane0_digest;
                            pending_mask[0] <= 1'b0;
                        end
                        if (pending_mask[1] && lane1_done) begin
                            lane1_results[256*pair_slot +: 256] <= lane1_digest;
                            pending_mask[1] <= 1'b0;
                        end
                        if ((pending_mask & ~{lane1_done, lane0_done}) == 2'b00) begin
                            result_masks[2*pair_slot +: 2] <= accepted_lane_mask;
                            lane_active_mask <= 2'b00;
                            pending_mask <= 2'b00;
                            rsp_valid <= 1'b1;
                            state <= S_IDLE;
                        end
                    end
                end

                default: begin
                    lane_active_mask <= 2'b00;
                    pending_mask <= 2'b00;
                    rsp_error <= 1'b1;
                    rsp_error_code <= ERR_UNSUPPORTED_LAYOUT;
                    state <= S_IDLE;
                end
            endcase
        end
    end
endmodule

`default_nettype wire
