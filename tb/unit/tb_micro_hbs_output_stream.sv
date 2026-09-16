`timescale 1ns/1ps
`default_nettype none

module tb_micro_hbs_output_stream;
    localparam integer SCRATCH_WORDS = 16;

    logic clk = 1'b0;
    logic rst_n = 1'b0;
    logic emit_valid = 1'b0;
    wire emit_ready;
    logic [15:0] emit_base_slot = '0;
    logic emit_use_index = 1'b0;
    logic [31:0] emit_index_value = '0;
    logic [15:0] emit_length_words = '0;
    logic [3:0] emit_last_bytes = '0;
    wire scratch_read_valid;
    logic scratch_read_ready = 1'b0;
    wire [15:0] scratch_read_address;
    logic scratch_response_valid = 1'b0;
    wire scratch_response_ready;
    logic [63:0] scratch_response_data = '0;
    logic scratch_response_error = 1'b0;
    wire out_valid;
    logic out_ready = 1'b0;
    wire [63:0] out_data;
    wire [7:0] out_keep;
    wire out_last;
    wire busy, done, error;
    wire [15:0] error_code;

    logic [63:0] scratch [0:SCRATCH_WORDS-1];
    logic initialized [0:SCRATCH_WORDS-1];
    logic [63:0] expected_data [0:7];
    logic [7:0] expected_keep [0:7];
    logic expected_last [0:7];
    integer expected_count = 0;
    integer received_count = 0;
    integer request_count = 0;
    integer done_count = 0;
    integer error_count = 0;
    integer stall_cycles = 0;
    integer cycle_count = 0;
    integer watchdog;
    integer i;
    logic stall_snapshot_valid = 1'b0;
    logic [63:0] stalled_data;
    logic [7:0] stalled_keep;
    logic stalled_last;

    always #5 clk = ~clk;

    micro_hbs_output_stream #(
        .SCRATCH_WORDS(SCRATCH_WORDS),
        .ADDRESS_WIDTH(16)
    ) dut (.*);

    // Deterministic independent backpressure on both interfaces.
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            cycle_count <= 0;
            scratch_read_ready <= 1'b0;
            out_ready <= 1'b0;
        end else begin
            cycle_count <= cycle_count + 1;
            scratch_read_ready <= (cycle_count % 3 != 0);
            out_ready <= (cycle_count % 4 == 1 || cycle_count % 4 == 2);
        end
    end

    // Single-outstanding synchronous Scratchpad response model.  An
    // uninitialized word reports an error instead of returning data.
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            scratch_response_valid <= 1'b0;
            scratch_response_data <= '0;
            scratch_response_error <= 1'b0;
        end else begin
            if (scratch_response_valid && scratch_response_ready) begin
                scratch_response_valid <= 1'b0;
                scratch_response_error <= 1'b0;
            end
            if (scratch_read_valid && scratch_read_ready) begin
                if (scratch_response_valid && !scratch_response_ready)
                    $fatal(1, "DUT issued a second outstanding Scratchpad read");
                if (scratch_read_address >= SCRATCH_WORDS)
                    $fatal(1, "DUT issued out-of-range Scratchpad read %0d",
                           scratch_read_address);
                scratch_response_valid <= 1'b1;
                scratch_response_data <= scratch[scratch_read_address[3:0]];
                scratch_response_error <= !initialized[scratch_read_address[3:0]];
            end
        end
    end

    // Scoreboard at the exact output handshake edge.
    always @(posedge clk) begin
        if (rst_n && scratch_read_valid && scratch_read_ready)
            request_count = request_count + 1;
        if (rst_n && out_valid && out_ready) begin
            if (received_count >= expected_count)
                $fatal(1, "unexpected extra output word");
            if (out_data !== expected_data[received_count]
                || out_keep !== expected_keep[received_count]
                || out_last !== expected_last[received_count])
                $fatal(1, "output[%0d] mismatch data=%h keep=%h last=%0d",
                       received_count, out_data, out_keep, out_last);
            received_count = received_count + 1;
        end
        #1;
        if (done && error)
            $fatal(1, "done and error asserted together");
        if (done)
            done_count = done_count + 1;
        if (error)
            error_count = error_count + 1;
    end

    // Observe settled signals between clock edges.  Any number of stalled
    // cycles must retain the complete stream payload tuple unchanged.
    always @(negedge clk) begin
        if (rst_n && out_valid && !out_ready) begin
            stall_cycles = stall_cycles + 1;
            if (stall_snapshot_valid
                && (out_data !== stalled_data || out_keep !== stalled_keep
                    || out_last !== stalled_last))
                $fatal(1, "stream payload changed under backpressure");
            stalled_data = out_data;
            stalled_keep = out_keep;
            stalled_last = out_last;
            stall_snapshot_valid = 1'b1;
        end else begin
            stall_snapshot_valid = 1'b0;
        end
    end

    task automatic send_command;
        input [15:0] base_slot;
        input use_index;
        input [31:0] index_value;
        input [15:0] length_words;
        input [3:0] last_bytes;
        begin
            @(negedge clk);
            while (!emit_ready) @(negedge clk);
            emit_base_slot = base_slot;
            emit_use_index = use_index;
            emit_index_value = index_value;
            emit_length_words = length_words;
            emit_last_bytes = last_bytes;
            emit_valid = 1'b1;
            @(negedge clk);
            emit_valid = 1'b0;
        end
    endtask

    task automatic wait_done;
        input integer previous_done_count;
        begin
            watchdog = 0;
            while (done_count == previous_done_count && error_count == 0) begin
                @(posedge clk);
                #2;
                watchdog = watchdog + 1;
                if (watchdog > 100)
                    $fatal(1, "output command timeout");
            end
            if (error_count != 0)
                $fatal(1, "successful output command raised error %h", error_code);
        end
    endtask

    task automatic expect_error;
        input [15:0] expected_code;
        input integer previous_error_count;
        integer request_count_before;
        integer received_count_before;
        begin
            request_count_before = request_count;
            received_count_before = received_count;
            watchdog = 0;
            while (error_count == previous_error_count) begin
                @(posedge clk);
                #2;
                watchdog = watchdog + 1;
                if (watchdog > 30)
                    $fatal(1, "invalid command did not fail closed");
            end
            if (done || error_code != expected_code)
                $fatal(1, "error result mismatch done=%0d code=%h expected=%h",
                       done, error_code, expected_code);
            if (expected_code != 16'h0504
                && (request_count != request_count_before
                    || received_count != received_count_before))
                $fatal(1, "invalid command touched Scratchpad/output");
        end
    endtask

    initial begin
        for (i = 0; i < SCRATCH_WORDS; i = i + 1) begin
            scratch[i] = 64'h0706050403020100 + 64'(i) * 64'h1010101010101010;
            initialized[i] = 1'b1;
        end
        initialized[8] = 1'b0;

        repeat (3) @(posedge clk);
        rst_n = 1'b1;
        @(posedge clk);

        // Three words with a five-byte tail and arbitrary output stalls.
        expected_data[0] = scratch[2];
        expected_data[1] = scratch[3];
        expected_data[2] = scratch[4];
        expected_keep[0] = 8'hff;
        expected_keep[1] = 8'hff;
        expected_keep[2] = 8'h1f;
        expected_last[0] = 1'b0;
        expected_last[1] = 1'b0;
        expected_last[2] = 1'b1;
        expected_count = 3;
        received_count = 0;
        send_command(2, 1'b0, 0, 3, 5);
        if (!busy || emit_ready)
            $fatal(1, "executor did not lock after command acceptance");

        // A second command remains unaccepted and cannot perturb the active
        // one.  This is deliberately not an external task queue.
        emit_base_slot = 12;
        emit_length_words = 1;
        emit_last_bytes = 8;
        emit_valid = 1'b1;
        @(posedge clk);
        if (emit_ready)
            $fatal(1, "second command accepted while busy");
        @(negedge clk);
        emit_valid = 1'b0;
        wait_done(0);
        if (received_count != expected_count || request_count != 3)
            $fatal(1, "first command lost/duplicated words received=%0d reads=%0d",
                   received_count, request_count);

        // Optional index is a word offset: base 1 + index 3 starts at slot 4.
        expected_data[0] = scratch[4];
        expected_data[1] = scratch[5];
        expected_keep[0] = 8'hff;
        expected_keep[1] = 8'hff;
        expected_last[0] = 1'b0;
        expected_last[1] = 1'b1;
        expected_count = 2;
        received_count = 0;
        send_command(1, 1'b1, 3, 2, 8);
        wait_done(1);
        if (received_count != 2 || request_count != 5)
            $fatal(1, "indexed command accounting mismatch");

        // Command-time checks reject zero length, malformed final byte count,
        // and a range whose inclusive end exceeds the Scratchpad.
        send_command(0, 1'b0, 0, 0, 8);
        expect_error(16'h0501, 0);
        @(posedge clk); #2;
        send_command(0, 1'b0, 0, 1, 0);
        expect_error(16'h0502, 1);
        @(posedge clk); #2;
        send_command(0, 1'b0, 0, 1, 9);
        expect_error(16'h0502, 2);
        @(posedge clk); #2;
        send_command(14, 1'b0, 0, 3, 8);
        expect_error(16'h0503, 3);
        @(posedge clk); #2;
        send_command(15, 1'b1, 1, 1, 8);
        expect_error(16'h0503, 4);
        @(posedge clk); #2;

        // Slot 8 is deliberately uninitialized in the Scratchpad model.  The
        // response error propagates without emitting its undefined data.
        expected_count = 0;
        received_count = 0;
        send_command(8, 1'b0, 0, 1, 8);
        expect_error(16'h0504, 5);
        if (received_count != 0 || request_count != 6)
            $fatal(1, "Scratchpad error leaked data or duplicated reads");
        if (done_count != 2 || error_count != 6)
            $fatal(1, "terminal pulse totals done=%0d error=%0d",
                   done_count, error_count);
        if (stall_cycles == 0)
            $fatal(1, "test did not exercise output backpressure");

        $display("PASS internal EMIT output stream: indexed bounds, partial keep, %0d stalled cycles, no loss/duplication, Scratchpad error propagation",
                 stall_cycles);
        $finish;
    end
endmodule

`default_nettype wire
