`timescale 1ns/1ps
`default_nettype none

module tb_micro_hbs_lms_tree_parent;
    logic clk = 1'b0;
    logic rst_n = 1'b0;
    logic req_valid = 1'b0;
    wire req_ready;
    logic [127:0] req_identifier = '0;
    logic [31:0] req_node_number = '0;
    logic [255:0] req_left_node = '0;
    logic [255:0] req_right_node = '0;
    wire rsp_valid;
    logic rsp_ready = 1'b0;
    wire [255:0] rsp_parent;
    wire rsp_error;

    integer request_count = 0;
    integer response_count = 0;
    integer compressed_blocks = 0;
    integer timeout;
    logic [255:0] held_node;

    // Independent hashlib.sha256 vectors over the exact RFC 8554 preimage.
    localparam logic [255:0] EXPECTED_BASE =
        256'h098342dc0589f447e4bebd3b8719b87a8aa1c4c2c2fc5041ea9ce7c24cb84a1f;
    localparam logic [255:0] EXPECTED_SWAPPED =
        256'h801698f22609c313cee82ff4a6b6e145e3a4879ab6696006331774eb4b45b05e;
    localparam logic [255:0] EXPECTED_R18 =
        256'hfa4c9dfe095dbb5803d4a3acac9b037604ac2833e37e8991499deea6e6cdffcd;
    localparam logic [255:0] EXPECTED_IDENTITY =
        256'hf9254fec0d36d668f5bfc7389de65ec04a468582348b4034057d295c02900025;

    always #5 clk = ~clk;

    micro_hbs_lms_tree_parent dut (
        .clk, .rst_n, .req_valid, .req_ready, .req_identifier,
        .req_node_number, .req_left_node, .req_right_node,
        .rsp_valid, .rsp_ready, .rsp_parent, .rsp_error
    );

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            request_count <= 0;
            response_count <= 0;
            compressed_blocks <= 0;
        end else begin
            if (req_valid && req_ready) begin
                request_count <= request_count + 1;
                if (dut.hash_message[8*20 +: 16] !== 16'h8383 ||
                    dut.hash_message[8*16 +: 32] !== {
                        req_node_number[7:0], req_node_number[15:8],
                        req_node_number[23:16], req_node_number[31:24]} ||
                    dut.hash_message[8*22 +: 256] !== req_left_node ||
                    dut.hash_message[8*54 +: 256] !== req_right_node ||
                    dut.hash_message[951:8*86] !== 0)
                    $fatal(1, "RFC8554 parent preimage layout mismatch");
            end
            if (rsp_valid && rsp_ready)
                response_count <= response_count + 1;
            if (dut.sha256.state == 2'd2 && dut.sha256.round_index == 63)
                compressed_blocks <= compressed_blocks + 1;
        end
    end

    task automatic run_vector(
        input [255:0] expected_parent,
        input integer expected_count
    );
        begin
            while (!req_ready) @(negedge clk);
            @(negedge clk);
            req_valid = 1'b1;
            @(posedge clk);
            #1;
            if (request_count != expected_count || req_ready)
                $fatal(1, "LMS request handshake mismatch count=%0d",
                       request_count);
            repeat (3) begin
                @(posedge clk);
                #1;
                if (req_ready || request_count != expected_count)
                    $fatal(1, "duplicate LMS parent request accepted");
            end
            @(negedge clk);
            req_valid = 1'b0;

            timeout = 0;
            while (!rsp_valid && timeout < 180) begin
                @(negedge clk);
                timeout = timeout + 1;
            end
            if (!rsp_valid || rsp_error || rsp_parent !== expected_parent)
                $fatal(1, "LMS parent mismatch parent=%h error=%b",
                       rsp_parent, rsp_error);
            if (compressed_blocks != 2*expected_count)
                $fatal(1, "LMS parent did not use two SHA-256 blocks: %0d",
                       compressed_blocks);

            held_node = rsp_parent;
            repeat (3) begin
                @(posedge clk);
                #1;
                if (!rsp_valid || req_ready || rsp_error ||
                    rsp_parent !== held_node)
                    $fatal(1, "LMS response changed under backpressure");
            end
            @(negedge clk);
            rsp_ready = 1'b1;
            @(posedge clk);
            #1;
            if (response_count != expected_count || rsp_valid)
                $fatal(1, "LMS response handshake mismatch count=%0d",
                       response_count);
            @(negedge clk);
            rsp_ready = 1'b0;
        end
    endtask

    initial begin
        req_identifier = 128'h3445e734d84ecba8f01f09a2d4ab8fd0;
        req_node_number = 32'd17;
        req_left_node =
            256'h3f3e3d3c3b3a393837363534333231302f2e2d2c2b2a29282726252423222120;
        req_right_node =
            256'h9f9e9d9c9b9a999897969594939291908f8e8d8c8b8a89888786858483828180;

        repeat (3) @(posedge clk);
        rst_n = 1'b1;

        run_vector(EXPECTED_BASE, 1);

        held_node = req_left_node;
        req_left_node = req_right_node;
        req_right_node = held_node;
        run_vector(EXPECTED_SWAPPED, 2);

        held_node = req_left_node;
        req_left_node = req_right_node;
        req_right_node = held_node;
        req_node_number = 32'd18;
        run_vector(EXPECTED_R18, 3);

        req_node_number = 32'd17;
        req_identifier[7:0] = 8'hd1;
        run_vector(EXPECTED_IDENTITY, 4);

        // Inject an error on a completed bounded-lane response.  The wrapper
        // must mask the otherwise valid digest to zero for the full stalled
        // error response, then consume it once.
        while (!req_ready) @(negedge clk);
        @(negedge clk);
        req_valid = 1'b1;
        @(negedge clk);
        req_valid = 1'b0;
        while (!rsp_valid) @(negedge clk);
        force dut.hash_rsp_error = 1'b1;
        #1;
        if (!rsp_valid || !rsp_error || rsp_parent !== 0 || req_ready)
            $fatal(1, "LMS wrapper error did not fail closed parent=%h",
                   rsp_parent);
        repeat (3) begin
            @(posedge clk);
            #1;
            if (!rsp_valid || !rsp_error || rsp_parent !== 0 || req_ready)
                $fatal(1, "LMS error response changed under backpressure");
        end
        @(negedge clk);
        rsp_ready = 1'b1;
        @(posedge clk);
        #1;
        release dut.hash_rsp_error;
        if (response_count != 5 || rsp_valid || rsp_error || rsp_parent != 0)
            $fatal(1, "LMS error response did not retire exactly once");
        if (request_count != 5 || compressed_blocks != 10)
            $fatal(1, "LMS final counters req=%0d blocks=%0d",
                   request_count, compressed_blocks);

        $display("PASS RFC8554 LMS SHA256/256 parent vectors, identity/order, flow control, and error");
        $finish;
    end
endmodule

`default_nettype wire
