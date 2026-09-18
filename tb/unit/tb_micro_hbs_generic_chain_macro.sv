`timescale 1ns/1ps
`default_nettype none

module tb_micro_hbs_generic_chain_macro;
    logic clk = 0;
    logic rst_n = 0;
    logic job_valid = 0;
    wire job_ready;
    wire out_valid;
    logic out_ready = 1;
    wire [63:0] out_data;
    wire [7:0] out_keep;
    wire out_last, busy, done, error;
    wire [15:0] error_code;
    integer cycles = 0;
    integer words = 0;

    always #5 clk = ~clk;
    always @(posedge clk) begin
        cycles <= cycles + 1;
        if (cycles > 1000)
            $fatal(1, "CHAIN macro timeout");
        if (out_valid && out_ready) begin
            if (out_keep !== 8'hff)
                $fatal(1, "CHAIN out_keep mismatch");
            if (words == 0 && out_data !== 64'h130115893bd6ddd8)
                $fatal(1, "CHAIN word 0 mismatch: %h", out_data);
            if (words == 1 && out_data !== 64'hf065e78697ba62f0)
                $fatal(1, "CHAIN word 1 mismatch: %h", out_data);
            if (out_last !== (words == 1))
                $fatal(1, "CHAIN out_last mismatch");
            words <= words + 1;
        end
    end

    micro_hbs_horizontal_hbs_top #(
        .PROGRAM_TOKENS(2), .OUTPUT_BYTES(16),
        .REQUIRE_MESSAGE(1'b0), .PROFILE_ENABLE(1'b1),
        .TOKEN_INIT_FILE("tb/vectors/generic_chain_tokens.mem"),
        .TEMPLATE_INIT_FILE("tb/vectors/generic_chain_templates.mem"),
        .DESCRIPTOR_INIT_FILE(
            "rtl/microcode/slh_dsa_128f_sign_macro_descriptors.mem")
    ) dut (
        .clk, .rst_n, .job_valid, .job_ready,
        .job_message_length(0),
        .job_sk_seed(128'hd1d06dcbb9181a55aabce64467d6b81d),
        .job_sk_prf(0),
        .job_pk_seed(128'hf416dc35e41222ef87445111008541d5),
        .job_pk_root(0), .job_opt_rand(0),
        .message_valid(0), .message_ready(), .message_data(0),
        .message_keep(0), .message_last(0),
        .out_valid, .out_ready, .out_data, .out_keep, .out_last,
        .busy, .done, .error, .error_code,
        .hash_contexts(), .keccak_permutations(),
        .lane0_active_cycles(), .lane1_active_cycles()
    );

    task tick; begin @(posedge clk); #1; end endtask
    initial begin
        repeat (3) tick();
        rst_n = 1;
        tick();
        job_valid = 1;
        while (!job_ready) tick();
        tick();
        job_valid = 0;
        while (!done && !error) tick();
        if (error)
            $fatal(1, "CHAIN macro error %h", error_code);
        if (words != 2)
            $fatal(1, "CHAIN output words=%0d", words);
        $display("GENERIC_CHAIN_MACRO_PASS cycles=%0d", cycles);
        $finish;
    end
endmodule

`default_nettype wire
