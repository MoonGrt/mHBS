`timescale 1ns/1ps
`default_nettype none

module tb_micro_hbs_slh_dsa_tree_parent;
    logic clk = 1'b0;
    logic rst_n = 1'b0;
    logic req_valid = 1'b0;
    wire req_ready;
    logic [127:0] req_public_seed = '0;
    logic [255:0] req_address = '0;
    logic [127:0] req_left_node = '0;
    logic [127:0] req_right_node = '0;
    wire rsp_valid;
    logic rsp_ready = 1'b0;
    wire [127:0] rsp_parent;
    wire rsp_error;

    integer request_handshakes = 0;
    integer response_handshakes = 0;
    integer shake_starts = 0;
    integer permutation_starts = 0;
    integer completed_permutations = 0;
    integer timeout;
    integer byte_index;
    logic [127:0] held_parent;

    // Independent Python hashlib.shake_256 vectors.  Serialized inputs are:
    //   PK.seed = 10..1f
    //   ADRS    = words [2,0,1,0x23456789,2,0,3,tree_index], big endian
    //   left    = a0..af
    //   right   = b0..bf
    // hashlib input is PK.seed || ADRS || left || right and output is 16 B.
    localparam logic [127:0] EXPECTED_BASE =
        128'h35e9ea9a5d76df6a7a6ba5fd2ce0dca5;
    localparam logic [127:0] EXPECTED_SWAPPED =
        128'h4b3fa77b07c6e3521dfb3d46211b515b;
    localparam logic [127:0] EXPECTED_ADDRESS_6 =
        128'h16c16d7b07208ad08aba05098c08e92f;

    always #5 clk = ~clk;

    micro_hbs_slh_dsa_tree_parent #(.UNROLL(2)) dut (
        .clk,
        .rst_n,
        .req_valid,
        .req_ready,
        .req_public_seed,
        .req_address,
        .req_left_node,
        .req_right_node,
        .rsp_valid,
        .rsp_ready,
        .rsp_parent,
        .rsp_error
    );

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            request_handshakes <= 0;
            response_handshakes <= 0;
            shake_starts <= 0;
            permutation_starts <= 0;
            completed_permutations <= 0;
        end else begin
            if (req_valid && req_ready)
                request_handshakes <= request_handshakes + 1;
            if (rsp_valid && rsp_ready)
                response_handshakes <= response_handshakes + 1;
            if (dut.shake_start) begin
                shake_starts <= shake_starts + 1;
                if (dut.shake_length != 80 || dut.shake_message[1087:640] != 0)
                    $fatal(1, "SLH-DSA H did not issue one 80-byte SHAKE input");
                if (dut.shake_message[639:0] !== {
                        req_right_node, req_left_node, req_address,
                        req_public_seed})
                    $fatal(1, "SLH-DSA H input field order mismatch");
            end
            if (dut.shake_lane.permutation_start) begin
                permutation_starts <= permutation_starts + 1;
                if (dut.shake_lane.padded_state[8*80 +: 8] != 8'h1f ||
                    dut.shake_lane.padded_state[8*135 +: 8] != 8'h80)
                    $fatal(1, "SHAKE domain/rate-end padding mismatch");
                for (byte_index = 81; byte_index < 135;
                     byte_index = byte_index + 1)
                    if (dut.shake_lane.padded_state[8*byte_index +: 8] != 0)
                        $fatal(1, "nonzero byte inside SHAKE padding at %0d",
                               byte_index);
            end
            if (dut.shake_done) begin
                completed_permutations <= completed_permutations + 1;
                if (dut.shake_lane.permutation_rounds != 24)
                    $fatal(1, "Keccak-f round boundary mismatch rounds=%0d",
                           dut.shake_lane.permutation_rounds);
            end
        end
    end

    task automatic run_success(
        input logic [127:0] expected_parent,
        input integer expected_count
    );
        begin
            while (!req_ready) @(negedge clk);
            @(negedge clk);
            req_valid = 1'b1;
            @(posedge clk);
            #1;
            if (request_handshakes != expected_count || req_ready)
                $fatal(1, "request handshake/count mismatch count=%0d",
                       request_handshakes);

            // Keep valid asserted after its handshake.  While this request is
            // active, it must neither restart SHAKE nor be accepted twice.
            repeat (3) begin
                @(posedge clk);
                #1;
                if (req_ready || request_handshakes != expected_count ||
                    shake_starts != expected_count)
                    $fatal(1, "duplicate parent request accepted");
            end
            @(negedge clk);
            req_valid = 1'b0;

            timeout = 0;
            while (!rsp_valid && timeout < 100) begin
                @(negedge clk);
                timeout = timeout + 1;
            end
            if (!rsp_valid || rsp_error || rsp_parent !== expected_parent)
                $fatal(1, "parent mismatch/error got=%h error=%b",
                       rsp_parent, rsp_error);
            if (shake_starts != expected_count ||
                permutation_starts != expected_count ||
                completed_permutations != expected_count)
                $fatal(1, "expected one SHAKE/permutation per parent: %0d/%0d/%0d",
                       shake_starts, permutation_starts,
                       completed_permutations);

            // The response and its status must remain stable under sink
            // backpressure, and no next request may be accepted meanwhile.
            held_parent = rsp_parent;
            repeat (4) begin
                @(posedge clk);
                #1;
                if (!rsp_valid || req_ready || rsp_error ||
                    rsp_parent !== held_parent)
                    $fatal(1, "parent response changed under backpressure");
            end
            @(negedge clk);
            rsp_ready = 1'b1;
            @(posedge clk);
            #1;
            if (response_handshakes != expected_count || rsp_valid)
                $fatal(1, "response handshake/count mismatch count=%0d",
                       response_handshakes);
            @(negedge clk);
            rsp_ready = 1'b0;
        end
    endtask

    initial begin
        req_public_seed = 128'h1f1e1d1c1b1a19181716151413121110;
        req_address =
            256'h0500000003000000000000000200000089674523010000000000000002000000;
        req_left_node = 128'hafaeadacabaaa9a8a7a6a5a4a3a2a1a0;
        req_right_node = 128'hbfbebdbcbbbab9b8b7b6b5b4b3b2b1b0;

        repeat (3) @(posedge clk);
        rst_n = 1'b1;

        run_success(EXPECTED_BASE, 1);

        // Node order is part of H's input and must not be commuted.
        held_parent = req_left_node;
        req_left_node = req_right_node;
        req_right_node = held_parent;
        run_success(EXPECTED_SWAPPED, 2);

        held_parent = req_left_node;
        req_left_node = req_right_node;
        req_right_node = held_parent;
        // Change only ADRS.treeIndex from 5 to 6.  SHAKE profiles consume the
        // full ADRS, so this byte must affect the parent.
        req_address[8*31 +: 8] = 8'h06;
        run_success(EXPECTED_ADDRESS_6, 3);

        // Fault-inject the primitive's otherwise unreachable fixed-length
        // error path.  Even if its in-flight permutation later completes, the
        // buffered response must stay error+zero until accepted.
        while (!req_ready) @(negedge clk);
        @(negedge clk);
        req_valid = 1'b1;
        @(negedge clk);
        req_valid = 1'b0;
        repeat (2) @(posedge clk);
        force dut.shake_error = 1'b1;
        @(posedge clk);
        #1;
        release dut.shake_error;
        if (!rsp_valid || !rsp_error || rsp_parent !== 0 || req_ready)
            $fatal(1, "primitive error did not fail closed parent=%h",
                   rsp_parent);
        repeat (30) begin
            @(posedge clk);
            #1;
            if (!rsp_valid || !rsp_error || rsp_parent !== 0 || req_ready)
                $fatal(1, "error response changed while backpressured");
        end
        @(negedge clk);
        rsp_ready = 1'b1;
        @(posedge clk);
        #1;
        if (response_handshakes != 4 || rsp_valid || rsp_error ||
            rsp_parent != 0)
            $fatal(1, "error response did not retire/clear exactly once");

        if (request_handshakes != 4 || shake_starts != 4 ||
            permutation_starts != 4 || completed_permutations != 4)
            $fatal(1, "final call/permutation counts req=%0d shake=%0d perm=%0d done=%0d",
                   request_handshakes, shake_starts, permutation_starts,
                   completed_permutations);

        $display("PASS FIPS205 SLH-DSA SHAKE-n16 parent vectors, ADRS/order, flow control, and fail-closed error");
        $finish;
    end
endmodule

`default_nettype wire
