`timescale 1ns/1ps
`default_nettype none

module tb_micro_hbs_scratch_arbiter;
    localparam integer ADDRESS_WIDTH = 8;
    localparam logic [1:0] OWNER_ALU = 2'd0;
    localparam logic [1:0] OWNER_EMIT = 2'd1;
    localparam logic [1:0] OWNER_TREE = 2'd2;
    localparam logic [1:0] OWNER_NONE = 2'd3;

    logic clk = 1'b0;
    logic rst_n = 1'b0;

    logic alu_request_valid = 1'b0;
    wire alu_request_ready;
    logic alu_request_write = 1'b0;
    logic [7:0] alu_request_address = '0;
    logic [63:0] alu_request_write_data = '0;
    wire alu_response_valid;
    logic alu_response_ready = 1'b0;
    wire [63:0] alu_response_read_data;
    wire alu_response_error;

    logic emit_request_valid = 1'b0;
    wire emit_request_ready;
    logic emit_request_write = 1'b0;
    logic [7:0] emit_request_address = '0;
    logic [63:0] emit_request_write_data = '0;
    wire emit_response_valid;
    logic emit_response_ready = 1'b0;
    wire [63:0] emit_response_read_data;
    wire emit_response_error;

    logic tree_request_valid = 1'b0;
    wire tree_request_ready;
    logic tree_request_write = 1'b0;
    logic [7:0] tree_request_address = '0;
    logic [63:0] tree_request_write_data = '0;
    wire tree_response_valid;
    logic tree_response_ready = 1'b0;
    wire [63:0] tree_response_read_data;
    wire tree_response_error;

    wire scratch_request_valid;
    logic scratch_request_ready = 1'b0;
    wire scratch_request_write;
    wire [7:0] scratch_request_address;
    wire [63:0] scratch_request_write_data;
    logic scratch_response_valid = 1'b0;
    logic [63:0] scratch_response_read_data = '0;
    logic scratch_bounds_error = 1'b0;

    wire busy;
    wire outstanding;
    wire [1:0] active_owner;
    wire [31:0] alu_grants;
    wire [31:0] emit_grants;
    wire [31:0] tree_grants;
    wire [31:0] accepted_transactions;
    wire [31:0] completed_transactions;
    wire [31:0] error_transactions;

    integer scratch_handshakes = 0;
    integer alu_response_handshakes = 0;
    integer emit_response_handshakes = 0;
    integer tree_response_handshakes = 0;
    integer timeout_count;
    logic request_held = 1'b0;
    logic held_write;
    logic [7:0] held_address;
    logic [63:0] held_write_data;

    always #5 clk = ~clk;

    micro_hbs_scratch_arbiter #(.ADDRESS_WIDTH(ADDRESS_WIDTH)) dut (.*);

    // Protocol monitors count actual handshakes and verify that both the
    // Scratchpad request and each routed response remain stable while stalled.
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            scratch_handshakes <= 0;
            alu_response_handshakes <= 0;
            emit_response_handshakes <= 0;
            tree_response_handshakes <= 0;
            request_held <= 1'b0;
        end else begin
            if (scratch_request_valid && scratch_request_ready)
                scratch_handshakes <= scratch_handshakes + 1;
            if (alu_response_valid && alu_response_ready)
                alu_response_handshakes <= alu_response_handshakes + 1;
            if (emit_response_valid && emit_response_ready)
                emit_response_handshakes <= emit_response_handshakes + 1;
            if (tree_response_valid && tree_response_ready)
                tree_response_handshakes <= tree_response_handshakes + 1;

            if (scratch_request_valid && !scratch_request_ready) begin
                if (!request_held) begin
                    request_held <= 1'b1;
                    held_write <= scratch_request_write;
                    held_address <= scratch_request_address;
                    held_write_data <= scratch_request_write_data;
                end else if (scratch_request_write !== held_write
                             || scratch_request_address !== held_address
                             || scratch_request_write_data !== held_write_data) begin
                    $fatal(1, "Scratchpad request changed under backpressure");
                end
            end else begin
                request_held <= 1'b0;
            end

            if ((alu_response_valid + emit_response_valid
                 + tree_response_valid) > 1)
                $fatal(1, "response routed to multiple owners");
        end
    end

    task automatic wait_for_scratch_request;
        input expected_write;
        input [7:0] expected_address;
        input [63:0] expected_data;
        begin
            timeout_count = 0;
            while (!scratch_request_valid && timeout_count < 20) begin
                @(negedge clk);
                timeout_count = timeout_count + 1;
            end
            if (!scratch_request_valid
                || scratch_request_write !== expected_write
                || scratch_request_address !== expected_address
                || scratch_request_write_data !== expected_data)
                $fatal(1, "scratch request mismatch write=%b addr=%02x data=%016x",
                       scratch_request_write, scratch_request_address,
                       scratch_request_write_data);
        end
    endtask

    task automatic accept_scratch_request;
        begin
            scratch_request_ready = 1'b1;
            @(negedge clk);
            scratch_request_ready = 1'b0;
        end
    endtask

    task automatic return_read;
        input [63:0] value;
        begin
            @(negedge clk);
            scratch_response_read_data = value;
            scratch_response_valid = 1'b1;
            @(negedge clk);
            scratch_response_valid = 1'b0;
        end
    endtask

    task automatic expect_alu_response_stalled;
        input [63:0] expected_data;
        begin
            while (!alu_response_valid) @(negedge clk);
            repeat (3) begin
                if (!alu_response_valid || alu_response_error
                    || alu_response_read_data !== expected_data
                    || emit_response_valid || tree_response_valid
                    || !outstanding || active_owner != OWNER_ALU)
                    $fatal(1, "ALU response was not stable or exclusively routed");
                @(negedge clk);
            end
            alu_response_ready = 1'b1;
            @(negedge clk);
            alu_response_ready = 1'b0;
            if (alu_response_valid)
                $fatal(1, "ALU response repeated after acceptance");
        end
    endtask

    task automatic expect_emit_response;
        begin
            while (!emit_response_valid) @(negedge clk);
            if (emit_response_error || emit_response_read_data != 0
                || alu_response_valid || tree_response_valid
                || active_owner != OWNER_EMIT)
                $fatal(1, "EMIT write response routing mismatch");
            emit_response_ready = 1'b1;
            @(negedge clk);
            emit_response_ready = 1'b0;
            if (emit_response_valid)
                $fatal(1, "EMIT response repeated after acceptance");
        end
    endtask

    task automatic expect_tree_error_stalled;
        begin
            while (!tree_response_valid) @(negedge clk);
            repeat (2) begin
                if (!tree_response_valid || !tree_response_error
                    || tree_response_read_data != 0
                    || alu_response_valid || emit_response_valid
                    || active_owner != OWNER_TREE)
                    $fatal(1, "TreeHash error response was not stable/exclusive");
                @(negedge clk);
            end
            tree_response_ready = 1'b1;
            @(negedge clk);
            tree_response_ready = 1'b0;
            if (tree_response_valid)
                $fatal(1, "TreeHash response repeated after acceptance");
        end
    endtask

    initial begin
        repeat (3) @(negedge clk);
        rst_n = 1'b1;

        // All request together.  With Scratchpad stalled, the ALU request must
        // remain selected and stable even though lower-priority requests wait.
        alu_request_valid = 1'b1;
        alu_request_write = 1'b0;
        alu_request_address = 8'h11;
        alu_request_write_data = 64'h0;
        emit_request_valid = 1'b1;
        emit_request_write = 1'b1;
        emit_request_address = 8'h22;
        emit_request_write_data = 64'hfeed_face_dead_beef;
        tree_request_valid = 1'b1;
        tree_request_write = 1'b0;
        tree_request_address = 8'h33;
        tree_request_write_data = 64'h0;

        repeat (3) begin
            @(negedge clk);
            if (!scratch_request_valid || scratch_request_address != 8'h11
                || alu_request_ready || emit_request_ready || tree_request_ready
                || active_owner != OWNER_ALU)
                $fatal(1, "fixed ALU priority/backpressure mismatch");
        end
        accept_scratch_request();
        alu_request_valid = 1'b0;
        if (!outstanding || active_owner != OWNER_ALU)
            $fatal(1, "ALU transaction owner was not retained");

        // Memory may respond before the client is ready; the arbiter must latch
        // and hold it while the pending EMIT/TreeHash requests remain blocked.
        repeat (2) @(negedge clk);
        return_read(64'h0123_4567_89ab_cdef);
        expect_alu_response_stalled(64'h0123_4567_89ab_cdef);

        // EMIT wins over the still-asserted TreeHash request.  This is a write,
        // so success is synthesized after the Scratchpad error-check cycle.
        wait_for_scratch_request(1'b1, 8'h22, 64'hfeed_face_dead_beef);
        if (tree_request_ready || active_owner != OWNER_EMIT)
            $fatal(1, "EMIT priority over TreeHash was not enforced");
        accept_scratch_request();
        emit_request_valid = 1'b0;
        expect_emit_response();

        // The held TreeHash request is finally granted.  A downstream bounds
        // error is captured and held until only TreeHash accepts it.
        wait_for_scratch_request(1'b0, 8'h33, 64'h0);
        accept_scratch_request();
        tree_request_valid = 1'b0;
        @(negedge clk);
        scratch_bounds_error = 1'b1;
        @(negedge clk);
        scratch_bounds_error = 1'b0;
        expect_tree_error_stalled();

        @(negedge clk);
        if (busy || outstanding || active_owner != OWNER_NONE
            || scratch_request_valid || alu_response_valid
            || emit_response_valid || tree_response_valid)
            $fatal(1, "arbiter did not return to idle");
        if (alu_grants != 1 || emit_grants != 1 || tree_grants != 1
            || accepted_transactions != 3 || completed_transactions != 3
            || error_transactions != 1 || scratch_handshakes != 3
            || alu_response_handshakes != 1
            || emit_response_handshakes != 1
            || tree_response_handshakes != 1)
            $fatal(1, "counter/duplicate mismatch grants=%0d/%0d/%0d accepted=%0d completed=%0d errors=%0d scratch=%0d responses=%0d/%0d/%0d",
                   alu_grants, emit_grants, tree_grants,
                   accepted_transactions, completed_transactions,
                   error_transactions, scratch_handshakes,
                   alu_response_handshakes, emit_response_handshakes,
                   tree_response_handshakes);

        $display("PASS Scratchpad fixed-priority arbiter: ALU>EMIT>TreeHash, stable backpressure, exact owner response/error routing, no loss/duplicates");
        $finish;
    end
endmodule

`default_nettype wire
