`timescale 1ns/1ps
`default_nettype none

// Bounded address generator for static microcode descriptors.
//
// Computes, without a DSP multiplier:
//   address = base + (use_base_reg ? base_reg_value : 0)
//                  + (use_index ? index_value * stride : 0)
// and proves that the complete [address, address + span_words) interval is
// inside the local Scratchpad.  The serial shift/add multiply is deliberate:
// descriptor address generation is off the Keccak critical datapath and must
// not consume the DSP budget merely to support uncommon strides.
module micro_hbs_agu #(
    parameter integer SCRATCH_WORDS = 512,
    parameter integer ADDRESS_WIDTH = 16
) (
    input  wire                     clk,
    input  wire                     rst_n,

    input  wire                     req_valid,
    output wire                     req_ready,
    input  wire [31:0]              req_base,
    input  wire                     req_use_base_reg,
    input  wire [31:0]              req_base_reg_value,
    input  wire                     req_use_index,
    input  wire [31:0]              req_index_value,
    input  wire [15:0]              req_stride,
    input  wire [15:0]              req_span_words,

    output wire                     rsp_valid,
    input  wire                     rsp_ready,
    output logic                    rsp_error,
    output logic [15:0]             rsp_error_code,
    output logic [ADDRESS_WIDTH-1:0] rsp_address,
    output logic [ADDRESS_WIDTH-1:0] rsp_last_address,

    output logic [31:0]             accepted_requests,
    output logic [31:0]             completed_responses,
    output logic [31:0]             error_responses
);
    localparam logic [15:0] ERR_NONE      = 16'h0000;
    localparam logic [15:0] ERR_ZERO_SPAN = 16'h0301;
    localparam logic [15:0] ERR_BOUNDS    = 16'h0302;

    typedef enum logic [1:0] {S_IDLE, S_MUL, S_CHECK, S_RESPONSE} state_t;
    state_t state;

    logic [31:0] base_latched;
    logic [31:0] base_reg_latched;
    logic [15:0] span_latched;
    logic [47:0] product;
    logic [47:0] multiplicand;
    logic [15:0] multiplier;
    logic [4:0] multiply_steps;

    logic [48:0] start_sum;
    logic [48:0] last_sum;
    logic [48:0] span_minus_one;
    localparam logic [48:0] SCRATCH_WORDS_EXT = SCRATCH_WORDS;

    assign req_ready = (state == S_IDLE);
    assign rsp_valid = (state == S_RESPONSE);
    assign start_sum = {17'b0, base_latched}
        + {17'b0, base_reg_latched}
        + {1'b0, product};
    assign span_minus_one = (span_latched == 0)
        ? 49'b0 : ({33'b0, span_latched} - 1'b1);
    assign last_sum = start_sum + span_minus_one;

    initial begin
        if (SCRATCH_WORDS < 1 || SCRATCH_WORDS > (1 << ADDRESS_WIDTH))
            $error("invalid SCRATCH_WORDS/ADDRESS_WIDTH");
        if (ADDRESS_WIDTH < 1 || ADDRESS_WIDTH > 32)
            $error("ADDRESS_WIDTH must be in 1..32");
    end

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= S_IDLE;
            base_latched <= '0;
            base_reg_latched <= '0;
            span_latched <= '0;
            product <= '0;
            multiplicand <= '0;
            multiplier <= '0;
            multiply_steps <= '0;
            rsp_error <= 1'b0;
            rsp_error_code <= ERR_NONE;
            rsp_address <= '0;
            rsp_last_address <= '0;
            accepted_requests <= '0;
            completed_responses <= '0;
            error_responses <= '0;
        end else begin
            case (state)
                S_IDLE: begin
                    if (req_valid) begin
                        base_latched <= req_base;
                        base_reg_latched <= req_use_base_reg
                            ? req_base_reg_value : 32'b0;
                        span_latched <= req_span_words;
                        product <= 48'b0;
                        multiplicand <= {16'b0, req_index_value};
                        multiplier <= req_use_index ? req_stride : 16'b0;
                        multiply_steps <= 5'b0;
                        rsp_error <= 1'b0;
                        rsp_error_code <= ERR_NONE;
                        rsp_address <= '0;
                        rsp_last_address <= '0;
                        accepted_requests <= accepted_requests + 1'b1;
                        if (!req_use_index || req_index_value == 0
                            || req_stride == 0)
                            state <= S_CHECK;
                        else
                            state <= S_MUL;
                    end
                end

                S_MUL: begin
                    if (multiplier[0])
                        product <= product + multiplicand;
                    multiplicand <= multiplicand << 1;
                    multiplier <= multiplier >> 1;
                    if (multiply_steps == 15)
                        state <= S_CHECK;
                    else
                        multiply_steps <= multiply_steps + 1'b1;
                end

                S_CHECK: begin
                    if (span_latched == 0) begin
                        rsp_error <= 1'b1;
                        rsp_error_code <= ERR_ZERO_SPAN;
                        error_responses <= error_responses + 1'b1;
                    end else if (start_sum >= SCRATCH_WORDS_EXT
                                 || last_sum >= SCRATCH_WORDS_EXT) begin
                        rsp_error <= 1'b1;
                        rsp_error_code <= ERR_BOUNDS;
                        error_responses <= error_responses + 1'b1;
                    end else begin
                        rsp_error <= 1'b0;
                        rsp_error_code <= ERR_NONE;
                        rsp_address <= start_sum[ADDRESS_WIDTH-1:0];
                        rsp_last_address <= last_sum[ADDRESS_WIDTH-1:0];
                    end
                    state <= S_RESPONSE;
                end

                S_RESPONSE: begin
                    if (rsp_ready) begin
                        completed_responses <= completed_responses + 1'b1;
                        state <= S_IDLE;
                    end
                end

                default: begin
                    rsp_error <= 1'b1;
                    rsp_error_code <= ERR_BOUNDS;
                    error_responses <= error_responses + 1'b1;
                    state <= S_RESPONSE;
                end
            endcase
        end
    end
endmodule

`default_nettype wire
