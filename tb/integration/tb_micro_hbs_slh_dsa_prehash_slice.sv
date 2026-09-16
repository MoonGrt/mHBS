`timescale 1ns/1ps
`default_nettype none

module tb_micro_hbs_slh_dsa_prehash_slice;
    logic clk = 1'b0;
    logic rst_n = 1'b0;
    always #5 clk = ~clk;

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
    logic bitfield_cfg_valid = 1'b0;
    wire bitfield_cfg_ready;
    logic [15:0] bitfield_cfg_id = '0;
    logic [127:0] bitfield_cfg_descriptor = '0;
    wire bitfield_cfg_error;
    wire [15:0] bitfield_cfg_error_code;
    logic expr_descriptor_cfg_valid = 1'b0;
    wire expr_descriptor_cfg_ready;
    logic [15:0] expr_descriptor_cfg_id = '0;
    logic [63:0] expr_descriptor_cfg_data = '0;
    wire expr_descriptor_cfg_error;
    wire [15:0] expr_descriptor_cfg_error_code;
    logic expr_token_cfg_valid = 1'b0;
    wire expr_token_cfg_ready;
    logic [5:0] expr_token_cfg_index = '0;
    logic [63:0] expr_token_cfg_data = '0;
    logic base_w_cfg_valid = 1'b0;
    wire base_w_cfg_ready;
    logic [15:0] base_w_cfg_id = '0;
    logic [63:0] base_w_cfg_data = '0;
    wire base_w_cfg_error;
    wire [15:0] base_w_cfg_error_code;
    logic wide_shift_cfg_valid = 1'b0;
    wire wide_shift_cfg_ready;
    logic [15:0] wide_shift_cfg_id = '0;
    logic [63:0] wide_shift_cfg_data = '0;
    wire wide_shift_cfg_error;
    wire [15:0] wide_shift_cfg_error_code;
    logic data_descriptor_cfg_valid = 1'b0;
    wire data_descriptor_cfg_ready;
    logic [15:0] data_descriptor_cfg_id = '0;
    logic [127:0] data_descriptor_cfg_data = '0;
    wire data_descriptor_cfg_error;
    wire [15:0] data_descriptor_cfg_error_code;
    logic data_binding_cfg_valid = 1'b0;
    wire data_binding_cfg_ready;
    logic [15:0] data_binding_cfg_id = '0;
    logic [63:0] data_binding_cfg_data = '0;
    wire data_binding_cfg_error;
    wire [15:0] data_binding_cfg_error_code;
    logic tree_cfg_valid = 1'b0;
    wire tree_cfg_ready;
    logic [15:0] tree_cfg_id = '0;
    logic [63:0] tree_cfg_data = '0;
    wire tree_cfg_error;
    wire [15:0] tree_cfg_error_code;
    logic job_valid = 1'b0;
    wire job_ready;
    logic [8:0] job_entry = '0;
    logic [31:0] job_message_length = 1;
    logic [127:0] job_sk_seed = 128'hd1d06dcbb9181a55aabce64467d6b81d;
    logic [127:0] job_sk_prf = 128'hca423fc52136322bce5c73a684d95cb7;
    logic [127:0] job_pk_seed = 128'hf416dc35e41222ef87445111008541d5;
    logic [127:0] job_pk_root = 128'h3d774653892d5f3695b370c7cdab63ff;
    logic [127:0] job_opt_rand = 128'hf416dc35e41222ef87445111008541d5;
    logic message_valid = 1'b0;
    wire message_ready;
    logic [63:0] message_data = 64'h8f;
    logic [7:0] message_keep = 8'h01;
    logic message_last = 1'b1;
    wire out_valid;
    logic out_ready = 1'b1;
    wire [63:0] out_data;
    wire [7:0] out_keep;
    wire out_last;
    wire busy, done, error;
    wire [15:0] error_code;
    wire [255:0] last_digest;
    wire [31:0] accepted_job_commands, admitted_message_words;
    wire [31:0] host_control_writes_during_busy, issued_hash_requests;
    wire [31:0] tree_parent_hashes;
    wire [31:0] retired_instructions, scratch_reads, scratch_writes;
    wire [31:0] absorbed_blocks, retired_components;
    logic [127:0] layout_image [0:13];
    logic [191:0] component_image [0:120];
    logic [127:0] bitfield_image [0:5];
    logic [63:0] expr_descriptor_image [0:5];
    logic [63:0] expr_token_image [0:35];
    logic [63:0] base_w_descriptor_image [0:0];
    logic [63:0] wide_shift_descriptor_image [0:0];
    logic [127:0] data_descriptor_image [0:4];
    logic [63:0] data_binding_image [0:2];
    logic [63:0] tree_descriptor_image [0:6];
    logic [63:0] expected_fors_words [0:461];
    logic [63:0] expected_fors_root [0:1];
    logic [63:0] expected_signature_words [0:2135];
    logic [63:0] program_image [0:143];
    integer index;
    integer cycles;
    integer height;
    integer program_pc;
    integer output_words_seen;

    localparam logic [7:0] OP_HASH_LAYOUT = 8'h03;
    localparam logic [7:0] OP_MOVI = 8'h01;
    localparam logic [7:0] OP_LOAD = 8'h08;
    localparam logic [7:0] OP_STORE = 8'h09;
    localparam logic [7:0] OP_LOOP_SETUP = 8'h04;
    localparam logic [7:0] OP_LOOP_END = 8'h05;
    localparam logic [7:0] OP_TREE_PUSH = 8'h0b;
    localparam logic [7:0] OP_EMIT = 8'h0c;
    localparam logic [7:0] OP_HALT = 8'h0d;

    micro_hbs_slh_dsa_prehash_slice #(
        .PROGRAM_WORDS(256), .COMPONENT_WORDS(128)
    ) dut (.*);

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n)
            output_words_seen <= 0;
        else if (out_valid && out_ready) begin
            if (out_keep !== 8'hff)
                $fatal(1, "unexpected partial FORS output word %0d keep=%h",
                       output_words_seen, out_keep);
            if (output_words_seen >= 2136)
                $fatal(1, "SLH-DSA emitted excess signature word");
            else if (out_data !== expected_signature_words[output_words_seen])
                $fatal(1, "SLH-DSA signature mismatch word=%0d got=%h expected=%h",
                       output_words_seen, out_data,
                       expected_signature_words[output_words_seen]);
            output_words_seen <= output_words_seen + 1;
        end
    end

    function automatic [63:0] enc(input [7:0] opcode,
        input [7:0] flags, input [7:0] rd, input [7:0] rs,
        input [31:0] imm);
        enc = {opcode, flags, rd, rs, imm};
    endfunction

    task automatic write_program(input [8:0] address, input [63:0] word);
        begin
            @(negedge clk);
            program_addr = address;
            program_wdata = word;
            program_we = 1'b1;
            @(negedge clk);
            program_we = 1'b0;
        end
    endtask

    task automatic configure_expr_descriptor(input [15:0] id,
                                              input [63:0] value);
        begin
            while (!expr_descriptor_cfg_ready) @(negedge clk);
            @(negedge clk);
            expr_descriptor_cfg_id = id;
            expr_descriptor_cfg_data = value;
            expr_descriptor_cfg_valid = 1'b1;
            @(posedge clk); #1 expr_descriptor_cfg_valid = 1'b0;
            if (expr_descriptor_cfg_error)
                $fatal(1, "expression descriptor configuration failed %h",
                       expr_descriptor_cfg_error_code);
        end
    endtask

    task automatic configure_expr_token(input [5:0] id,
                                         input [63:0] value);
        begin
            while (!expr_token_cfg_ready) @(negedge clk);
            @(negedge clk);
            expr_token_cfg_index = id;
            expr_token_cfg_data = value;
            expr_token_cfg_valid = 1'b1;
            @(posedge clk); #1 expr_token_cfg_valid = 1'b0;
        end
    endtask

    task automatic configure_base_w(input [15:0] id,
                                    input [63:0] value);
        begin
            while (!base_w_cfg_ready) @(negedge clk);
            @(negedge clk);
            base_w_cfg_id = id;
            base_w_cfg_data = value;
            base_w_cfg_valid = 1'b1;
            @(posedge clk); #1 base_w_cfg_valid = 1'b0;
            if (base_w_cfg_error)
                $fatal(1, "base-w configuration failed %h",
                       base_w_cfg_error_code);
        end
    endtask

    task automatic configure_wide_shift(input [15:0] id,
                                        input [63:0] value);
        begin
            while (!wide_shift_cfg_ready) @(negedge clk);
            @(negedge clk);
            wide_shift_cfg_id = id;
            wide_shift_cfg_data = value;
            wide_shift_cfg_valid = 1'b1;
            @(posedge clk); #1 wide_shift_cfg_valid = 1'b0;
            if (wide_shift_cfg_error)
                $fatal(1, "wide-shift configuration failed %h",
                       wide_shift_cfg_error_code);
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
            @(posedge clk); #1 data_descriptor_cfg_valid = 1'b0;
            if (data_descriptor_cfg_error)
                $fatal(1, "data descriptor configuration failed %h",
                       data_descriptor_cfg_error_code);
        end
    endtask

    task automatic configure_data_binding(input [15:0] id,
                                          input [63:0] value);
        begin
            while (!data_binding_cfg_ready) @(negedge clk);
            @(negedge clk);
            data_binding_cfg_id = id;
            data_binding_cfg_data = value;
            data_binding_cfg_valid = 1'b1;
            @(posedge clk); #1 data_binding_cfg_valid = 1'b0;
            if (data_binding_cfg_error)
                $fatal(1, "data binding configuration failed %h",
                       data_binding_cfg_error_code);
        end
    endtask

    task automatic configure_tree(input [15:0] id,
                                  input [63:0] value);
        begin
            while (!tree_cfg_ready) @(negedge clk);
            @(negedge clk);
            tree_cfg_id = id;
            tree_cfg_data = value;
            tree_cfg_valid = 1'b1;
            @(posedge clk); #1 tree_cfg_valid = 1'b0;
            if (tree_cfg_error)
                $fatal(1, "tree configuration failed %h",
                       tree_cfg_error_code);
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
            @(posedge clk); #1 layout_cfg_valid = 1'b0;
            if (layout_cfg_error)
                $fatal(1, "layout configuration failed %h",
                       layout_cfg_error_code);
        end
    endtask

    task automatic configure_component(input [15:0] id,
                                       input [191:0] value);
        begin
            while (!component_cfg_ready) @(negedge clk);
            @(negedge clk);
            component_cfg_index = id;
            component_cfg_descriptor = value;
            component_cfg_valid = 1'b1;
            @(posedge clk); #1 component_cfg_valid = 1'b0;
            if (component_cfg_error)
                $fatal(1, "component configuration failed %h",
                       component_cfg_error_code);
        end
    endtask

    task automatic configure_bitfield(input [15:0] id,
                                      input [127:0] value);
        begin
            while (!bitfield_cfg_ready) @(negedge clk);
            @(negedge clk);
            bitfield_cfg_id = id;
            bitfield_cfg_descriptor = value;
            bitfield_cfg_valid = 1'b1;
            @(posedge clk); #1 bitfield_cfg_valid = 1'b0;
            if (bitfield_cfg_error)
                $fatal(1, "bitfield configuration failed %h",
                       bitfield_cfg_error_code);
        end
    endtask

    initial begin
        $readmemh(
            "manifests/programs/rtl_images/slh_dsa_shake_128f_sign_prehash_layouts.hex",
            layout_image);
        $readmemh(
            "manifests/programs/rtl_images/slh_dsa_shake_128f_sign_prehash_components.hex",
            component_image);
        $readmemh(
            "manifests/programs/rtl_images/slh_dsa_shake_128f_sign_digest_bitfields.hex",
            bitfield_image);
        $readmemh(
            "manifests/programs/rtl_images/slh_dsa_shake_128f_sign_expr_descriptors.hex",
            expr_descriptor_image);
        $readmemh(
            "manifests/programs/rtl_images/slh_dsa_shake_128f_sign_expr_tokens.hex",
            expr_token_image);
        $readmemh(
            "manifests/programs/rtl_images/slh_dsa_shake_128f_sign_base_w_descriptor.hex",
            base_w_descriptor_image);
        $readmemh(
            "manifests/programs/rtl_images/slh_dsa_shake_128f_sign_wide_shift_descriptor.hex",
            wide_shift_descriptor_image);
        $readmemh(
            "manifests/programs/rtl_images/slh_dsa_shake_128f_sign_data_descriptors.hex",
            data_descriptor_image);
        $readmemh(
            "manifests/programs/rtl_images/slh_dsa_shake_128f_sign_data_bindings.hex",
            data_binding_image);
        $readmemh(
            "manifests/programs/rtl_images/slh_dsa_shake_128f_sign_tree_descriptors.hex",
            tree_descriptor_image);
        $readmemh(
            "manifests/programs/rtl_images/slh_dsa_shake_128f_fors_signature_expected.hex",
            expected_fors_words);
        $readmemh(
            "manifests/programs/rtl_images/slh_dsa_shake_128f_fors_root_expected.hex",
            expected_fors_root);
        $readmemh(
            "manifests/programs/rtl_images/slh_dsa_shake_128f_signature_expected.hex",
            expected_signature_words);
        $readmemh(
            "manifests/programs/rtl_images/slh_dsa_slh_dsa_shake_128f_sign.hex",
            program_image);
        repeat (3) @(negedge clk);
        rst_n = 1'b1;

        for (index = 0; index < 144; index = index + 1)
            write_program(index[8:0], program_image[index]);
        for (index = 0; index < 5; index = index + 1)
            configure_layout(index[15:0], layout_image[index]);
        configure_layout(10, layout_image[5]);
        configure_layout(11, layout_image[6]);
        configure_layout(12, layout_image[7]);
        configure_layout(13, layout_image[8]);
        configure_layout(14, layout_image[9]);
        configure_layout(15, layout_image[10]);
        configure_layout(18, layout_image[11]);
        configure_layout(19, layout_image[12]);
        configure_layout(20, layout_image[13]);
        for (index = 0; index < 121; index = index + 1)
            configure_component(index[15:0], component_image[index]);
        configure_bitfield(0, bitfield_image[0]);
        configure_bitfield(1, bitfield_image[1]);
        configure_bitfield(2, bitfield_image[2]);
        configure_bitfield(3, bitfield_image[3]);
        configure_bitfield(10, bitfield_image[4]);
        configure_bitfield(12, bitfield_image[5]);
        configure_expr_descriptor(4, expr_descriptor_image[0]);
        configure_expr_descriptor(5, expr_descriptor_image[1]);
        configure_expr_descriptor(6, expr_descriptor_image[2]);
        configure_expr_descriptor(7, expr_descriptor_image[3]);
        configure_expr_descriptor(8, expr_descriptor_image[4]);
        configure_expr_descriptor(11, expr_descriptor_image[5]);
        for (index = 0; index < 36; index = index + 1)
            configure_expr_token(index[5:0], expr_token_image[index]);
        configure_base_w(9, base_w_descriptor_image[0]);
        configure_wide_shift(13, wide_shift_descriptor_image[0]);
        for (index = 0; index < 5; index = index + 1)
            configure_data_descriptor(index[15:0], data_descriptor_image[index]);
        for (index = 0; index < 3; index = index + 1)
            configure_data_binding(index[15:0], data_binding_image[index]);
        configure_tree(5, tree_descriptor_image[0]);
        configure_tree(6, tree_descriptor_image[1]);
        configure_tree(7, tree_descriptor_image[2]);
        configure_tree(8, tree_descriptor_image[3]);
        configure_tree(9, tree_descriptor_image[4]);
        configure_tree(16, tree_descriptor_image[5]);
        configure_tree(17, tree_descriptor_image[6]);

        while (!job_ready) @(negedge clk);
        @(negedge clk);
        job_valid = 1'b1;
        @(negedge clk);
        job_valid = 1'b0;
        cycles = 0;

        // Configuration is frozen from Job acceptance, including payload load.
        program_addr = 0;
        program_wdata = 64'hffffffffffffffff;
        program_we = 1'b1;
        @(negedge clk);
        program_we = 1'b0;

        // Mutating the external fixed-field buses cannot affect the Job.
        job_sk_seed = '0;
        job_sk_prf = '0;
        job_pk_seed = '0;
        job_pk_root = '0;
        job_opt_rand = '0;
        while (!message_ready && cycles < 200) begin
            @(negedge clk);
            cycles = cycles + 1;
        end
        if (!message_ready)
            $fatal(1, "message admission timeout loader=%0d fixed=%0d seq=%0d sp=%0d/%0d bounds=%0d",
                   dut.loader.state, dut.loader.fixed_word_index,
                   dut.sequencer.state, dut.sp_valid, dut.sp_ready,
                   dut.sp_bounds_error);
        message_valid = 1'b1;
        @(negedge clk);
        cycles = cycles + 1;
        message_valid = 1'b0;

        while (!done && !error && cycles < 30000000) begin
            @(negedge clk);
            cycles = cycles + 1;
        end
        if (!done || error)
            $fatal(1, "SLH-DSA prehash failed code=%h cycles=%0d seq=%0d pc=%0d generic=%0d alu=%0d sp=%0d/%0d rsp=%0d",
                   error_code, cycles, dut.sequencer.state, dut.sequencer.pc,
                   dut.generic_data_engine.state,
                   dut.generic_data_engine.scratch_alu.state,
                   dut.sp_valid, dut.sp_ready, dut.sp_rsp_valid);

        // R = 4c19417603ebaab13c32592134b55663 at logical slot 236.
        if (dut.scratchpad.memory[472] !== 64'hb1aaeb037641194c
            || dut.scratchpad.memory[473] !== 64'h6356b5342159323c)
            $fatal(1, "SLH-DSA PRF_msg mismatch");
        // H_msg is 34 bytes, proving that the rate-output path is not
        // truncated to the legacy 32-byte digest port.
        if (dut.scratchpad.memory[480] !== 64'ha05f4bf6064db89a
            || dut.scratchpad.memory[481] !== 64'he569f6ae43b1826a
            || dut.scratchpad.memory[482] !== 64'haa229e7fadc54061
            || dut.scratchpad.memory[483] !== 64'h523d0b6814d60916
            || dut.scratchpad.memory[484] !== 64'h000000000000fae9)
            $fatal(1, "SLH-DSA H_msg mismatch");
        if (output_words_seen != 2136)
            $fatal(1, "SLH-DSA signature output length mismatch words=%0d",
                   output_words_seen);
        if (accepted_job_commands != 1 || admitted_message_words != 1
            || host_control_writes_during_busy != 1)
            $fatal(1, "accounting mismatch job=%0d msg=%0d host=%0d hash=%0d data=%0d tree=%0d inst=%0d scratch=%0d/%0d blocks=%0d components=%0d",
                   accepted_job_commands, admitted_message_words,
                   host_control_writes_during_busy, issued_hash_requests,
                   dut.issued_data_requests, dut.issued_tree_requests,
                   retired_instructions, scratch_reads, scratch_writes,
                   absorbed_blocks, retired_components);

        if (cycles != 15167426
            || issued_hash_requests != 102968
            || tree_parent_hashes != 1969
            || dut.issued_tree_requests != 2178
            || dut.issued_data_requests != 5542
            || retired_instructions != 221811
            || scratch_reads != 630294
            || scratch_writes != 205939
            || absorbed_blocks != 103672
            || retired_components != 835169)
            $fatal(1, "complete Sign counter mismatch cycles=%0d hash=%0d+%0d tree=%0d data=%0d inst=%0d scratch=%0d/%0d blocks=%0d components=%0d",
                   cycles, issued_hash_requests, tree_parent_hashes,
                   dut.issued_tree_requests, dut.issued_data_requests,
                   retired_instructions, scratch_reads, scratch_writes,
                   absorbed_blocks, retired_components);
        if (issued_hash_requests + tree_parent_hashes != 104937
            || absorbed_blocks + tree_parent_hashes != 105641)
            $fatal(1, "complete Sign SHAKE accounting mismatch calls=%0d permutations=%0d",
                   issued_hash_requests + tree_parent_hashes,
                   absorbed_blocks + tree_parent_hashes);

        $display("PASS no-DMA complete SLH-DSA Sign cycles=%0d hash=%0d+%0d tree=%0d data=%0d inst=%0d scratch=%0d/%0d blocks=%0d+%0d components=%0d",
                 cycles, issued_hash_requests, tree_parent_hashes,
                 dut.issued_tree_requests,
                 dut.issued_data_requests, retired_instructions,
                 scratch_reads, scratch_writes, absorbed_blocks,
                 tree_parent_hashes,
                 retired_components);
        $finish;
    end
endmodule

`default_nettype wire
