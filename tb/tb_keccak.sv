`timescale 1ns/1ps
module tb_keccak;
    logic [1599:0] state_in;
    logic [4:0] round_index;
    wire [1599:0] state_out;
    logic [3204:0] vectors[0:815];
    string vector_file;
    integer count;
    keccak dut(.*);
    initial begin
        if (!$value$plusargs("VECTOR=%s", vector_file)
            || !$value$plusargs("COUNT=%d", count)) $fatal(1,"missing vectors");
        $readmemh(vector_file, vectors);
        for (integer i=0; i<count; i=i+1) begin
            {round_index,state_in}=vectors[i][3204:1600];
            #1;
            if (state_out !== vectors[i][1599:0])
                $fatal(1,"round %0d vector %0d mismatch",round_index,i);
        end
        $display("KECCAK_ROUND_PASS vectors=%0d",count);
        $finish;
    end
endmodule
