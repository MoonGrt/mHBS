`timescale 1ns/1ps
`default_nettype none

module tb_micro_hbs_shake256_single_block;
    logic clk = 1'b0;
    logic rst_n = 1'b0;
    logic start = 1'b0;
    logic [1087:0] message = '0;
    logic [7:0] message_length = '0;
    wire ready;
    wire [255:0] digest;
    wire done;
    wire error;
    integer i;

    always #5 clk = ~clk;

    micro_hbs_shake256_single_block #(.UNROLL(2)) dut (
        .clk, .rst_n, .start, .ready, .message, .message_length,
        .repeat_enable(1'b0), .repeat_prefix(1'b0),
        .repeat_prefix_preserve_counter(1'b0),
        .repeat_prefix_domain(3'b0), .repeat_count(8'd1),
        .repeat_counter_offset(8'b0), .repeat_feedback_offset(8'b0),
        .repeat_feedback_bytes(6'b0), .repeat_counter_start(32'b0),
        .capture_enable(1'b0), .capture_after(8'b0),
        .capture_digest(), .capture_valid(),
        .digest, .done, .error
    );

    task automatic run_vector;
        input [7:0] length;
        input [255:0] expected;
        begin
            message_length = length;
            while (!ready) @(posedge clk);
            start = 1'b1;
            @(posedge clk);
            #1 start = 1'b0;
            while (!done && !error) begin
                @(posedge clk);
                #1;
            end
            if (error) $fatal(1, "unexpected SHAKE error for length %0d", length);
            if (digest !== expected)
                $fatal(1, "SHAKE mismatch length=%0d got=%064x expected=%064x",
                       length, digest, expected);
        end
    endtask

    initial begin
        repeat (3) @(posedge clk);
        rst_n = 1'b1;
        @(posedge clk);

        message = '0;
        run_vector(0, 256'h2f76d56e64270cb5821bb862ea52cd3f24eb3e74eb3f3b23138da80b2bddb946);

        message = '0;
        message[7:0] = 8'h61;
        message[15:8] = 8'h62;
        message[23:16] = 8'h63;
        run_vector(3, 256'h39578be737ea944feee1f1f83045b48d4d11c40c0863681c77a8601360663348);

        message = '0;
        for (i = 0; i < 135; i = i + 1)
            message[8*i +: 8] = i[7:0];
        run_vector(135, 256'he0ad4e847ad57455bea670dbee961cd97f7357759dac7baaf5a2d84a62ae5dc4);

        message_length = 136;
        while (!ready) @(posedge clk);
        start = 1'b1;
        @(posedge clk);
        #1 start = 1'b0;
        if (!error || done) $fatal(1, "invalid length did not fail closed");

        $display("PASS SHAKE256 single-block KAT empty/abc/rate-edge and length rejection");
        $finish;
    end
endmodule

`default_nettype wire
