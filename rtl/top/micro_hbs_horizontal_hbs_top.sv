`timescale 1ns/1ps
`default_nettype none

// Descriptor-driven horizontal HBS engine.  The sequencer only orders the
// five public macros; this module materializes one generic HASH, CHAIN, TREE,
// TRANSFORM, or EMIT operation at a time.  Algorithm names do not participate
// in the datapath control.
module micro_hbs_horizontal_hbs_top #(
    parameter integer UNROLL = 2,
    parameter integer MAX_MESSAGE_BYTES = 87,
    parameter integer PROGRAM_TOKENS = 384,
    parameter integer OUTPUT_BYTES = 17088,
    parameter bit REQUIRE_MESSAGE = 1'b1,
    parameter bit PROFILE_ENABLE = 1'b0,
    parameter bit SWAP_PHYSICAL_LANES = 1'b0,
    parameter TOKEN_INIT_FILE =
        "rtl/microcode/slh_dsa_128f_sign_macro_tokens.mem",
    parameter TEMPLATE_INIT_FILE =
        "rtl/microcode/slh_dsa_128f_sign_macro_templates.mem",
    parameter DESCRIPTOR_INIT_FILE =
        "rtl/microcode/slh_dsa_128f_sign_macro_descriptors.mem"
) (
    input  wire         clk,
    input  wire         rst_n,
    input  wire         job_valid,
    output wire         job_ready,
    input  wire [31:0]  job_message_length,
    input  wire [127:0] job_sk_seed,
    input  wire [127:0] job_sk_prf,
    input  wire [127:0] job_pk_seed,
    input  wire [127:0] job_pk_root,
    input  wire [127:0] job_opt_rand,
    input  wire         message_valid,
    output wire         message_ready,
    input  wire [63:0]  message_data,
    input  wire [7:0]   message_keep,
    input  wire         message_last,
    output wire         out_valid,
    input  wire         out_ready,
    output wire [63:0]  out_data,
    output wire [7:0]   out_keep,
    output wire         out_last,
    output wire         busy,
    output logic        done,
    output logic        error,
    output logic [15:0] error_code,
    output logic [31:0] hash_contexts,
    output logic [31:0] keccak_permutations,
    output logic [31:0] lane0_active_cycles,
    output logic [31:0] lane1_active_cycles
);
    localparam integer OUTPUT_BEATS = OUTPUT_BYTES / 8;
    localparam logic [15:0] ERR_MESSAGE    = 16'h2101;
    localparam logic [15:0] ERR_MACRO      = 16'h2102;
    localparam logic [15:0] ERR_DESCRIPTOR = 16'h2103;
    localparam logic [15:0] ERR_LANE       = 16'h2104;
    localparam logic [15:0] ERR_OUTPUT     = 16'h2105;

    localparam logic [3:0] MACRO_HASH      = 4'd1;
    localparam logic [3:0] MACRO_CHAIN     = 4'd2;
    localparam logic [3:0] MACRO_TREE      = 4'd3;
    localparam logic [3:0] MACRO_TRANSFORM = 4'd4;
    localparam logic [3:0] MACRO_EMIT      = 4'd5;

    localparam logic [3:0] DESC_HASH      = 4'd1;
    localparam logic [3:0] DESC_SEGMENT   = 4'd2;
    localparam logic [3:0] DESC_CHAIN     = 4'd4;
    localparam logic [3:0] DESC_TREE      = 4'd5;
    localparam logic [3:0] DESC_ROUTE     = 4'd6;
    localparam logic [3:0] DESC_ACTION    = 4'd7;
    localparam logic [3:0] DESC_TRANSFORM = 4'd8;
    localparam logic [3:0] DESC_EMIT      = 4'd9;

    localparam logic [3:0] SEG_JOB       = 4'd1;
    localparam logic [3:0] SEG_MESSAGE   = 4'd2;
    localparam logic [3:0] SEG_VALUE     = 4'd3;
    localparam logic [3:0] SEG_ADDRESS   = 4'd4;
    localparam logic [3:0] SEG_NODE_LEFT = 4'd5;
    localparam logic [3:0] SEG_NODE_RIGHT= 4'd6;
    localparam logic [3:0] SEG_ENDPOINTS = 4'd7;
    localparam logic [3:0] SEG_CONSTANT  = 4'd8;

    localparam logic [3:0] ACT_WRITE_VALUE = 4'd1;
    localparam logic [3:0] ACT_WRITE_SCALAR= 4'd2;
    localparam logic [3:0] ACT_EMIT_DIGEST = 4'd3;
    localparam logic [3:0] ACT_STORE_VALUE = 4'd4;
    localparam logic [3:0] ACT_SET_CURRENT = 4'd5;

    localparam logic [3:0] TRANSFORM_BASE_W = 4'd1;
    localparam logic [3:0] TRANSFORM_INDEX  = 4'd2;

    localparam logic [3:0] FLAG_CAPTURE       = 4'h1;
    localparam logic [3:0] FLAG_AUTH          = 4'h2;
    localparam logic [3:0] FLAG_EXTERNAL_ROOT = 4'h8;

    localparam logic [2:0] DEST_DIRECT = 3'd0;
    localparam logic [2:0] DEST_CHAIN  = 3'd1;
    localparam logic [2:0] DEST_LEAF   = 3'd2;
    localparam logic [2:0] DEST_PARENT = 3'd3;

    typedef enum logic [5:0] {
        S_IDLE, S_MESSAGE, S_FETCH, S_DECODE,
        S_HASH_CONTEXT, S_HASH_PREP, S_HASH_BLOCK, S_HASH_WAIT, S_HASH_COMMIT,
        S_TREE_INIT, S_TREE_CHAIN_SETUP, S_TREE_CHAIN_ADVANCE,
        S_TREE_LEAF_REDUCE, S_TREE_LEAF_ADVANCE, S_TREE_AUTH,
        S_TREE_PARENT_SETUP, S_TREE_PARENT_ADVANCE, S_TREE_FINISH,
        S_ROUTE, S_ROUTE_NEXT, S_TRANSFORM, S_TRANSFORM_WORK,
        S_EMIT, S_EMIT_ADVANCE, S_OUTPUT, S_DONE, S_ERROR
    } state_t;
    state_t state, output_return_state;

    (* rom_style = "distributed" *) logic [63:0]
        descriptor_memory [0:511];
    initial $readmemh(DESCRIPTOR_INIT_FILE, descriptor_memory);

    logic [31:0] message_length;
    logic [MAX_MESSAGE_BYTES*8-1:0] message_buffer;
    logic [7:0] message_received;
    logic [127:0] sk_seed, sk_prf, pk_seed, pk_root, opt_rand;
    logic [271:0] value_register [0:3];
    logic [63:0] scalar_tree;
    logic [2:0] scalar_leaf;
    logic [11:0] chain_checksum;
    logic [3:0] checksum_byte;

    logic sequencer_start, sequencer_task_done;
    wire sequencer_job_ready, sequencer_done, sequencer_busy;
    wire sequencer_error;
    wire [7:0] sequencer_error_code;
    wire lane0_command_valid, lane1_command_valid;
    wire [47:0] lane0_command, lane1_command;
    wire [2:0] lane0_event, lane1_event;
    wire command_ready = state == S_FETCH;

    logic [3:0] macro_code;
    logic [7:0] macro_descriptor, macro_route;
    logic [3:0] macro_flags;
    logic [23:0] macro_coordinate;
    wire [4:0] coordinate_layer = macro_coordinate[23:19];
    wire [5:0] coordinate_group = macro_coordinate[18:13];

    logic [7:0] task_recipe;
    logic [2:0] task_segment_count;
    logic [63:0] task_segment [0:3];
    logic [10:0] task_segment_start [0:3];
    logic [7:0] task_route;
    logic [1:0] active_mask, pending_mask;
    logic [2:0] task_destination;
    logic task_chain_enable, task_chain_prefix;
    logic task_chain_preserve;
    logic [2:0] task_chain_domain;
    logic [4:0] task_chain_count [0:1];
    logic task_capture [0:1];
    logic [4:0] task_capture_after [0:1];
    logic [4:0] task_layer;
    logic [63:0] task_tree;
    logic [7:0] task_address_type;
    logic [31:0] task_keypair [0:1];
    logic [31:0] task_word6 [0:1];
    logic [31:0] task_word7 [0:1];
    logic [127:0] task_left [0:1];
    logic [127:0] task_right [0:1];
    logic [5:0] task_store_address [0:1];
    logic [10:0] task_input_length;
    logic [2:0] task_blocks;
    logic [2:0] block_index;
    logic [3:0] append_beat;
    logic [271:0] result_digest [0:1];
    logic [127:0] result_capture [0:1];

    logic [7:0] tree_chain_id, tree_parent_recipe;
    logic [2:0] tree_height, tree_level;
    logic [7:0] tree_target_selector;
    logic [7:0] tree_leaf_mode, tree_keypair_mode;
    logic [3:0] tree_flags;
    logic [6:0] tree_leaf_count, tree_leaf_cursor;
    logic [6:0] tree_parent_count, tree_parent_cursor;
    logic [5:0] tree_target;
    logic [7:0] chain_endpoint_count;
    logic [4:0] chain_hash_count;
    logic [7:0] chain_reduce_recipe;
    logic [5:0] chain_cursor;
    logic standalone_chain;

    logic [7:0] route_action_base;
    logic [2:0] route_action_count, route_action_index;
    logic [271:0] route_result;
    logic [7:0] emit_segment_base;
    logic [3:0] emit_segment_count, emit_segment_index;

    logic [127:0] emit_word0, emit_word1;
    logic emit_two_words;
    logic [1:0] emit_beat;
    logic [11:0] output_address;

    logic node_write0_valid, node_write1_valid;
    logic [5:0] node_write0_address, node_write1_address;
    logic [127:0] node_write0_data, node_write1_data;
    logic [5:0] node_read0_address, node_read1_address;
    logic [5:0] node_read2_address, node_read3_address;
    wire [127:0] node_read0_data, node_read1_data;
    wire [127:0] node_read2_data, node_read3_data;
    logic endpoint_write0_valid, endpoint_write1_valid;
    logic [5:0] endpoint_write0_address, endpoint_write1_address;
    logic [127:0] endpoint_write0_data, endpoint_write1_data;
    logic [5:0] endpoint_read_address, endpoint_read1_address;
    wire [127:0] endpoint_read_data, endpoint_read1_data;

    wire [1:0] hash_context_ready, hash_block_ready;
    wire [1:0] hash_response_valid, hash_capture_valid, hash_error;
    wire [271:0] hash_response_digest [0:1];
    wire [127:0] hash_capture_digest [0:1];
    logic [127:0] hash_block_data [0:1];
    logic [127:0] prepared_block_data [0:1];
    wire contexts_fire = &(~active_mask | hash_context_ready);
    wire blocks_fire = &(~active_mask | hash_block_ready);

    integer byte_index;
    integer lane_index;
    integer compose_lane;
    integer segment_index;
    integer absolute_byte;
    integer local_offset;
    integer segment_start;
    integer segment_length;
    integer setup_scan, setup_total;
    reg [63:0] descriptor_work;
    reg [63:0] macro_chain_work;
    reg [63:0] tree_chain_work;
    reg [63:0] action_work;
    reg [7:0] setup_recipe;
    reg [63:0] setup_hash_work;
    reg [63:0] setup_address_work;
    reg [63:0] setup_segment_work [0:3];
    reg [10:0] setup_segment_start_work [0:3];
    reg [10:0] setup_input_length;
    reg [63:0] compose_segment0;
    integer compose_segment0_start;
    reg [63:0] emit_segment_work;

    function automatic [31:0] pack_be32(input [31:0] value);
        pack_be32 = {value[7:0], value[15:8], value[23:16], value[31:24]};
    endfunction

    function automatic [7:0] vector_byte(
        input [271:0] value, input integer index
    );
        vector_byte = value[index*8 +: 8];
    endfunction

    function automatic [7:0] key_byte(
        input [127:0] value, input integer index
    );
        key_byte = value[index*8 +: 8];
    endfunction

    function automatic [4:0] chain_digit(input integer digit_index);
        reg [7:0] octet;
        begin
            if (digit_index < 32) begin
                octet = vector_byte(value_register[2], digit_index >> 1);
                chain_digit = digit_index[0]
                    ? {1'b0, octet[3:0]} : {1'b0, octet[7:4]};
            end else begin
                case (digit_index)
                    32: chain_digit = chain_checksum[11:8];
                    33: chain_digit = chain_checksum[7:4];
                    default: chain_digit = chain_checksum[3:0];
                endcase
            end
        end
    endfunction

    function automatic [5:0] bitfield_target(input [5:0] group);
        integer bit_number;
        integer target_value;
        begin
            target_value = 0;
            for (bit_number = 0; bit_number < 6; bit_number = bit_number + 1)
                target_value = (target_value << 1)
                    | value_register[1][8*(((group*6)+bit_number)>>3)
                        + 7-(((group*6)+bit_number)&7)];
            bitfield_target = target_value[5:0];
        end
    endfunction

    function automatic [7:0] address_byte(
        input integer lane_number, input integer index
    );
        reg [31:0] address_word;
        begin
            case (index >> 2)
                0: address_word = task_layer;
                1: address_word = 0;
                2: address_word = task_tree[63:32];
                3: address_word = task_tree[31:0];
                4: address_word = task_address_type;
                5: address_word = task_keypair[lane_number];
                6: address_word = task_word6[lane_number];
                default: address_word = task_word7[lane_number];
            endcase
            case (index & 3)
                0: address_byte = address_word[31:24];
                1: address_byte = address_word[23:16];
                2: address_byte = address_word[15:8];
                default: address_byte = address_word[7:0];
            endcase
        end
    endfunction

    function automatic [127:0] segment_window(
        input integer lane_number,
        input [63:0] segment_word,
        input integer segment_offset_value
    );
        reg [3:0] kind;
        reg [3:0] selector;
        begin
            kind = segment_word[59:56];
            selector = segment_word[55:52];
            case (kind)
                SEG_JOB: case (selector)
                    0: segment_window = sk_seed;
                    1: segment_window = sk_prf;
                    2: segment_window = pk_seed;
                    3: segment_window = pk_root;
                    default: segment_window = opt_rand;
                endcase
                SEG_MESSAGE: case (segment_offset_value >> 4)
                    0: segment_window = message_buffer[0 +: 128];
                    1: segment_window = message_buffer[128 +: 128];
                    2: segment_window = message_buffer[256 +: 128];
                    3: segment_window = message_buffer[384 +: 128];
                    4: segment_window = message_buffer[512 +: 128];
                    default: segment_window = {
                        72'd0, message_buffer[640 +: 56]};
                endcase
                SEG_VALUE:
                    segment_window = value_register[selector[1:0]][127:0];
                SEG_ADDRESS: if (segment_offset_value < 16)
                    segment_window = {
                        pack_be32(task_tree[31:0]),
                        pack_be32(task_tree[63:32]),
                        32'd0, pack_be32(task_layer)};
                else
                    segment_window = {
                        pack_be32(task_word7[lane_number]),
                        pack_be32(task_word6[lane_number]),
                        pack_be32(task_keypair[lane_number]),
                        pack_be32(task_address_type)};
                SEG_NODE_LEFT:
                    segment_window = task_left[lane_number];
                SEG_NODE_RIGHT:
                    segment_window = task_right[lane_number];
                SEG_ENDPOINTS: begin
                    if (segment_offset_value[3])
                        segment_window = {endpoint_read1_data[63:0],
                                          endpoint_read_data[127:64]};
                    else
                        segment_window = endpoint_read_data;
                end
                SEG_CONSTANT: segment_window = {
                    4{segment_word[31:0]}};
                default: segment_window = 0;
            endcase
        end
    endfunction

    function automatic [127:0] compose_beat(
        input integer lane_number, input [2:0] rate_block,
        input [3:0] beat_number
    );
        integer position;
        integer global_byte;
        reg [127:0] result;
        begin
            global_byte = rate_block*136 + beat_number*16;
            result = segment_window(lane_number, compose_segment0,
                                    global_byte-compose_segment0_start);
            for (position = 0; position < 16; position = position + 1) begin
                if (global_byte+position > task_input_length)
                    result[position*8 +: 8] = 0;
                else if (global_byte+position == task_input_length)
                    result[position*8 +: 8] = 8'h1f;
            end
            if (rate_block == task_blocks-1 && beat_number == 8)
                result[63] = 1'b1;
            compose_beat = result;
        end
    endfunction

    function automatic [127:0] emit_source_word(input [63:0] segment_word);
        reg [3:0] kind;
        reg [3:0] selector;
        begin
            kind = segment_word[59:56];
            selector = segment_word[55:52];
            case (kind)
                SEG_JOB: case (selector)
                    0: emit_source_word = sk_seed;
                    1: emit_source_word = sk_prf;
                    2: emit_source_word = pk_seed;
                    3: emit_source_word = pk_root;
                    default: emit_source_word = opt_rand;
                endcase
                SEG_VALUE: emit_source_word = value_register[selector][127:0];
                default: emit_source_word = 0;
            endcase
        end
    endfunction

    always_comb begin
        setup_recipe = task_recipe;
        case (state)
            S_DECODE: if (macro_code == MACRO_HASH)
                setup_recipe = macro_descriptor;
            S_TREE_CHAIN_SETUP: setup_recipe = tree_chain_work[59:52];
            S_TREE_LEAF_REDUCE: setup_recipe = chain_reduce_recipe;
            S_TREE_PARENT_SETUP: setup_recipe = tree_parent_recipe;
            default: begin end
        endcase
        setup_hash_work = descriptor_memory[setup_recipe];
        setup_address_work = descriptor_memory[setup_hash_work[47:40]];
        setup_total = 0;
        for (setup_scan = 0; setup_scan < 4; setup_scan = setup_scan + 1) begin
            setup_segment_start_work[setup_scan] = setup_total[10:0];
            setup_segment_work[setup_scan] = descriptor_memory[
                setup_hash_work[59:52]+setup_scan];
            if (setup_scan < setup_hash_work[51:48]) begin
                if (setup_segment_work[setup_scan][59:56] == SEG_MESSAGE)
                    setup_total = setup_total + message_length;
                else if (setup_segment_work[setup_scan][59:56]
                            == SEG_ENDPOINTS)
                    setup_total = setup_total
                        + setup_segment_work[setup_scan][23:0]*16;
                else
                    setup_total = setup_total
                        + setup_segment_work[setup_scan][51:40];
            end
        end
        setup_input_length = setup_total[10:0];

        absolute_byte = block_index*136 + append_beat*16;
        compose_segment0 = task_segment[0];
        compose_segment0_start = task_segment_start[0];
        if (task_segment_count > 3
                && absolute_byte >= task_segment_start[3]) begin
            compose_segment0 = task_segment[3];
            compose_segment0_start = task_segment_start[3];
        end else if (task_segment_count > 2
                && absolute_byte >= task_segment_start[2]) begin
            compose_segment0 = task_segment[2];
            compose_segment0_start = task_segment_start[2];
        end else if (task_segment_count > 1
                && absolute_byte >= task_segment_start[1]) begin
            compose_segment0 = task_segment[1];
            compose_segment0_start = task_segment_start[1];
        end

        endpoint_read_address = compose_segment0[59:56] == SEG_ENDPOINTS
            ? (absolute_byte-compose_segment0_start) >> 4 : 0;
        endpoint_read1_address = endpoint_read_address + 1'b1;
    end

    always_comb begin
        hash_block_data[0] = compose_beat(0, block_index, append_beat);
        if (compose_segment0[59:56] == SEG_ADDRESS
                || compose_segment0[59:56] == SEG_NODE_LEFT
                || compose_segment0[59:56] == SEG_NODE_RIGHT)
            hash_block_data[1] = compose_beat(1, block_index, append_beat);
        else
            hash_block_data[1] = hash_block_data[0];
    end

    micro_hbs_static_task_sequencer #(
        .PROGRAM_TOKENS(PROGRAM_TOKENS),
        .TOKEN_INIT_FILE(TOKEN_INIT_FILE),
        .TEMPLATE_INIT_FILE(TEMPLATE_INIT_FILE)
    ) macro_sequencer (
        .clk, .rst_n, .job_valid(sequencer_start), .job_entry(9'd0),
        .job_ready(sequencer_job_ready), .done(sequencer_done),
        .busy(sequencer_busy), .error(sequencer_error),
        .error_code(sequencer_error_code),
        .lane0_valid(lane0_command_valid), .lane0_ready(command_ready),
        .lane0_command, .lane0_event,
        .lane1_valid(lane1_command_valid), .lane1_ready(command_ready),
        .lane1_command, .lane1_event,
        .lane0_done_valid(sequencer_task_done), .lane0_done_event(3'd0),
        .lane1_done_valid(1'b0), .lane1_done_event(3'd0),
        .program_counter(), .pending_events(),
        .retired_words(), .retired_tokens()
    );

    genvar physical_lane;
    generate for (physical_lane = 0; physical_lane < 2;
                  physical_lane = physical_lane + 1) begin : lanes
        localparam integer LOGICAL_LANE = SWAP_PHYSICAL_LANES
            ? 1-physical_lane : physical_lane;
        (* keep_hierarchy = "yes" *)
        micro_hbs_compact_shake_context_lane #(.UNROLL(UNROLL)) lane (
            .clk, .rst_n,
            .context_valid(state == S_HASH_CONTEXT
                && active_mask[LOGICAL_LANE]),
            .context_ready(hash_context_ready[LOGICAL_LANE]),
            .fast_block_valid(1'b0), .fast_block_ready(),
            .fast_block_data(1088'b0),
            .chain_enable(task_chain_enable),
            .chain_prefix(task_chain_prefix),
            .chain_prefix_preserve_counter(task_chain_preserve),
            .chain_prefix_domain(task_chain_domain),
            .chain_count(task_chain_count[LOGICAL_LANE]),
            .capture_enable(task_capture[LOGICAL_LANE]),
            .capture_after(task_capture_after[LOGICAL_LANE]),
            .block_valid(state == S_HASH_BLOCK
                && active_mask[LOGICAL_LANE]),
            .block_ready(hash_block_ready[LOGICAL_LANE]),
            .block_data(prepared_block_data[LOGICAL_LANE]),
            .block_last(block_index == task_blocks-1),
            .response_valid(hash_response_valid[LOGICAL_LANE]),
            .response_digest(hash_response_digest[LOGICAL_LANE]),
            .finish_valid(), .finish_digest(),
            .capture_digest(hash_capture_digest[LOGICAL_LANE]),
            .capture_valid(hash_capture_valid[LOGICAL_LANE]),
            .error(hash_error[LOGICAL_LANE])
        );
    end endgenerate

    micro_hbs_local_array128_4r node_store (
        .clk,
        .write0_valid(node_write0_valid),
        .write0_address(node_write0_address), .write0_data(node_write0_data),
        .write1_valid(node_write1_valid),
        .write1_address(node_write1_address), .write1_data(node_write1_data),
        .read0_address(node_read0_address), .read0_data(node_read0_data),
        .read1_address(node_read1_address), .read1_data(node_read1_data),
        .read2_address(node_read2_address), .read2_data(node_read2_data),
        .read3_address(node_read3_address), .read3_data(node_read3_data)
    );

    micro_hbs_local_array128_4r endpoint_store (
        .clk,
        .write0_valid(endpoint_write0_valid),
        .write0_address(endpoint_write0_address),
        .write0_data(endpoint_write0_data),
        .write1_valid(endpoint_write1_valid),
        .write1_address(endpoint_write1_address),
        .write1_data(endpoint_write1_data),
        .read0_address(endpoint_read_address), .read0_data(endpoint_read_data),
        .read1_address(endpoint_read1_address),
        .read1_data(endpoint_read1_data),
        .read2_address(6'd0), .read2_data(),
        .read3_address(6'd0), .read3_data()
    );

    assign job_ready = state == S_IDLE;
    assign message_ready = REQUIRE_MESSAGE && state == S_MESSAGE
        && message_received < message_length;
    assign busy = state != S_IDLE;
    assign out_valid = state == S_OUTPUT;
    assign out_data = emit_beat == 0 ? emit_word0[63:0]
        : emit_beat == 1 ? emit_word0[127:64]
        : emit_beat == 2 ? emit_word1[63:0] : emit_word1[127:64];
    assign out_keep = 8'hff;
    assign out_last = output_address == OUTPUT_BEATS-1;

    always_comb begin
        node_read0_address = 0;
        node_read1_address = 1;
        node_read2_address = 2;
        node_read3_address = 3;
        if (state == S_TREE_PARENT_SETUP) begin
            node_read0_address = tree_parent_cursor << 1;
            node_read1_address = (tree_parent_cursor << 1) + 1'b1;
            node_read2_address = (tree_parent_cursor << 1) + 2;
            node_read3_address = (tree_parent_cursor << 1) + 3;
        end else if (state == S_TREE_AUTH) begin
            node_read0_address = (tree_target >> (tree_level-1)) ^ 1'b1;
        end

        node_write0_valid = 0;
        node_write1_valid = 0;
        node_write0_address = task_store_address[0];
        node_write1_address = task_store_address[1];
        node_write0_data = result_digest[0][127:0];
        node_write1_data = result_digest[1][127:0];
        endpoint_write0_valid = 0;
        endpoint_write1_valid = 0;
        endpoint_write0_address = task_store_address[0];
        endpoint_write1_address = task_store_address[1];
        endpoint_write0_data = result_digest[0][127:0];
        endpoint_write1_data = result_digest[1][127:0];

        if (state == S_HASH_COMMIT) begin
            if (task_destination == DEST_CHAIN) begin
                endpoint_write0_valid = active_mask[0]
                    && chain_endpoint_count != 1;
                endpoint_write1_valid = active_mask[1]
                    && chain_endpoint_count != 1;
                if (chain_endpoint_count == 1) begin
                    node_write0_valid = active_mask[0];
                    node_write0_address = tree_leaf_cursor[5:0];
                end
            end else if (task_destination == DEST_LEAF) begin
                node_write0_valid = 1'b1;
                node_write0_address = tree_leaf_cursor[5:0];
            end else if (task_destination == DEST_PARENT) begin
                node_write0_valid = active_mask[0];
                node_write1_valid = active_mask[1];
            end
        end
        if (state == S_ROUTE && action_work[59:56] == ACT_STORE_VALUE) begin
            endpoint_write0_valid = 1'b1;
            endpoint_write0_address = coordinate_group;
            endpoint_write0_data = route_result[127:0];
        end
    end

    task automatic fail(input [15:0] code);
        begin
            error <= 1'b1;
            error_code <= code;
            state <= S_ERROR;
        end
    endtask

    task automatic start_output(
        input [127:0] word0,
        input [127:0] word1,
        input logic two_words,
        input state_t return_state
    );
        begin
            emit_word0 <= word0;
            emit_word1 <= word1;
            emit_two_words <= two_words;
            emit_beat <= 0;
            output_return_state <= return_state;
            state <= S_OUTPUT;
        end
    endtask

    task automatic complete_macro;
        begin
            sequencer_task_done <= 1'b1;
            state <= S_FETCH;
        end
    endtask

    task automatic begin_route(
        input [7:0] route_id, input [271:0] digest
    );
        reg [63:0] route_word;
        begin
            if (route_id == 0) begin
                sequencer_task_done <= 1'b1;
                state <= S_FETCH;
            end else begin
                route_word = descriptor_memory[route_id];
                if (route_word[63:60] != DESC_ROUTE)
                    fail(ERR_DESCRIPTOR);
                else begin
                    task_route <= route_id;
                    route_action_base <= route_word[59:52];
                    route_action_count <= route_word[50:48];
                    route_action_index <= 0;
                    route_result <= digest;
                    state <= S_ROUTE;
                end
            end
        end
    endtask

    always_comb begin
        descriptor_work = descriptor_memory[macro_descriptor];
        macro_chain_work = descriptor_memory[descriptor_work[59:52]];
        tree_chain_work = descriptor_memory[tree_chain_id];
        action_work = descriptor_memory[
            route_action_base + route_action_index];
        emit_segment_work = descriptor_memory[
            emit_segment_base + emit_segment_index];
    end

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= S_IDLE;
            done <= 0;
            error <= 0;
            error_code <= 0;
            sequencer_start <= 0;
            sequencer_task_done <= 0;
            message_length <= 0;
            message_received <= 0;
            scalar_tree <= 0;
            scalar_leaf <= 0;
            chain_checksum <= 0;
            checksum_byte <= 0;
            macro_code <= 0;
            macro_descriptor <= 0;
            macro_route <= 0;
            macro_flags <= 0;
            macro_coordinate <= 0;
            active_mask <= 0;
            pending_mask <= 0;
            task_recipe <= 0;
            task_segment_count <= 0;
            task_route <= 0;
            task_destination <= 0;
            task_chain_enable <= 0;
            task_chain_prefix <= 0;
            task_chain_preserve <= 0;
            task_chain_domain <= 0;
            task_input_length <= 0;
            task_blocks <= 0;
            block_index <= 0;
            append_beat <= 0;
            tree_chain_id <= 0;
            tree_parent_recipe <= 0;
            tree_height <= 0;
            tree_level <= 0;
            tree_target_selector <= 0;
            tree_leaf_mode <= 0;
            tree_keypair_mode <= 0;
            tree_flags <= 0;
            tree_leaf_count <= 0;
            tree_leaf_cursor <= 0;
            tree_parent_count <= 0;
            tree_parent_cursor <= 0;
            tree_target <= 0;
            chain_endpoint_count <= 0;
            chain_hash_count <= 0;
            chain_reduce_recipe <= 0;
            chain_cursor <= 0;
            standalone_chain <= 0;
            route_action_base <= 0;
            route_action_count <= 0;
            route_action_index <= 0;
            emit_segment_base <= 0;
            emit_segment_count <= 0;
            emit_segment_index <= 0;
            emit_two_words <= 0;
            emit_beat <= 0;
            output_address <= 0;
            hash_contexts <= 0;
            keccak_permutations <= 0;
            lane0_active_cycles <= 0;
            lane1_active_cycles <= 0;
            for (lane_index = 0; lane_index < 2; lane_index = lane_index + 1) begin
                task_chain_count[lane_index] <= 1;
                task_capture[lane_index] <= 0;
                task_capture_after[lane_index] <= 0;
                task_keypair[lane_index] <= 0;
                task_word6[lane_index] <= 0;
                task_word7[lane_index] <= 0;
                task_store_address[lane_index] <= 0;
                result_digest[lane_index] <= 0;
                result_capture[lane_index] <= 0;
            end
            for (segment_index = 0; segment_index < 4;
                 segment_index = segment_index + 1) begin
                task_segment[segment_index] <= 0;
                task_segment_start[segment_index] <= 0;
            end
        end else begin
            done <= 0;
            sequencer_start <= 0;
            sequencer_task_done <= 0;
            if (PROFILE_ENABLE) begin
                if (state != S_IDLE && active_mask[0])
                    lane0_active_cycles <= lane0_active_cycles + 1'b1;
                if (state != S_IDLE && active_mask[1])
                    lane1_active_cycles <= lane1_active_cycles + 1'b1;
            end
            if (|hash_error)
                fail(ERR_LANE);
            else if (sequencer_error)
                fail({8'h22, sequencer_error_code});
            else case (state)
                S_IDLE: if (job_valid) begin
                    if (REQUIRE_MESSAGE && (job_message_length == 0
                            || job_message_length > MAX_MESSAGE_BYTES))
                        fail(ERR_MESSAGE);
                    else begin
                        message_length <= REQUIRE_MESSAGE
                            ? job_message_length : 0;
                        message_received <= 0;
                        sk_seed <= job_sk_seed;
                        sk_prf <= job_sk_prf;
                        pk_seed <= job_pk_seed;
                        pk_root <= job_pk_root;
                        opt_rand <= job_opt_rand;
                        output_address <= 0;
                        error <= 0;
                        error_code <= 0;
                        hash_contexts <= 0;
                        keccak_permutations <= 0;
                        lane0_active_cycles <= 0;
                        lane1_active_cycles <= 0;
                        if (REQUIRE_MESSAGE)
                            state <= S_MESSAGE;
                        else begin
                            sequencer_start <= 1'b1;
                            state <= S_FETCH;
                        end
                    end
                end
                S_MESSAGE: if (message_valid && message_ready) begin
                    for (byte_index = 0; byte_index < 8;
                         byte_index = byte_index + 1)
                        if (message_keep[byte_index])
                            message_buffer[(message_received+byte_index)*8 +: 8]
                                <= message_data[byte_index*8 +: 8];
                    message_received <= message_received
                        + message_keep[0] + message_keep[1]
                        + message_keep[2] + message_keep[3]
                        + message_keep[4] + message_keep[5]
                        + message_keep[6] + message_keep[7];
                    if (message_last) begin
                        if (message_received
                                + message_keep[0] + message_keep[1]
                                + message_keep[2] + message_keep[3]
                                + message_keep[4] + message_keep[5]
                                + message_keep[6] + message_keep[7]
                                != message_length)
                            fail(ERR_MESSAGE);
                        else begin
                            sequencer_start <= 1'b1;
                            state <= S_FETCH;
                        end
                    end
                end
                S_FETCH: begin
                    if (sequencer_done) begin
                        if (output_address != OUTPUT_BEATS)
                            fail(ERR_OUTPUT);
                        else state <= S_DONE;
                    end else if (lane0_command_valid && command_ready) begin
                        if (lane1_command_valid
                                && (lane1_command[47:36]
                                    != lane0_command[47:36]))
                            fail(ERR_MACRO);
                        else begin
                            macro_code <= lane0_command[47:44];
                            macro_descriptor <= lane0_command[43:36];
                            macro_route <= lane0_command[35:28];
                            macro_flags <= lane0_command[27:24];
                            macro_coordinate <= lane0_command[23:0];
                            state <= S_DECODE;
                        end
                    end
                end
                S_DECODE: case (macro_code)
                    MACRO_HASH: begin
                        if (descriptor_work[63:60] != DESC_HASH)
                            fail(ERR_DESCRIPTOR);
                        else begin
                            task_recipe <= macro_descriptor;
                            task_route <= macro_route;
                            task_destination <= DEST_DIRECT;
                            active_mask <= 2'b01;
                            task_chain_enable <= 0;
                            task_chain_prefix <= 0;
                            task_chain_preserve <= 0;
                            task_chain_domain <= 0;
                            task_chain_count[0] <= 1;
                            task_capture[0] <= 0;
                            task_layer <= coordinate_layer;
                            task_tree <= scalar_tree;
                            task_keypair[0] <= scalar_leaf;
                            task_word6[0] <= 0;
                            task_word7[0] <= 0;
                            task_left[0] <= 0;
                            task_right[0] <= 0;
                            task_segment_count <= setup_hash_work[50:48];
                            for (segment_index = 0; segment_index < 4;
                                 segment_index = segment_index + 1)
                                task_segment[segment_index]
                                    <= setup_segment_work[segment_index];
                            for (segment_index = 0; segment_index < 4;
                                 segment_index = segment_index + 1)
                                task_segment_start[segment_index]
                                    <= setup_segment_start_work[segment_index];
                            task_input_length <= setup_input_length;
                            task_blocks <= setup_hash_work[30:28];
                            task_address_type <= setup_address_work[19:12];
                            block_index <= 0;
                            state <= S_HASH_CONTEXT;
                        end
                    end
                    MACRO_CHAIN: begin
                        if (descriptor_work[63:60] != DESC_CHAIN)
                            fail(ERR_DESCRIPTOR);
                        else begin
                            // CHAIN is the same iterator used by TREE leaves,
                            // with one synthetic leaf and a route at its end.
                            standalone_chain <= 1'b1;
                            tree_chain_id <= macro_descriptor;
                            tree_target_selector <= macro_flags[2:1];
                            tree_leaf_mode <= 0;
                            tree_keypair_mode <= 0;
                            tree_flags <= macro_flags;
                            tree_leaf_count <= 1;
                            tree_leaf_cursor <= 0;
                            tree_target <= 0;
                            chain_cursor <= 0;
                            chain_endpoint_count <= descriptor_work[51:44];
                            chain_hash_count <= descriptor_work[43:39];
                            task_chain_domain <= descriptor_work[38:36];
                            task_chain_preserve <= descriptor_work[35];
                            chain_reduce_recipe <= descriptor_work[34:27];
                            state <= S_TREE_CHAIN_SETUP;
                        end
                    end
                    MACRO_TREE: begin
                        if (descriptor_work[63:60] != DESC_TREE)
                            fail(ERR_DESCRIPTOR);
                        else state <= S_TREE_INIT;
                    end
                    MACRO_TRANSFORM: begin
                        if (descriptor_work[63:60] != DESC_TRANSFORM)
                            fail(ERR_DESCRIPTOR);
                        else state <= S_TRANSFORM;
                    end
                    MACRO_EMIT: begin
                        if (descriptor_work[63:60] != DESC_EMIT)
                            fail(ERR_DESCRIPTOR);
                        else begin
                            emit_segment_base <= descriptor_work[59:52];
                            emit_segment_count <= descriptor_work[51:48];
                            emit_segment_index <= 0;
                            state <= S_EMIT;
                        end
                    end
                    default: fail(ERR_MACRO);
                endcase
                S_TREE_INIT: begin
                    standalone_chain <= 1'b0;
                    tree_chain_id <= descriptor_work[59:52];
                    tree_height <= descriptor_work[50:48];
                    tree_parent_recipe <= descriptor_work[47:40];
                    tree_target_selector <= descriptor_work[39:32];
                    tree_leaf_mode <= descriptor_work[31:24];
                    tree_keypair_mode <= descriptor_work[23:16];
                    tree_flags <= macro_flags;
                    tree_leaf_count <= 1 << descriptor_work[50:48];
                    tree_leaf_cursor <= 0;
                    chain_cursor <= 0;
                    if (descriptor_work[39:32] == 1)
                        tree_target <= bitfield_target(coordinate_group);
                    else
                        tree_target <= scalar_leaf;
                    if (macro_chain_work[63:60] != DESC_CHAIN)
                        fail(ERR_DESCRIPTOR);
                    else begin
                        chain_endpoint_count <= macro_chain_work[51:44];
                        chain_hash_count <= macro_chain_work[43:39];
                        task_chain_domain <= macro_chain_work[38:36];
                        task_chain_preserve <= macro_chain_work[35];
                        chain_reduce_recipe <= macro_chain_work[34:27];
                        state <= S_TREE_CHAIN_SETUP;
                    end
                end
                S_TREE_CHAIN_SETUP: begin
                    task_recipe <= tree_chain_work[59:52];
                    task_route <= 0;
                    task_destination <= DEST_CHAIN;
                    active_mask[0] <= 1'b1;
                    active_mask[1] <= chain_cursor+1 < chain_endpoint_count;
                    task_chain_enable <= 1'b1;
                    task_chain_prefix <= 1'b1;
                    task_layer <= coordinate_layer;
                    task_tree <= scalar_tree;
                    task_segment_count <= setup_hash_work[50:48];
                    for (segment_index = 0; segment_index < 4;
                         segment_index = segment_index + 1)
                        task_segment[segment_index]
                            <= setup_segment_work[segment_index];
                    for (segment_index = 0; segment_index < 4;
                         segment_index = segment_index + 1)
                        task_segment_start[segment_index]
                            <= setup_segment_start_work[segment_index];
                    task_input_length <= setup_input_length;
                    task_blocks <= setup_hash_work[30:28];
                    task_address_type <= setup_address_work[19:12];
                    for (lane_index = 0; lane_index < 2;
                         lane_index = lane_index + 1) begin
                        task_keypair[lane_index] <= tree_keypair_mode == 1
                            ? scalar_leaf : tree_leaf_cursor;
                        task_word6[lane_index] <= chain_cursor + lane_index;
                        task_word7[lane_index] <= tree_leaf_mode == 1
                            ? coordinate_group*64 + tree_leaf_cursor : 0;
                        task_store_address[lane_index]
                            <= chain_cursor + lane_index;
                        task_capture[lane_index] <= tree_leaf_cursor == tree_target
                            && (tree_flags & FLAG_CAPTURE) != 0;
                        task_capture_after[lane_index]
                            <= tree_target_selector == 1 ? 1
                            : chain_digit(chain_cursor+lane_index) + 1'b1;
                        if (tree_leaf_cursor == tree_target
                                && (tree_flags & FLAG_EXTERNAL_ROOT) != 0)
                            task_chain_count[lane_index]
                                <= chain_digit(chain_cursor+lane_index) + 1'b1;
                        else
                            task_chain_count[lane_index] <= chain_hash_count;
                    end
                    block_index <= 0;
                    state <= S_HASH_CONTEXT;
                end
                S_TREE_CHAIN_ADVANCE: begin
                    if (chain_cursor + active_mask[0] + active_mask[1]
                            < chain_endpoint_count) begin
                        chain_cursor <= chain_cursor + 2;
                        state <= S_TREE_CHAIN_SETUP;
                    end else if (chain_reduce_recipe != 0
                            && !(tree_leaf_cursor == tree_target
                                && (tree_flags & FLAG_EXTERNAL_ROOT) != 0))
                        state <= S_TREE_LEAF_REDUCE;
                    else if (standalone_chain)
                        begin_route(macro_route, result_digest[0]);
                    else
                        state <= S_TREE_LEAF_ADVANCE;
                end
                S_TREE_LEAF_REDUCE: begin
                    task_recipe <= chain_reduce_recipe;
                    task_route <= standalone_chain ? macro_route : 0;
                    task_destination <= standalone_chain
                        ? DEST_DIRECT : DEST_LEAF;
                    active_mask <= 2'b01;
                    task_chain_enable <= 0;
                    task_chain_prefix <= 0;
                    task_chain_count[0] <= 1;
                    task_capture[0] <= 0;
                    task_layer <= coordinate_layer;
                    task_tree <= scalar_tree;
                    task_keypair[0] <= tree_leaf_cursor;
                    task_word6[0] <= 0;
                    task_word7[0] <= 0;
                    task_segment_count <= setup_hash_work[50:48];
                    for (segment_index = 0; segment_index < 4;
                         segment_index = segment_index + 1)
                        task_segment[segment_index]
                            <= setup_segment_work[segment_index];
                    for (segment_index = 0; segment_index < 4;
                         segment_index = segment_index + 1)
                        task_segment_start[segment_index]
                            <= setup_segment_start_work[segment_index];
                    task_input_length <= setup_input_length;
                    task_blocks <= setup_hash_work[30:28];
                    task_address_type <= setup_address_work[19:12];
                    block_index <= 0;
                    state <= S_HASH_CONTEXT;
                end
                S_TREE_LEAF_ADVANCE: begin
                    if (tree_leaf_cursor + 1 < tree_leaf_count) begin
                        tree_leaf_cursor <= tree_leaf_cursor + 1'b1;
                        chain_cursor <= 0;
                        state <= S_TREE_CHAIN_SETUP;
                    end else begin
                        tree_level <= 1;
                        tree_parent_count <= tree_leaf_count >> 1;
                        tree_parent_cursor <= 0;
                        state <= S_TREE_AUTH;
                    end
                end
                S_TREE_AUTH: begin
                    if ((tree_flags & FLAG_AUTH) != 0)
                        start_output(node_read0_data, 0, 1'b0,
                                     S_TREE_PARENT_SETUP);
                    else state <= S_TREE_PARENT_SETUP;
                end
                S_TREE_PARENT_SETUP: begin
                    active_mask[0] <= !((tree_flags & FLAG_EXTERNAL_ROOT) != 0
                        && tree_parent_cursor
                            == (tree_target >> tree_level));
                    active_mask[1] <= tree_parent_cursor+1 < tree_parent_count
                        && !((tree_flags & FLAG_EXTERNAL_ROOT) != 0
                            && tree_parent_cursor+1
                                == (tree_target >> tree_level));
                    if (((tree_flags & FLAG_EXTERNAL_ROOT) != 0)
                            && tree_parent_cursor
                                == (tree_target >> tree_level)
                            && (tree_parent_cursor+1 >= tree_parent_count
                                || tree_parent_cursor+1
                                    == (tree_target >> tree_level))) begin
                        state <= S_TREE_PARENT_ADVANCE;
                    end else begin
                        task_recipe <= tree_parent_recipe;
                        task_route <= 0;
                        task_destination <= DEST_PARENT;
                        task_chain_enable <= 0;
                        task_chain_prefix <= 0;
                        task_chain_count[0] <= 1;
                        task_chain_count[1] <= 1;
                        task_capture[0] <= 0;
                        task_capture[1] <= 0;
                        task_layer <= coordinate_layer;
                        task_tree <= scalar_tree;
                        task_segment_count <= setup_hash_work[50:48];
                        for (segment_index = 0; segment_index < 4;
                             segment_index = segment_index + 1)
                            task_segment[segment_index]
                                <= setup_segment_work[segment_index];
                        for (segment_index = 0; segment_index < 4;
                             segment_index = segment_index + 1)
                            task_segment_start[segment_index]
                                <= setup_segment_start_work[segment_index];
                        task_input_length <= setup_input_length;
                        task_blocks <= setup_hash_work[30:28];
                        task_address_type <= setup_address_work[19:12];
                        for (lane_index = 0; lane_index < 2;
                             lane_index = lane_index + 1) begin
                            task_keypair[lane_index] <= tree_keypair_mode == 1
                                ? scalar_leaf : 0;
                            task_word6[lane_index] <= tree_level;
                            task_word7[lane_index] <= tree_leaf_mode == 1
                                ? ((coordinate_group*64) >> tree_level)
                                    + tree_parent_cursor + lane_index
                                : tree_parent_cursor + lane_index;
                            task_left[lane_index] <= lane_index == 0
                                ? node_read0_data : node_read2_data;
                            task_right[lane_index] <= lane_index == 0
                                ? node_read1_data : node_read3_data;
                            task_store_address[lane_index]
                                <= tree_parent_cursor + lane_index;
                        end
                        block_index <= 0;
                        state <= S_HASH_CONTEXT;
                    end
                end
                S_TREE_PARENT_ADVANCE: begin
                    if (tree_parent_cursor + 2 < tree_parent_count) begin
                        tree_parent_cursor <= tree_parent_cursor + 2;
                        state <= S_TREE_PARENT_SETUP;
                    end else if (tree_level < tree_height) begin
                        tree_level <= tree_level + 1'b1;
                        tree_parent_count <= tree_parent_count >> 1;
                        tree_parent_cursor <= 0;
                        state <= S_TREE_AUTH;
                    end else state <= S_TREE_FINISH;
                end
                S_TREE_FINISH: begin
                    if ((tree_flags & FLAG_EXTERNAL_ROOT) != 0)
                        begin_route(macro_route, {144'd0, pk_root});
                    else
                        begin_route(macro_route, result_digest[0]);
                end
                S_HASH_CONTEXT: if (contexts_fire) begin
                    pending_mask <= active_mask;
                    if (PROFILE_ENABLE) begin
                        hash_contexts <= hash_contexts
                            + active_mask[0] + active_mask[1];
                        keccak_permutations <= keccak_permutations
                            + (active_mask[0] ? (task_chain_enable
                                ? task_chain_count[0] : task_blocks) : 0)
                            + (active_mask[1] ? (task_chain_enable
                                ? task_chain_count[1] : task_blocks) : 0);
                    end
                    append_beat <= 0;
                    block_index <= 0;
                    state <= S_HASH_PREP;
                end
                S_HASH_PREP: begin
                    prepared_block_data[0] <= hash_block_data[0];
                    prepared_block_data[1] <= hash_block_data[1];
                    state <= S_HASH_BLOCK;
                end
                S_HASH_BLOCK: if (blocks_fire) begin
                    if (append_beat == 8) begin
                        if (block_index + 1 < task_blocks) begin
                            block_index <= block_index + 1'b1;
                            append_beat <= 0;
                            state <= S_HASH_PREP;
                        end else state <= S_HASH_WAIT;
                    end else begin
                        append_beat <= append_beat + 1'b1;
                        state <= S_HASH_PREP;
                    end
                end
                S_HASH_WAIT: begin
                    for (lane_index = 0; lane_index < 2;
                         lane_index = lane_index + 1)
                        if (hash_response_valid[lane_index]) begin
                            pending_mask[lane_index] <= 0;
                            result_digest[lane_index]
                                <= hash_response_digest[lane_index];
                            result_capture[lane_index]
                                <= hash_capture_digest[lane_index];
                        end
                    if ((pending_mask & ~hash_response_valid) == 0)
                        state <= S_HASH_COMMIT;
                end
                S_HASH_COMMIT: begin
                    if (task_destination == DEST_DIRECT)
                        begin_route(task_route, result_digest[0]);
                    else if (task_destination == DEST_CHAIN) begin
                        if (tree_leaf_cursor == tree_target
                                && (tree_flags & FLAG_CAPTURE) != 0)
                            start_output(result_capture[0], result_capture[1],
                                active_mask[1], S_TREE_CHAIN_ADVANCE);
                        else state <= S_TREE_CHAIN_ADVANCE;
                    end else if (task_destination == DEST_LEAF)
                        state <= S_TREE_LEAF_ADVANCE;
                    else if (task_destination == DEST_PARENT)
                        state <= S_TREE_PARENT_ADVANCE;
                    else fail(ERR_MACRO);
                end
                S_ROUTE: begin
                    if (action_work[63:60] != DESC_ACTION)
                        fail(ERR_DESCRIPTOR);
                    else case (action_work[59:56])
                        ACT_WRITE_VALUE: begin
                            value_register[action_work[55:48]] <= route_result;
                            state <= S_ROUTE_NEXT;
                        end
                        ACT_WRITE_SCALAR: begin
                            if (action_work[55:48] == 0)
                                scalar_tree <= {
                                    vector_byte(route_result,25) & 8'h7f,
                                    vector_byte(route_result,26),
                                    vector_byte(route_result,27),
                                    vector_byte(route_result,28),
                                    vector_byte(route_result,29),
                                    vector_byte(route_result,30),
                                    vector_byte(route_result,31),
                                    vector_byte(route_result,32)};
                            else
                                scalar_leaf <= vector_byte(route_result,33)
                                    & 3'd7;
                            state <= S_ROUTE_NEXT;
                        end
                        ACT_EMIT_DIGEST:
                            start_output(route_result[127:0], 0, 1'b0,
                                         S_ROUTE_NEXT);
                        ACT_STORE_VALUE: state <= S_ROUTE_NEXT;
                        ACT_SET_CURRENT: begin
                            value_register[action_work[55:48]] <= route_result;
                            state <= S_ROUTE_NEXT;
                        end
                        default: fail(ERR_DESCRIPTOR);
                    endcase
                end
                S_ROUTE_NEXT: begin
                    if (route_action_index + 1 < route_action_count) begin
                        route_action_index <= route_action_index + 1'b1;
                        state <= S_ROUTE;
                    end else complete_macro();
                end
                S_TRANSFORM: begin
                    if (descriptor_work[59:56] == TRANSFORM_BASE_W) begin
                        chain_checksum <= 0;
                        checksum_byte <= 0;
                        state <= S_TRANSFORM_WORK;
                    end else if (descriptor_work[59:56] == TRANSFORM_INDEX) begin
                        scalar_leaf <= scalar_tree[2:0];
                        scalar_tree <= scalar_tree >> descriptor_work[39:32];
                        complete_macro();
                    end else fail(ERR_DESCRIPTOR);
                end
                S_TRANSFORM_WORK: begin
                    chain_checksum <= chain_checksum + 30
                        - value_register[2][checksum_byte*8 +: 4]
                        - value_register[2][checksum_byte*8+4 +: 4];
                    if (checksum_byte == 15)
                        complete_macro();
                    else checksum_byte <= checksum_byte + 1'b1;
                end
                S_EMIT: begin
                    start_output(emit_source_word(emit_segment_work), 0, 1'b0,
                        S_EMIT_ADVANCE);
                end
                S_EMIT_ADVANCE: begin
                    if (emit_segment_index + 1 < emit_segment_count) begin
                        emit_segment_index <= emit_segment_index + 1'b1;
                        state <= S_EMIT;
                    end else complete_macro();
                end
                S_OUTPUT: if (out_ready) begin
                    output_address <= output_address + 1'b1;
                    if ((!emit_two_words && emit_beat == 1)
                            || (emit_two_words && emit_beat == 3))
                        state <= output_return_state;
                    else emit_beat <= emit_beat + 1'b1;
                end
                S_DONE: begin
                    done <= 1'b1;
                    state <= S_IDLE;
                end
                S_ERROR: state <= S_IDLE;
                default: fail(ERR_MACRO);
            endcase
        end
    end

    initial begin
        if ((OUTPUT_BYTES & 7) != 0)
            $error("generic HBS output length must be 64-bit aligned");
    end
endmodule

`default_nettype wire
