`timescale 1ns/1ps
module tb_mhbs_keccak_u2;
    logic [1599:0] state_in;
    logic [3:0] pair_index;
    wire [1599:0] actual, middle, expected;
    reg [31:0] rng=32'hb73a91c5;
    integer checks=0;
    mhbs_keccak_u2 dut(.state_in,.pair_index,.state_out(actual));
    mhbs_keccak_baseline reference_even(.state_in,
        .round_index({pair_index,1'b0}),.state_out(middle));
    mhbs_keccak_baseline reference_odd(.state_in(middle),
        .round_index({pair_index,1'b1}),.state_out(expected));
    initial begin
        for(integer pattern=0;pattern<66;pattern=pattern+1)begin
            if(pattern==0)state_in='0;
            else if(pattern==1)state_in='1;
            else for(integer word_index=0;word_index<50;word_index=word_index+1)begin
                rng=rng^(rng<<13);rng=rng^(rng>>17);rng=rng^(rng<<5);
                state_in[word_index*32 +:32]=rng;
            end
            for(integer pair_number=0;pair_number<12;pair_number=pair_number+1)begin
                pair_index=pair_number;
                #1;
                if(actual!==expected)$fatal(1,"U2 mismatch pattern=%0d pair=%0d",pattern,pair_number);
                checks=checks+1;
            end
        end
        $display("KECCAK_U2_EQUIVALENCE_PASS checks=%0d",checks);
        $finish;
    end
endmodule
