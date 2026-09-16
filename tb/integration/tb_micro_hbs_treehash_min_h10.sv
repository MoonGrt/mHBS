`timescale 1ns/1ps
`default_nettype none

module tb_micro_hbs_treehash_min_h10;
    logic clk = 1'b0;
    logic rst_n = 1'b0;
    logic start = 1'b0;
    wire ready;
    logic [15:0] target_leaf = 16'd513;
    logic leaf_valid = 1'b0;
    wire leaf_ready;
    logic [15:0] leaf_index = '0;
    logic [255:0] leaf_value = '0;
    wire parent_req_valid, parent_req_ready;
    wire [7:0] parent_req_height;
    wire [15:0] parent_req_start_leaf;
    wire [255:0] parent_req_left, parent_req_right;
    wire parent_rsp_valid, parent_rsp_error;
    wire [255:0] parent_rsp_value;
    wire auth_valid;
    wire [7:0] auth_level;
    wire [255:0] auth_node;
    wire root_valid;
    wire [255:0] root;
    wire busy, error;
    wire [15:0] error_code;
    wire [15:0] accepted_leaves, parent_hashes;
    wire [7:0] peak_stack_nodes;
    reg [255:0] captured_auth [0:9];
    reg [9:0] captured_mask = '0;
    reg [255:0] expected_auth [0:9];
    integer i;
    integer byte_index;
    integer watchdog = 0;

    always #5 clk = ~clk;
    always @(posedge clk) begin
        if (rst_n && auth_valid) begin
            captured_auth[auth_level] <= auth_node;
            captured_mask[auth_level] <= 1'b1;
        end
        if (rst_n && busy) begin
            watchdog <= watchdog + 1;
            if (watchdog > 40000) $fatal(1, "h10 TreeHash timeout");
        end
    end

    micro_hbs_treehash_min #(.TREE_HEIGHT(10)) treehash (.*);
    micro_hbs_tree_parent_shake #(.UNROLL(2)) parent_hash (
        .clk, .rst_n, .req_valid(parent_req_valid), .req_ready(parent_req_ready),
        .left_node(parent_req_left), .right_node(parent_req_right),
        .rsp_valid(parent_rsp_valid), .rsp_value(parent_rsp_value),
        .rsp_error(parent_rsp_error)
    );

    initial begin
        expected_auth[0] = 256'h0000000000000000000000000000000000000000000000000000000000000000;
        expected_auth[1] = 256'ha5b51107ce613c3efead13b1a3cabfec55338265fe000124919fc7e16161372c;
        expected_auth[2] = 256'h4d11e891e48519e8081a966aeafded79d7705cd6405a0f6220576d5f62570d61;
        expected_auth[3] = 256'h05cf9754412209e7bae69d17243870717b690594a18de9abc005ddf7cbe9260c;
        expected_auth[4] = 256'hb0042c3de5ed382e50b24b95f4feb85b31fb55599201e8e9bb3866fad9a72ceb;
        expected_auth[5] = 256'hbd0b7ba3c71d97c551abdf33112816e7af93d05d0eacc0d1768bc68eb67b710b;
        expected_auth[6] = 256'h7456f1ae93089a75fa37f38329c18b393d4a3f373ec7dd3b2c0f91c8861e2178;
        expected_auth[7] = 256'h75a7c9ba5c8bdebf805c188601b8a80cda447deb4bb4ea466b2420c40e80b444;
        expected_auth[8] = 256'h97cb66dd292b014a8cbb1ad4d697a3761f91239478663059ebf99e3475a61512;
        expected_auth[9] = 256'hdc2d1997a8e569585dadba76fb431efbeb23a6bd84f8e27c501820d1f87a3619;

        repeat (3) @(posedge clk);
        rst_n = 1'b1;
        @(negedge clk);
        start = 1'b1;
        @(posedge clk);
        #1 start = 1'b0;

        for (i = 0; i < 1024; i = i + 1) begin
            while (!leaf_ready) @(negedge clk);
            @(negedge clk);
            leaf_index = i[15:0];
            for (byte_index = 0; byte_index < 32; byte_index = byte_index + 1)
                leaf_value[8*byte_index +: 8] = i[7:0];
            leaf_valid = 1'b1;
            @(posedge clk);
            #1 leaf_valid = 1'b0;
        end

        while (!root_valid && !error) begin
            @(posedge clk);
            #1;
        end
        if (error) $fatal(1, "h10 TreeHash error %h", error_code);
        if (root !== 256'he74e8e14105d92a82ca0f985aa63ced0d00459242fe921a7ec94417d28a51570)
            $fatal(1, "h10 root mismatch got=%064x", root);
        if (captured_mask != 10'h3ff) $fatal(1, "h10 auth mask mismatch %h", captured_mask);
        for (i = 0; i < 10; i = i + 1)
            if (captured_auth[i] !== expected_auth[i])
                $fatal(1, "h10 auth mismatch level=%0d got=%064x", i, captured_auth[i]);
        if (accepted_leaves != 1024 || parent_hashes != 1023 || peak_stack_nodes != 10)
            $fatal(1, "h10 metrics leaves=%0d parents=%0d peak=%0d",
                   accepted_leaves, parent_hashes, peak_stack_nodes);
        $display("PASS TreeHash-min h10 root/auth leaves=1024 parents=1023 peak_stack=10");
        $finish;
    end
endmodule

`default_nettype wire
