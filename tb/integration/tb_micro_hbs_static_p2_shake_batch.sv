`timescale 1ns/1ps
`default_nettype none

module tb_micro_hbs_static_p2_shake_batch;
    localparam integer MAX_TASKS = 5;

    logic clk = 1'b0;
    logic rst_n = 1'b0;
    logic batch_start = 1'b0;
    logic [7:0] batch_count = '0;
    logic [MAX_TASKS*1088-1:0] batch_messages = '0;
    logic [MAX_TASKS*8-1:0] batch_message_lengths = '0;
    wire [MAX_TASKS*256-1:0] batch_digests;
    wire batch_ready;
    wire busy;
    wire batch_done;
    wire batch_error;
    wire dispatch_valid;
    wire [1:0] dispatch_lane_mask;
    wire [7:0] dispatch_pair_index;
    wire [31:0] lane0_active_cycles;
    wire [31:0] lane0_idle_cycles;
    wire [31:0] lane1_active_cycles;
    wire [31:0] lane1_idle_cycles;

    logic [1:0] observed_masks [0:2];
    logic [7:0] observed_pairs [0:2];
    integer observed_dispatches = 0;
    integer accepted_batch_pulses = 0;
    integer watchdog;
    integer i;

    always #5 clk = ~clk;

    micro_hbs_static_p2_shake_batch #(
        .MAX_TASKS(MAX_TASKS),
        .UNROLL(2)
    ) dut (.*);

    always @(posedge clk) begin
        if (batch_start && batch_ready)
            accepted_batch_pulses = accepted_batch_pulses + 1;
        #1;
        if (dispatch_valid) begin
            observed_masks[observed_dispatches] = dispatch_lane_mask;
            observed_pairs[observed_dispatches] = dispatch_pair_index;
            observed_dispatches = observed_dispatches + 1;
        end
    end

    task automatic set_task;
        input integer slot;
        input [7:0] length;
        input [1087:0] message;
        begin
            batch_messages[1088*slot +: 1088] = message;
            batch_message_lengths[8*slot +: 8] = length;
        end
    endtask

    task automatic launch_batch;
        input [7:0] count;
        begin
            // Always create a full setup interval, including when this task is
            // entered while the preceding batch_done pulse is still visible.
            @(negedge clk);
            while (!batch_ready) @(negedge clk);
            batch_count = count;
            batch_start = 1'b1;
            @(negedge clk);
            batch_start = 1'b0;

            // The input vectors are not a runtime stream.  The accepted batch
            // must survive immediate host-side mutation without extra writes.
            batch_count = 0;
            batch_messages = '1;
            batch_message_lengths = '1;

            watchdog = 0;
            if (!busy)
                $fatal(1, "accepted batch did not enter busy state");
            while (!batch_done && !batch_error) begin
                @(posedge clk);
                #1;
                watchdog = watchdog + 1;
                if (watchdog > 200)
                    $fatal(1, "static P=2 batch timeout");
            end
            if (batch_error)
                $fatal(1, "unexpected batch error");
        end
    endtask

    task automatic expect_digest;
        input integer slot;
        input [255:0] expected;
        begin
            if (batch_digests[256*slot +: 256] !== expected)
                $fatal(1, "digest[%0d] mismatch got=%064x expected=%064x",
                       slot, batch_digests[256*slot +: 256], expected);
        end
    endtask

    task automatic expect_rejected;
        input [7:0] count;
        begin
            @(negedge clk);
            while (!batch_ready) @(negedge clk);
            batch_count = count;
            batch_start = 1'b1;
            @(posedge clk);
            #1;
            batch_start = 1'b0;
            if (!batch_error || busy || batch_done)
                $fatal(1, "invalid batch was not rejected count=%0d error=%0b busy=%0b done=%0b",
                       count, batch_error, busy, batch_done);
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
        @(negedge clk);

        // Even batch: both statically paired dispatches must use both lanes.
        batch_messages = '0;
        batch_message_lengths = '0;
        set_task(0, 0, empty_message);
        set_task(1, 3, abc_message);
        set_task(2, 135, rate_edge_message);
        set_task(3, 1, zero_byte_message);
        observed_dispatches = 0;
        launch_batch(4);
        expect_digest(0, 256'h2f76d56e64270cb5821bb862ea52cd3f24eb3e74eb3f3b23138da80b2bddb946);
        expect_digest(1, 256'h39578be737ea944feee1f1f83045b48d4d11c40c0863681c77a8601360663348);
        expect_digest(2, 256'he0ad4e847ad57455bea670dbee961cd97f7357759dac7baaf5a2d84a62ae5dc4);
        expect_digest(3, 256'h540d60b8f4366ea8f02e0430bf0bdee541cfeaddf636c6825807f755f81dd0b8);
        if (observed_dispatches != 2
            || observed_masks[0] != 2'b11 || observed_masks[1] != 2'b11
            || observed_pairs[0] != 0 || observed_pairs[1] != 1)
            $fatal(1, "even static assignment mismatch dispatches=%0d masks=%b,%b pairs=%0d,%0d",
                   observed_dispatches, observed_masks[0], observed_masks[1],
                   observed_pairs[0], observed_pairs[1]);
        if (lane0_active_cycles != 32 || lane1_active_cycles != 32
            || lane0_idle_cycles != 2 || lane1_idle_cycles != 2)
            $fatal(1, "even batch lane accounting mismatch active=%0d/%0d idle=%0d/%0d",
                   lane0_active_cycles, lane1_active_cycles,
                   lane0_idle_cycles, lane1_idle_cycles);

        // Odd batch: one dual-valid pair followed by the fixed lane-0 tail.
        batch_messages = '0;
        batch_message_lengths = '0;
        set_task(0, 3, abc_message);
        set_task(1, 0, empty_message);
        set_task(2, 1, zero_byte_message);
        observed_dispatches = 0;
        launch_batch(3);
        expect_digest(0, 256'h39578be737ea944feee1f1f83045b48d4d11c40c0863681c77a8601360663348);
        expect_digest(1, 256'h2f76d56e64270cb5821bb862ea52cd3f24eb3e74eb3f3b23138da80b2bddb946);
        expect_digest(2, 256'h540d60b8f4366ea8f02e0430bf0bdee541cfeaddf636c6825807f755f81dd0b8);
        if (observed_dispatches != 2
            || observed_masks[0] != 2'b11 || observed_masks[1] != 2'b01
            || observed_pairs[0] != 0 || observed_pairs[1] != 1)
            $fatal(1, "odd static assignment mismatch dispatches=%0d masks=%b,%b pairs=%0d,%0d",
                   observed_dispatches, observed_masks[0], observed_masks[1],
                   observed_pairs[0], observed_pairs[1]);
        if (lane0_active_cycles != 32 || lane1_active_cycles != 16
            || lane0_idle_cycles != 2 || lane1_idle_cycles != 18)
            $fatal(1, "odd-tail lane accounting mismatch active=%0d/%0d idle=%0d/%0d",
                   lane0_active_cycles, lane1_active_cycles,
                   lane0_idle_cycles, lane1_idle_cycles);
        if ((lane0_active_cycles + lane0_idle_cycles)
            != (lane1_active_cycles + lane1_idle_cycles))
            $fatal(1, "lane accounting windows differ");
        if (accepted_batch_pulses != 2)
            $fatal(1, "expected exactly two batch requests, got %0d",
                   accepted_batch_pulses);

        // Reject invalid work before either lane is started.
        batch_message_lengths = '0;
        expect_rejected(0);
        batch_message_lengths = '0;
        expect_rejected(MAX_TASKS + 1);
        batch_message_lengths = '0;
        batch_message_lengths[7:0] = 8'd136;
        expect_rejected(1);

        $display("PASS static P=2 U2 SHAKE256 batch KAT: 7 hashes/2 requests, masks 11/01, invalid batches rejected, lane accounting active=%0d/%0d idle=%0d/%0d",
                 lane0_active_cycles, lane1_active_cycles,
                 lane0_idle_cycles, lane1_idle_cycles);
        $finish;
    end
endmodule

`default_nettype wire
