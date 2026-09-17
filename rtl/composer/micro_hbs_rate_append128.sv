`timescale 1ns/1ps
`default_nettype none

// Select up to two 64-bit words for the descriptor-driven SHAKE rate buffer.
// Byte zero in append_data is the next message byte.  Scratch sources expose
// either an 8-byte scalar window or a 16-byte banked/local-feedback window.
module micro_hbs_rate_append128 (
    input  wire [7:0]   component_kind,
    input  wire [7:0]   component_remaining,
    input  wire [31:0]  component_immediate,
    input  wire [127:0] source_a_data,
    input  wire [127:0] source_b_data,
    input  wire [4:0]   source_window_bytes,
    input  wire [3:0]   source_byte_index,
    input  wire [7:0]   rate_fill,
    output logic [127:0] append_data,
    output logic [4:0]   append_bytes
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
    logic [8:0] selected_bytes;
    logic [8:0] source_limit;
    logic [8:0] rate_limit;
    logic [127:0] immediate_data;
    logic [127:0] selected_data;
    logic [127:0] append_mask;
    integer byte_index;

    always_comb begin
        source_kind = component_kind == COMP_SCRATCH
            || component_kind == COMP_SCRATCH_XOR
            || component_kind == COMP_SELECT_SCRATCH;
        source_limit = source_kind
            ? {4'b0, source_window_bytes} - {5'b0, source_byte_index}
            : 9'd16;
        rate_limit = rate_fill < 8'd136
            ? 9'd136 - {1'b0, rate_fill} : 9'd0;

        selected_bytes = component_remaining < 16
            ? {1'b0, component_remaining} : 9'd16;
        if (source_limit < selected_bytes)
            selected_bytes = source_limit;
        if (rate_limit < selected_bytes)
            selected_bytes = rate_limit;
        append_bytes = selected_bytes[4:0];

        immediate_data = '0;
        case (component_remaining)
            8'd1: immediate_data[7:0] = component_immediate[7:0];
            8'd2: immediate_data[15:0] = {
                component_immediate[7:0], component_immediate[15:8]};
            8'd3: immediate_data[23:0] = {
                component_immediate[7:0], component_immediate[15:8],
                component_immediate[23:16]};
            8'd4: immediate_data[31:0] = {
                component_immediate[7:0], component_immediate[15:8],
                component_immediate[23:16], component_immediate[31:24]};
            default: begin end
        endcase

        case (component_kind)
            COMP_LITERAL_BE, COMP_REGISTER_BE32,
            COMP_AFFINE_BE32, COMP_SHIFTED_AFFINE_BE32:
                selected_data = immediate_data;
            COMP_ZERO:
                selected_data = '0;
            COMP_SCRATCH, COMP_SELECT_SCRATCH:
                selected_data = source_a_data >> {source_byte_index, 3'b000};
            COMP_SCRATCH_XOR:
                selected_data = (source_a_data ^ source_b_data)
                    >> {source_byte_index, 3'b000};
            default:
                selected_data = '0;
        endcase

        append_mask = '0;
        for (byte_index = 0; byte_index < 16; byte_index = byte_index + 1)
            if (byte_index < selected_bytes)
                append_mask[8*byte_index +: 8] = 8'hff;
        append_data = selected_data & append_mask;
    end
endmodule

`default_nettype wire
