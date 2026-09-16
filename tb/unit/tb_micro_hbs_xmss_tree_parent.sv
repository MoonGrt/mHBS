`timescale 1ns/1ps
`default_nettype none

module tb_micro_hbs_xmss_tree_parent;
    logic clk = 1'b0;
    logic rst_n = 1'b0;
    logic req_valid = 1'b0;
    wire req_ready;
    logic [255:0] req_public_seed = '0;
    logic [255:0] req_address = '0;
    logic [255:0] req_left_node = '0;
    logic [255:0] req_right_node = '0;
    wire rsp_valid;
    logic rsp_ready = 1'b0;
    wire [255:0] rsp_parent;
    wire rsp_error;

    integer request_handshakes = 0;
    integer response_handshakes = 0;
    integer timeout;
    integer i;
    logic [255:0] held_parent;

    // Generated independently with Python hashlib.shake_256 from:
    //   public_seed = bytes(0x40..0x5f)
    //   ADRS words  = [0, 0, 0, 1, 5, 2, 3, 0] (big endian)
    //   left        = bytes(0xa0..0xbf)
    //   right       = bytes(0xc0..0xdf)
    // following RFC 8391 Algorithm 7 (RAND_HASH) with n=32.
    localparam logic [255:0] EXPECTED_PARENT =
        256'h131f4ebe7c3f2e7dfc359e0153352572e613acb46772250f26664a94979c091d;

    always #5 clk = ~clk;

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            request_handshakes <= 0;
            response_handshakes <= 0;
        end else begin
            if (req_valid && req_ready)
                request_handshakes <= request_handshakes + 1;
            if (rsp_valid && rsp_ready)
                response_handshakes <= response_handshakes + 1;
        end
    end

    micro_hbs_xmss_tree_parent #(.UNROLL(2)) dut (
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

    task automatic load_known_vector;
        begin
            for (i = 0; i < 32; i = i + 1) begin
                req_public_seed[8*i +: 8] = 8'h40 + i;
                req_left_node[8*i +: 8] = 8'ha0 + i;
                req_right_node[8*i +: 8] = 8'hc0 + i;
            end
            // Big-endian ADRS words [0,0,0,1,5,2,3,0].
            req_address = '0;
            req_address[8*15 +: 8] = 8'h01;
            req_address[8*19 +: 8] = 8'h05;
            req_address[8*23 +: 8] = 8'h02;
            req_address[8*27 +: 8] = 8'h03;
        end
    endtask

    task automatic accept_request_and_check_duplicate_guard;
        begin
            while (!req_ready) @(negedge clk);
            @(negedge clk);
            req_valid = 1'b1;
            @(posedge clk);
            #1;
            if (request_handshakes != 1 || req_ready)
                $fatal(1, "initial request handshake failed count=%0d ready=%b",
                       request_handshakes, req_ready);

            // A level-held valid must not restart the already active hash.
            // It remains backpressured until explicitly withdrawn.
            repeat (5) begin
                @(posedge clk);
                #1;
                if (req_ready || request_handshakes != 1)
                    $fatal(1, "duplicate request accepted while active count=%0d",
                           request_handshakes);
            end
            @(negedge clk);
            req_valid = 1'b0;
        end
    endtask

    initial begin
        load_known_vector();
        repeat (3) @(posedge clk);
        rst_n = 1'b1;

        accept_request_and_check_duplicate_guard();

        timeout = 0;
        while (!rsp_valid && timeout < 300) begin
            // A different request offered while hashing must be backpressured
            // and must not disturb the accepted request's latched operands.
            if (timeout == 3) begin
                req_left_node = ~req_left_node;
                req_valid = 1'b1;
            end
            if (timeout == 7) begin
                req_valid = 1'b0;
                req_left_node = ~req_left_node;
            end
            @(negedge clk);
            if (req_ready || request_handshakes != 1)
                $fatal(1, "request accepted before prior response count=%0d",
                       request_handshakes);
            timeout = timeout + 1;
        end
        req_valid = 1'b0;
        if (!rsp_valid || rsp_error || rsp_parent !== EXPECTED_PARENT)
            $fatal(1, "RFC8391 parent mismatch error=%b parent=%h",
                   rsp_error, rsp_parent);
        if (dut.hash_calls != 4)
            $fatal(1, "RAND_HASH did not use four SHAKE calls: %0d",
                   dut.hash_calls);

        // Response payload and error indication are held until ready.
        held_parent = rsp_parent;
        repeat (4) begin
            @(posedge clk);
            #1;
            if (!rsp_valid || req_ready || rsp_error ||
                rsp_parent !== held_parent || response_handshakes != 0)
                $fatal(1, "response changed under backpressure");
        end
        @(negedge clk);
        rsp_ready = 1'b1;
        @(posedge clk);
        #1;
        if (response_handshakes != 1 || rsp_valid)
            $fatal(1, "response handshake failed count=%0d valid=%b",
                   response_handshakes, rsp_valid);
        @(negedge clk);
        rsp_ready = 1'b0;

        // Fault-inject the existing composer's error indication.  The wrapper
        // must return an error response with no digest disclosure and must
        // continue to suppress duplicate requests while it is outstanding.
        while (!req_ready) @(negedge clk);
        req_valid = 1'b1;
        @(negedge clk);
        req_valid = 1'b0;
        repeat (3) @(posedge clk);
        force dut.hash_error = 1'b1;
        @(posedge clk);
        #1;
        release dut.hash_error;
        if (!rsp_valid || !rsp_error || rsp_parent !== 0 || req_ready)
            $fatal(1, "hash error did not fail closed parent=%h", rsp_parent);
        held_parent = rsp_parent;
        repeat (3) begin
            @(posedge clk);
            #1;
            if (!rsp_valid || !rsp_error || rsp_parent !== held_parent || req_ready)
                $fatal(1, "error response changed under backpressure");
        end
        @(negedge clk);
        rsp_ready = 1'b1;
        @(posedge clk);
        #1;
        if (response_handshakes != 2 || rsp_valid)
            $fatal(1, "error response did not retire exactly once");

        if (request_handshakes != 2)
            $fatal(1, "unexpected accepted request count %0d",
                   request_handshakes);
        $display("PASS RFC8391 XMSS SHAKE256 parent, backpressure, duplicate guard, and fail-closed error");
        $finish;
    end
endmodule

`default_nettype wire
