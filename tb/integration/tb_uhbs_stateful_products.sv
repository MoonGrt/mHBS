`timescale 1ns/1ps
module tb_uhbs_stateful_products;
    parameter integer PROFILE = 0;
    parameter integer SWAP = 0;
    parameter integer BACKPRESSURE = 0;
    localparam integer MESSAGE_LENGTH = PROFILE == 0 ? 21 : 20;
    localparam integer KEYGEN_BYTES = PROFILE == 0 ? 196 : 140;
    localparam integer SIGN_BYTES = PROFILE == 0 ? 2500 : 2508;

    logic clk = 0, rst_n = 0;
    logic job_valid = 0, job_operation = 0;
    logic [31:0] job_message_length = 0;
    logic [10:0] job_initial_q = 5;
    logic [255:0] job_secret_seed = 0, job_secret_prf = 0;
    logic [255:0] job_public_seed = 0, job_randomizer = 0;
    logic [127:0] job_identifier = 0;
    logic message_valid = 0, message_last = 0;
    logic [63:0] message_data = 0;
    logic [7:0] message_keep = 0;
    logic state_commit_ready = 0, out_ready = 1;
    wire job_ready, message_ready, state_commit_valid;
    wire [10:0] state_next_q;
    wire out_valid, out_last, busy, done, error, tree_cache_valid;
    wire [63:0] out_data;
    wire [7:0] out_keep;
    wire [15:0] error_code;
    wire [31:0] hash_contexts, keccak_permutations;
    wire [31:0] lane0_active_cycles, lane1_active_cycles;

    logic [7:0] expected_keygen [0:KEYGEN_BYTES-1];
    logic [7:0] expected_sign [0:SIGN_BYTES-1];
    logic [7:0] expected_sign_q6 [0:SIGN_BYTES-1];
    logic [7:0] message_bytes [0:20];
    integer operation_phase = 0;
    integer output_index = 0;
    logic commit_ack_seen = 0;
    integer cycles = 0;
    integer keygen_cycles = 0;
    integer sign_cycles = 0;
    integer index, beat, byte_index, valid_bytes;
    logic [15:0] ready_lfsr = 16'h1;

    always #5 clk = ~clk;
    always @(posedge clk) if (rst_n) cycles = cycles + 1;
    always @(negedge clk) begin
        if (!rst_n) begin
            ready_lfsr <= 16'h1;
            out_ready <= 1'b1;
        end else begin
            ready_lfsr <= {ready_lfsr[14:0],
                           ready_lfsr[15] ^ ready_lfsr[13]
                           ^ ready_lfsr[12] ^ ready_lfsr[10]};
            out_ready <= !BACKPRESSURE || ready_lfsr[2:0] != 3'b000;
        end
    end

    uhbs_stateful_hbs #(
        .UNROLL(2), .PROFILE_ENABLE(1'b1),
        .SWAP_PHYSICAL_LANES(SWAP != 0),
        .TOKEN_INIT_FILE(PROFILE == 0
            ? "rtl/microcode/xmss_shake256_h10_w4_tokens.mem"
            : "rtl/microcode/lms_shake256_h10_w4_research_tokens.mem"),
        .TEMPLATE_INIT_FILE(PROFILE == 0
            ? "rtl/microcode/xmss_shake256_h10_w4_templates.mem"
            : "rtl/microcode/lms_shake256_h10_w4_research_templates.mem"),
        .DESCRIPTOR_INIT_FILE(PROFILE == 0
            ? "rtl/microcode/xmss_shake256_h10_w4_descriptors.mem"
            : "rtl/microcode/lms_shake256_h10_w4_research_descriptors.mem")
    ) dut (.*);

    always @(posedge clk) begin
        if (rst_n && state_commit_valid && state_commit_ready)
            commit_ack_seen = 1;
        if (rst_n && out_valid && out_ready) begin
            for (byte_index = 0; byte_index < 8; byte_index = byte_index + 1)
                if (out_keep[byte_index]) begin
                    if (operation_phase == 0) begin
                        if (output_index >= KEYGEN_BYTES
                            || out_data[byte_index*8 +: 8]
                               !== expected_keygen[output_index])
                            $fatal(1, "Keygen byte %0d mismatch got=%02h expected=%02h root=%h",
                                   output_index, out_data[byte_index*8 +: 8],
                                   expected_keygen[output_index], dut.root_value);
                    end else if (operation_phase == 1) begin
                        if (output_index >= SIGN_BYTES
                            || out_data[byte_index*8 +: 8]
                               !== expected_sign[output_index])
                            $fatal(1, "Sign byte %0d mismatch", output_index);
                    end else begin
                        if (output_index >= SIGN_BYTES
                            || out_data[byte_index*8 +: 8]
                               !== expected_sign_q6[output_index])
                            $fatal(1, "second Sign byte %0d mismatch",
                                   output_index);
                    end
                    output_index = output_index + 1;
                end
            if (out_last != (operation_phase == 0
                    ? output_index == KEYGEN_BYTES : output_index == SIGN_BYTES))
                $fatal(1, "out_last position mismatch");
        end
        if (rst_n && operation_phase >= 1 && out_valid && !commit_ack_seen)
            $fatal(1, "output preceded durable q commit phase=%0d byte=%0d front=%0d macro=%0d",
                   operation_phase, output_index, dut.front_state,
                   dut.macro_state);
    end

    task tick; begin @(posedge clk); #1; end endtask

    task submit_job(input logic operation, input integer length);
        begin
            while (!job_ready) tick();
            job_operation = operation;
            job_message_length = length;
            job_valid = 1;
            tick();
            job_valid = 0;
        end
    endtask

    task run_sign(
        input integer phase,
        input integer expected_next_q,
        input integer expected_contexts,
        input integer expected_permutations
    );
        integer sign_start;
        begin
            operation_phase = phase;
            output_index = 0;
            commit_ack_seen = 0;
            sign_start = cycles;
            submit_job(1'b1, MESSAGE_LENGTH);
            send_message();
            while (!state_commit_valid && !error) tick();
            if (error) $fatal(1, "Sign reserve error %h", error_code);
            if (state_next_q != expected_next_q)
                $fatal(1, "wrong committed next q");
            repeat (5) tick();
            state_commit_ready = 1;
            tick();
            state_commit_ready = 0;
            repeat (3) tick();
            if (state_commit_valid)
                $fatal(1, "state commit valid did not retire");
            while (!done && !error) begin
                tick();
                if (cycles-sign_start > 1_000_000)
                    $fatal(1, "Sign timeout");
            end
            if (error) $fatal(1, "Sign error %h", error_code);
            if (output_index != SIGN_BYTES)
                $fatal(1, "Sign output size %0d", output_index);
            if (hash_contexts != expected_contexts
                || keccak_permutations != expected_permutations)
                $fatal(1, "Sign operation counts %0d/%0d",
                       hash_contexts, keccak_permutations);
            if (phase == 1)
                sign_cycles = cycles-sign_start;
        end
    endtask

    task send_message;
        begin
            beat = 0;
            while (beat < MESSAGE_LENGTH) begin
                while (!message_ready) tick();
                message_data = 0;
                message_keep = 0;
                valid_bytes = MESSAGE_LENGTH - beat > 8
                    ? 8 : MESSAGE_LENGTH - beat;
                for (index = 0; index < valid_bytes; index = index + 1) begin
                    message_data[index*8 +: 8] = message_bytes[beat+index];
                    message_keep[index] = 1;
                end
                message_last = beat + valid_bytes == MESSAGE_LENGTH;
                message_valid = 1;
                tick();
                message_valid = 0;
                message_last = 0;
                beat = beat + valid_bytes;
            end
        end
    endtask

    initial begin
        if (PROFILE == 0) begin
            $readmemh("tests/kat/xmss_stateful_keygen_bytes.mem", expected_keygen);
            $readmemh("tests/kat/xmss_stateful_sign_bytes.mem", expected_sign);
            $readmemh("tests/kat/xmss_stateful_sign_q6_bytes.mem",
                      expected_sign_q6);
            for (index = 0; index < MESSAGE_LENGTH; index = index + 1)
                message_bytes[index] = expected_sign[0];
            // "micro-hbs-xmss-kat-v1"
            {message_bytes[0], message_bytes[1], message_bytes[2],
             message_bytes[3], message_bytes[4], message_bytes[5],
             message_bytes[6], message_bytes[7], message_bytes[8],
             message_bytes[9], message_bytes[10], message_bytes[11],
             message_bytes[12], message_bytes[13], message_bytes[14],
             message_bytes[15], message_bytes[16], message_bytes[17],
             message_bytes[18], message_bytes[19], message_bytes[20]}
                = 168'h6d6963726f2d6862732d786d73732d6b61742d7631;
        end else begin
            $readmemh("tests/kat/lms_shake_stateful_keygen_bytes.mem", expected_keygen);
            $readmemh("tests/kat/lms_shake_stateful_sign_bytes.mem", expected_sign);
            $readmemh("tests/kat/lms_shake_stateful_sign_q6_bytes.mem",
                      expected_sign_q6);
            // "micro-hbs-lms-kat-v1"
            {message_bytes[0], message_bytes[1], message_bytes[2],
             message_bytes[3], message_bytes[4], message_bytes[5],
             message_bytes[6], message_bytes[7], message_bytes[8],
             message_bytes[9], message_bytes[10], message_bytes[11],
             message_bytes[12], message_bytes[13], message_bytes[14],
             message_bytes[15], message_bytes[16], message_bytes[17],
             message_bytes[18], message_bytes[19]}
                = 160'h6d6963726f2d6862732d6c6d732d6b61742d7631;
        end
        for (index = 0; index < 32; index = index + 1) begin
            job_secret_seed[index*8 +: 8] = index;
            job_secret_prf[index*8 +: 8] = index + 32;
            job_public_seed[index*8 +: 8] = index + 64;
            job_randomizer[index*8 +: 8] = index + 64;
            if (index < 16) job_identifier[index*8 +: 8] = index;
        end
        if (PROFILE == 1)
            for (index = 0; index < 32; index = index + 1)
                job_secret_seed[index*8 +: 8] = index + 32;

        repeat (4) tick();
        rst_n = 1;
        tick();
        submit_job(1'b0, 0);
        while (!done && !error) begin
            tick();
            if (cycles > 80_000_000) begin
                $display("DEBUG front=%0d macro=%0d pc=%0d pending=%h leaf=%0d chain=%0d reducer=%0d writes=%0d queued=%0d",
                    dut.front_state, dut.macro_state,
                    dut.macro_sequencer.program_counter,
                    dut.macro_sequencer.pending_events,
                    dut.leaf_cursor, dut.chain_cursor,
                    dut.tree_reducer.state, dut.cache_tree_writes,
                    dut.cache_queued_writes);
                $display("DEBUG lane_state=%0d/%0d shake=%0d/%0d launch=%b response=%b valid=%b",
                    dut.lanes[0].lane.state, dut.lanes[1].lane.state,
                    dut.lanes[0].lane.shake.lane_state,
                    dut.lanes[1].lane.shake.lane_state,
                    dut.launch_pending, dut.response_pending,
                    dut.lane_response_valid);
                $fatal(1, "Keygen timeout");
            end
        end
        if (error) $fatal(1, "Keygen error %h", error_code);
        if (output_index != KEYGEN_BYTES || !tree_cache_valid)
            $fatal(1, "Keygen output/cache incomplete");
        if (PROFILE == 0
            && (hash_contexts != 3_430_396
                || keccak_permutations != 3_430_396))
            $fatal(1, "XMSS Keygen operation counts");
        if (PROFILE == 1
            && (hash_contexts != 1_100_799
                || keccak_permutations != 1_116_159))
            $fatal(1, "LMS Keygen operation counts");
        keygen_cycles = cycles;

        if (PROFILE == 0) begin
            run_sign(1, 6, 1_554, 1_555);
            run_sign(2, 7, 1_689, 1_690);
        end else begin
            run_sign(1, 6, 548, 548);
            run_sign(2, 7, 548, 548);
        end
        $display("STATEFUL_PRODUCT_PASS profile=%0d keygen_cycles=%0d sign_cycles=%0d lane=%0d/%0d",
                 PROFILE, keygen_cycles, sign_cycles,
                 lane0_active_cycles, lane1_active_cycles);
        $finish;
    end
endmodule
