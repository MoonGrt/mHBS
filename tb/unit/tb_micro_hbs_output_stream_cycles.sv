`timescale 1ns/1ps
`default_nettype none

module tb_micro_hbs_output_stream_cycles;
    logic clk = 1'b0;
    logic rst_n = 1'b0;
    logic emit_valid = 1'b0;
    wire emit_ready;
    logic [15:0] emit_base_slot = '0;
    logic emit_use_index = 1'b0;
    logic [31:0] emit_index_value = '0;
    logic [15:0] emit_length_words = '0;
    logic [3:0] emit_last_bytes = 4'd8;
    wire scratch_read_valid;
    wire scratch_read_ready = 1'b1;
    wire [15:0] scratch_read_address;
    logic scratch_response_valid = 1'b0;
    wire scratch_response_ready;
    logic [63:0] scratch_response_data = '0;
    logic scratch_response_error = 1'b0;
    wire out_valid;
    wire out_ready = 1'b1;
    wire [63:0] out_data;
    wire [7:0] out_keep;
    wire out_last;
    wire busy;
    wire done;
    wire error;
    wire [15:0] error_code;

    integer cycle_counter = 0;
    integer accepted_reads = 0;
    integer accepted_outputs = 0;
    integer latency_1;
    integer latency_2;
    integer latency_3;

    always #5 clk = ~clk;
    always @(posedge clk) cycle_counter = cycle_counter + 1;

    micro_hbs_output_stream #(
        .SCRATCH_WORDS(16), .ADDRESS_WIDTH(16)
    ) dut (.*);

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            scratch_response_valid <= 1'b0;
            scratch_response_data <= '0;
            accepted_reads <= 0;
            accepted_outputs <= 0;
        end else begin
            if (scratch_response_valid && scratch_response_ready)
                scratch_response_valid <= 1'b0;
            if (scratch_read_valid && scratch_read_ready) begin
                scratch_response_valid <= 1'b1;
                scratch_response_data <= {48'h0123_4567_89ab,
                                          scratch_read_address};
                accepted_reads <= accepted_reads + 1;
            end
            if (out_valid && out_ready)
                accepted_outputs <= accepted_outputs + 1;
        end
    end

    task automatic run_emit;
        input integer words;
        output integer measured_latency;
        integer start_cycle;
        begin
            @(negedge clk);
            while (!emit_ready) @(negedge clk);
            emit_length_words = words[15:0];
            emit_valid = 1'b1;
            @(posedge clk);
            #1 start_cycle = cycle_counter;
            @(negedge clk);
            emit_valid = 1'b0;
            while (!done && !error) begin
                @(posedge clk);
                #1;
            end
            if (error)
                $fatal(1, "unexpected output-stream error %h", error_code);
            measured_latency = cycle_counter - start_cycle;
        end
    endtask

    initial begin
        repeat (3) @(negedge clk);
        rst_n = 1'b1;
        run_emit(1, latency_1);
        run_emit(2, latency_2);
        run_emit(3, latency_3);
        if (latency_1 != 3 || latency_2 != 6 || latency_3 != 9)
            $fatal(1, "output latency mismatch one=%0d two=%0d three=%0d",
                   latency_1, latency_2, latency_3);
        if (accepted_reads != 6 || accepted_outputs != 6)
            $fatal(1, "output accounting mismatch reads=%0d outputs=%0d",
                   accepted_reads, accepted_outputs);
        $display("PASS output stream cycle calibration: words 1/2/3 -> cycles %0d/%0d/%0d, formula 3*words no-stall",
                 latency_1, latency_2, latency_3);
        $finish;
    end
endmodule

`default_nettype wire
