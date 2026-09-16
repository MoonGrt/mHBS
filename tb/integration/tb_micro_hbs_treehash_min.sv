`timescale 1ns/1ps
`default_nettype none

module tb_micro_hbs_treehash_min;
    logic clk = 1'b0;
    logic rst_n = 1'b0;
    logic start = 1'b0;
    wire ready;
    logic [15:0] target_leaf = 16'd5;
    logic leaf_valid = 1'b0;
    wire leaf_ready;
    logic [15:0] leaf_index = '0;
    logic [255:0] leaf_value = '0;
    wire parent_req_valid;
    wire parent_req_ready;
    wire [7:0] parent_req_height;
    wire [15:0] parent_req_start_leaf;
    wire [255:0] parent_req_left;
    wire [255:0] parent_req_right;
    wire parent_rsp_valid;
    wire [255:0] parent_rsp_value;
    wire parent_rsp_error;
    wire auth_valid;
    wire [7:0] auth_level;
    wire [255:0] auth_node;
    wire root_valid;
    wire [255:0] root;
    wire busy;
    wire error;
    wire [15:0] error_code;
    wire [15:0] accepted_leaves;
    wire [15:0] parent_hashes;
    wire [7:0] peak_stack_nodes;
    reg [255:0] captured_auth [0:2];
    reg [2:0] captured_mask = '0;
    integer i;
    integer watchdog = 0;

    always #5 clk = ~clk;
    always @(posedge clk) begin
        if (rst_n && auth_valid) begin
            captured_auth[auth_level] <= auth_node;
            captured_mask[auth_level] <= 1'b1;
        end
        if (rst_n && busy) begin
            watchdog <= watchdog + 1;
            if (watchdog > 300)
                $fatal(1, "TreeHash timeout state=%0d sp=%0d leaves=%0d parents=%0d req=%0d rsp=%0d",
                       treehash.state, treehash.stack_sp, accepted_leaves, parent_hashes,
                       parent_req_valid, parent_rsp_valid);
        end
    end

    micro_hbs_treehash_min #(.TREE_HEIGHT(3)) treehash (.*);
    micro_hbs_tree_parent_shake #(.UNROLL(2)) parent_hash (
        .clk, .rst_n, .req_valid(parent_req_valid), .req_ready(parent_req_ready),
        .left_node(parent_req_left), .right_node(parent_req_right),
        .rsp_valid(parent_rsp_valid), .rsp_value(parent_rsp_value),
        .rsp_error(parent_rsp_error)
    );

    task automatic send_leaf;
        input [15:0] index_value;
        input [7:0] fill_byte;
        integer byte_index;
        begin
            while (!leaf_ready) @(negedge clk);
            @(negedge clk);
            leaf_index = index_value;
            for (byte_index = 0; byte_index < 32; byte_index = byte_index + 1)
                leaf_value[8*byte_index +: 8] = fill_byte;
            leaf_valid = 1'b1;
            @(posedge clk);
            #1 leaf_valid = 1'b0;
        end
    endtask

    initial begin
        repeat (3) @(posedge clk);
        rst_n = 1'b1;
        @(negedge clk);
        start = 1'b1;
        @(posedge clk);
        #1 start = 1'b0;

        for (i = 0; i < 8; i = i + 1)
            send_leaf(i[15:0], i[7:0]);

        while (!root_valid && !error) begin
            @(posedge clk);
            #1;
        end
        if (error) $fatal(1, "TreeHash error %h", error_code);
        if (root !== 256'h8b6d34f4de669ae6d99c1d69d9ea4677461e47f99f659752bdfe48fe0e630cd8)
            $fatal(1, "root mismatch got=%064x", root);
        if (captured_mask != 3'b111) $fatal(1, "auth mask mismatch %b", captured_mask);
        if (captured_auth[0] !== 256'h0404040404040404040404040404040404040404040404040404040404040404)
            $fatal(1, "auth level 0 mismatch");
        if (captured_auth[1] !== 256'h37625def1a14451301f6c7427d36d89fb377086b3364fc1c80f9c9a30f0bf83b)
            $fatal(1, "auth level 1 mismatch got=%064x", captured_auth[1]);
        if (captured_auth[2] !== 256'h9c76244d9eae66584ddaf7df47f84479f3005c6f450e1bdc01ce7b3c54ce3d31)
            $fatal(1, "auth level 2 mismatch got=%064x", captured_auth[2]);
        if (accepted_leaves != 8 || parent_hashes != 7 || peak_stack_nodes > 3)
            $fatal(1, "metrics leaves=%0d parents=%0d peak=%0d",
                   accepted_leaves, parent_hashes, peak_stack_nodes);
        $display("PASS TreeHash-min SHAKE root/auth leaves=8 parents=7 peak_stack=%0d",
                 peak_stack_nodes);
        $finish;
    end
endmodule

`default_nettype wire
