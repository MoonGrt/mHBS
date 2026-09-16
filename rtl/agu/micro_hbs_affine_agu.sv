`timescale 1ns/1ps
`default_nettype none

// Bounded two-term affine address generator for v2 address bindings.
//
//   address = base + (use_term0 ? value0 * scale0 : 0)
//                  + (use_term1 ? value1 * scale1 : 0)
//
// Both products use one deterministic serial shift/add datapath (16 cycles
// each at most). No inferred multiplier or DSP is required. The complete
// access span is proven before an address becomes visible.
module micro_hbs_affine_agu #(
    parameter integer SCRATCH_WORDS = 512,
    parameter integer ADDRESS_WIDTH = 16
) (
    input  wire                     clk,
    input  wire                     rst_n,
    input  wire                     req_valid,
    output wire                     req_ready,
    input  wire [31:0]              req_base,
    input  wire                     req_use_term0,
    input  wire [31:0]              req_term0_value,
    input  wire [15:0]              req_term0_scale,
    input  wire                     req_use_term1,
    input  wire [31:0]              req_term1_value,
    input  wire [15:0]              req_term1_scale,
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
    localparam logic [15:0] ERR_ZERO_SPAN = 16'h0311;
    localparam logic [15:0] ERR_BOUNDS    = 16'h0312;

    typedef enum logic [2:0] {
        S_IDLE, S_MUL0, S_MUL1, S_CHECK, S_RESPONSE
    } state_t;
    state_t state;
    logic [31:0] base_latched;
    logic [15:0] span_latched;
    logic use_term1_latched;
    logic [31:0] term1_value_latched;
    logic [15:0] term1_scale_latched;
    logic [48:0] product_sum;
    logic [47:0] product;
    logic [47:0] multiplicand;
    logic [15:0] multiplier;
    logic [4:0] multiply_steps;
    wire [49:0] start_sum;
    wire [49:0] last_sum;
    wire [49:0] span_minus_one;
    localparam logic [49:0] SCRATCH_WORDS_EXT = SCRATCH_WORDS;

    assign req_ready = (state == S_IDLE);
    assign rsp_valid = (state == S_RESPONSE);
    assign start_sum = {18'b0, base_latched} + product_sum
        + {2'b0, product};
    assign span_minus_one = (span_latched == 0)
        ? 50'b0 : ({34'b0, span_latched} - 1'b1);
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
            span_latched <= '0;
            use_term1_latched <= 1'b0;
            term1_value_latched <= '0;
            term1_scale_latched <= '0;
            product_sum <= '0;
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
                S_IDLE: if (req_valid) begin
                    base_latched <= req_base;
                    span_latched <= req_span_words;
                    use_term1_latched <= req_use_term1;
                    term1_value_latched <= req_term1_value;
                    term1_scale_latched <= req_term1_scale;
                    product_sum <= '0;
                    product <= '0;
                    multiplicand <= {16'b0, req_term0_value};
                    multiplier <= req_term0_scale;
                    multiply_steps <= '0;
                    rsp_error <= 1'b0;
                    rsp_error_code <= ERR_NONE;
                    rsp_address <= '0;
                    rsp_last_address <= '0;
                    accepted_requests <= accepted_requests + 1'b1;
                    if (req_use_term0 && req_term0_value != 0
                        && req_term0_scale != 0)
                        state <= S_MUL0;
                    else if (req_use_term1 && req_term1_value != 0
                             && req_term1_scale != 0) begin
                        multiplicand <= {16'b0, req_term1_value};
                        multiplier <= req_term1_scale;
                        state <= S_MUL1;
                    end else
                        state <= S_CHECK;
                end

                S_MUL0: begin
                    if (multiplier[0])
                        product <= product + multiplicand;
                    multiplicand <= multiplicand << 1;
                    multiplier <= multiplier >> 1;
                    if (multiply_steps == 15) begin
                        // Include the last conditional add because nonblocking
                        // product is not visible until after this clock edge.
                        product_sum <= product_sum + {1'b0, product}
                            + (multiplier[0] ? {1'b0, multiplicand} : 49'b0);
                        product <= '0;
                        multiplicand <= {16'b0, term1_value_latched};
                        multiplier <= term1_scale_latched;
                        multiply_steps <= '0;
                        if (use_term1_latched && term1_value_latched != 0
                            && term1_scale_latched != 0)
                            state <= S_MUL1;
                        else
                            state <= S_CHECK;
                    end else
                        multiply_steps <= multiply_steps + 1'b1;
                end

                S_MUL1: begin
                    if (multiplier[0])
                        product <= product + multiplicand;
                    multiplicand <= multiplicand << 1;
                    multiplier <= multiplier >> 1;
                    if (multiply_steps == 15) begin
                        product_sum <= product_sum + {1'b0, product}
                            + (multiplier[0] ? {1'b0, multiplicand} : 49'b0);
                        product <= '0;
                        multiply_steps <= '0;
                        state <= S_CHECK;
                    end else
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

                S_RESPONSE: if (rsp_ready) begin
                    completed_responses <= completed_responses + 1'b1;
                    state <= S_IDLE;
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
