`timescale 1ns/1ps
`default_nettype none

module micro_hbs_ordered_pair #(
    parameter integer NODE_BITS = 128
) (
    input  wire                 reverse,
    input  wire [NODE_BITS-1:0] current_node,
    input  wire [NODE_BITS-1:0] auth_node,
    output logic [NODE_BITS-1:0] left_node,
    output logic [NODE_BITS-1:0] right_node
);
    always @* begin
        if (reverse) begin
            left_node = auth_node;
            right_node = current_node;
        end else begin
            left_node = current_node;
            right_node = auth_node;
        end
    end
endmodule

`default_nettype wire
