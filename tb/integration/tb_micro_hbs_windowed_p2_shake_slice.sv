`timescale 1ns/1ps
`default_nettype none

module tb_micro_hbs_windowed_p2_shake_slice;
    localparam integer PAIR_CAPACITY = 2;

    logic clk = 1'b0;
    logic rst_n = 1'b0;
    logic program_we = 1'b0;
    logic [8:0] program_addr = '0;
    logic [63:0] program_wdata = '0;
    logic host_message_write_valid = 1'b0;
    wire host_message_write_ready;
    logic host_message_bank = 1'b0;
    logic [15:0] host_message_address = '0;
    logic [63:0] host_message_write_data = '0;
    wire host_message_bounds_error;
    logic job_valid = 1'b0;
    wire job_ready;
    logic [8:0] job_entry = '0;
    wire busy, done, error;
    wire [15:0] error_code;
    logic [15:0] result_read_pair = '0;
    wire [255:0] result_lane0;
    wire [255:0] result_lane1;
    wire [1:0] result_lane_mask;
    wire pair_dispatch_valid;
    wire [1:0] pair_dispatch_lane_mask;
    wire [15:0] pair_dispatch_index;
    wire [31:0] accepted_job_commands;
    wire [31:0] host_control_writes_during_busy;
    wire [31:0] host_message_writes_rejected_busy;
    wire [31:0] issued_hash_requests;
    wire [31:0] retired_instructions;
    wire [31:0] lane0_active_cycles;
    wire [31:0] lane0_idle_cycles;
    wire [31:0] lane1_active_cycles;
    wire [31:0] lane1_idle_cycles;
    wire [31:0] compose_cycles;

    logic [1:0] observed_masks [0:1];
    logic [15:0] observed_indices [0:1];
    integer observed_dispatches = 0;
    integer bank0_reads = 0;
    integer bank1_reads = 0;
    integer watchdog;
    integer i;
    integer even_compose_cycles;

    always #5 clk = ~clk;

    micro_hbs_windowed_p2_shake_slice #(
        .PROGRAM_WORDS(512),
        .PAIR_CAPACITY(PAIR_CAPACITY),
        .UNROLL(2)
    ) dut (.*);

    always @(posedge clk) begin
        #1;
        if (pair_dispatch_valid) begin
            observed_masks[observed_dispatches] = pair_dispatch_lane_mask;
            observed_indices[observed_dispatches] = pair_dispatch_index;
            observed_dispatches = observed_dispatches + 1;
        end
        if (dut.bank0_read_valid && dut.bank0_read_ready)
            bank0_reads = bank0_reads + 1;
        if (dut.bank1_read_valid && dut.bank1_read_ready)
            bank1_reads = bank1_reads + 1;
    end

    function automatic [63:0] enc;
        input [7:0] opcode;
        input [7:0] flags;
        input [7:0] rd;
        input [7:0] rs;
        input [31:0] imm;
        enc = {opcode, flags, rd, rs, imm};
    endfunction

    task automatic write_program;
        input [8:0] address;
        input [63:0] word;
        begin
            @(negedge clk);
            program_addr = address;
            program_wdata = word;
            program_we = 1'b1;
            @(negedge clk);
            program_we = 1'b0;
        end
    endtask

    task automatic write_message_word;
        input bank_select;
        input [15:0] address;
        input [63:0] word;
        begin
            @(negedge clk);
            while (!host_message_write_ready) @(negedge clk);
            host_message_bank = bank_select;
            host_message_address = address;
            host_message_write_data = word;
            host_message_write_valid = 1'b1;
            @(negedge clk);
            host_message_write_valid = 1'b0;
            if (host_message_bounds_error)
                $fatal(1, "unexpected host message bounds error");
        end
    endtask

    task automatic load_record;
        input bank_select;
        input integer pair;
        input [7:0] length;
        input [1087:0] message;
        integer word_index;
        begin
            write_message_word(bank_select, 16'(pair*18), {56'b0, length});
            for (word_index = 0; word_index < 17; word_index = word_index + 1)
                write_message_word(bank_select,
                                   16'(pair*18 + word_index + 1),
                                   message[64*word_index +: 64]);
        end
    endtask

    task automatic run_job_and_reject_busy_write;
        begin
            @(negedge clk);
            while (!job_ready) @(negedge clk);
            job_entry = 0;
            job_valid = 1'b1;
            @(negedge clk);
            job_valid = 1'b0;

            if (!busy)
                $fatal(1, "Job acceptance did not enter BUSY");

            // Mutate every external command/data bus immediately after the
            // single Job acceptance.  No further message transaction is used.
            job_entry = '1;
            program_addr = '1;
            program_wdata = '1;
            host_message_bank = 1'b0;
            host_message_address = 1;
            host_message_write_data = 64'hffffffffffffffff;
            host_message_write_valid = 1'b1;
            if (host_message_write_ready)
                $fatal(1, "message write interface remained ready during BUSY");
            @(posedge clk);
            #1;
            if (!busy || host_message_write_ready)
                $fatal(1, "busy message write was not rejected");
            @(negedge clk);
            host_message_write_valid = 1'b0;

            watchdog = 0;
            while (!done && !error) begin
                @(posedge clk);
                #1;
                watchdog = watchdog + 1;
                if (watchdog > 400)
                    $fatal(1, "windowed P2/U2 Job timeout");
            end
            if (error)
                $fatal(1, "unexpected Job error code=%h", error_code);
        end
    endtask

    task automatic expect_pair;
        input [15:0] pair;
        input [1:0] expected_mask;
        input [255:0] expected_lane0;
        input [255:0] expected_lane1;
        begin
            result_read_pair = pair;
            #1;
            if (result_lane_mask !== expected_mask)
                $fatal(1, "result pair %0d mask=%b expected=%b",
                       pair, result_lane_mask, expected_mask);
            if (result_lane0 !== expected_lane0)
                $fatal(1, "result pair %0d lane0 mismatch got=%064x",
                       pair, result_lane0);
            if (expected_mask[1] && result_lane1 !== expected_lane1)
                $fatal(1, "result pair %0d lane1 mismatch got=%064x",
                       pair, result_lane1);
        end
    endtask

    task automatic run_job_expect_error;
        input [15:0] expected_error;
        begin
            @(negedge clk);
            while (!job_ready) @(negedge clk);
            job_entry = 0;
            job_valid = 1'b1;
            @(negedge clk);
            job_valid = 1'b0;
            watchdog = 0;
            while (!done && !error) begin
                @(posedge clk);
                #1;
                watchdog = watchdog + 1;
                if (watchdog > 40)
                    $fatal(1, "invalid windowed Job timeout");
            end
            if (done || !error || error_code != expected_error)
                $fatal(1, "invalid Job did not fail closed done=%b code=%h",
                       done, error_code);
        end
    endtask

    initial begin : kat
        reg [1087:0] empty_message;
        reg [1087:0] abc_message;
        reg [1087:0] zero_byte_message;
        reg [1087:0] rate_edge_message;

        empty_message = '0;
        abc_message = '0;
        abc_message[7:0] = 8'h61;
        abc_message[15:8] = 8'h62;
        abc_message[23:16] = 8'h63;
        zero_byte_message = '0;
        rate_edge_message = '0;
        for (i = 0; i < 135; i = i + 1)
            rate_edge_message[8*i +: 8] = i[7:0];

        repeat (3) @(posedge clk);
        rst_n = 1'b1;

        // The Job issues exactly two static pair requests.  R0 selects pair 0
        // and is incremented before the second request selects pair 1.
        write_program(0, enc(8'h03, 8'h03, 0, 0, 32'h0200));
        write_program(1, enc(8'h02, 0, 0, 0, 1));
        write_program(2, enc(8'h03, 8'h03, 0, 0, 32'h0200));
        write_program(3, enc(8'h0d, 0, 0, 0, 0));

        load_record(0, 0, 0, empty_message);
        load_record(1, 0, 3, abc_message);
        load_record(0, 1, 135, rate_edge_message);
        load_record(1, 1, 1, zero_byte_message);

        observed_dispatches = 0;
        bank0_reads = 0;
        bank1_reads = 0;
        run_job_and_reject_busy_write();
        expect_pair(0, 2'b11,
            256'h2f76d56e64270cb5821bb862ea52cd3f24eb3e74eb3f3b23138da80b2bddb946,
            256'h39578be737ea944feee1f1f83045b48d4d11c40c0863681c77a8601360663348);
        expect_pair(1, 2'b11,
            256'he0ad4e847ad57455bea670dbee961cd97f7357759dac7baaf5a2d84a62ae5dc4,
            256'h540d60b8f4366ea8f02e0430bf0bdee541cfeaddf636c6825807f755f81dd0b8);
        if (observed_dispatches != 2
            || observed_masks[0] != 2'b11 || observed_masks[1] != 2'b11
            || observed_indices[0] != 0 || observed_indices[1] != 1)
            $fatal(1, "even dispatch sequence mismatch");
        if (bank0_reads != 36 || bank1_reads != 36)
            $fatal(1, "even bank reads mismatch %0d/%0d", bank0_reads, bank1_reads);
        if (accepted_job_commands != 1 || issued_hash_requests != 2)
            $fatal(1, "even autonomy counters jobs=%0d hashes=%0d",
                   accepted_job_commands, issued_hash_requests);
        if (retired_instructions != 4)
            $fatal(1, "even retired instruction count %0d", retired_instructions);
        if (host_control_writes_during_busy != 0
            || host_message_writes_rejected_busy != 1)
            $fatal(1, "even host isolation counters control=%0d message=%0d",
                   host_control_writes_during_busy,
                   host_message_writes_rejected_busy);
        if (lane0_active_cycles != 32 || lane1_active_cycles != 32
            || lane0_idle_cycles != 52 || lane1_idle_cycles != 52
            || compose_cycles != 38)
            $fatal(1, "even utilization accounting mismatch active=%0d/%0d idle=%0d/%0d compose=%0d",
                   lane0_active_cycles, lane1_active_cycles,
                   lane0_idle_cycles, lane1_idle_cycles, compose_cycles);
        even_compose_cycles = compose_cycles;

        // Change only the second HASH_LAYOUT mask and replace three records.
        // Bank1/pair1 deliberately retains stale data; mask 01 must prevent a
        // read or lane1 launch for the odd tail.
        write_program(2, enc(8'h03, 8'h01, 0, 0, 32'h0200));
        load_record(0, 0, 3, abc_message);
        load_record(1, 0, 0, empty_message);
        load_record(0, 1, 1, zero_byte_message);

        observed_dispatches = 0;
        bank0_reads = 0;
        bank1_reads = 0;
        run_job_and_reject_busy_write();
        expect_pair(0, 2'b11,
            256'h39578be737ea944feee1f1f83045b48d4d11c40c0863681c77a8601360663348,
            256'h2f76d56e64270cb5821bb862ea52cd3f24eb3e74eb3f3b23138da80b2bddb946);
        expect_pair(1, 2'b01,
            256'h540d60b8f4366ea8f02e0430bf0bdee541cfeaddf636c6825807f755f81dd0b8,
            '0);
        if (observed_dispatches != 2
            || observed_masks[0] != 2'b11 || observed_masks[1] != 2'b01
            || observed_indices[0] != 0 || observed_indices[1] != 1)
            $fatal(1, "odd dispatch sequence mismatch");
        if (bank0_reads != 36 || bank1_reads != 18)
            $fatal(1, "odd-tail bank reads mismatch %0d/%0d", bank0_reads, bank1_reads);
        if (accepted_job_commands != 2 || issued_hash_requests != 4)
            $fatal(1, "odd autonomy counters jobs=%0d hashes=%0d",
                   accepted_job_commands, issued_hash_requests);
        if (retired_instructions != 8)
            $fatal(1, "cumulative retired instruction count %0d",
                   retired_instructions);
        if (host_control_writes_during_busy != 0
            || host_message_writes_rejected_busy != 2)
            $fatal(1, "odd host isolation counters control=%0d message=%0d",
                   host_control_writes_during_busy,
                   host_message_writes_rejected_busy);
        if (lane0_active_cycles != 32 || lane1_active_cycles != 16
            || lane0_idle_cycles != 52 || lane1_idle_cycles != 68)
            $fatal(1, "odd-tail utilization accounting mismatch active=%0d/%0d idle=%0d/%0d",
                   lane0_active_cycles, lane1_active_cycles,
                   lane0_idle_cycles, lane1_idle_cycles);
        if ((lane0_active_cycles + lane0_idle_cycles)
            != (lane1_active_cycles + lane1_idle_cycles))
            $fatal(1, "lane accounting windows differ");
        if (compose_cycles != even_compose_cycles)
            $fatal(1, "compose cycles changed with tail mask even=%0d odd=%0d",
                   even_compose_cycles, compose_cycles);

        // The microcode can only request the fixed 11/01 mapping.  A corrupt
        // image encoding 10 must fail before any bank read or lane dispatch.
        write_program(0, enc(8'h03, 8'h02, 0, 0, 32'h0200));
        observed_dispatches = 0;
        bank0_reads = 0;
        bank1_reads = 0;
        run_job_expect_error(16'h0302);
        if (observed_dispatches != 0 || bank0_reads != 0 || bank1_reads != 0
            || result_lane_mask != 0)
            $fatal(1, "invalid mask exposed a bank/lane/result side effect");

        $display("PASS windowed Job P2/U2 KAT: even4+odd3, 1 Job each, requests=2 each; invalid mask fail-closed");
        $finish;
    end
endmodule

`default_nettype wire
