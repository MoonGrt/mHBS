`timescale 1ns/1ps
`default_nettype none

module tb_micro_hbs_xmss_generic_leaf_slice;
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
    logic [8:0] job_entry = 9'd1;
    logic [15:0] job_target_leaf = '0;
    logic [255:0] job_sk_seed = '0;
    logic [255:0] job_public_seed = '0;
    logic [255:0] job_address_template = '0;
    wire busy, done, error;
    wire [15:0] error_code;
    wire [255:0] last_digest;
    wire [31:0] accepted_job_commands;
    wire [31:0] host_control_writes_during_busy;
    wire [31:0] issued_hash_requests, issued_data_requests;
    wire [31:0] issued_tree_requests;
    wire [31:0] retired_instructions, retired_components;
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
    logic [63:0] leaf_word [0:3];
    integer index;
    integer cycles;

    localparam logic [63:0] HALT = 64'h0d00000000000000;
    localparam logic [127:0] XMSS_STORE_DESC =
        128'h02000200000000000000048500002000;
    localparam logic [63:0] XMSS_SOURCE_BIND = 64'h37c0010001000000;
    localparam logic [63:0] XMSS_DEST_BIND   = 64'hbac0010001000000;
    localparam logic [255:0] EXPECTED_LEAF0 =
        256'hcf5ffcb36abd65966bdd7b5fec1da321ce4f5eaf4fcfadb90ffc5b77d147b85c;

    always #5 clk = ~clk;

    micro_hbs_xmss_generic_leaf_slice dut (.*);

    task automatic write_program(input [8:0] address, input [63:0] value);
        begin
            @(negedge clk);
            program_addr = address;
            program_wdata = value;
            program_we = 1'b1;
            @(negedge clk);
            program_we = 1'b0;
        end
    endtask

    task automatic configure_layout(input [15:0] id,
                                    input [127:0] value);
        begin
            while (!layout_cfg_ready) @(negedge clk);
            @(negedge clk);
            layout_cfg_id = id;
            layout_cfg_descriptor = value;
            layout_cfg_valid = 1'b1;
            @(posedge clk);
            #1 layout_cfg_valid = 1'b0;
            if (layout_cfg_error)
                $fatal(1, "layout config failed %h", layout_cfg_error_code);
        end
    endtask

    task automatic configure_component(input [15:0] address,
                                       input [191:0] value);
        begin
            while (!component_cfg_ready) @(negedge clk);
            @(negedge clk);
            component_cfg_index = address;
            component_cfg_descriptor = value;
            component_cfg_valid = 1'b1;
            @(posedge clk);
            #1 component_cfg_valid = 1'b0;
            if (component_cfg_error)
                $fatal(1, "component config failed %h",
                       component_cfg_error_code);
        end
    endtask

    task automatic configure_data_descriptor(input [15:0] id,
                                              input [127:0] value);
        begin
            while (!data_descriptor_cfg_ready) @(negedge clk);
            @(negedge clk);
            data_descriptor_cfg_id = id;
            data_descriptor_cfg_data = value;
            data_descriptor_cfg_valid = 1'b1;
            @(posedge clk);
            #1 data_descriptor_cfg_valid = 1'b0;
            if (data_descriptor_cfg_error)
                $fatal(1, "data descriptor config failed %h",
                       data_descriptor_cfg_error_code);
        end
    endtask

    task automatic configure_binding(input [15:0] id, input [63:0] value);
        begin
            while (!binding_cfg_ready) @(negedge clk);
            @(negedge clk);
            binding_cfg_id = id;
            binding_cfg_data = value;
            binding_cfg_valid = 1'b1;
            @(posedge clk);
            #1 binding_cfg_valid = 1'b0;
            if (binding_cfg_error)
                $fatal(1, "binding config failed %h", binding_cfg_error_code);
        end
    endtask

    task automatic scratch_write(input [15:0] address,
                                 input [63:0] value);
        begin
            while (!scratch_init_ready) @(negedge clk);
            @(negedge clk);
            scratch_init_address = address;
            scratch_init_write_data = value;
            scratch_init_write = 1'b1;
            scratch_init_valid = 1'b1;
            @(posedge clk);
            #1 scratch_init_valid = 1'b0;
            scratch_init_write = 1'b0;
            if (scratch_init_error)
                $fatal(1, "scratch write failed at %0d", address);
        end
    endtask

    task automatic scratch_read(input [15:0] address,
                                output [63:0] value);
        begin
            while (!scratch_init_ready) @(negedge clk);
            @(negedge clk);
            scratch_init_address = address;
            scratch_init_write = 1'b0;
            scratch_init_valid = 1'b1;
            @(posedge clk);
            #1 scratch_init_valid = 1'b0;
            while (!scratch_init_rsp_valid && !scratch_init_error) begin
                @(posedge clk);
                #1;
            end
            if (scratch_init_error)
                $fatal(1, "scratch read failed at %0d", address);
            value = scratch_init_rsp_data;
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
        repeat (3) @(negedge clk);
        rst_n = 1'b1;

        for (index = 0; index < 93; index = index + 1)
            write_program(index[8:0], program_image[index]);
        // Start at PC=1 (inside the outer leaf loop) and terminate where the
        // unmodified image would TREE_PUSH the completed leaf.
        write_program(9'd89, HALT);
        for (index = 0; index < 8; index = index + 1)
            configure_layout(index[15:0], layout_image[index]);
        for (index = 0; index <= 80; index = index + 1)
            configure_component(index[15:0], component_image[index]);
        configure_data_descriptor(0, XMSS_STORE_DESC);
        configure_binding(0, XMSS_SOURCE_BIND);
        configure_binding(1, XMSS_DEST_BIND);

        while (!job_ready) @(negedge clk);
        @(negedge clk);
        job_valid = 1'b1;
        @(negedge clk);
        job_valid = 1'b0;
        cycles = 0;
        while (!done && !error && cycles < 2000000) begin
            @(negedge clk);
            cycles = cycles + 1;
        end
        if (!done || error)
            $fatal(1, "generic leaf failed code=%h cycles=%0d job_state=%0d load_word=%0d seq_busy=%0d seq_ready=%0d sp_valid=%0d",
                   error_code, cycles, dut.job_state, dut.job_load_word,
                   dut.seq_busy, dut.seq_job_ready, dut.sp_rsp_valid);

        for (index = 0; index < 4; index = index + 1)
            scratch_read(16'd548 + index[15:0], leaf_word[index]);
        if ({leaf_word[3], leaf_word[2], leaf_word[1], leaf_word[0]}
            !== EXPECTED_LEAF0)
            $fatal(1, "generic WOTS leaf mismatch got=%016x%016x%016x%016x",
                   leaf_word[3], leaf_word[2], leaf_word[1], leaf_word[0]);
        if (accepted_job_commands != 1
            || host_control_writes_during_busy != 0
            || issued_hash_requests != 3346 || issued_data_requests != 5)
            $fatal(1, "command accounting mismatch jobs=%0d hash=%0d data=%0d host=%0d",
                   accepted_job_commands, issued_hash_requests,
                   issued_data_requests, host_control_writes_during_busy);
        if (cycles != 659517
            || retired_instructions != 4664
            || retired_components != 29772
            || composer_scratch_reads != 22748
            || composer_scratch_writes != 13384
            || scratch_transactions != 36172
            || absorbed_blocks != 3346)
            $fatal(1, "execution accounting mismatch cycles=%0d retired=%0d components=%0d scratch=%0d/%0d/%0d blocks=%0d",
                   cycles, retired_instructions, retired_components,
                   composer_scratch_reads, composer_scratch_writes,
                   scratch_transactions, absorbed_blocks);

        $display("PASS JSON-component XMSS WOTS+/L-tree leaf cycles=%0d hash=%0d data=%0d retired=%0d components=%0d scratch=%0d/%0d/%0d blocks=%0d",
                 cycles, issued_hash_requests, issued_data_requests,
                 retired_instructions, retired_components,
                 composer_scratch_reads, composer_scratch_writes,
                 scratch_transactions, absorbed_blocks);
        $finish;
    end
endmodule

`default_nettype wire
