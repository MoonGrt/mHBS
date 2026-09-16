`timescale 1ns/1ps
`default_nettype none

// Combinational base-2^b conversion for an MSB-first byte string.
//
// Byte zero occupies stream[8*INPUT_BYTES-1 -: 8].  Digit i is exposed at
// digits[DIGIT_BITS*i +: DIGIT_BITS], matching FIPS 205 Algorithm 4.  Digits
// may cross byte boundaries (for example, the 6-bit FORS indices).
module micro_hbs_digit_unpack #(
    parameter integer INPUT_BYTES = 34,
    parameter integer DIGIT_BITS = 6,
    parameter integer COUNT = 33
) (
    input  wire [8*INPUT_BYTES-1:0]       stream,
    output wire [DIGIT_BITS*COUNT-1:0]    digits
);
    genvar digit_index;
    generate
        for (digit_index = 0; digit_index < COUNT; digit_index = digit_index + 1) begin : g_digit
            assign digits[DIGIT_BITS*digit_index +: DIGIT_BITS] =
                stream[8*INPUT_BYTES-1-DIGIT_BITS*digit_index -: DIGIT_BITS];
        end
    endgenerate

    initial begin
        if (INPUT_BYTES <= 0)
            $error("INPUT_BYTES must be positive");
        if (DIGIT_BITS <= 0)
            $error("DIGIT_BITS must be positive");
        if (COUNT <= 0)
            $error("COUNT must be positive");
        if (DIGIT_BITS * COUNT > 8 * INPUT_BYTES)
            $error("digit output exceeds input bitstream capacity");
    end
endmodule

`default_nettype wire
