`timescale 1ns/1ps
`default_nettype none

module tb_micro_hbs_slh_dsa_job_stream_loader;
    logic clk = 1'b0;
    logic rst_n = 1'b0;
    always #5 clk = ~clk;

    logic job_valid = 1'b0;
    wire job_ready;
    logic [8:0] job_entry = 9'd7;
    logic [31:0] job_message_length = '0;
    logic [127:0] job_sk_seed = 128'h0f0e0d0c0b0a09080706050403020100;
    logic [127:0] job_sk_prf = 128'h1f1e1d1c1b1a19181716151413121110;
    logic [127:0] job_pk_seed = 128'h2f2e2d2c2b2a29282726252423222120;
    logic [127:0] job_pk_root = 128'h3f3e3d3c3b3a39383736353433323130;
    logic [127:0] job_opt_rand = 128'h4f4e4d4c4b4a49484746454443424140;
    logic message_valid = 1'b0;
    wire message_ready;
    logic [63:0] message_data = '0;
    logic [7:0] message_keep = '0;
    logic message_last = 1'b0;
    wire core_start_valid;
    logic core_start_ready = 1'b1;
    wire [8:0] core_entry;
    wire [31:0] core_message_length;
    wire [127:0] core_sk_seed, core_sk_prf, core_pk_seed;
    wire [127:0] core_pk_root, core_opt_rand;
    logic core_done = 1'b0;
    logic core_error = 1'b0;
    logic [15:0] core_error_code = '0;
    wire sp_valid, sp_ready, sp_write, sp_bounds_error;
    wire [15:0] sp_address;
    wire [63:0] sp_write_data, sp_read_data;
    wire sp_response_valid;
    wire busy, done, error;
    wire [15:0] error_code;
    wire [31:0] accepted_jobs, admitted_message_words;
    integer core_countdown = 0;
    integer launches = 0;
    integer timeout;

    micro_hbs_slh_dsa_job_stream_loader #(
        .SCRATCH_WORDS(1024), .MAX_MESSAGE_BYTES(64)
    ) dut (
        .clk, .rst_n, .job_valid, .job_ready, .job_entry,
        .job_message_length, .job_sk_seed, .job_sk_prf, .job_pk_seed,
        .job_pk_root, .job_opt_rand, .message_valid, .message_ready,
        .message_data, .message_keep, .message_last,
        .core_start_valid, .core_start_ready, .core_entry,
        .core_message_length, .core_sk_seed, .core_sk_prf, .core_pk_seed,
        .core_pk_root, .core_opt_rand, .core_done, .core_error,
        .core_error_code, .scratch_request_valid(sp_valid),
        .scratch_request_ready(sp_ready), .scratch_request_write(sp_write),
        .scratch_request_address(sp_address),
        .scratch_request_write_data(sp_write_data),
        .scratch_bounds_error(sp_bounds_error), .busy, .done, .error,
        .error_code, .accepted_jobs, .admitted_message_words
    );

    micro_hbs_scratchpad64 #(.WORDS(1024), .ADDRESS_WIDTH(16)) scratch (
        .clk, .rst_n, .request_valid(sp_valid), .request_ready(sp_ready),
        .request_write(sp_write), .request_address(sp_address),
        .request_write_data(sp_write_data),
        .response_valid(sp_response_valid), .response_read_data(sp_read_data),
        .bounds_error(sp_bounds_error), .scrub_start(1'b0),
        .scrub_busy(), .scrub_done()
    );

    always_ff @(posedge clk) begin
        core_done <= 1'b0;
        if (core_start_valid && core_start_ready) begin
            launches <= launches + 1;
            core_countdown <= 3;
            if (core_entry != 9'd7)
                $fatal(1, "latched entry mismatch");
        end else if (core_countdown != 0) begin
            core_countdown <= core_countdown - 1;
            if (core_countdown == 1)
                core_done <= 1'b1;
        end
    end

    task automatic submit_job(input [31:0] length);
        begin
            while (!job_ready) @(negedge clk);
            job_message_length = length;
            job_valid = 1'b1;
            @(negedge clk);
            job_valid = 1'b0;
        end
    endtask

    task automatic send_beat(input [63:0] data,
                             input [7:0] keep,
                             input last);
        begin
            while (!message_ready) @(negedge clk);
            message_data = data;
            message_keep = keep;
            message_last = last;
            message_valid = 1'b1;
            @(negedge clk);
            message_valid = 1'b0;
        end
    endtask

    task automatic wait_done_or_error;
        begin
            timeout = 0;
            while (!done && !error && timeout < 200) begin
                @(negedge clk);
                timeout = timeout + 1;
            end
            if (timeout == 200)
                $fatal(1, "Job loader timeout");
        end
    endtask

    initial begin
        repeat (3) @(negedge clk);
        rst_n = 1'b1;

        submit_job(9);
        // The external Job bus is not live after acceptance.
        job_sk_seed = '0;
        job_sk_prf = '0;
        job_pk_seed = '0;
        job_pk_root = '0;
        job_opt_rand = '0;
        send_beat(64'h0706050403020100, 8'hff, 1'b0);
        send_beat(64'h0000000000000008, 8'h01, 1'b1);
        wait_done_or_error();
        if (!done || error)
            $fatal(1, "valid streamed Job failed code=%h", error_code);
        if (scratch.memory[512] !== 64'h0706050403020100
            || scratch.memory[513] !== 64'h0f0e0d0c0b0a0908
            || scratch.memory[514] !== 64'h1716151413121110
            || scratch.memory[516] !== 64'h2726252423222120
            || scratch.memory[518] !== 64'h3736353433323130
            || scratch.memory[520] !== 64'h4746454443424140)
            $fatal(1, "fixed Job fields were not atomically latched");
        if (scratch.memory[522] !== 64'h0706050403020100
            || scratch.memory[523] !== 64'h0000000000000008)
            $fatal(1, "message payload storage mismatch");
        if (core_message_length != 9 || core_sk_seed == 0
            || core_pk_seed == 0 || launches != 1)
            $fatal(1, "core launch snapshot mismatch");

        // Restore inputs for a second Job, then prove malformed keep fails
        // before launching the core.
        job_sk_seed = 128'h0f0e0d0c0b0a09080706050403020100;
        job_sk_prf = 128'h1f1e1d1c1b1a19181716151413121110;
        job_pk_seed = 128'h2f2e2d2c2b2a29282726252423222120;
        job_pk_root = 128'h3f3e3d3c3b3a39383736353433323130;
        job_opt_rand = 128'h4f4e4d4c4b4a49484746454443424140;
        submit_job(9);
        send_beat(64'h0706050403020100, 8'h7f, 1'b0);
        wait_done_or_error();
        if (!error || error_code != 16'h0c02 || launches != 1)
            $fatal(1, "malformed keep did not fail closed code=%h", error_code);

        submit_job(65);
        wait_done_or_error();
        if (!error || error_code != 16'h0c01 || launches != 1)
            $fatal(1, "oversize message did not fail closed code=%h", error_code);

        submit_job(0);
        wait_done_or_error();
        if (!done || error || launches != 2)
            $fatal(1, "zero-length message Job failed");
        if (accepted_jobs != 4 || admitted_message_words != 2)
            $fatal(1, "accounting mismatch jobs=%0d words=%0d",
                   accepted_jobs, admitted_message_words);

        $display("PASS no-DMA SLH-DSA Job/message loader jobs=%0d message_words=%0d launches=%0d",
                 accepted_jobs, admitted_message_words, launches);
        $finish;
    end
endmodule

`default_nettype wire
