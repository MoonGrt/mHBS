`timescale 1ns/1ps
`default_nettype none

// Bounded WOTS post-process capability. Digit i is exposed at [8*i +: 8].
module micro_hbs_base_w_checksum #(
    parameter integer N_BYTES = 32,
    parameter integer LOG_W = 4,
    parameter integer LEN1 = 64,
    parameter integer LEN2 = 3
) (
    input  wire [8*N_BYTES-1:0] digest,
    output logic [8*(LEN1+LEN2)-1:0] chain_lengths
);
    localparam integer W = 1 << LOG_W;
    localparam integer DIGITS_PER_BYTE = 8 / LOG_W;
    localparam integer CHECKSUM_BITS = LEN2 * LOG_W;
    localparam integer CHECKSUM_BYTES = (CHECKSUM_BITS + 7) / 8;
    localparam integer CHECKSUM_SHIFT = 8 - (CHECKSUM_BITS % 8);

    integer digit_index;
    integer byte_index;
    integer digit_in_byte;
    integer bit_shift;
    integer checksum;
    integer shifted_checksum;
    integer value;

    always @* begin
        chain_lengths = '0;
        checksum = 0;
        for (digit_index = 0; digit_index < LEN1; digit_index = digit_index + 1) begin
            byte_index = digit_index / DIGITS_PER_BYTE;
            digit_in_byte = digit_index % DIGITS_PER_BYTE;
            bit_shift = 8 - LOG_W * (digit_in_byte + 1);
            value = (digest[8*(N_BYTES-byte_index)-1 -: 8] >> bit_shift) & (W-1);
            chain_lengths[8*digit_index +: 8] = value[7:0];
            checksum = checksum + (W - 1 - value);
        end
        shifted_checksum = checksum << CHECKSUM_SHIFT;
        for (digit_index = 0; digit_index < LEN2; digit_index = digit_index + 1) begin
            bit_shift = 8*CHECKSUM_BYTES - LOG_W*(digit_index+1);
            value = (shifted_checksum >> bit_shift) & (W-1);
            chain_lengths[8*(LEN1+digit_index) +: 8] = value[7:0];
        end
    end

    initial begin
        if (LOG_W <= 0 || LOG_W > 8 || (8 % LOG_W) != 0)
            $error("LOG_W must divide eight");
        if (LEN1 > N_BYTES * DIGITS_PER_BYTE)
            $error("LEN1 exceeds digest capacity");
    end
endmodule

`default_nettype wire
