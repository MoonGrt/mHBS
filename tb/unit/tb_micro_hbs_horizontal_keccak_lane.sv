`timescale 1ns/1ps
`default_nettype none

module tb_micro_hbs_horizontal_keccak_lane;
    logic clk = 1'b0;
    logic rst_n = 1'b0;
    logic [1:0] request_valid = 0;
    wire [1:0] request_ready;
    logic [2:0] request_event [0:1];
    logic [1599:0] request_state [0:1];
    wire [1:0] response_valid;
    wire [2:0] response_event [0:1];
    wire [1599:0] response_state [0:1];
    wire [5:0] rounds_executed [0:1];
    integer seen = 0;
    integer cycle = 0;
    integer accepted_cycle = 0;
    genvar lane;

    always #5 clk = ~clk;
    always @(posedge clk) if (rst_n) cycle <= cycle + 1;

    generate
        for (lane = 0; lane < 2; lane = lane + 1) begin : lanes
            micro_hbs_horizontal_keccak_lane #(.UNROLL(2)) dut (
                .clk, .rst_n, .request_valid(request_valid[lane]),
                .request_ready(request_ready[lane]),
                .request_event(request_event[lane]),
                .request_state(request_state[lane]),
                .chain_enable(1'b0), .chain_prefix(1'b0),
                .chain_prefix_preserve_counter(1'b0),
                .chain_prefix_domain(3'b0), .chain_count(8'd1),
                .chain_counter_offset(8'b0),
                .chain_feedback_offset(8'b0),
                .chain_feedback_bytes(6'b0),
                .chain_counter_start(32'b0), .capture_enable(1'b0),
                .capture_after(8'b0),
                .response_valid(response_valid[lane]),
                .response_event(response_event[lane]),
                .response_state(response_state[lane]), .capture_digest(),
                .capture_valid(), .rounds_executed(rounds_executed[lane])
            );
        end
    endgenerate

    always @(posedge clk) begin
        if (rst_n) begin
            if (response_valid[0]) begin
                if (response_event[0] != 3'd2
                    || response_state[0][255:0]
                       != 256'h39578be737ea944feee1f1f83045b48d4d11c40c0863681c77a8601360663348)
                    $fatal(1, "direct lane0 response mismatch");
                if (cycle - accepted_cycle != 13)
                    $fatal(1, "lane0 completion latency=%0d", cycle-accepted_cycle);
                seen = seen | 1;
            end
            if (response_valid[1]) begin
                if (response_event[1] != 3'd5
                    || response_state[1][255:0]
                       != 256'h2f76d56e64270cb5821bb862ea52cd3f24eb3e74eb3f3b23138da80b2bddb946)
                    $fatal(1, "direct lane1 response mismatch");
                if (rounds_executed[1] != 24)
                    $fatal(1, "lane1 round count mismatch");
                seen = seen | 2;
            end
            if (seen == 3) begin
                $display("PASS two equal direct Keccak lanes, U2, 12 active cycles");
                $finish;
            end
        end
    end

    initial begin
        request_state[0] = '0;
        request_state[0][23:0] = 24'h636261;
        request_state[0][8*3 +: 8] = 8'h1f;
        request_state[0][8*135 +: 8] = 8'h80;
        request_state[1] = '0;
        request_state[1][7:0] = 8'h1f;
        request_state[1][8*135 +: 8] = 8'h80;
        request_event[0] = 2;
        request_event[1] = 5;
        repeat (3) @(posedge clk);
        rst_n = 1'b1;
        @(negedge clk);
        request_valid = 2'b11;
        @(posedge clk);
        accepted_cycle = cycle;
        #1 request_valid = 0;
    end

    initial begin
        #2000;
        $fatal(1, "direct Keccak lane timeout seen=%0d", seen);
    end
endmodule

`default_nettype wire
