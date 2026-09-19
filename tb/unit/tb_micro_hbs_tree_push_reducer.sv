`timescale 1ns/1ps
module tb_micro_hbs_tree_push_reducer;
    logic clk = 0, rst_n = 0;
    logic push_valid = 0, push_clear = 0, push_last = 0;
    logic push_promote_odd = 0;
    logic [1:0] push_root_height = 3;
    wire push_ready, push_done;
    logic push_context = 0;
    logic [2:0] push_index = 0, push_target_index = 0;
    logic [31:0] push_value = 0;
    logic push_capture_auth = 1, push_cache_all = 1;
    wire parent_valid;
    logic parent_ready = 1;
    wire parent_context;
    wire [1:0] parent_level;
    wire [2:0] parent_index;
    wire [31:0] parent_left, parent_right;
    logic parent_response_valid = 0;
    logic [31:0] parent_response_value = 0;
    wire cache_valid, cache_context;
    logic cache_ready = 1;
    wire [1:0] cache_level;
    wire [2:0] cache_index;
    wire [31:0] cache_value;
    wire auth_valid, auth_context;
    logic auth_ready = 1;
    wire [1:0] auth_level;
    wire [31:0] auth_value;
    wire root_valid, root_context, error;
    logic root_ready = 1;
    wire [31:0] root_value;
    integer roots = 0, auths = 0, stores = 0;
    logic [31:0] seen_root [0:1];

    always #5 clk = ~clk;
    micro_hbs_tree_push_reducer #(
        .VALUE_BITS(32), .TREE_HEIGHT(3), .CONTEXTS(2)
    ) dut (.*);

    always_ff @(posedge clk) begin
        parent_response_valid <= parent_valid && parent_ready;
        if (parent_valid && parent_ready)
            parent_response_value <= parent_left ^ parent_right
                ^ {28'd0, parent_level};
        if (cache_valid && cache_ready) stores <= stores + 1;
        if (auth_valid && auth_ready) auths <= auths + 1;
        if (root_valid && root_ready) begin
            seen_root[root_context] <= root_value;
            roots <= roots + 1;
        end
    end

    task tick; begin @(posedge clk); #1; end endtask
    task push(input logic context_id, input integer index_value);
        begin
            while (!push_ready) tick();
            push_context = context_id;
            push_index = index_value;
            push_value = (context_id ? 32'h100 : 32'h0) + index_value + 1;
            push_target_index = context_id ? 3'd5 : 3'd2;
            push_clear = index_value == 0;
            push_last = index_value == 7;
            push_valid = 1;
            tick();
            push_valid = 0;
            while (!push_done && !error) tick();
            if (error) $fatal(1, "tree reducer error context=%0d leaf=%0d",
                              context_id, index_value);
        end
    endtask

    task push_odd(input integer index_value);
        begin
            while (!push_ready) tick();
            push_context = 0;
            push_index = index_value;
            push_value = index_value + 1;
            push_target_index = 0;
            push_clear = index_value == 0;
            push_last = index_value == 4;
            push_promote_odd = 1;
            push_root_height = 3;
            push_capture_auth = 0;
            push_cache_all = 0;
            push_valid = 1;
            tick();
            push_valid = 0;
            while (!push_done && !error) tick();
            if (error) $fatal(1, "odd reducer error leaf=%0d", index_value);
        end
    endtask

    integer leaf;
    initial begin
        repeat (2) tick(); rst_n = 1; tick();
        for (leaf = 0; leaf < 8; leaf = leaf + 1) begin
            push(0, leaf);
            push(1, leaf);
        end
        if (roots != 2) $fatal(1, "root count %0d", roots);
        if (seen_root[0] != 32'h0a || seen_root[1] != 32'h0a)
            $fatal(1, "root mismatch %h %h", seen_root[0], seen_root[1]);
        if (auths != 6 || stores != 30)
            $fatal(1, "capture count auth=%0d stores=%0d", auths, stores);
        for (leaf = 0; leaf < 5; leaf = leaf + 1)
            push_odd(leaf);
        if (roots != 3 || seen_root[0] != 32'h2)
            $fatal(1, "odd promotion root mismatch roots=%0d value=%h",
                   roots, seen_root[0]);
        $display("TREE_PUSH_REDUCER_PASS roots=%0d auth=%0d stores=%0d",
                 roots, auths, stores);
        $finish;
    end
endmodule
