`timescale 1ns/1ps
`default_nettype none

// Layout-driven randomized hash capability used by XMSS/WOTS+/SLH-DSA.
// NODE_COUNT=1 performs KEY, BM0, F; NODE_COUNT=2 performs KEY, BM0, BM1, H.
// Byte zero of each packed byte string is in bits [7:0].
module micro_hbs_randomized_hash #(
    parameter integer NODE_COUNT = 1,
    parameter integer UNROLL = 2
) (
    input  wire         clk,
    input  wire         rst_n,
    input  wire         start,
    output logic        ready,
    input  wire [255:0] pub_seed,
    input  wire [255:0] address,
    input  wire [511:0] node_data,
    output logic [255:0] digest,
    output logic        done,
    output logic        error,
    output logic [2:0]  hash_calls
);
    typedef enum logic [3:0] {
        S_IDLE, S_KEY_START, S_KEY_WAIT, S_MASK0_START, S_MASK0_WAIT,
        S_MASK1_START, S_MASK1_WAIT, S_FINAL_START, S_FINAL_WAIT
    } state_t;
    state_t state;

    logic [255:0] saved_seed;
    logic [255:0] saved_address;
    logic [511:0] saved_data;
    logic [255:0] key_value;
    logic [255:0] mask0_value;
    logic [255:0] mask1_value;
    logic [1087:0] shake_message;
    logic [7:0] shake_length;
    logic shake_start;
    wire shake_ready;
    wire [255:0] shake_digest;
    wire shake_done;
    wire shake_error;
    integer byte_index;

    assign ready = (state == S_IDLE);
    assign shake_start = (state == S_KEY_START || state == S_MASK0_START ||
                          state == S_MASK1_START || state == S_FINAL_START) && shake_ready;

    always_comb begin
        shake_message = '0;
        shake_length = 8'd96;
        if (state == S_KEY_START || state == S_MASK0_START || state == S_MASK1_START) begin
            shake_message[8*31 +: 8] = 8'h03;
            for (byte_index = 0; byte_index < 32; byte_index = byte_index + 1) begin
                shake_message[8*(32+byte_index) +: 8] = saved_seed[8*byte_index +: 8];
                shake_message[8*(64+byte_index) +: 8] = saved_address[8*byte_index +: 8];
            end
            shake_message[8*92 +: 8] = 8'h00;
            shake_message[8*93 +: 8] = 8'h00;
            shake_message[8*94 +: 8] = 8'h00;
            if (state == S_KEY_START)
                shake_message[8*95 +: 8] = 8'h00;
            else if (state == S_MASK0_START)
                shake_message[8*95 +: 8] = 8'h01;
            else
                shake_message[8*95 +: 8] = 8'h02;
        end else if (state == S_FINAL_START) begin
            shake_message[8*31 +: 8] = NODE_COUNT == 1 ? 8'h00 : 8'h01;
            for (byte_index = 0; byte_index < 32; byte_index = byte_index + 1) begin
                shake_message[8*(32+byte_index) +: 8] = key_value[8*byte_index +: 8];
                shake_message[8*(64+byte_index) +: 8] =
                    saved_data[8*byte_index +: 8] ^ mask0_value[8*byte_index +: 8];
                if (NODE_COUNT == 2)
                    shake_message[8*(96+byte_index) +: 8] =
                        saved_data[8*(32+byte_index) +: 8] ^ mask1_value[8*byte_index +: 8];
            end
            shake_length = NODE_COUNT == 1 ? 8'd96 : 8'd128;
        end
    end

    micro_hbs_shake256_single_block #(.UNROLL(UNROLL)) shake (
        .clk, .rst_n, .start(shake_start), .ready(shake_ready),
        .message(shake_message), .message_length(shake_length),
        .repeat_enable(1'b0), .repeat_prefix(1'b0),
        .repeat_prefix_preserve_counter(1'b0),
        .repeat_prefix_domain(3'b0), .repeat_count(8'd1),
        .repeat_counter_offset(8'b0), .repeat_feedback_offset(8'b0),
        .repeat_feedback_bytes(6'b0), .repeat_counter_start(32'b0),
        .capture_enable(1'b0), .capture_after(8'b0),
        .capture_digest(), .capture_valid(),
        .digest(shake_digest), .done(shake_done), .error(shake_error)
    );

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= S_IDLE;
            saved_seed <= '0;
            saved_address <= '0;
            saved_data <= '0;
            key_value <= '0;
            mask0_value <= '0;
            mask1_value <= '0;
            digest <= '0;
            done <= 1'b0;
            error <= 1'b0;
            hash_calls <= '0;
        end else begin
            done <= 1'b0;
            error <= 1'b0;
            case (state)
                S_IDLE: if (start) begin
                    if (NODE_COUNT != 1 && NODE_COUNT != 2) begin
                        error <= 1'b1;
                    end else begin
                        saved_seed <= pub_seed;
                        saved_address <= address;
                        saved_data <= node_data;
                        hash_calls <= '0;
                        state <= S_KEY_START;
                    end
                end
                S_KEY_START: if (shake_ready) state <= S_KEY_WAIT;
                S_KEY_WAIT: if (shake_error) begin error <= 1'b1; state <= S_IDLE; end
                            else if (shake_done) begin key_value <= shake_digest; hash_calls <= hash_calls + 1'b1; state <= S_MASK0_START; end
                S_MASK0_START: if (shake_ready) state <= S_MASK0_WAIT;
                S_MASK0_WAIT: if (shake_error) begin error <= 1'b1; state <= S_IDLE; end
                              else if (shake_done) begin mask0_value <= shake_digest; hash_calls <= hash_calls + 1'b1; state <= NODE_COUNT == 2 ? S_MASK1_START : S_FINAL_START; end
                S_MASK1_START: if (shake_ready) state <= S_MASK1_WAIT;
                S_MASK1_WAIT: if (shake_error) begin error <= 1'b1; state <= S_IDLE; end
                              else if (shake_done) begin mask1_value <= shake_digest; hash_calls <= hash_calls + 1'b1; state <= S_FINAL_START; end
                S_FINAL_START: if (shake_ready) state <= S_FINAL_WAIT;
                S_FINAL_WAIT: if (shake_error) begin error <= 1'b1; state <= S_IDLE; end
                              else if (shake_done) begin digest <= shake_digest; hash_calls <= hash_calls + 1'b1; done <= 1'b1; state <= S_IDLE; end
                default: begin error <= 1'b1; state <= S_IDLE; end
            endcase
        end
    end
endmodule

`default_nettype wire
