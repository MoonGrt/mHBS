`timescale 1ns/1ps
`default_nettype none

module tb_micro_hbs_hash_lane_service;
    logic clk = 1'b0;
    logic rst_n = 1'b0;
    logic [1:0] job_valid = 0;
    wire [1:0] job_ready;
    logic [2:0] job_event [0:1];
    logic [1:0] block_valid = 0;
    wire [1:0] block_ready;
    logic [1087:0] block_data [0:1];
    logic [7:0] block_bytes [0:1];
    wire [1:0] response_valid;
    wire [2:0] response_event [0:1];
    wire [255:0] response_digest [0:1];
    wire [1:0] error;
    integer seen = 0;
    genvar lane;

    always #5 clk = ~clk;

    generate
        for (lane = 0; lane < 2; lane = lane + 1) begin : lanes
            micro_hbs_hash_lane_service #(.UNROLL(2)) dut (
                .clk, .rst_n, .job_valid(job_valid[lane]),
                .job_ready(job_ready[lane]), .job_event(job_event[lane]),
                .repeat_enable(1'b0), .repeat_prefix(1'b0),
                .repeat_prefix_preserve_counter(1'b0),
                .repeat_prefix_domain(3'b0), .repeat_count(8'd1),
                .repeat_counter_offset(8'b0),
                .repeat_feedback_offset(8'b0),
                .repeat_feedback_bytes(6'b0),
                .repeat_counter_start(32'b0), .capture_enable(1'b0),
                .capture_after(8'b0), .block_valid(block_valid[lane]),
                .block_ready(block_ready[lane]), .block_data(block_data[lane]),
                .block_bytes(block_bytes[lane]), .block_last(1'b1),
                .response_valid(response_valid[lane]),
                .response_event(response_event[lane]),
                .response_digest(response_digest[lane]), .response_rate(),
                .capture_digest(), .capture_valid(), .error(error[lane]),
                .busy()
            );
        end
    endgenerate

    always @(posedge clk) begin
        if (rst_n) begin
            if (|error)
                $fatal(1, "equal hash lane service reported error");
            if (response_valid[0]) begin
                if (response_event[0] != 3'd2
                    || response_digest[0]
                       != 256'h39578be737ea944feee1f1f83045b48d4d11c40c0863681c77a8601360663348)
                    $fatal(1, "lane0 response mismatch");
                seen = seen | 1;
            end
            if (response_valid[1]) begin
                if (response_event[1] != 3'd5
                    || response_digest[1]
                       != 256'h2f76d56e64270cb5821bb862ea52cd3f24eb3e74eb3f3b23138da80b2bddb946)
                    $fatal(1, "lane1 response mismatch");
                seen = seen | 2;
            end
            if (seen == 3) begin
                $display("PASS two equivalent horizontal SHAKE lane services");
                $finish;
            end
        end
    end

    initial begin
        block_data[0] = '0;
        block_data[0][23:0] = 24'h636261;
        block_data[1] = '0;
        block_bytes[0] = 3;
        block_bytes[1] = 0;
        job_event[0] = 2;
        job_event[1] = 5;
        repeat (3) @(posedge clk);
        rst_n = 1'b1;
        @(negedge clk);
        if (job_ready != 2'b11)
            $fatal(1, "lanes not simultaneously ready");
        job_valid = 2'b11;
        block_valid = 2'b11;
        @(posedge clk);
        #1;
        job_valid = 0;
        block_valid = 0;
    end

    initial begin
        #2000;
        $fatal(1, "hash lane service timeout seen=%0d", seen);
    end
endmodule

`default_nettype wire
