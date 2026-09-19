`timescale 1ns/1ps
`default_nettype none

// Joins byte-granular macro results into the existing 64-bit stream.  Partial
// words occur only at the end of a job and are marked through out_keep.
module micro_hbs_byte_output_packer (
    input  wire        clk,
    input  wire        rst_n,
    input  wire        clear,
    input  wire        in_valid,
    output wire        in_ready,
    input  wire [7:0]  in_byte,
    input  wire        in_last,
    output wire        out_valid,
    input  wire        out_ready,
    output logic [63:0] out_data,
    output logic [7:0] out_keep,
    output logic       out_last,
    output wire        idle
);
    logic [2:0] byte_count;
    logic output_valid;
    wire accept_byte = in_valid && in_ready;
    wire accept_output = output_valid && out_ready;

    assign in_ready = !output_valid;
    assign out_valid = output_valid;
    assign idle = !output_valid && byte_count == 0;

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            byte_count <= '0;
            output_valid <= 1'b0;
            out_data <= '0;
            out_keep <= '0;
            out_last <= 1'b0;
        end else if (clear) begin
            byte_count <= '0;
            output_valid <= 1'b0;
            out_data <= '0;
            out_keep <= '0;
            out_last <= 1'b0;
        end else begin
            if (accept_output)
                output_valid <= 1'b0;
            if (accept_byte) begin
                out_data[byte_count*8 +: 8] <= in_byte;
                if (byte_count == 7 || in_last) begin
                    output_valid <= 1'b1;
                    out_keep <= in_last
                        ? (8'hff >> (7-byte_count)) : 8'hff;
                    out_last <= in_last;
                    byte_count <= '0;
                end else
                    byte_count <= byte_count + 1'b1;
            end
        end
    end
endmodule

`default_nettype wire
