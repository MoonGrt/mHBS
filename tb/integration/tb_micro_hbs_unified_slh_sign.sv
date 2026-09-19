`timescale 1ns/1ps
`default_nettype none

module tb_micro_hbs_unified_slh_sign #(
    parameter bit SWAP = 1'b0,
    parameter bit BACKPRESSURE = 1'b0
);
    logic clk = 0, rst_n = 0, job_valid = 0;
    wire job_ready;
    logic [1:0] job_algorithm = 0;
    logic [1:0] job_operation = 1;
    logic [31:0] job_message_length = 1;
    logic [10:0] job_initial_q = 0;
    logic [255:0] job_secret_seed
        = 128'hd1d06dcbb9181a55aabce64467d6b81d;
    logic [255:0] job_secret_prf
        = 128'hca423fc52136322bce5c73a684d95cb7;
    logic [255:0] job_public_seed
        = 128'hf416dc35e41222ef87445111008541d5;
    logic [255:0] job_public_root
        = 128'h3d774653892d5f3695b370c7cdab63ff;
    logic [255:0] job_randomizer
        = 128'hf416dc35e41222ef87445111008541d5;
    logic [127:0] job_identifier = 0;
    logic message_valid = 0;
    wire message_ready;
    logic [63:0] message_data = 64'h8f;
    logic [7:0] message_keep = 8'h01;
    logic message_last = 1;
    wire state_commit_valid;
    logic state_commit_ready = 1;
    wire [10:0] state_next_q;
    wire out_valid;
    logic out_ready = 1;
    wire [63:0] out_data;
    wire [7:0] out_keep;
    wire out_last, busy, done, error, tree_cache_valid;
    wire [15:0] error_code;
    wire [31:0] hash_contexts, keccak_permutations;
    wire [31:0] lane0_active_cycles, lane1_active_cycles;
    logic [63:0] expected_signature_words [0:2135];
    logic [7:0] ready_lfsr = 8'ha5;
    integer cycles = 0, output_words = 0;

    always #5 clk = ~clk;
    always @(posedge clk) begin
        if (!rst_n) begin
            ready_lfsr <= 8'ha5;
            out_ready <= 1;
        end else if (BACKPRESSURE) begin
            ready_lfsr <= {ready_lfsr[6:0],
                           ready_lfsr[7] ^ ready_lfsr[5]};
            out_ready <= ready_lfsr[0] | ready_lfsr[2];
        end
    end

    micro_hbs_unified_top #(
        .PROFILE_ENABLE(1'b1), .SWAP_PHYSICAL_LANES(SWAP)
    ) dut (.*);

    always @(posedge clk) begin
        cycles <= cycles + 1;
        if (cycles > 2_000_000) $fatal(1, "unified SLH Sign timeout");
        if (out_valid && out_ready) begin
            if (out_keep !== 8'hff
                || out_data !== expected_signature_words[output_words])
                $fatal(1, "unified SLH signature mismatch word=%0d",
                       output_words);
            if (out_last !== (output_words == 2135))
                $fatal(1, "unified SLH out_last mismatch word=%0d",
                       output_words);
            output_words <= output_words + 1;
        end
        if (state_commit_valid)
            $fatal(1, "stateless SLH unexpectedly requested q commit");
    end

    task tick; begin @(posedge clk); #1; end endtask
    initial begin
        $readmemh(
            "manifests/programs/rtl_images/slh_dsa_shake_128f_signature_expected.hex",
            expected_signature_words);
        repeat (3) tick(); rst_n = 1; tick();
        job_valid = 1; while (!job_ready) tick(); tick(); job_valid = 0;
        while (!message_ready) tick();
        message_valid = 1; tick(); message_valid = 0;
        while (!done && !error) tick();
        if (error || output_words != 2136)
            $fatal(1, "unified SLH Sign failed error=%0d code=%h words=%0d",
                   error, error_code, output_words);
        if (cycles > 1_000_000 || hash_contexts != 10680
            || keccak_permutations != 105641)
            $fatal(1, "unified SLH counters/cycles %0d %0d/%0d",
                   cycles, hash_contexts, keccak_permutations);
        $display("UNIFIED_SLH_SIGN_PASS cycles=%0d contexts=%0d permutations=%0d lane=%0d/%0d",
                 cycles, hash_contexts, keccak_permutations,
                 lane0_active_cycles, lane1_active_cycles);
        $finish;
    end
endmodule

`default_nettype wire
