`timescale 1ns/1ps
`default_nettype none

module tb_micro_hbs_horizontal_slh_dsa_sign_top #(
    parameter bit SWAP = 1'b0
);
    logic clk = 1'b0;
    logic rst_n = 1'b0;
    logic job_valid = 1'b0;
    wire job_ready;
    logic [31:0] job_message_length = 32'd1;
    logic [127:0] job_sk_seed = 128'hd1d06dcbb9181a55aabce64467d6b81d;
    logic [127:0] job_sk_prf = 128'hca423fc52136322bce5c73a684d95cb7;
    logic [127:0] job_pk_seed = 128'hf416dc35e41222ef87445111008541d5;
    logic [127:0] job_pk_root = 128'h3d774653892d5f3695b370c7cdab63ff;
    logic [127:0] job_opt_rand = 128'hf416dc35e41222ef87445111008541d5;
    logic message_valid = 1'b0;
    wire message_ready;
    logic [63:0] message_data = 64'h8f;
    logic [7:0] message_keep = 8'h01;
    logic message_last = 1'b1;
    wire out_valid;
    logic out_ready = 1'b1;
    wire [63:0] out_data;
    wire [7:0] out_keep;
    wire out_last;
    wire busy, done, error;
    wire [15:0] error_code;
    wire [31:0] hash_contexts, keccak_permutations;
    wire [31:0] lane0_active_cycles, lane1_active_cycles;
    logic [63:0] expected_signature_words [0:2135];
    integer cycles = 0;
    integer output_words = 0;

    always #5 clk = ~clk;

    micro_hbs_horizontal_slh_dsa_sign_top #(
        .PROFILE_ENABLE(1'b1), .SWAP_PHYSICAL_LANES(SWAP)
    ) dut (.*);

    always @(posedge clk) begin
        cycles <= cycles + 1;
        if (cycles > 2000000)
            $fatal(1, "horizontal signer timeout state=%0d rc=%0d pending=%b layer=%0d leaf=%0d chain=%0d parent=%0d/%0d lane_state=%0d/%0d round=%0d/%0d remain=%0d/%0d",
                   dut.state, dut.return_code, dut.pending_mask, dut.layer,
                   dut.xmss_leaf, dut.chain_base, dut.parent_base,
                   dut.parent_count,
                   dut.hash_lanes[0].hash_lane.lane_state,
                   dut.hash_lanes[1].hash_lane.lane_state,
                   dut.hash_lanes[0].hash_lane.round_index,
                   dut.hash_lanes[1].hash_lane.round_index,
                   dut.hash_lanes[0].hash_lane.chains_remaining,
                   dut.hash_lanes[1].hash_lane.chains_remaining);
        if (out_valid && out_ready) begin
            if (out_keep !== 8'hff
                || out_data !== expected_signature_words[output_words])
                $fatal(1, "signature mismatch word=%0d got=%h expected=%h state=%0d layer=%0d",
                       output_words, out_data,
                       expected_signature_words[output_words], dut.state,
                       dut.layer);
            if (out_last !== (output_words == 2135))
                $fatal(1, "out_last mismatch word=%0d", output_words);
            output_words <= output_words + 1;
        end
    end

    task tick; begin @(posedge clk); #1; end endtask

    initial begin
        $readmemh(
            "manifests/programs/rtl_images/slh_dsa_shake_128f_signature_expected.hex",
            expected_signature_words);
        repeat (3) tick();
        rst_n = 1'b1;
        tick();
        job_valid = 1'b1;
        while (!job_ready) tick();
        tick();
        job_valid = 1'b0;
        while (!message_ready) tick();
        message_valid = 1'b1;
        tick();
        message_valid = 1'b0;
        while (!done && !error) tick();
        if (error)
            $fatal(1, "horizontal signer error code=%h state=%0d",
                   error_code, dut.state);
        if (output_words != 2136)
            $fatal(1, "signature length mismatch words=%0d", output_words);
        if (cycles > 1000000)
            $fatal(1, "cycle target missed got=%0d", cycles);
        if (hash_contexts != 10680)
            $fatal(1, "context count mismatch got=%0d", hash_contexts);
        if (keccak_permutations != 105641)
            $fatal(1, "permutation count mismatch got=%0d", keccak_permutations);
        $display("HORIZONTAL_SLH_DSA_SIGN_PASS cycles=%0d contexts=%0d permutations=%0d lane_cycles=%0d/%0d",
                 cycles, hash_contexts, keccak_permutations,
                 lane0_active_cycles, lane1_active_cycles);
        $finish;
    end
endmodule

`default_nettype wire
