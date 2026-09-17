`timescale 1ns/1ps
`default_nettype none

module tb_micro_hbs_slh_dsa_static_top;
    logic clk = 1'b0;
    logic rst_n = 1'b0;
    always #5 clk = ~clk;

    wire init_done, init_error;
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
    wire [255:0] last_digest;
    wire [31:0] accepted_job_commands, admitted_message_words;
    wire [31:0] issued_hash_requests, tree_parent_hashes;
    wire [31:0] retired_instructions, scratch_reads, scratch_writes;
    wire [31:0] absorbed_blocks, retired_components;
    logic [63:0] expected_signature_words [0:2135];
    integer output_words_seen;
    integer cycles;
    logic output_last_seen;

    micro_hbs_slh_dsa_static_top dut (.*);

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            output_words_seen <= 0;
            output_last_seen <= 1'b0;
        end else if (out_valid && out_ready) begin
            if (output_words_seen >= 2136 || out_keep !== 8'hff
                || out_data !== expected_signature_words[output_words_seen])
                $fatal(1, "static top signature mismatch word=%0d got=%h keep=%h",
                       output_words_seen, out_data, out_keep);
            output_words_seen <= output_words_seen + 1;
            if (out_last)
                output_last_seen <= 1'b1;
        end
    end

    initial begin
        $readmemh(
            "manifests/programs/rtl_images/slh_dsa_shake_128f_signature_expected.hex",
            expected_signature_words);
        repeat (3) @(negedge clk);
        rst_n = 1'b1;
        cycles = 0;
        while (!init_done && !init_error && cycles < 1000) begin
            @(negedge clk);
            cycles = cycles + 1;
        end
        if (!init_done || init_error)
            $fatal(1, "static image initialization failed cycles=%0d state=%0d xor=%h",
                   cycles, dut.init_state, dut.image_xor);
        if (!job_ready)
            $fatal(1, "static top not ready after image initialization");

        @(negedge clk);
        job_valid = 1'b1;
        @(negedge clk);
        job_valid = 1'b0;
        cycles = 0;
        while (!message_ready && cycles < 1200) begin
            @(negedge clk);
            cycles = cycles + 1;
        end
        if (!message_ready)
            $fatal(1, "static top message admission timeout");
        message_valid = 1'b1;
        @(negedge clk);
        message_valid = 1'b0;

        while (!done && !error && cycles < 30000000) begin
            @(negedge clk);
            cycles = cycles + 1;
        end
        if (!done || error)
            $fatal(1, "static top Sign failed code=%h cycles=%0d",
                   error_code, cycles);
        if (output_words_seen != 2136 || !output_last_seen)
            $fatal(1, "static top output length mismatch words=%0d last=%0d",
                   output_words_seen, output_last_seen);
        if (cycles != 1003278
            || accepted_job_commands != 1 || admitted_message_words != 1
            || issued_hash_requests != 5016 || tree_parent_hashes != 1969
            || retired_instructions != 21134 || scratch_reads != 41518
            || scratch_writes != 19501 || absorbed_blocks != 103672
            || retired_components != 81458)
            $fatal(1, "static top counters mismatch cycles=%0d job=%0d msg=%0d hash=%0d+%0d inst=%0d scratch=%0d/%0d blocks=%0d components=%0d",
                   cycles, accepted_job_commands, admitted_message_words,
                   issued_hash_requests, tree_parent_hashes,
                   retired_instructions, scratch_reads, scratch_writes,
                   absorbed_blocks, retired_components);
        $display("PASS static-ROM SLH-DSA Sign init=%0d cycles=%0d words=%0d",
                 init_done, cycles, output_words_seen);

        // A corrupt or missing readmemh image produces a checksum mismatch;
        // the product interface must then remain fail-closed.
        rst_n = 1'b0;
        repeat (2) @(negedge clk);
        rst_n = 1'b1;
        cycles = 0;
        while (dut.init_state != 11 && cycles < 1000) begin
            @(negedge clk);
            cycles = cycles + 1;
        end
        if (dut.init_state != 11)
            $fatal(1, "static image integrity check was not reached");
        dut.image_xor = dut.image_xor ^ 64'h1;
        @(negedge clk);
        if (!init_error || init_done || job_ready)
            $fatal(1, "corrupt static image did not fail closed state=%0d xor=%h",
                   dut.init_state, dut.image_xor);
        $display("PASS static-ROM corruption fail-closed cycles=%0d", cycles);
        $finish;
    end
endmodule

`default_nettype wire
