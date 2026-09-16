`timescale 1ns/1ps
`default_nettype none

// Four real JSON-component WOTS+/L-tree leaves followed by a real h=2
// TreeHash reduction.  The program image is the existing h=10 Keygen image;
// only its public outer bound is reduced to four and EMIT is replaced by HALT.
module tb_micro_hbs_xmss_generic_tree_h2 #(
    parameter integer TEST_TREE_HEIGHT = 2
);
    logic clk = 1'b0;
    logic rst_n = 1'b0;
    logic program_we = 1'b0;
    logic [8:0] program_addr = '0;
    logic [63:0] program_wdata = '0;
    logic layout_cfg_valid = 1'b0;
    wire layout_cfg_ready;
    logic [15:0] layout_cfg_id = '0;
    logic [127:0] layout_cfg_descriptor = '0;
    wire layout_cfg_error;
    wire [15:0] layout_cfg_error_code;
    logic component_cfg_valid = 1'b0;
    wire component_cfg_ready;
    logic [15:0] component_cfg_index = '0;
    logic [191:0] component_cfg_descriptor = '0;
    wire component_cfg_error;
    wire [15:0] component_cfg_error_code;
    logic data_descriptor_cfg_valid = 1'b0;
    wire data_descriptor_cfg_ready;
    logic [15:0] data_descriptor_cfg_id = '0;
    logic [127:0] data_descriptor_cfg_data = '0;
    wire data_descriptor_cfg_error;
    wire [15:0] data_descriptor_cfg_error_code;
    logic binding_cfg_valid = 1'b0;
    wire binding_cfg_ready;
    logic [15:0] binding_cfg_id = '0;
    logic [7:0] binding_cfg_format_version = 8'h01;
    logic [63:0] binding_cfg_data = '0;
    wire binding_cfg_error;
    wire [15:0] binding_cfg_error_code;
    logic scratch_init_valid = 1'b0;
    wire scratch_init_ready;
    logic scratch_init_write = 1'b0;
    logic [15:0] scratch_init_address = '0;
    logic [63:0] scratch_init_write_data = '0;
    wire scratch_init_rsp_valid;
    wire [63:0] scratch_init_rsp_data;
    wire scratch_init_error;
    logic job_valid = 1'b0;
    wire job_ready;
    logic [8:0] job_entry = 9'd0;
    logic [15:0] job_target_leaf = 16'd1;
    logic [255:0] job_sk_seed = '0;
    logic [255:0] job_public_seed = '0;
    logic [255:0] job_address_template = '0;
    wire busy, done, error;
    wire [15:0] error_code;
    wire [255:0] last_digest;
    wire [31:0] accepted_job_commands;
    wire [31:0] host_control_writes_during_busy;
    wire [31:0] issued_hash_requests, issued_data_requests;
    wire [31:0] issued_tree_requests, retired_instructions;
    wire [31:0] retired_components;
    wire [31:0] composer_scratch_reads, composer_scratch_writes;
    wire [31:0] absorbed_blocks, scratch_transactions;
    wire root_valid, auth_valid;
    wire [255:0] root, auth_node;
    wire [7:0] auth_level;
    wire [15:0] accepted_leaves, parent_hashes;
    wire out_valid;
    logic out_ready = 1'b1;
    wire [63:0] out_data;
    wire [7:0] out_keep;
    wire out_last;

    logic [63:0] program_image [0:92];
    logic [127:0] layout_image [0:9];
    logic [191:0] component_image [0:90];
    logic [255:0] captured_root;
    logic [255:0] captured_auth [0:9];
    logic [9:0] captured_auth_mask;
    logic [255:0] emitted_root;
    integer emitted_words;
    integer index;
    integer level;
    integer cycles;

    localparam logic [63:0] OUTER_LOOP_FOUR = 64'h0400000000000004;
    localparam logic [63:0] HALT = 64'h0d00000000000000;
    localparam logic [127:0] XMSS_STORE_DESC =
        128'h02000200000000000000048500002000;
    localparam logic [127:0] XMSS_ROOT_EMIT_DESC =
        128'h02000802b20000000000048000000000;
    localparam logic [63:0] XMSS_SOURCE_BIND = 64'h37c0010001000000;
    localparam logic [63:0] XMSS_DEST_BIND   = 64'hbac0010001000000;
    localparam logic [255:0] EXPECTED_ROOT_H2 =
        256'hf9475994eae032b3e5ce9bce7754e4bb9eef436292d454b676433fd517bec637;
    localparam logic [255:0] EXPECTED_ROOT_H10 =
        256'h251451dc9b735dc3221eec5a48cff52c23dafc3c9df1663ea636f19ac3bd62ba;

    always #5 clk = ~clk;

    micro_hbs_xmss_generic_leaf_slice #(.TREE_HEIGHT(TEST_TREE_HEIGHT)) dut (.*);

    function automatic [255:0] expected_auth(input integer auth_index);
        begin
            if (TEST_TREE_HEIGHT == 2) begin
                case (auth_index)
                    0: expected_auth = 256'hcf5ffcb36abd65966bdd7b5fec1da321ce4f5eaf4fcfadb90ffc5b77d147b85c;
                    1: expected_auth = 256'h241c1a2800ae23fd22c2ea7e0476b4ba929599626b0461c70cfa558e559704dc;
                    default: expected_auth = 'x;
                endcase
            end else begin
                case (auth_index)
                    0: expected_auth = 256'had26933c91a6b104602213e06344ed8ec29d2a0d7bba15baf968f4cecbbe2da6;
                    1: expected_auth = 256'h0a5afd093798fc8709cd37a3168079322aa29ca2a4dfe7ac8660b6c0c9e790b1;
                    2: expected_auth = 256'hf9475994eae032b3e5ce9bce7754e4bb9eef436292d454b676433fd517bec637;
                    3: expected_auth = 256'hfb52ed6351e9119ba79e4902e984a58ac42e7f346c6e6f8eb535cbb266462d13;
                    4: expected_auth = 256'h2d4ac857c402cac5d1b5f7a0230c7bf94c78955796f266c13c829e9b9c7e50b3;
                    5: expected_auth = 256'h9fb36cd4cee69c9aea7e86f47dc00d46be46df3a0bbaf263f872480ce5c4a2bd;
                    6: expected_auth = 256'h83b56c93008b82b3e882ed14497e54b3ee4d3c507a0b670ee0cf9f70a7d8d045;
                    7: expected_auth = 256'h7a693117e3e1b10dd0487aed3f43293b2fc8b30373c9bfae82bf17afd9af0cf0;
                    8: expected_auth = 256'h3ff9979004ac5c74815b6515f5aaf578cae96472705edc1adca805944d24ba91;
                    9: expected_auth = 256'h4b92e8b546a94dc58b07dc1a1094ba51cd5cbf98ef199157de1cede275b370b7;
                    default: expected_auth = 'x;
                endcase
            end
        end
    endfunction

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            captured_root <= '0;
            captured_auth_mask <= '0;
            emitted_root <= '0;
            emitted_words <= 0;
            for (level = 0; level < 10; level = level + 1)
                captured_auth[level] <= '0;
        end else begin
            if (root_valid)
                captured_root <= root;
            if (auth_valid) begin
                if (auth_level >= TEST_TREE_HEIGHT)
                    $fatal(1, "auth level out of range %0d", auth_level);
                captured_auth[auth_level] <= auth_node;
                captured_auth_mask[auth_level] <= 1'b1;
            end
            if (out_valid && out_ready) begin
                if (emitted_words >= 4 || out_keep != 8'hff
                    || out_last != (emitted_words == 3))
                    $fatal(1, "root EMIT framing error word=%0d keep=%h last=%0d",
                           emitted_words, out_keep, out_last);
                emitted_root[64*emitted_words +: 64] <= out_data;
                emitted_words <= emitted_words + 1;
            end
        end
    end

    task automatic write_program(input [8:0] address, input [63:0] value);
        begin
            @(negedge clk); program_addr = address; program_wdata = value;
            program_we = 1'b1;
            @(negedge clk); program_we = 1'b0;
        end
    endtask

    task automatic configure_layout(input [15:0] id,
                                    input [127:0] value);
        begin
            while (!layout_cfg_ready) @(negedge clk);
            @(negedge clk); layout_cfg_id = id;
            layout_cfg_descriptor = value; layout_cfg_valid = 1'b1;
            @(posedge clk); #1 layout_cfg_valid = 1'b0;
            if (layout_cfg_error)
                $fatal(1, "layout config failed %h", layout_cfg_error_code);
        end
    endtask

    task automatic configure_component(input [15:0] address,
                                       input [191:0] value);
        begin
            while (!component_cfg_ready) @(negedge clk);
            @(negedge clk); component_cfg_index = address;
            component_cfg_descriptor = value; component_cfg_valid = 1'b1;
            @(posedge clk); #1 component_cfg_valid = 1'b0;
            if (component_cfg_error)
                $fatal(1, "component config failed %h",
                       component_cfg_error_code);
        end
    endtask

    task automatic configure_data_descriptor(input [15:0] id,
                                              input [127:0] value);
        begin
            while (!data_descriptor_cfg_ready) @(negedge clk);
            @(negedge clk); data_descriptor_cfg_id = id;
            data_descriptor_cfg_data = value; data_descriptor_cfg_valid = 1'b1;
            @(posedge clk); #1 data_descriptor_cfg_valid = 1'b0;
            if (data_descriptor_cfg_error)
                $fatal(1, "data descriptor config failed %h",
                       data_descriptor_cfg_error_code);
        end
    endtask

    task automatic configure_binding(input [15:0] id, input [63:0] value);
        begin
            while (!binding_cfg_ready) @(negedge clk);
            @(negedge clk); binding_cfg_id = id; binding_cfg_data = value;
            binding_cfg_valid = 1'b1;
            @(posedge clk); #1 binding_cfg_valid = 1'b0;
            if (binding_cfg_error)
                $fatal(1, "binding config failed %h", binding_cfg_error_code);
        end
    endtask

    task automatic scratch_write(input [15:0] address,
                                 input [63:0] value);
        begin
            while (!scratch_init_ready) @(negedge clk);
            @(negedge clk); scratch_init_address = address;
            scratch_init_write_data = value; scratch_init_write = 1'b1;
            scratch_init_valid = 1'b1;
            @(posedge clk); #1 scratch_init_valid = 1'b0;
            scratch_init_write = 1'b0;
            if (scratch_init_error)
                $fatal(1, "scratch write failed at %0d", address);
        end
    endtask

    initial begin
        $readmemh(
            "manifests/programs/rtl_images/xmss_xmss_shake256_h10_w4_keygen.hex",
            program_image);
        $readmemh(
            "manifests/programs/rtl_images/xmss_xmss_shake256_h10_w4_sign_layouts.hex",
            layout_image);
        $readmemh(
            "manifests/programs/rtl_images/xmss_xmss_shake256_h10_w4_sign_components.hex",
            component_image);
        for (index = 0; index < 32; index = index + 1) begin
            job_sk_seed[8*index +: 8] = index[7:0];
            job_public_seed[8*index +: 8] = 8'h40 + index[7:0];
        end
        if (TEST_TREE_HEIGHT == 10)
            job_target_leaf = 16'd5;

        repeat (3) @(negedge clk);
        rst_n = 1'b1;
        for (index = 0; index < 93; index = index + 1)
            write_program(index[8:0], program_image[index]);
        if (TEST_TREE_HEIGHT == 2)
            write_program(9'd0, OUTER_LOOP_FOUR);
        for (index = 0; index < 8; index = index + 1)
            configure_layout(index[15:0], layout_image[index]);
        for (index = 0; index <= 80; index = index + 1)
            configure_component(index[15:0], component_image[index]);
        configure_data_descriptor(0, XMSS_STORE_DESC);
        configure_data_descriptor(1, XMSS_ROOT_EMIT_DESC);
        configure_binding(0, XMSS_SOURCE_BIND);
        configure_binding(1, XMSS_DEST_BIND);

        while (!job_ready) @(negedge clk);
        @(negedge clk); job_valid = 1'b1;
        @(negedge clk); job_valid = 1'b0;
        cycles = 0;
        while (!done && !error && cycles < 800000000) begin
            @(negedge clk); cycles = cycles + 1;
        end
        if (!done || error)
            $fatal(1, "generic h2 failed code=%h cycles=%0d",
                   error_code, cycles);
        if (captured_root !== ((TEST_TREE_HEIGHT == 2)
                              ? EXPECTED_ROOT_H2 : EXPECTED_ROOT_H10))
            $fatal(1, "generic tree root mismatch h=%0d root=%064x",
                   TEST_TREE_HEIGHT, captured_root);
        if (emitted_words != 4
            || emitted_root !== ((TEST_TREE_HEIGHT == 2)
                                 ? EXPECTED_ROOT_H2 : EXPECTED_ROOT_H10))
            $fatal(1, "generic tree emitted root mismatch h=%0d words=%0d root=%064x",
                   TEST_TREE_HEIGHT, emitted_words, emitted_root);
        if (captured_auth_mask !== ((TEST_TREE_HEIGHT == 2)
                                    ? 10'h003 : 10'h3ff))
            $fatal(1, "generic tree auth mask mismatch h=%0d mask=%03x",
                   TEST_TREE_HEIGHT, captured_auth_mask);
        for (index = 0; index < TEST_TREE_HEIGHT; index = index + 1)
            if (captured_auth[index] !== expected_auth(index))
                $fatal(1, "generic tree auth[%0d] mismatch got=%064x",
                       index, captured_auth[index]);
        if (accepted_job_commands != 1
            || host_control_writes_during_busy != 0
            || issued_hash_requests != 3346 * (1 << TEST_TREE_HEIGHT)
            || issued_data_requests != (5 * (1 << TEST_TREE_HEIGHT) + 1)
            || issued_tree_requests != (1 << TEST_TREE_HEIGHT)
            || accepted_leaves != (1 << TEST_TREE_HEIGHT)
            || parent_hashes != ((1 << TEST_TREE_HEIGHT) - 1)
            || retired_components != 29772 * (1 << TEST_TREE_HEIGHT)
            || composer_scratch_reads != 22748 * (1 << TEST_TREE_HEIGHT)
            || composer_scratch_writes != 13384 * (1 << TEST_TREE_HEIGHT)
            || scratch_transactions != (36176 * (1 << TEST_TREE_HEIGHT) + 8)
            || absorbed_blocks != 3346 * (1 << TEST_TREE_HEIGHT))
            $fatal(1, "generic tree command accounting mismatch h=%0d jobs=%0d hash=%0d data=%0d tree=%0d leaves=%0d parents=%0d host=%0d",
                   TEST_TREE_HEIGHT,
                   accepted_job_commands, issued_hash_requests,
                   issued_data_requests, issued_tree_requests,
                   accepted_leaves, parent_hashes,
                   host_control_writes_during_busy);
        if (TEST_TREE_HEIGHT == 2
            && (cycles != 2638342 || retired_instructions != 18663))
            $fatal(1, "generic h2 cycle/retired mismatch cycles=%0d retired=%0d",
                   cycles, retired_instructions);
        if (TEST_TREE_HEIGHT == 10
            && (cycles != 675417082 || retired_instructions != 4776963))
            $fatal(1, "generic h10 cycle/retired mismatch cycles=%0d retired=%0d",
                   cycles, retired_instructions);
        $display("PASS JSON-component XMSS h%0d TreeHash cycles=%0d hash=%0d data=%0d tree=%0d retired=%0d components=%0d scratch=%0d/%0d/%0d blocks=%0d",
                 TEST_TREE_HEIGHT, cycles,
                 issued_hash_requests, issued_data_requests,
                 issued_tree_requests, retired_instructions,
                 retired_components, composer_scratch_reads,
                 composer_scratch_writes, scratch_transactions,
                 absorbed_blocks);
        $finish;
    end
endmodule

`default_nettype wire
