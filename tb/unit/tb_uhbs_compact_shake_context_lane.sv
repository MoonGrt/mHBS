`timescale 1ns/1ps
`default_nettype none

module tb_uhbs_compact_shake_context_lane;
    wire [5:0] node_bytes=16;
    wire [383:0] chain_prefix_data=0;
    logic clk = 1'b0;
    logic rst = 1'b1;
    logic context_valid = 1'b0;
    wire context_ready;
    logic fast_block_valid = 1'b0;
    wire fast_block_ready;
    logic [1087:0] fast_block_data = '0;
    logic chain_enable = 1'b0;
    logic chain_prefix = 1'b0;
    logic chain_prefix_preserve_counter = 1'b0;
    logic [2:0] chain_prefix_domain = '0;
    logic [4:0] chain_count = 5'd1;
    logic capture_enable = 1'b0;
    logic [4:0] capture_after = '0;
    logic block_valid = 1'b0;
    wire block_ready;
    logic [127:0] block_data = '0;
    logic block_last = 1'b0;
    wire response_valid;
    wire [271:0] response_digest;
    wire chain_feedback_valid;
    wire [3:0] chain_feedback_counter;
    wire finish_valid;
    wire [271:0] finish_digest;
    wire [127:0] capture_digest;
    wire capture_valid;
    wire error;
    byte message [0:607];
    integer index;

    localparam [271:0] EXPECT_135 = 272'hc45dae624ad8a2f5aa7bac9d7557737fd91c96eedb70a6be5574d57a844eade07f40;
    localparam [271:0] EXPECT_136 = 272'hb7ff4073b3f5a8eabd6e17705ca7f6761a31058f9df781a6a47e3a3063b9d67a757e;
    localparam [271:0] EXPECT_137 = 272'h01d90952c642a5eb2a8fc9d713f843a45d7ac05132dddcb2efc9bebc27e37bcbe421;

    localparam [271:0] EXPECT_200 =
        272'h4ee1ca03272b05d3bfb1e1c79a967f823b9fc5e4bb3987b1ba9e9cb5afb07a5ee3a0;
    localparam [271:0] EXPECT_608 =
        272'h80d2b3c38ca9553941ab20c313013445533a8d66500f54bbb422e9c8c00b85e27c31;
    localparam [271:0] EXPECT_CHAIN3 =
        272'hc74e44ee63bb0abbebf4732157217c37ee639054a9f7f01c77d4475fb99107cb0c74;
    localparam [127:0] EXPECT_CAPTURE2 =
        128'hddb7193341317323287dffab3c961491;

    always #5 clk = ~clk;

    uhbs_compact_shake_context_lane #(.UNROLL(2)) dut (.*);

    task automatic tick;
        begin @(posedge clk); #1; end
    endtask

    task automatic start_context;
        begin
            context_valid = 1'b1;
            while (!context_ready) tick();
            tick();
            context_valid = 1'b0;
        end
    endtask

    task automatic send_rate_block(
        input [1087:0] rate_block,
        input logic is_last
    );
        integer beat;
        begin
            block_last = is_last;
            for (beat = 0; beat < 9; beat = beat + 1) begin
                block_data = beat == 8
                    ? {64'd0, rate_block[1024 +: 64]}
                    : rate_block[beat*128 +: 128];
                block_valid = 1'b1;
                while (!block_ready) tick();
                tick();
                block_valid = 1'b0;
            end
        end
    endtask

    task automatic check_digest(input [271:0] expected);
        integer byte_index;
        begin
            while (!response_valid) tick();
            if (error)
                $fatal(1, "compact SHAKE lane reported error");
            for (byte_index = 0; byte_index < 34;
                 byte_index = byte_index + 1)
                if (response_digest[byte_index*8 +: 8]
                    !== expected[(33-byte_index)*8 +: 8])
                    $fatal(1, "digest mismatch byte=%0d", byte_index);
            tick();
        end
    endtask

    task automatic run_message(
        input integer length,
        input [271:0] expected
    );
        integer block_count;
        integer block_index;
        integer byte_in_block;
        integer global_byte;
        reg [1087:0] next_block;
        begin
            chain_enable = 1'b0;
            capture_enable = 1'b0;
            chain_count = 5'd1;
            start_context();
            block_count = (length / 136) + 1;
            for (block_index = 0; block_index < block_count;
                 block_index = block_index + 1) begin
                next_block = '0;
                for (byte_in_block = 0; byte_in_block < 136;
                     byte_in_block = byte_in_block + 1) begin
                    global_byte = block_index * 136 + byte_in_block;
                    if (global_byte < length)
                        next_block[byte_in_block*8 +: 8]
                            = message[global_byte];
                    else if (global_byte == length)
                        next_block[byte_in_block*8 +: 8] = 8'h1f;
                end
                if (block_index == block_count - 1)
                    next_block[1087] = 1'b1;
                send_rate_block(next_block,
                    block_index == block_count - 1);
            end
            check_digest(expected);
        end
    endtask

    task automatic run_chain_capture;
        integer byte_index;
        reg [1087:0] next_block;
        begin
            chain_enable = 1'b1;
            chain_prefix = 1'b0;
            chain_prefix_preserve_counter = 1'b0;
            chain_count = 5'd3;
            capture_enable = 1'b1;
            capture_after = 5'd2;
            start_context();
            next_block = '0;
            for (byte_index = 0; byte_index < 48;
                 byte_index = byte_index + 1)
                next_block[byte_index*8 +: 8] = byte_index[7:0];
            for (byte_index = 0; byte_index < 16;
                 byte_index = byte_index + 1)
                next_block[(48+byte_index)*8 +: 8]
                    = 8'ha0 + byte_index[7:0];
            next_block[64*8 +: 8] = 8'h1f;
            next_block[1087] = 1'b1;
            send_rate_block(next_block, 1'b1);
            while (!response_valid) tick();
            if (error || !capture_valid)
                $fatal(1, "chain/capture completion mismatch");
            for (byte_index = 0; byte_index < 34;
                 byte_index = byte_index + 1)
                if (response_digest[byte_index*8 +: 8]
                    !== EXPECT_CHAIN3[(33-byte_index)*8 +: 8])
                    $fatal(1, "chain digest mismatch byte=%0d", byte_index);
            for (byte_index = 0; byte_index < 16;
                 byte_index = byte_index + 1)
                if (capture_digest[byte_index*8 +: 8]
                    !== EXPECT_CAPTURE2[(15-byte_index)*8 +: 8])
                    $fatal(1, "capture mismatch byte=%0d", byte_index);
            tick();
        end
    endtask

    initial begin #1000000; $fatal(1,"compact SHAKE unit timeout"); end

    initial begin
        for (index = 0; index < 608; index = index + 1)
            message[index] = index[7:0];
        repeat (3) tick();
        rst = 1'b0;
        tick();
        run_message(135, EXPECT_135);
        run_message(136, EXPECT_136);
        run_message(137, EXPECT_137);
        run_message(200, EXPECT_200);
        run_message(608, EXPECT_608);
        run_chain_capture();
        $display("COMPACT_SHAKE_CONTEXT_LANE_PASS");
        $finish;
    end
endmodule

`default_nettype wire
