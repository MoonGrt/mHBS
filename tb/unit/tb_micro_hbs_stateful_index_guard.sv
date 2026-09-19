`timescale 1ns/1ps
module tb_micro_hbs_stateful_index_guard;
    logic clk = 0;
    logic rst_n = 0;
    logic initialize_valid = 0, invalidate = 0, sign_valid = 0;
    logic [10:0] initial_q = 0;
    logic state_commit_ready = 0;
    wire initialize_ready, sign_ready, sign_grant, state_commit_valid;
    wire [9:0] sign_q;
    wire [10:0] state_next_q, current_q;
    wire initialized, error;
    wire [15:0] error_code;
    always #5 clk = ~clk;

    micro_hbs_stateful_index_guard dut (.*);

    task tick; begin @(posedge clk); #1; end endtask
    initial begin
        repeat (2) tick(); rst_n = 1; tick();
        sign_valid = 1; tick(); sign_valid = 0;
        if (!error || error_code != 16'h2501) $fatal(1, "sign-before-keygen");
        initial_q = 11'd5; initialize_valid = 1; tick();
        initialize_valid = 0; tick();
        if (!initialized || current_q != 5) $fatal(1, "initialize");
        sign_valid = 1; tick(); sign_valid = 0;
        if (!state_commit_valid || state_next_q != 6 || sign_grant)
            $fatal(1, "reservation");
        repeat (3) begin tick(); if (sign_grant) $fatal(1, "early release"); end
        state_commit_ready = 1; tick(); state_commit_ready = 0;
        if (!sign_grant || sign_q != 5 || current_q != 6)
            $fatal(1, "commit release");
        initial_q = 11'd1024; initialize_valid = 1; tick();
        initialize_valid = 0; sign_valid = 1; tick(); sign_valid = 0;
        if (!error || error_code != 16'h2502) $fatal(1, "exhaustion");
        $display("STATEFUL_INDEX_GUARD_PASS");
        $finish;
    end
endmodule
