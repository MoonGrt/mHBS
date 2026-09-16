`timescale 1ns/1ps
`default_nettype none

module tb_micro_hbs_digit_unpack;
    localparam integer INPUT_BYTES = 34;
    localparam integer FORS_DIGIT_BITS = 6;
    localparam integer FORS_COUNT = 33;
    localparam integer NIBBLE_COUNT = 68;

    logic [8*INPUT_BYTES-1:0] stream;
    wire [FORS_DIGIT_BITS*FORS_COUNT-1:0] fors_digits;
    wire [4*NIBBLE_COUNT-1:0] nibble_digits;
    integer index;

    micro_hbs_digit_unpack #(
        .INPUT_BYTES(INPUT_BYTES),
        .DIGIT_BITS(FORS_DIGIT_BITS),
        .COUNT(FORS_COUNT)
    ) fors_dut (
        .stream(stream),
        .digits(fors_digits)
    );

    micro_hbs_digit_unpack #(
        .INPUT_BYTES(INPUT_BYTES),
        .DIGIT_BITS(4),
        .COUNT(NIBBLE_COUNT)
    ) nibble_dut (
        .stream(stream),
        .digits(nibble_digits)
    );

    function automatic [5:0] expected_fors_index(input integer digit_index);
        begin
            case (digit_index)
                 0: expected_fors_index = 38;
                 1: expected_fors_index = 43;
                 2: expected_fors_index = 33;
                 3: expected_fors_index = 13;
                 4: expected_fors_index = 1;
                 5: expected_fors_index = 47;
                 6: expected_fors_index = 25;
                 7: expected_fors_index = 11;
                 8: expected_fors_index = 23;
                 9: expected_fors_index = 58;
                10: expected_fors_index = 1;
                11: expected_fors_index = 42;
                12: expected_fors_index = 32;
                13: expected_fors_index = 43;
                14: expected_fors_index = 5;
                15: expected_fors_index = 3;
                16: expected_fors_index = 43;
                17: expected_fors_index = 47;
                18: expected_fors_index = 25;
                19: expected_fors_index = 41;
                20: expected_fors_index = 57;
                21: expected_fors_index = 22;
                22: expected_fors_index = 5;
                23: expected_fors_index = 0;
                24: expected_fors_index = 49;
                25: expected_fors_index = 26;
                26: expected_fors_index = 53;
                27: expected_fors_index = 63;
                28: expected_fors_index = 39;
                29: expected_fors_index = 34;
                30: expected_fors_index = 10;
                31: expected_fors_index = 42;
                32: expected_fors_index = 5;
                default: expected_fors_index = 0;
            endcase
        end
    endfunction

    task automatic check_all_fors(input [5:0] expected);
        begin
            for (index = 0; index < FORS_COUNT; index = index + 1)
                if (fors_digits[FORS_DIGIT_BITS*index +: FORS_DIGIT_BITS] !== expected)
                    $fatal(1, "FORS boundary digit %0d got=%0d expected=%0d",
                           index,
                           fors_digits[FORS_DIGIT_BITS*index +: FORS_DIGIT_BITS],
                           expected);
        end
    endtask

    task automatic check_all_nibbles(input [3:0] expected);
        begin
            for (index = 0; index < NIBBLE_COUNT; index = index + 1)
                if (nibble_digits[4*index +: 4] !== expected)
                    $fatal(1, "nibble boundary digit %0d got=%0d expected=%0d",
                           index, nibble_digits[4*index +: 4], expected);
        end
    endtask

    initial begin
        // NIST ACVP SLH-DSA-SHAKE-128f sigGen tc137 H_msg digest.
        stream = 272'h9ab84d06f64b5fa06a82b143aef669e56140c5ad7f9e22aa1609d614680b3d52e9fa;
        #1;
        for (index = 0; index < FORS_COUNT; index = index + 1)
            if (fors_digits[FORS_DIGIT_BITS*index +: FORS_DIGIT_BITS] !==
                expected_fors_index(index))
                $fatal(1, "tc137 FORS index %0d got=%0d expected=%0d",
                       index,
                       fors_digits[FORS_DIGIT_BITS*index +: FORS_DIGIT_BITS],
                       expected_fors_index(index));

        // The 4-bit configuration consumes the same byte string nibble-wise.
        for (index = 0; index < NIBBLE_COUNT; index = index + 1)
            if (nibble_digits[4*index +: 4] !==
                stream[8*INPUT_BYTES-1-4*index -: 4])
                $fatal(1, "4-bit digit %0d mismatch", index);

        stream = '0;
        #1;
        check_all_fors(6'd0);
        check_all_nibbles(4'd0);

        stream = '1;
        #1;
        check_all_fors(6'd63);
        check_all_nibbles(4'd15);

        // Digit one contains the low two bits of byte zero followed by the
        // high four bits of byte one, so exercise both ends of that crossing.
        stream = '0;
        stream[265] = 1'b1;
        stream[260] = 1'b1;
        #1;
        if (fors_digits[6*1 +: 6] !== 6'd33 ||
            fors_digits[6*0 +: 6] !== 0 ||
            fors_digits[6*2 +: 6] !== 0)
            $fatal(1, "cross-byte FORS digit mismatch");

        // FORS consumes 198 high-order bits.  The final digit occupies the
        // high six bits of byte 24; the lower 74 stream bits must be ignored.
        stream = '0;
        stream[74] = 1'b1;
        #1;
        if (fors_digits[6*32 +: 6] !== 6'd1)
            $fatal(1, "final consumed-bit FORS boundary mismatch");
        stream[73] = 1'b1;
        #1;
        if (fors_digits[6*32 +: 6] !== 6'd1)
            $fatal(1, "unused bit changed final FORS digit");
        for (index = 0; index < 32; index = index + 1)
            if (fors_digits[6*index +: 6] !== 0)
                $fatal(1, "unused-bit boundary leaked into FORS digit %0d", index);

        // The 4-bit instance consumes all 272 bits, including the low edge.
        stream = '0;
        stream[271] = 1'b1;
        stream[0] = 1'b1;
        #1;
        if (nibble_digits[0 +: 4] !== 4'd8 ||
            nibble_digits[4*(NIBBLE_COUNT-1) +: 4] !== 4'd1)
            $fatal(1, "4-bit MSB/LSB boundary mismatch");

        $display("PASS generic MSB-first digit unpack: tc137 FORS-33, 4-bit, and boundaries");
        $finish;
    end
endmodule

`default_nettype wire
