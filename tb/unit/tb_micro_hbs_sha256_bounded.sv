`timescale 1ns/1ps
`default_nettype none

module tb_micro_hbs_sha256_bounded;
    logic clk = 1'b0;
    logic rst_n = 1'b0;
    logic req_valid = 1'b0;
    wire req_ready;
    logic [951:0] req_message = '0;
    logic [6:0] req_length = '0;
    wire rsp_valid;
    logic rsp_ready = 1'b0;
    wire [255:0] rsp_digest;
    wire rsp_error;

    integer request_count = 0;
    integer response_count = 0;
    integer compressed_blocks = 0;
    integer timeout;
    integer byte_index;
    logic [255:0] held_digest;

    always #5 clk = ~clk;

    micro_hbs_sha256_bounded dut (
        .clk, .rst_n, .req_valid, .req_ready, .req_message, .req_length,
        .rsp_valid, .rsp_ready, .rsp_digest, .rsp_error
    );

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            request_count <= 0;
            response_count <= 0;
            compressed_blocks <= 0;
        end else begin
            if (req_valid && req_ready)
                request_count <= request_count + 1;
            if (rsp_valid && rsp_ready)
                response_count <= response_count + 1;
            if (dut.state == 2'd2 && dut.round_index == 63)
                compressed_blocks <= compressed_blocks + 1;
        end
    end

    task automatic set_sequence(input integer length);
        begin
            req_message = '0;
            for (byte_index = 0; byte_index < length; byte_index = byte_index + 1)
                req_message[8*byte_index +: 8] = byte_index[7:0];
        end
    endtask

    task automatic run_vector(
        input [6:0] length,
        input [255:0] expected_digest,
        input integer expected_request_count,
        input integer expected_total_blocks
    );
        begin
            req_length = length;
            while (!req_ready) @(negedge clk);
            @(negedge clk);
            req_valid = 1'b1;
            @(posedge clk);
            #1;
            if (request_count != expected_request_count || req_ready)
                $fatal(1, "SHA-256 request handshake mismatch count=%0d",
                       request_count);

            // A held request valid must not restart the active compression.
            repeat (3) begin
                @(posedge clk);
                #1;
                if (req_ready || request_count != expected_request_count)
                    $fatal(1, "duplicate SHA-256 request accepted");
            end
            @(negedge clk);
            req_valid = 1'b0;

            timeout = 0;
            while (!rsp_valid && timeout < 180) begin
                @(negedge clk);
                timeout = timeout + 1;
            end
            if (!rsp_valid || rsp_error || rsp_digest !== expected_digest)
                $fatal(1, "SHA-256 length %0d mismatch digest=%h error=%b",
                       length, rsp_digest, rsp_error);
            if (compressed_blocks != expected_total_blocks)
                $fatal(1, "SHA-256 length %0d block count=%0d expected=%0d",
                       length, compressed_blocks, expected_total_blocks);

            held_digest = rsp_digest;
            repeat (3) begin
                @(posedge clk);
                #1;
                if (!rsp_valid || req_ready || rsp_error ||
                    rsp_digest !== held_digest)
                    $fatal(1, "SHA-256 response changed under backpressure");
            end
            @(negedge clk);
            rsp_ready = 1'b1;
            @(posedge clk);
            #1;
            if (response_count != expected_request_count || rsp_valid)
                $fatal(1, "SHA-256 response handshake mismatch count=%0d",
                       response_count);
            @(negedge clk);
            rsp_ready = 1'b0;
        end
    endtask

    initial begin
        repeat (3) @(posedge clk);
        rst_n = 1'b1;

        req_message = '0;
        run_vector(0,
            256'h55b852781b9995a44c939b64e441ae2724b96f99c8f4fb9a141cfc9842c4b0e3,
            1, 1);

        req_message = '0;
        req_message[7:0] = 8'h61;
        req_message[15:8] = 8'h62;
        req_message[23:16] = 8'h63;
        run_vector(3,
            256'had1500f261ff10b49c7a1796a36103b02322ae5dde404141eacf018fbf1678ba,
            2, 2);

        set_sequence(55);
        run_vector(55,
            256'h598b599be55ad4e029a22a671f138112570c6953cca4c0960a2ef8728eb23e46,
            3, 3);

        set_sequence(56);
        run_vector(56,
            256'h62f59508a682de590ed89b049ddcac45dfdfb17a3ef218a3f24867b3d6e42ada,
            4, 5);

        set_sequence(86);
        run_vector(86,
            256'h208b94c88f65a34ec7c35bbbcc0369f9907a2d0f341f46a1a849dd74df2302b9,
            5, 7);

        set_sequence(119);
        run_vector(119,
            256'hc67e8fd1396d1afac39528ede63851cdd8a22497427f84f077a7c3d77e7918da,
            6, 9);

        // Length 120 exceeds the contract.  It must not execute a block and
        // must expose neither a stale nor partial digest.
        req_length = 120;
        while (!req_ready) @(negedge clk);
        @(negedge clk);
        req_valid = 1'b1;
        @(negedge clk);
        req_valid = 1'b0;
        while (!rsp_valid) @(negedge clk);
        if (!rsp_error || rsp_digest !== 0 || compressed_blocks != 9 ||
            request_count != 7)
            $fatal(1, "out-of-range length did not fail closed digest=%h blocks=%0d",
                   rsp_digest, compressed_blocks);
        repeat (2) begin
            @(posedge clk);
            #1;
            if (!rsp_valid || !rsp_error || rsp_digest !== 0 || req_ready)
                $fatal(1, "error response changed under backpressure");
        end
        @(negedge clk);
        rsp_ready = 1'b1;
        @(posedge clk);
        #1;
        if (response_count != 7 || rsp_valid || rsp_error || rsp_digest != 0)
            $fatal(1, "error response did not retire and clear");

        $display("PASS bounded SHA-256 empty/abc/55/56/86/119, blocks, flow control, and bounds error");
        $finish;
    end
endmodule

`default_nettype wire
