`timescale 1ns/1ps
`default_nettype none

module tb_micro_hbs_generic_keygen_top;
    logic clk = 0;
    logic rst_n = 0;
    logic job_valid = 0;
    wire job_ready;
    logic [31:0] job_message_length = 0;
    logic [127:0] job_sk_seed = 128'h61d0260374f07a90fc224d1b39ab5639;
    logic [127:0] job_sk_prf = 128'he4b33977d786e0eb862b6f4306b20eab;
    logic [127:0] job_pk_seed = 128'ha39dcc7d4c7101b2a67f4e9f225c5056;
    logic [127:0] job_pk_root = 0;
    logic [127:0] job_opt_rand = 0;
    logic message_valid = 0;
    wire message_ready;
    logic [63:0] message_data = 0;
    logic [7:0] message_keep = 0;
    logic message_last = 0;
    wire out_valid;
    logic out_ready = 1;
    wire [63:0] out_data;
    wire [7:0] out_keep;
    wire out_last, busy, done, error;
    wire [15:0] error_code;
    wire [31:0] hash_contexts, keccak_permutations;
    wire [31:0] lane0_active_cycles, lane1_active_cycles;
    logic [63:0] expected [0:11];
    integer cycles = 0;
    integer words = 0;

    always #5 clk = ~clk;

    micro_hbs_horizontal_slh_dsa_keygen_top #(
        .PROFILE_ENABLE(1'b1)
    ) dut (.*);

    always @(posedge clk) begin
        cycles <= cycles + 1;
        if (cycles > 50000)
            $fatal(1, "generic keygen timeout state=%0d", dut.engine.state);
        if (out_valid && out_ready) begin
            if (out_keep !== 8'hff || out_data !== expected[words])
                $fatal(1, "generic keygen mismatch word=%0d got=%h expected=%h state=%0d",
                    words, out_data, expected[words], dut.engine.state);
            if (out_last !== (words == 11))
                $fatal(1, "generic keygen last mismatch word=%0d", words);
            words <= words + 1;
        end
    end

    task tick; begin @(posedge clk); #1; end endtask
    initial begin
        expected[0]=64'hfc224d1b39ab5639;
        expected[1]=64'h61d0260374f07a90;
        expected[2]=64'h862b6f4306b20eab;
        expected[3]=64'he4b33977d786e0eb;
        expected[4]=64'ha67f4e9f225c5056;
        expected[5]=64'ha39dcc7d4c7101b2;
        expected[6]=64'h37fec3241f8f5766;
        expected[7]=64'hdc9ce7e04cc1971c;
        expected[8]=64'ha67f4e9f225c5056;
        expected[9]=64'ha39dcc7d4c7101b2;
        expected[10]=64'h37fec3241f8f5766;
        expected[11]=64'hdc9ce7e04cc1971c;
        repeat (3) tick();
        rst_n = 1;
        tick();
        job_valid = 1;
        while (!job_ready) tick();
        tick();
        job_valid = 0;
        while (!done && !error) tick();
        if (error)
            $fatal(1, "generic keygen error=%h state=%0d",
                   error_code, dut.engine.state);
        if (words != 12)
            $fatal(1, "generic keygen words=%0d", words);
        if (keccak_permutations != 4527)
            $fatal(1, "generic keygen permutations=%0d", keccak_permutations);
        $display("GENERIC_KEYGEN_PASS cycles=%0d contexts=%0d permutations=%0d",
            cycles, hash_contexts, keccak_permutations);
        $finish;
    end
endmodule

`default_nettype wire
