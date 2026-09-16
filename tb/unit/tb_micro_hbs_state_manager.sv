`timescale 1ns/1ps
`default_nettype none

module tb_micro_hbs_state_manager;
    logic clk = 1'b0;
    logic rst_n = 1'b0;
    logic configure = 1'b0;
    logic [31:0] recovered_next_index = '0;
    logic [31:0] recovery_floor = '0;
    logic [31:0] maximum_index_exclusive = '0;
    wire configured;
    logic reserve = 1'b0;
    wire reserve_ready;
    wire persist_req_valid;
    wire [31:0] persist_next_index;
    logic persist_ack = 1'b0;
    wire release_valid;
    wire [31:0] release_index;
    logic consume = 1'b0;
    logic cancel = 1'b0;
    logic soft_reset = 1'b0;
    wire [31:0] next_index, burned_count, consumed_count;
    wire error;
    wire [15:0] error_code;

    always #5 clk = ~clk;
    micro_hbs_state_manager dut (.*);

    task automatic pulse_configure;
        input [31:0] recovered;
        input [31:0] floor;
        input [31:0] maximum;
        begin
            @(negedge clk);
            recovered_next_index = recovered;
            recovery_floor = floor;
            maximum_index_exclusive = maximum;
            configure = 1'b1;
            @(posedge clk);
            #1 configure = 1'b0;
        end
    endtask

    task automatic pulse_reserve;
        begin
            @(negedge clk);
            reserve = 1'b1;
            @(posedge clk);
            #1 reserve = 1'b0;
        end
    endtask

    initial begin
        repeat (3) @(posedge clk);
        rst_n = 1'b1;

        pulse_configure(2, 2, 5);
        if (!configured || !reserve_ready || next_index != 2 || error)
            $fatal(1, "configuration failed");

        pulse_reserve();
        if (!persist_req_valid || persist_next_index != 3 || release_valid)
            $fatal(1, "reserve did not enter persist-before-release");
        @(negedge clk);
        soft_reset = 1'b1;
        @(posedge clk);
        #1 soft_reset = 1'b0;
        if (!persist_req_valid || release_valid)
            $fatal(1, "soft reset bypassed required burn persistence");
        @(negedge clk);
        persist_ack = 1'b1;
        @(posedge clk);
        #1 persist_ack = 1'b0;
        if (release_valid || burned_count != 1 || next_index != 3)
            $fatal(1, "soft-reset index was not burned");

        pulse_reserve();
        if (release_valid || persist_next_index != 4)
            $fatal(1, "second reserve mismatch");
        @(negedge clk);
        persist_ack = 1'b1;
        @(posedge clk);
        #1 persist_ack = 1'b0;
        if (!release_valid || release_index != 3 || next_index != 4)
            $fatal(1, "index released before/without persistence");
        @(negedge clk);
        cancel = 1'b1;
        @(posedge clk);
        #1 cancel = 1'b0;
        if (release_valid || burned_count != 2)
            $fatal(1, "released then cancelled index was not burned");

        pulse_reserve();
        if (release_valid || persist_next_index != 5)
            $fatal(1, "third reserve mismatch");
        @(negedge clk);
        persist_ack = 1'b1;
        @(posedge clk);
        #1 persist_ack = 1'b0;
        if (!release_valid || release_index != 4 || next_index != 5)
            $fatal(1, "third index release mismatch");
        @(negedge clk);
        consume = 1'b1;
        @(posedge clk);
        #1 consume = 1'b0;
        if (release_valid || consumed_count != 1)
            $fatal(1, "consume transition failed");

        pulse_reserve();
        if (!error || error_code != 16'h0302)
            $fatal(1, "exhaustion not rejected");

        // A fresh recovery with a lower trusted floor must be rejected.
        @(negedge clk);
        rst_n = 1'b0;
        @(posedge clk);
        @(negedge clk);
        rst_n = 1'b1;
        pulse_configure(1, 2, 5);
        if (!error || error_code != 16'h0301 || configured)
            $fatal(1, "rollback recovery not rejected");

        $display("PASS state manager persist-before-release burn/consume/exhaustion/rollback");
        $finish;
    end
endmodule

`default_nettype wire
