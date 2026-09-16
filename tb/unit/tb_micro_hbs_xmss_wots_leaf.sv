`timescale 1ns/1ps
`default_nettype none

module tb_micro_hbs_xmss_wots_leaf;
    logic clk = 1'b0;
    logic rst_n = 1'b0;
    logic req_valid = 1'b0;
    wire req_ready;
    logic [255:0] sk_seed = '0;
    logic [255:0] pub_seed = '0;
    logic [255:0] address_template = '0;
    logic [31:0] leaf_index = '0;
    wire rsp_valid;
    logic rsp_ready = 1'b1;
    wire [255:0] leaf;
    wire rsp_error;
    wire [31:0] prf_keygen_calls, chain_steps, ltree_parents, shake_calls;
    integer byte_index, timeout;

    localparam logic [255:0] EXPECTED_LEAF0 =
        256'hcf5ffcb36abd65966bdd7b5fec1da321ce4f5eaf4fcfadb90ffc5b77d147b85c;
    localparam logic [255:0] EXPECTED_LEAF1 =
        256'hc3d718baf73c8d78d5b59d60b6e7f0ef36e3f784644c6b8e78639a83629bd8b1;

    always #5 clk = ~clk;

    micro_hbs_xmss_wots_leaf #(.UNROLL(2)) dut (.*);

    task automatic run_leaf(input [31:0] index,
                            input [255:0] expected);
        begin
            @(negedge clk);
            if (!req_ready) $fatal(1, "leaf engine not ready");
            leaf_index = index;
            req_valid = 1'b1;
            @(negedge clk);
            req_valid = 1'b0;
            timeout = 0;
            while (!rsp_valid && timeout < 100000) begin
                @(negedge clk);
                timeout = timeout + 1;
            end
            if (!rsp_valid || rsp_error || leaf !== expected)
                $fatal(1, "WOTS leaf %0d mismatch/error=%0b got=%064x",
                       index, rsp_error, leaf);
            if (prf_keygen_calls != 67 || chain_steps != 1005
                || ltree_parents != 66 || shake_calls != 3346)
                $fatal(1, "accounting mismatch prf=%0d F=%0d H=%0d shake=%0d",
                       prf_keygen_calls, chain_steps, ltree_parents,
                       shake_calls);
            // Hold the response and its payload stable under backpressure.
            rsp_ready = 1'b0;
            repeat (3) begin
                @(negedge clk);
                if (!rsp_valid || leaf !== expected)
                    $fatal(1, "response changed under backpressure");
            end
            rsp_ready = 1'b1;
            @(negedge clk);
        end
    endtask

    initial begin
        for (byte_index = 0; byte_index < 32; byte_index = byte_index + 1) begin
            sk_seed[8*byte_index +: 8] = byte_index[7:0];
            pub_seed[8*byte_index +: 8] = 8'h40 + byte_index[7:0];
        end
        repeat (3) @(negedge clk);
        rst_n = 1'b1;
        run_leaf(0, EXPECTED_LEAF0);
        run_leaf(1, EXPECTED_LEAF1);
        $display("PASS RFC8391 WOTS+ leaf: 67 PRF_keygen, 1005 F steps, 66 L-tree parents, backpressure");
        $finish;
    end
endmodule

`default_nettype wire
