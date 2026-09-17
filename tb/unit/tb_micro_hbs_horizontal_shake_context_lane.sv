`timescale 1ns/1ps
`default_nettype none

module tb_micro_hbs_horizontal_shake_context_lane;
    logic clk = 1'b0;
    logic rst_n = 1'b0;
    logic context_valid = 1'b0;
    wire context_ready;
    logic [2:0] context_event = '0;
    logic block_valid = 1'b0;
    wire block_ready;
    logic [1087:0] block_data = '0;
    logic block_last = 1'b0;
    wire response_valid;
    wire [2:0] response_event;
    wire [1599:0] response_state;
    wire error;
    byte message [0:607];
    integer index;
    integer block_index;
    integer position;
    integer message_length;

    // SHAKE256(range(200), 32) and SHAKE256(range(256)||range(256)||range(96),32)
    localparam [255:0] EXPECT_200 =
        256'h4ee1ca03272b05d3bfb1e1c79a967f823b9fc5e4bb3987b1ba9e9cb5afb07a5e;
    localparam [255:0] EXPECT_608 =
        256'h80d2b3c38ca9553941ab20c313013445533a8d66500f54bbb422e9c8c00b85e2;

    always #5 clk = ~clk;

    micro_hbs_horizontal_shake_context_lane #(.UNROLL(2)) dut (
        .clk, .rst_n, .context_valid, .context_ready, .context_event,
        .chain_enable(1'b0), .chain_prefix(1'b0),
        .chain_prefix_preserve_counter(1'b0), .chain_prefix_domain(3'd0),
        .chain_count(8'd1), .chain_counter_start(32'd0),
        .capture_enable(1'b0), .capture_after(8'd0),
        .block_valid, .block_ready, .block_data, .block_last,
        .response_valid, .response_event, .response_state,
        .capture_digest(), .capture_valid(), .error
    );

    task automatic tick;
        begin @(posedge clk); #1; end
    endtask

    task automatic run_message(
        input integer length,
        input [255:0] expected,
        input [2:0] event_id
    );
        integer block_count;
        integer byte_in_block;
        integer global_byte;
        reg [1087:0] next_block;
        begin
            message_length = length;
            context_event = event_id;
            context_valid = 1'b1;
            while (!context_ready) tick();
            tick();
            context_valid = 1'b0;

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
                    next_block[1087 -: 8] = next_block[1087 -: 8] | 8'h80;
                block_data = next_block;
                block_last = block_index == block_count - 1;
                block_valid = 1'b1;
                while (!block_ready) tick();
                tick();
                block_valid = 1'b0;
            end
            while (!response_valid) tick();
            if (error || response_event != event_id)
                $fatal(1, "context completion tag/error mismatch");
            // State bytes are little-endian in ascending packed slices.  The
            // literal is written in conventional hex order, hence byte swap.
            for (index = 0; index < 32; index = index + 1)
                if (response_state[index*8 +: 8]
                    !== expected[(31-index)*8 +: 8])
                    $fatal(1, "SHAKE mismatch length=%0d byte=%0d got=%02x expected=%02x",
                           length, index, response_state[index*8 +: 8],
                           expected[(31-index)*8 +: 8]);
            tick();
        end
    endtask

    initial begin
        for (index = 0; index < 608; index = index + 1)
            message[index] = index[7:0];
        repeat (3) tick();
        rst_n = 1'b1;
        tick();
        run_message(200, EXPECT_200, 3'd3);
        run_message(608, EXPECT_608, 3'd6);
        $display("HORIZONTAL_SHAKE_CONTEXT_LANE_PASS");
        $finish;
    end
endmodule

`default_nettype wire
