`timescale 1ns/1ps
module tb_micro_hbs_stateful_recipe_lane;
    logic clk = 0;
    logic rst_n = 0;
    logic request_valid = 0;
    wire request_ready;
    logic [3:0] request_recipe = 0;
    logic [255:0] request_secret_seed = 0, request_secret_prf = 0;
    logic [255:0] request_public_seed = 0, request_root = 0;
    logic [127:0] request_identifier = 0;
    logic [255:0] request_randomizer = 0;
    logic [87*8-1:0] request_message = 0;
    logic [6:0] request_message_length = 0;
    logic [9:0] request_q = 0;
    logic [6:0] request_item = 0;
    logic [4:0] request_steps = 0;
    logic [255:0] request_address = 0, request_left = 0, request_right = 0;
    wire [6:0] endpoint_read_index;
    logic [255:0] endpoint_read_data;
    logic [255:0] endpoint_test_memory [0:66];
    wire response_valid;
    logic response_ready = 1;
    wire [255:0] response_value;
    wire error;
    wire [31:0] hash_contexts, permutations, active_cycles;
    integer endpoint, endpoint_byte;
    always #5 clk = ~clk;
    always_ff @(posedge clk)
        endpoint_read_data <= endpoint_test_memory[endpoint_read_index];

    micro_hbs_stateful_recipe_lane #(.UNROLL(2)) dut (
        .external_context_valid(), .external_context_ready(1'b0),
        .external_fast_block_valid(), .external_fast_block_ready(1'b0),
        .external_fast_block_data(), .external_block_valid(),
        .external_block_ready(1'b0), .external_block_data(),
        .external_block_last(), .external_response_valid(1'b0),
        .external_response_digest(272'b0), .external_finish_valid(1'b0),
        .external_finish_digest(272'b0), .external_error(1'b0), .*
    );
    task tick; begin @(posedge clk); #1; end endtask
    task start_request;
        begin
            while (!request_ready) tick();
            request_valid = 1; tick(); request_valid = 0;
        end
    endtask
    task wait_response;
        begin
            while (!response_valid) tick();
            if (error) $fatal(1, "recipe error");
        end
    endtask

    initial begin
        for (endpoint = 0; endpoint < 67; endpoint = endpoint + 1)
            for (endpoint_byte = 0; endpoint_byte < 32;
                 endpoint_byte = endpoint_byte + 1)
                endpoint_test_memory[endpoint][endpoint_byte*8 +: 8]
                    = (endpoint*32 + endpoint_byte) & 8'hff;
        repeat (2) tick(); rst_n = 1; tick();
        // Project SHAKE-LMS private element followed by j=0,1,2.
        request_recipe = 6;
        request_identifier = 128'hffeeddccbbaa99887766554433221100;
        request_secret_seed = 256'h1f1e1d1c1b1a191817161514131211100f0e0d0c0b0a09080706050403020100;
        request_q = 5;
        request_item = 0;
        request_steps = 3;
        start_request(); wait_response();
        if (response_value != 256'hb1bd13b1381f49eaf514ec4f42cb507df996c8ae2a00a3acf86959d951993c92)
            $fatal(1, "prefix chain mismatch");
        tick();
        request_recipe = 7;
        request_steps = 0;
        start_request(); wait_response();
        if (response_value
            != 256'hce3655dd763fc777d4eb666414cdb15cd9e0210a486ecda267a098c24ac697a8)
            $fatal(1, "prefix list mismatch got=%h", response_value);
        if (hash_contexts != 5 || permutations != 20)
            $fatal(1, "recipe counters");
        $display("STATEFUL_RECIPE_LANE_PASS cycles=%0d", active_cycles);
        $finish;
    end
endmodule
