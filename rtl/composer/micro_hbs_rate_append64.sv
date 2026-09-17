`timescale 1ns/1ps
`default_nettype none

// Select up to one 64-bit word for the descriptor-driven SHAKE rate buffer.
// The append is bounded by the component, the current Scratchpad word and the
// 136-byte SHAKE256 rate.  Byte zero in append_data is always the next stream
// byte; the caller advances all counters by append_bytes after accepting it.
module micro_hbs_rate_append64 (
    input  wire [7:0]  component_kind,
    input  wire [7:0]  component_remaining,
    input  wire [31:0] component_immediate,
    input  wire [63:0] source_a_word,
    input  wire [63:0] source_b_word,
    input  wire [2:0]  source_byte_index,
    input  wire [7:0]  rate_fill,
    output logic [63:0] append_data,
    output logic [3:0]  append_bytes
);
    localparam logic [7:0] COMP_LITERAL_BE          = 8'h01;
    localparam logic [7:0] COMP_ZERO                = 8'h02;
    localparam logic [7:0] COMP_REGISTER_BE32       = 8'h03;
    localparam logic [7:0] COMP_SCRATCH             = 8'h04;
    localparam logic [7:0] COMP_SCRATCH_XOR         = 8'h05;
    localparam logic [7:0] COMP_AFFINE_BE32         = 8'h06;
    localparam logic [7:0] COMP_SHIFTED_AFFINE_BE32 = 8'h07;
    localparam logic [7:0] COMP_SELECT_SCRATCH      = 8'h08;

    logic source_kind;
    logic [3:0] selected_bytes;
    logic [8:0] rate_limit;
    logic [3:0] source_limit;
    logic [63:0] immediate_data;
    logic [63:0] selected_data;
    logic [63:0] append_mask;
    wire [5:0] source_shift = {source_byte_index, 3'b000};
    wire [63:0] source_a_aligned = source_a_word >> source_shift;
    wire [63:0] source_b_aligned = source_b_word >> source_shift;

    always_comb begin
        source_kind = component_kind == COMP_SCRATCH
            || component_kind == COMP_SCRATCH_XOR
            || component_kind == COMP_SELECT_SCRATCH;

        rate_limit = rate_fill < 8'd136
            ? 9'd136 - {1'b0, rate_fill} : 9'd0;
        source_limit = source_kind
            ? 4'd8 - {1'b0, source_byte_index} : 4'd8;

        selected_bytes = component_remaining < 8
            ? component_remaining[3:0] : 4'd8;
        if ({5'b0, source_limit} < {5'b0, selected_bytes})
            selected_bytes = source_limit;
        if (rate_limit < {5'b0, selected_bytes})
            selected_bytes = rate_limit[3:0];
        append_bytes = selected_bytes;

        // Immediate components are at most four bytes.  Reverse only the
        // still-unconsumed big-endian suffix so byte zero is the next byte.
        case (component_remaining)
            8'd1: immediate_data = {56'b0, component_immediate[7:0]};
            8'd2: immediate_data = {
                48'b0, component_immediate[7:0],
                component_immediate[15:8]};
            8'd3: immediate_data = {
                40'b0, component_immediate[7:0],
                component_immediate[15:8], component_immediate[23:16]};
            8'd4: immediate_data = {
                32'b0, component_immediate[7:0],
                component_immediate[15:8], component_immediate[23:16],
                component_immediate[31:24]};
            default: immediate_data = 64'b0;
        endcase

        case (component_kind)
            COMP_LITERAL_BE, COMP_REGISTER_BE32,
            COMP_AFFINE_BE32, COMP_SHIFTED_AFFINE_BE32:
                selected_data = immediate_data;
            COMP_ZERO:
                selected_data = 64'b0;
            COMP_SCRATCH, COMP_SELECT_SCRATCH:
                selected_data = source_a_aligned;
            COMP_SCRATCH_XOR:
                selected_data = source_a_aligned ^ source_b_aligned;
            default:
                selected_data = 64'b0;
        endcase

        case (selected_bytes)
            4'd0: append_mask = 64'h0000000000000000;
            4'd1: append_mask = 64'h00000000000000ff;
            4'd2: append_mask = 64'h000000000000ffff;
            4'd3: append_mask = 64'h0000000000ffffff;
            4'd4: append_mask = 64'h00000000ffffffff;
            4'd5: append_mask = 64'h000000ffffffffff;
            4'd6: append_mask = 64'h0000ffffffffffff;
            4'd7: append_mask = 64'h00ffffffffffffff;
            default: append_mask = 64'hffffffffffffffff;
        endcase
        append_data = selected_data & append_mask;
    end
endmodule

`default_nettype wire
