`timescale 1ns/1ps
`default_nettype none

module tb_micro_hbs_static_microcode_messages;
    localparam integer JOBS = 5;
    localparam integer SIGNATURE_BEATS = 2136;
    logic clk = 0, rst_n = 0, job_valid = 0;
    wire job_ready;
    logic [31:0] job_message_length;
    logic [127:0] job_sk_seed, job_sk_prf, job_pk_seed, job_pk_root;
    logic [127:0] job_opt_rand;
    logic message_valid = 0;
    wire message_ready;
    logic [63:0] message_data;
    logic [7:0] message_keep;
    logic message_last;
    wire out_valid;
    logic out_ready = 1;
    wire [63:0] out_data;
    wire [7:0] out_keep;
    wire out_last, busy, done, error;
    wire [15:0] error_code;
    wire [31:0] hash_contexts, keccak_permutations;
    wire [31:0] lane0_active_cycles, lane1_active_cycles;

    logic [7:0] lengths [0:JOBS-1];
    logic [127:0] sk_seed [0:JOBS-1];
    logic [127:0] sk_prf [0:JOBS-1];
    logic [127:0] pk_seed [0:JOBS-1];
    logic [127:0] pk_root [0:JOBS-1];
    logic [695:0] messages [0:JOBS-1];
    logic [63:0] signatures [0:JOBS*SIGNATURE_BEATS-1];
    logic [31:0] permutations [0:JOBS-1];
    integer cycles, output_words, job_index, beat, bytes_this_beat;

    always #5 clk = ~clk;

    micro_hbs_horizontal_slh_dsa_sign_top #(.PROFILE_ENABLE(1'b1)) dut (.*);

    always @(posedge clk) begin
        cycles <= cycles + 1;
        if (cycles > 1000000)
            $fatal(1, "message-vector timeout job=%0d state=%0d pc=%0d",
                   job_index, dut.state,
                   dut.static_microcode.program_counter);
        if (out_valid && out_ready) begin
            if (out_keep !== 8'hff
                    || out_data !== signatures[
                        job_index*SIGNATURE_BEATS + output_words])
                $fatal(1, "message-vector mismatch job=%0d word=%0d got=%h expected=%h",
                       job_index, output_words, out_data,
                       signatures[job_index*SIGNATURE_BEATS + output_words]);
            if (out_last !== (output_words == SIGNATURE_BEATS-1))
                $fatal(1, "message-vector out_last job=%0d word=%0d",
                       job_index, output_words);
            output_words <= output_words + 1;
        end
    end

    task tick; begin @(posedge clk); #1; end endtask

    initial begin
        $readmemh("build/static_microcode_vectors/lengths.mem", lengths);
        $readmemh("build/static_microcode_vectors/sk_seed.mem", sk_seed);
        $readmemh("build/static_microcode_vectors/sk_prf.mem", sk_prf);
        $readmemh("build/static_microcode_vectors/pub_seed.mem", pk_seed);
        $readmemh("build/static_microcode_vectors/root.mem", pk_root);
        $readmemh("build/static_microcode_vectors/message.mem", messages);
        $readmemh("build/static_microcode_vectors/signature.mem", signatures);
        $readmemh("build/static_microcode_vectors/permutations.mem", permutations);
        cycles = 0;
        output_words = 0;
        job_index = 0;
        repeat (3) tick();
        rst_n = 1;
        tick();
        for (job_index = 0; job_index < JOBS; job_index = job_index + 1) begin
            cycles = 0;
            output_words = 0;
            job_message_length = lengths[job_index];
            job_sk_seed = sk_seed[job_index];
            job_sk_prf = sk_prf[job_index];
            job_pk_seed = pk_seed[job_index];
            job_pk_root = pk_root[job_index];
            job_opt_rand = pk_seed[job_index];
            job_valid = 1;
            while (!job_ready) tick();
            tick();
            job_valid = 0;
            beat = 0;
            while (beat * 8 < lengths[job_index]) begin
                while (!message_ready) tick();
                bytes_this_beat = lengths[job_index] - beat*8;
                if (bytes_this_beat > 8) bytes_this_beat = 8;
                message_data = messages[job_index][beat*64 +: 64];
                message_keep = (1 << bytes_this_beat) - 1;
                message_last = (beat*8 + bytes_this_beat
                                == lengths[job_index]);
                message_valid = 1;
                tick();
                message_valid = 0;
                beat = beat + 1;
            end
            while (!done && !error) tick();
            if (error)
                $fatal(1, "message-vector error job=%0d code=%h",
                       job_index, error_code);
            if (output_words != SIGNATURE_BEATS)
                $fatal(1, "message-vector length job=%0d words=%0d",
                       job_index, output_words);
            if (keccak_permutations != permutations[job_index])
                $fatal(1, "message-vector permutation job=%0d got=%0d expected=%0d",
                       job_index, keccak_permutations,
                       permutations[job_index]);
            $display("STATIC_MICROCODE_MESSAGE_PASS job=%0d length=%0d cycles=%0d permutations=%0d",
                     job_index, lengths[job_index], cycles,
                     keccak_permutations);
            tick();
        end
        $finish;
    end
endmodule

`default_nettype wire
