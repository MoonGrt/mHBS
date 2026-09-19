`timescale 1ns/1ps
`default_nettype none

module tb_micro_hbs_unified_top;
    logic clk = 0;
    logic rst_n = 0;
    logic job_valid = 0;
    wire job_ready;
    logic [1:0] job_algorithm = 0;
    logic [1:0] job_operation = 0;
    logic [31:0] job_message_length = 0;
    logic [10:0] job_initial_q = 0;
    logic [255:0] job_secret_seed = 0;
    logic [255:0] job_secret_prf = 0;
    logic [255:0] job_public_seed = 0;
    logic [255:0] job_public_root = 0;
    logic [255:0] job_randomizer = 0;
    logic [127:0] job_identifier = 0;
    logic message_valid = 0;
    wire message_ready;
    logic [63:0] message_data = 0;
    logic [7:0] message_keep = 0;
    logic message_last = 0;
    wire state_commit_valid;
    logic state_commit_ready = 1;
    wire [10:0] state_next_q;
    wire out_valid;
    logic out_ready = 1;
    wire [63:0] out_data;
    wire [7:0] out_keep;
    wire out_last, busy, done, error;
    wire [15:0] error_code;
    wire [31:0] hash_contexts, keccak_permutations;
    wire [31:0] lane0_active_cycles, lane1_active_cycles;
    wire tree_cache_valid;
    logic [63:0] expected [0:11];
    integer cycles = 0;
    integer words = 0;

    always #5 clk = ~clk;

    micro_hbs_unified_top #(.PROFILE_ENABLE(1'b1)) dut (.*);

    always @(posedge clk) begin
        cycles <= cycles + 1;
        if (cycles > 60000)
            $fatal(1, "unified dispatcher timeout state=%0d", dut.state);
        if (out_valid && out_ready) begin
            if (out_keep !== 8'hff || out_data !== expected[words])
                $fatal(1, "unified SLH keygen mismatch word=%0d", words);
            if (out_last !== (words == 11))
                $fatal(1, "unified SLH keygen last mismatch word=%0d", words);
            words <= words + 1;
        end
    end

    task tick; begin @(posedge clk); #1; end endtask

    task submit(input [1:0] algorithm, input [1:0] operation);
        begin
            job_algorithm = algorithm;
            job_operation = operation;
            job_valid = 1;
            while (!job_ready) tick();
            tick();
            job_valid = 0;
        end
    endtask

    task expect_reject(input [15:0] expected_code);
        begin
            while (!error) tick();
            if (error_code !== expected_code)
                $fatal(1, "reject code got=%h expected=%h",
                       error_code, expected_code);
            job_valid = 0;
            tick();
            while (busy) tick();
        end
    endtask

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

        job_secret_seed[127:0]
            = 128'h61d0260374f07a90fc224d1b39ab5639;
        job_secret_prf[127:0]
            = 128'he4b33977d786e0eb862b6f4306b20eab;
        job_public_seed[127:0]
            = 128'ha39dcc7d4c7101b2a67f4e9f225c5056;
        submit(2'd0, 2'd0);
        while (!done && !error) tick();
        if (error || words != 12 || keccak_permutations != 4527)
            $fatal(1, "unified SLH Keygen failed error=%0d words=%0d perm=%0d",
                   error, words, keccak_permutations);
        tick();

        submit(2'd3, 2'd0);
        expect_reject(16'h2701);
        submit(2'd0, 2'd2);
        expect_reject(16'h2702);

        job_secret_seed[255] = 1;
        submit(2'd0, 2'd0);
        expect_reject(16'h2703);
        job_secret_seed[255] = 0;

        // Stateful Sign is rejected until the matching family has completed
        // Keygen and committed its cache/profile tag.
        job_message_length = 1;
        submit(2'd1, 2'd1);
        expect_reject(16'h2501);

        $display("UNIFIED_DISPATCH_PASS cycles=%0d", cycles);
        $finish;
    end
endmodule

`default_nettype wire
