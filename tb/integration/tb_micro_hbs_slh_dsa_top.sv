`timescale 1ns/1ps
`default_nettype none

module tb_micro_hbs_slh_dsa_top #(
    parameter integer DUT_UNROLL = 2
);
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
    logic [127:0] layout_image [0:16];
    logic [191:0] component_image [0:109];
    logic [127:0] bitfield_image [0:7];
    logic [63:0] expr_descriptor_image [0:5];
    logic [63:0] expr_token_image [0:37];
    logic [63:0] base_w_descriptor_image [0:0];
    logic [63:0] wide_shift_descriptor_image [0:0];
    logic [127:0] data_descriptor_image [0:4];
    logic [63:0] data_binding_image [0:2];
    logic [63:0] tree_descriptor_image [0:6];
    logic [63:0] expected_fors_words [0:461];
    logic [63:0] expected_fors_root [0:1];
    logic [63:0] expected_signature_words [0:2135];
    localparam integer PROGRAM_IMAGE_WORDS = 160;
    logic [63:0] program_image [0:PROGRAM_IMAGE_WORDS-1];
    integer index;
    integer cycles;
    integer height;
    integer program_pc;
    integer output_words_seen;
    integer profile_index;
    integer sequencer_state_cycles [0:15];
    integer composer_state_cycles [0:31];
    integer tree_adapter_state_cycles [0:15];
    integer treehash_state_cycles [0:7];
    integer bitfield_state_cycles [0:7];
    integer generic_data_state_cycles [0:15];
    integer profile_scratch_requests;
    integer profile_scratch_responses;
    integer profile_dynamic_bound_cycles;
    integer profile_generic_busy_cycles;
    integer profile_bitfield_busy_cycles;
    integer profile_expr_busy_cycles;
    integer profile_base_w_busy_cycles;
    integer profile_wide_shift_busy_cycles;
    integer profile_tree_busy_cycles;
    integer profile_prefetch_hits;
    integer profile_prefetch_bubble_entries;
    integer profile_prefetch_validation_stalls;
    integer profile_feedback_read_hits;
    integer profile_pair_command_cycles;
    integer profile_pair_overlap_cycles;
    integer previous_composer_state;

    localparam logic [7:0] OP_HASH = 8'h03;
    localparam logic [7:0] OP_SET_REG = 8'h01;
    localparam logic [7:0] OP_DATA_LOAD = 8'h08;
    localparam logic [7:0] OP_DATA_MOVE = 8'h09;
    localparam logic [7:0] OP_LOOP_BEGIN = 8'h04;
    localparam logic [7:0] OP_LOOP_END = 8'h05;
    localparam logic [7:0] OP_TREE_PUSH = 8'h0b;
    localparam logic [7:0] OP_OUTPUT = 8'h0c;
    localparam logic [7:0] OP_HALT = 8'h0d;

    micro_hbs_slh_dsa_top #(
        .PROGRAM_WORDS(256), .COMPONENT_WORDS(128), .UNROLL(DUT_UNROLL)
    ) dut (.*);

    task automatic sample_profile;
        begin
            sequencer_state_cycles[dut.sequencer.state] =
                sequencer_state_cycles[dut.sequencer.state] + 1;
            composer_state_cycles[dut.composer.state] =
                composer_state_cycles[dut.composer.state] + 1;
            tree_adapter_state_cycles[dut.tree_adapter.state] =
                tree_adapter_state_cycles[dut.tree_adapter.state] + 1;
            treehash_state_cycles[dut.tree_adapter.treehash.state] =
                treehash_state_cycles[dut.tree_adapter.treehash.state] + 1;
            bitfield_state_cycles[dut.bitfield_adapter.state] =
                bitfield_state_cycles[dut.bitfield_adapter.state] + 1;
            generic_data_state_cycles[dut.generic_data_engine.state] =
                generic_data_state_cycles[dut.generic_data_engine.state] + 1;
            if (dut.sp_valid && dut.sp_ready)
                profile_scratch_requests = profile_scratch_requests + 1;
            if (dut.sp_rsp_valid)
                profile_scratch_responses = profile_scratch_responses + 1;
            if (dut.dynamic_bound_req)
                profile_dynamic_bound_cycles = profile_dynamic_bound_cycles + 1;
            if (dut.generic_busy)
                profile_generic_busy_cycles = profile_generic_busy_cycles + 1;
            if (dut.bitfield_busy)
                profile_bitfield_busy_cycles = profile_bitfield_busy_cycles + 1;
            if (dut.expr_busy)
                profile_expr_busy_cycles = profile_expr_busy_cycles + 1;
            if (dut.base_w_busy)
                profile_base_w_busy_cycles = profile_base_w_busy_cycles + 1;
            if (dut.wide_shift_busy)
                profile_wide_shift_busy_cycles =
                    profile_wide_shift_busy_cycles + 1;
            if (dut.tree_busy)
                profile_tree_busy_cycles = profile_tree_busy_cycles + 1;
            if (dut.composer.state == 16
                && dut.composer.emit_component_done
                && dut.composer.components_remaining > 1
                && (dut.composer.prefetch_ready
                    || dut.composer.prefetch_products_pending))
                profile_prefetch_hits = profile_prefetch_hits + 1;
            if (dut.composer.state == 20
                && previous_composer_state != 20)
                profile_prefetch_bubble_entries
                    = profile_prefetch_bubble_entries + 1;
            if (dut.composer.state == 11
                && previous_composer_state == 11)
                profile_prefetch_validation_stalls
                    = profile_prefetch_validation_stalls + 1;
            if (dut.composer.feedback_word_used)
                profile_feedback_read_hits = profile_feedback_read_hits
                    + dut.composer.feedback_word_used;
            if (dut.composer.pair_mode && dut.composer.state != 0)
                profile_pair_command_cycles = profile_pair_command_cycles + 1;
            if (dut.composer.pair_mode && dut.composer.lane0_running
                && dut.composer.lane1_running)
                profile_pair_overlap_cycles = profile_pair_overlap_cycles + 1;
            previous_composer_state = dut.composer.state;
        end
    endtask

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

        for (index = 0; index < PROGRAM_IMAGE_WORDS; index = index + 1)
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
        configure_layout(21, layout_image[14]);
        configure_layout(22, layout_image[15]);
        configure_layout(23, layout_image[16]);
        for (index = 0; index < 110; index = index + 1)
            configure_component(index[15:0], component_image[index]);
        configure_bitfield(0, bitfield_image[0]);
        configure_bitfield(1, bitfield_image[1]);
        configure_bitfield(2, bitfield_image[2]);
        configure_bitfield(3, bitfield_image[3]);
        configure_bitfield(10, bitfield_image[4]);
        configure_bitfield(12, bitfield_image[5]);
        configure_bitfield(14, bitfield_image[6]);
        configure_bitfield(15, bitfield_image[7]);
        configure_expr_descriptor(4, expr_descriptor_image[0]);
        configure_expr_descriptor(5, expr_descriptor_image[1]);
        configure_expr_descriptor(6, expr_descriptor_image[2]);
        configure_expr_descriptor(7, expr_descriptor_image[3]);
        configure_expr_descriptor(8, expr_descriptor_image[4]);
        configure_expr_descriptor(11, expr_descriptor_image[5]);
        for (index = 0; index < 38; index = index + 1)
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
        for (profile_index = 0; profile_index < 16;
             profile_index = profile_index + 1) begin
            sequencer_state_cycles[profile_index] = 0;
            tree_adapter_state_cycles[profile_index] = 0;
            generic_data_state_cycles[profile_index] = 0;
        end
        for (profile_index = 0; profile_index < 32;
             profile_index = profile_index + 1)
            composer_state_cycles[profile_index] = 0;
        for (profile_index = 0; profile_index < 8;
             profile_index = profile_index + 1) begin
            treehash_state_cycles[profile_index] = 0;
            bitfield_state_cycles[profile_index] = 0;
        end
        profile_scratch_requests = 0;
        profile_scratch_responses = 0;
        profile_dynamic_bound_cycles = 0;
        profile_generic_busy_cycles = 0;
        profile_bitfield_busy_cycles = 0;
        profile_expr_busy_cycles = 0;
        profile_base_w_busy_cycles = 0;
        profile_wide_shift_busy_cycles = 0;
        profile_tree_busy_cycles = 0;
        profile_prefetch_hits = 0;
        profile_prefetch_bubble_entries = 0;
        profile_prefetch_validation_stalls = 0;
        profile_feedback_read_hits = 0;
        profile_pair_command_cycles = 0;
        profile_pair_overlap_cycles = 0;
        previous_composer_state = -1;

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
            sample_profile();
        end
        if (!message_ready)
            $fatal(1, "message admission timeout loader=%0d fixed=%0d seq=%0d sp=%0d/%0d bounds=%0d",
                   dut.loader.state, dut.loader.fixed_word_index,
                   dut.sequencer.state, dut.sp_valid, dut.sp_ready,
                   dut.sp_bounds_error);
        message_valid = 1'b1;
        @(negedge clk);
        cycles = cycles + 1;
        sample_profile();
        message_valid = 1'b0;

        while (!done && !error && cycles < 30000000) begin
            @(negedge clk);
            cycles = cycles + 1;
            sample_profile();
        end
        if (!done || error)
            $fatal(1, "SLH-DSA prehash failed code=%h cycles=%0d seq=%0d pc=%0d flags=%h rs=%0d hasherr=%0d/%h ext=%0d lane1=%0d extcnt=%0d/%0d/%0d preq=%0d/%0d prsp=%0d generic=%0d alu=%0d sp=%0d/%0d rsp=%0d",
                   error_code, cycles, dut.sequencer.state, dut.sequencer.pc,
                   dut.sequencer.flags, dut.sequencer.rs,
                   dut.hash_rsp_error, dut.hash_rsp_error_code,
                   dut.composer.ext_hash_active,
                   dut.composer.shake_lane1.permutation.active,
                   dut.composer.ext_hash_accepts,
                   dut.composer.ext_hash_responses,
                   dut.composer.ext_hash_errors,
                   dut.parent_hash_req_valid, dut.parent_hash_req_ready,
                   dut.parent_hash_rsp_valid,
                   dut.generic_data_engine.state,
                   dut.generic_data_engine.scratch_alu.state,
                   dut.sp_valid, dut.sp_ready, dut.sp_rsp_valid);

        // R = 4c19417603ebaab13c32592134b55663 at logical slot 236.
        if (dut.scratchpad.bank0_memory.memory[236]
                !== 64'hb1aaeb037641194c
            || dut.scratchpad.bank1_memory.memory[236]
                !== 64'h6356b5342159323c)
            $fatal(1, "SLH-DSA PRF_msg mismatch");
        // H_msg is 34 bytes, proving that the rate-output path is not
        // truncated to the legacy 32-byte digest port.
        if (dut.scratchpad.bank0_memory.memory[240]
                !== 64'ha05f4bf6064db89a
            || dut.scratchpad.bank1_memory.memory[240]
                !== 64'he569f6ae43b1826a
            || dut.scratchpad.bank0_memory.memory[241]
                !== 64'haa229e7fadc54061
            || dut.scratchpad.bank1_memory.memory[241]
                !== 64'h523d0b6814d60916
            || dut.scratchpad.bank0_memory.memory[242]
                !== 64'h000000000000fae9)
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

        $display("CURRENT exact cycles=%0d hash=%0d tree_parent=%0d tree_req=%0d data=%0d inst=%0d scratch=%0d/%0d blocks=%0d components=%0d feedback=%0d spreq=%0d paircmd=%0d overlap=%0d service=%0d lane0=%0d lane1=%0d prefetch=%0d",
                 cycles, issued_hash_requests, tree_parent_hashes,
                 dut.issued_tree_requests, dut.issued_data_requests,
                 retired_instructions, scratch_reads, scratch_writes,
                 absorbed_blocks, retired_components,
                 profile_feedback_read_hits, profile_scratch_requests,
                 profile_pair_command_cycles, profile_pair_overlap_cycles,
                 dut.composer.dual_service_cycles,
                 dut.composer.lane0_active_cycles,
                 dut.composer.lane1_active_cycles, profile_prefetch_hits);
        if (issued_hash_requests != 5016
            || tree_parent_hashes != 1969
            || dut.issued_tree_requests != 2178
            || dut.issued_data_requests != 3784
            || retired_instructions != 21134
            || scratch_reads != 41518
            || scratch_writes != 19501
            || absorbed_blocks != 103672
            || retired_components != 81458)
            $fatal(1, "complete Sign counter mismatch cycles=%0d hash=%0d+%0d tree=%0d data=%0d inst=%0d scratch=%0d/%0d blocks=%0d components=%0d",
                   cycles, issued_hash_requests, tree_parent_hashes,
                   dut.issued_tree_requests, dut.issued_data_requests,
                   retired_instructions, scratch_reads, scratch_writes,
                   absorbed_blocks, retired_components);
        if (DUT_UNROLL == 2 && cycles != 1003278)
            $fatal(1, "K2U2 complete Sign cycle mismatch cycles=%0d", cycles);
        if (profile_feedback_read_hits != 1064
            || scratch_reads + profile_feedback_read_hits != 42582
            || profile_scratch_requests != 50023)
            $fatal(1, "feedback cache accounting mismatch hits=%0d physical_plus_hits=%0d requests=%0d",
                   profile_feedback_read_hits,
                   scratch_reads + profile_feedback_read_hits,
                   profile_scratch_requests);
        if (absorbed_blocks + tree_parent_hashes != 105641)
            $fatal(1, "complete Sign SHAKE accounting mismatch calls=%0d permutations=%0d",
                   issued_hash_requests + tree_parent_hashes,
                   absorbed_blocks + tree_parent_hashes);
        if (DUT_UNROLL == 2
            && (profile_pair_command_cycles != 745106
                || profile_pair_overlap_cycles != 607746
                || dut.composer.dual_service_cycles != 607746
                || dut.composer.lane1_active_cycles != 607746))
            $fatal(1, "dual lane overlap mismatch command=%0d overlap=%0d service=%0d lane1=%0d",
                   profile_pair_command_cycles, profile_pair_overlap_cycles,
                   dut.composer.dual_service_cycles,
                   dut.composer.lane1_active_cycles);
        if (profile_prefetch_hits != 40460
            || profile_prefetch_bubble_entries != 0
            || composer_state_cycles[20] != 0
            || profile_prefetch_validation_stalls != 0)
            $fatal(1, "component prefetch regression hits=%0d bubbles=%0d/%0d validation_stalls=%0d",
                   profile_prefetch_hits, profile_prefetch_bubble_entries,
                   composer_state_cycles[20],
                   profile_prefetch_validation_stalls);

        $display("PROFILE sequencer idle=%0d fetch=%0d run=%0d hash_req=%0d hash_wait=%0d bound_wait=%0d data_req=%0d data_wait=%0d tree_req=%0d tree_wait=%0d",
                 sequencer_state_cycles[0], sequencer_state_cycles[1],
                 sequencer_state_cycles[2], sequencer_state_cycles[3],
                 sequencer_state_cycles[4], sequencer_state_cycles[5],
                 sequencer_state_cycles[6], sequencer_state_cycles[7],
                 sequencer_state_cycles[8], sequencer_state_cycles[9]);
        $display("PROFILE composer idle=%0d layout_wait=%0d layout_product=%0d layout_validate=%0d hash_start=%0d contig_prep=%0d contig_req=%0d contig_wait=%0d comp_req=%0d comp_wait=%0d comp_product=%0d comp_validate=%0d src_a_req=%0d src_a_wait=%0d src_b_req=%0d src_b_wait=%0d emit_word=%0d block_send=%0d digest_wait=%0d write_req=%0d prefetch_wait=%0d",
                 composer_state_cycles[0], composer_state_cycles[1],
                 composer_state_cycles[2], composer_state_cycles[3],
                 composer_state_cycles[4], composer_state_cycles[5],
                 composer_state_cycles[6], composer_state_cycles[7],
                 composer_state_cycles[8], composer_state_cycles[9],
                 composer_state_cycles[10], composer_state_cycles[11],
                 composer_state_cycles[12], composer_state_cycles[13],
                 composer_state_cycles[14], composer_state_cycles[15],
                 composer_state_cycles[16], composer_state_cycles[17],
                 composer_state_cycles[18], composer_state_cycles[19],
                 composer_state_cycles[20]);
        $display("PROFILE prefetch hits=%0d bubble_entries=%0d bubble_cycles=%0d validation_stalls=%0d",
                 profile_prefetch_hits, profile_prefetch_bubble_entries,
                 composer_state_cycles[20],
                 profile_prefetch_validation_stalls);
        $display("PROFILE feedback read_hits=%0d",
                 profile_feedback_read_hits);
        $display("PROFILE dual pairs=%0d command=%0d service=%0d overlap=%0d lane0_active=%0d lane1_active=%0d",
                 dut.composer.dual_hash_pairs,
                 profile_pair_command_cycles,
                 dut.composer.dual_service_cycles,
                 profile_pair_overlap_cycles,
                 dut.composer.lane0_active_cycles,
                 dut.composer.lane1_active_cycles);
        $display("PROFILE tree_adapter idle=%0d ctx0_req=%0d ctx0_wait=%0d ctx1_req=%0d ctx1_wait=%0d start=%0d leaf0_req=%0d leaf0_wait=%0d leaf1_req=%0d leaf1_wait=%0d push=%0d settle=%0d root0=%0d root1=%0d response=%0d",
                 tree_adapter_state_cycles[0], tree_adapter_state_cycles[1],
                 tree_adapter_state_cycles[2], tree_adapter_state_cycles[3],
                 tree_adapter_state_cycles[4], tree_adapter_state_cycles[5],
                 tree_adapter_state_cycles[6], tree_adapter_state_cycles[7],
                 tree_adapter_state_cycles[8], tree_adapter_state_cycles[9],
                 tree_adapter_state_cycles[10], tree_adapter_state_cycles[11],
                 tree_adapter_state_cycles[12], tree_adapter_state_cycles[13],
                 tree_adapter_state_cycles[14]);
        $display("PROFILE treehash idle=%0d accept=%0d merge=%0d parent_req=%0d parent_wait=%0d abort=%0d emit_auth=%0d",
                 treehash_state_cycles[0], treehash_state_cycles[1],
                 treehash_state_cycles[2], treehash_state_cycles[3],
                 treehash_state_cycles[4], treehash_state_cycles[5],
                 treehash_state_cycles[6]);
        $display("PROFILE bitfield idle=%0d operands=%0d product=%0d launch=%0d wait=%0d error=%0d",
                 bitfield_state_cycles[0], bitfield_state_cycles[1],
                 bitfield_state_cycles[2], bitfield_state_cycles[3],
                 bitfield_state_cycles[4], bitfield_state_cycles[5]);
        $display("PROFILE data_engine idle=%0d lookup_req=%0d lookup_rsp=%0d addr_prep=%0d bind_req=%0d bind_rsp=%0d agu_req=%0d agu_rsp=%0d exec_start=%0d exec_wait=%0d response=%0d",
                 generic_data_state_cycles[0], generic_data_state_cycles[1],
                 generic_data_state_cycles[2], generic_data_state_cycles[3],
                 generic_data_state_cycles[4], generic_data_state_cycles[5],
                 generic_data_state_cycles[6], generic_data_state_cycles[7],
                 generic_data_state_cycles[8], generic_data_state_cycles[9],
                 generic_data_state_cycles[10]);
        $display("PROFILE busy generic=%0d bitfield=%0d expr=%0d base_w=%0d wide_shift=%0d tree=%0d dynamic_bound=%0d scratch_req=%0d scratch_rsp=%0d",
                 profile_generic_busy_cycles, profile_bitfield_busy_cycles,
                 profile_expr_busy_cycles, profile_base_w_busy_cycles,
                 profile_wide_shift_busy_cycles, profile_tree_busy_cycles,
                 profile_dynamic_bound_cycles, profile_scratch_requests,
                 profile_scratch_responses);

        $display("PASS no-DMA complete SLH-DSA Sign U=%0d cycles=%0d hash=%0d+%0d tree=%0d data=%0d inst=%0d scratch=%0d/%0d blocks=%0d+%0d components=%0d",
                 DUT_UNROLL, cycles, issued_hash_requests, tree_parent_hashes,
                 dut.issued_tree_requests,
                 dut.issued_data_requests, retired_instructions,
                 scratch_reads, scratch_writes, absorbed_blocks,
                 tree_parent_hashes,
                 retired_components);
        $finish;
    end
endmodule

`default_nettype wire
