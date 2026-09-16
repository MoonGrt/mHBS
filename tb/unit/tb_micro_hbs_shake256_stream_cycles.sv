`timescale 1ns/1ps
`default_nettype none

module tb_micro_hbs_shake256_stream_cycles;
    logic clk = 1'b0;
    logic rst_n = 1'b0;
    logic hash_start = 1'b0;
    wire hash_ready;
    logic block_valid = 1'b0;
    wire block_ready;
    logic [1087:0] block_data = '0;
    logic [7:0] block_bytes = '0;
    logic block_last = 1'b0;
    wire [255:0] digest;
    wire [1087:0] rate_output;
    wire digest_valid;
    wire error;

    integer cycle_counter = 0;
    integer latency_1;
    integer latency_2;
    integer latency_5;
    integer accepted_jobs = 0;
    integer accepted_blocks = 0;

    always #5 clk = ~clk;

    always @(posedge clk) begin
        cycle_counter = cycle_counter + 1;
        if (hash_start && hash_ready)
            accepted_jobs = accepted_jobs + 1;
        if (block_valid && block_ready)
            accepted_blocks = accepted_blocks + 1;
    end

    micro_hbs_shake256_stream #(.UNROLL(2)) dut (.*);

    task automatic run_hash;
        input integer full_blocks;
        input integer final_bytes;
        output integer measured_latency;
        integer start_cycle;
        integer block_index;
        begin
            @(negedge clk);
            while (!hash_ready) @(negedge clk);
            hash_start = 1'b1;
            @(posedge clk);
            #1;
            start_cycle = cycle_counter;
            @(negedge clk);
            hash_start = 1'b0;

            for (block_index = 0; block_index <= full_blocks;
                 block_index = block_index + 1) begin
                while (!block_ready) @(negedge clk);
                block_data = '0;
                block_data[31:0] = block_index;
                block_valid = 1'b1;
                block_last = (block_index == full_blocks);
                block_bytes = block_last ? final_bytes[7:0] : 8'd136;
                @(negedge clk);
                block_valid = 1'b0;
                block_last = 1'b0;
                block_bytes = '0;
            end

            while (!digest_valid) begin
                @(posedge clk);
                #1;
                if (error)
                    $fatal(1, "unexpected SHAKE stream error");
            end
            measured_latency = cycle_counter - start_cycle;
        end
    endtask

    initial begin
        repeat (3) @(negedge clk);
        rst_n = 1'b1;

        run_hash(0, 0, latency_1);
        run_hash(1, 0, latency_2);
        run_hash(4, 64, latency_5);

        if (latency_1 != 15 || latency_2 != 30 || latency_5 != 75)
            $fatal(1, "U2 stream latency mismatch one=%0d two=%0d five=%0d",
                   latency_1, latency_2, latency_5);
        if (accepted_jobs != 3 || accepted_blocks != 8)
            $fatal(1, "acceptance accounting mismatch jobs=%0d blocks=%0d",
                   accepted_jobs, accepted_blocks);

        $display("PASS U2 SHAKE stream cycle calibration: blocks 1/2/5 -> cycles %0d/%0d/%0d, formula 15*blocks",
                 latency_1, latency_2, latency_5);
        $finish;
    end
endmodule

`default_nettype wire
