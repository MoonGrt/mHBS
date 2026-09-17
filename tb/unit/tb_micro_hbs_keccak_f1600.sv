`timescale 1ns/1ps
`default_nettype none

module tb_micro_hbs_keccak_f1600;
    logic clk = 1'b0;
    logic rst_n = 1'b0;
    logic start = 1'b0;
    logic [1599:0] state_in = '0;
    wire ready_u1;
    wire ready_u2;
    wire [1599:0] state_out_u1;
    wire [1599:0] state_out_u2;
    wire done_u1;
    wire done_u2;
    wire [5:0] rounds_u1;
    wire [5:0] rounds_u2;
    integer cycles;
    integer done_cycle_u1;
    integer done_cycle_u2;
    integer lane;
    reg [63:0] expected [0:24];

    always #5 clk = ~clk;

    micro_hbs_keccak_f1600 #(.UNROLL(1)) dut_u1 (
        .clk, .rst_n, .start, .ready(ready_u1), .state_in,
        .chain_enable(1'b0), .chain_count(8'd1),
        .chain_counter_offset(8'b0), .chain_feedback_offset(8'b0),
        .chain_feedback_bytes(6'b0), .chain_counter_start(32'b0),
        .capture_enable(1'b0), .capture_after(8'b0),
        .state_out(state_out_u1), .done(done_u1),
        .capture_digest(), .capture_valid(), .rounds_executed(rounds_u1)
    );
    micro_hbs_keccak_f1600 #(.UNROLL(2)) dut_u2 (
        .clk, .rst_n, .start, .ready(ready_u2), .state_in,
        .chain_enable(1'b0), .chain_count(8'd1),
        .chain_counter_offset(8'b0), .chain_feedback_offset(8'b0),
        .chain_feedback_bytes(6'b0), .chain_counter_start(32'b0),
        .capture_enable(1'b0), .capture_after(8'b0),
        .state_out(state_out_u2), .done(done_u2),
        .capture_digest(), .capture_valid(), .rounds_executed(rounds_u2)
    );

    initial begin
        expected[ 0] = 64'hf1258f7940e1dde7; expected[ 1] = 64'h84d5ccf933c0478a;
        expected[ 2] = 64'hd598261ea65aa9ee; expected[ 3] = 64'hbd1547306f80494d;
        expected[ 4] = 64'h8b284e056253d057; expected[ 5] = 64'hff97a42d7f8e6fd4;
        expected[ 6] = 64'h90fee5a0a44647c4; expected[ 7] = 64'h8c5bda0cd6192e76;
        expected[ 8] = 64'had30a6f71b19059c; expected[ 9] = 64'h30935ab7d08ffc64;
        expected[10] = 64'heb5aa93f2317d635; expected[11] = 64'ha9a6e6260d712103;
        expected[12] = 64'h81a57c16dbcf555f; expected[13] = 64'h43b831cd0347c826;
        expected[14] = 64'h01f22f1a11a5569f; expected[15] = 64'h05e5635a21d9ae61;
        expected[16] = 64'h64befef28cc970f2; expected[17] = 64'h613670957bc46611;
        expected[18] = 64'hb87c5a554fd00ecb; expected[19] = 64'h8c3ee88a1ccf32c8;
        expected[20] = 64'h940c7922ae3a2614; expected[21] = 64'h1841f924a2c509e4;
        expected[22] = 64'h16f53526e70465c2; expected[23] = 64'h75f644e97f30a13b;
        expected[24] = 64'heaf1ff7b5ceca249;

        repeat (3) @(posedge clk);
        rst_n <= 1'b1;
        @(posedge clk);
        if (!ready_u1 || !ready_u2) $fatal(1, "lanes not ready after reset");
        start <= 1'b1;
        @(posedge clk);
        start <= 1'b0;

        cycles = 0;
        done_cycle_u1 = 0;
        done_cycle_u2 = 0;
        while (done_cycle_u1 == 0 || done_cycle_u2 == 0) begin
            @(posedge clk);
            #1;
            cycles = cycles + 1;
            if (done_u1 && done_cycle_u1 == 0) done_cycle_u1 = cycles;
            if (done_u2 && done_cycle_u2 == 0) done_cycle_u2 = cycles;
            if (cycles > 30) $fatal(1, "permutation timeout");
        end
        #1;
        if (rounds_u1 != 24 || rounds_u2 != 24)
            $fatal(1, "wrong round count U1=%0d U2=%0d", rounds_u1, rounds_u2);
        if (done_cycle_u1 != 24 || done_cycle_u2 != 12)
            $fatal(1, "wrong latency U1=%0d U2=%0d", done_cycle_u1, done_cycle_u2);
        for (lane = 0; lane < 25; lane = lane + 1) begin
            if (state_out_u1[64*lane +: 64] !== expected[lane])
                $fatal(1, "U1 mismatch lane %0d got=%016x expected=%016x",
                       lane, state_out_u1[64*lane +: 64], expected[lane]);
            if (state_out_u2[64*lane +: 64] !== expected[lane])
                $fatal(1, "U2 mismatch lane %0d got=%016x expected=%016x",
                       lane, state_out_u2[64*lane +: 64], expected[lane]);
        end
        if (state_out_u1 !== state_out_u2) $fatal(1, "U1/U2 mismatch");
        $display("PASS keccak-f1600 zero-state U1_cycles=%0d U2_cycles=%0d",
                 done_cycle_u1, done_cycle_u2);
        $finish;
    end
endmodule

`default_nettype wire
