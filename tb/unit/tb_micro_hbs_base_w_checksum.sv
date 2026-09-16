`timescale 1ns/1ps
`default_nettype none

module tb_micro_hbs_base_w_checksum;
    logic [255:0] digest;
    logic [535:0] chain_lengths;
    integer index;
    integer nibble;
    integer total;

    micro_hbs_base_w_checksum dut (.digest, .chain_lengths);

    task automatic check_digest_digits;
        begin
            total = 0;
            for (index = 0; index < 64; index = index + 1) begin
                if ((index % 2) == 0)
                    nibble = digest[255-8*(index/2) -: 8] >> 4;
                else
                    nibble = digest[255-8*(index/2) -: 8] & 15;
                if (chain_lengths[8*index +: 8] !== nibble)
                    $fatal(1, "digit %0d got=%0d expected=%0d",
                           index, chain_lengths[8*index +: 8], nibble);
                total = total + chain_lengths[8*index +: 8];
            end
            total = total + chain_lengths[8*64 +: 8]
                          + chain_lengths[8*65 +: 8]
                          + chain_lengths[8*66 +: 8];
        end
    endtask

    initial begin
        digest = 256'hc71f259a96bd2819ba9317caf0665fb6d33543f5802eedae9ad4368590344385;
        #1;
        check_digest_digits();
        if (chain_lengths[8*64 +: 8] !== 8'h01 ||
            chain_lengths[8*65 +: 8] !== 8'h0e ||
            chain_lengths[8*66 +: 8] !== 8'h0d)
            $fatal(1, "KAT checksum digits mismatch");
        if (total != 495) $fatal(1, "KAT chain sum %0d", total);

        digest = '0;
        #1;
        check_digest_digits();
        if (chain_lengths[8*64 +: 8] !== 8'h03 ||
            chain_lengths[8*65 +: 8] !== 8'h0c ||
            chain_lengths[8*66 +: 8] !== 8'h00)
            $fatal(1, "zero checksum digits mismatch");

        digest = '1;
        #1;
        check_digest_digits();
        if (chain_lengths[8*64 +: 8] !== 0 ||
            chain_lengths[8*65 +: 8] !== 0 ||
            chain_lengths[8*66 +: 8] !== 0)
            $fatal(1, "max checksum digits mismatch");

        $display("PASS base-w/checksum KAT and boundary digests");
        $finish;
    end
endmodule

`default_nettype wire
