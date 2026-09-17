`timescale 1ns/1ps
`default_nettype none

module tb_micro_hbs_shake256_stream;
    logic clk = 1'b0;
    logic rst_n = 1'b0;
    logic hash_start = 1'b0;
    logic block_valid = 1'b0;
    logic [1087:0] block_data = '0;
    logic [7:0] block_bytes = '0;
    logic block_last = 1'b0;
    wire hash_ready;
    wire block_ready;
    wire [255:0] digest;
    wire [1087:0] rate_output;
    wire digest_valid;
    wire error;
    integer i;
    integer watchdog = 0;

    always #5 clk = ~clk;
    always @(posedge clk) begin
        if (rst_n) begin
            watchdog = watchdog + 1;
            if (watchdog > 160)
                $fatal(1, "stream timeout state=%0d block_ready=%0d digest_valid=%0d error=%0d",
                       dut.state, block_ready, digest_valid, error);
        end
    end

    micro_hbs_shake256_stream #(.UNROLL(2)) dut (
        .clk, .rst_n, .hash_start, .hash_ready, .block_valid, .block_ready,
        .block_data, .block_bytes, .block_last,
        .repeat_enable(1'b0), .repeat_prefix(1'b0),
        .repeat_prefix_preserve_counter(1'b0),
        .repeat_prefix_domain(3'b0), .repeat_count(8'd1),
        .repeat_counter_offset(8'b0), .repeat_feedback_offset(8'b0),
        .repeat_feedback_bytes(6'b0), .repeat_counter_start(32'b0),
        .capture_enable(1'b0), .capture_after(8'b0),
        .digest, .rate_output, .digest_valid,
        .capture_digest(), .capture_valid(), .error
    );

    task automatic begin_hash;
        begin
            while (!hash_ready) @(negedge clk);
            @(negedge clk);
            hash_start = 1'b1;
            @(posedge clk);
            #1 hash_start = 1'b0;
        end
    endtask

    task automatic send_block;
        input [7:0] length;
        input is_last;
        begin
            while (!block_ready) @(negedge clk);
            @(negedge clk);
            block_bytes = length;
            block_last = is_last;
            block_valid = 1'b1;
            @(posedge clk);
            #1 block_valid = 1'b0;
        end
    endtask

    task automatic wait_digest;
        input [255:0] expected;
        begin
            while (!digest_valid && !error) begin
                @(posedge clk);
                #1;
            end
            if (error) $fatal(1, "unexpected stream error");
            if (digest !== expected)
                $fatal(1, "stream digest mismatch got=%064x expected=%064x", digest, expected);
        end
    endtask

    initial begin
        repeat (3) @(posedge clk);
        rst_n = 1'b1;
        @(posedge clk);

        begin_hash();
        block_data = '0;
        block_data[31:0] = 32'hefbeadde;
        block_data[8*7 +: 32] = 32'h04030201;
        for (i = 0; i < 13; i = i + 1)
            block_data[8*(11+i) +: 8] = 8'h20 + i;
        for (i = 0; i < 11; i = i + 1)
            block_data[8*(24+i) +: 8] = 8'hc0;
        send_block(35, 1'b1);
        wait_digest(256'h17f0641acdefdc80493c36b9281bd7c205147618c4d169a8164be4b435612aff);

        // The horizontal scheduler presents a complete one-block job in a
        // single transfer.  It must be bit-identical to the split handshake.
        while (!hash_ready) @(negedge clk);
        block_data = '0;
        block_data[31:0] = 32'hefbeadde;
        block_data[8*7 +: 32] = 32'h04030201;
        for (i = 0; i < 13; i = i + 1)
            block_data[8*(11+i) +: 8] = 8'h20 + i;
        for (i = 0; i < 11; i = i + 1)
            block_data[8*(24+i) +: 8] = 8'hc0;
        block_bytes = 35;
        block_last = 1'b1;
        hash_start = 1'b1;
        block_valid = 1'b1;
        @(posedge clk);
        #1 hash_start = 1'b0;
        block_valid = 1'b0;
        wait_digest(256'h17f0641acdefdc80493c36b9281bd7c205147618c4d169a8164be4b435612aff);

        // Exactly one full rate block requires a following empty final block.
        begin_hash();
        block_data = '0;
        for (i = 0; i < 136; i = i + 1)
            block_data[8*i +: 8] = i[7:0];
        send_block(136, 1'b0);
        block_data = '0;
        send_block(0, 1'b1);
        wait_digest(256'h7ad6b963303a7ea4a681f79d8f05311a76f6a75c70176ebdeaa8f5b37340ffb7);

        // 200 bytes exercises a full block plus a 64-byte final block.
        begin_hash();
        block_data = '0;
        for (i = 0; i < 136; i = i + 1)
            block_data[8*i +: 8] = i[7:0];
        send_block(136, 1'b0);
        block_data = '0;
        for (i = 0; i < 64; i = i + 1)
            block_data[8*i +: 8] = (i + 136) & 8'hff;
        send_block(64, 1'b1);
        wait_digest(256'h5e7ab0afb59c9ebab18739bbe4c59f3b827f969ac7e1b1bfd3052b2703cae14e);

        // A non-final short block is malformed and must fail closed.
        begin_hash();
        block_data = '0;
        send_block(17, 1'b0);
        if (!error || digest_valid) $fatal(1, "malformed block did not fail closed");

        $display("PASS SHAKE256 stream KAT 136/200-byte and malformed-block rejection");
        $finish;
    end
endmodule

`default_nettype wire
