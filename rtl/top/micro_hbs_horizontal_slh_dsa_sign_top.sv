`timescale 1ns/1ps
`default_nettype none

// Static-horizontal SLH-DSA-SHAKE-128f signing engine.
//
// The control below is intentionally hash-context-granular: each issue owns a
// complete PRF/F chain, H parent, or T_l sponge context.  Two identical U2
// lanes consume the same request format.  WOTS and FORS intermediate values
// remain lane/local-array resident.  Architectural signature words stream as
// soon as they are produced; no full-signature buffer is instantiated.
//
// This first product slice accepts messages up to 87 bytes, which keeps
// PRF_msg and H_msg in one SHAKE rate block.  The core algorithm, including
// every FORS tree and all 22 XMSS layers, is complete.
module micro_hbs_horizontal_slh_dsa_sign_top #(
    parameter integer UNROLL = 2,
    parameter integer MAX_MESSAGE_BYTES = 87,
    parameter bit PROFILE_ENABLE = 1'b0
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
    localparam integer SIGNATURE_BEATS = 2136;
    localparam logic [15:0] ERR_MESSAGE = 16'h1101;
    localparam logic [15:0] ERR_LANE = 16'h1102;

    localparam logic [3:0] TK_PRF_MSG = 4'd0;
    localparam logic [3:0] TK_H_MSG = 4'd1;
    localparam logic [3:0] TK_FORS_LEAF = 4'd2;
    localparam logic [3:0] TK_H = 4'd3;
    localparam logic [3:0] TK_WOTS_CHAIN = 4'd4;
    localparam logic [3:0] TK_TL_FORS = 4'd5;
    localparam logic [3:0] TK_TL_WOTS = 4'd6;

    localparam logic [4:0] S_IDLE = 5'd0;
    localparam logic [4:0] S_MESSAGE = 5'd1;
    localparam logic [4:0] S_PREP_R = 5'd2;
    localparam logic [4:0] S_PREP_HMSG = 5'd3;
    localparam logic [4:0] S_PREP_FORS_LEAF = 5'd4;
    localparam logic [4:0] S_FORS_AUTH = 5'd5;
    localparam logic [4:0] S_PREP_FORS_PARENT = 5'd6;
    localparam logic [4:0] S_PREP_FORS_TL = 5'd7;
    localparam logic [4:0] S_PREP_WOTS_CHAIN = 5'd8;
    localparam logic [4:0] S_PREP_WOTS_TL = 5'd9;
    localparam logic [4:0] S_XMSS_AUTH = 5'd10;
    localparam logic [4:0] S_PREP_XMSS_PARENT = 5'd11;
    localparam logic [4:0] S_CONTEXT = 5'd12;
    localparam logic [4:0] S_BLOCK = 5'd13;
    localparam logic [4:0] S_WAIT = 5'd14;
    localparam logic [4:0] S_COMMIT = 5'd15;
    localparam logic [4:0] S_WOTS_CHECKSUM = 5'd16;
    localparam logic [4:0] S_OUTPUT_WAIT = 5'd17;
    localparam logic [4:0] S_OUTPUT = 5'd18;
    localparam logic [4:0] S_DONE = 5'd19;
    localparam logic [4:0] S_TL_BUILD = 5'd20;
    localparam logic [4:0] S_ERROR = 5'd21;

    localparam logic [3:0] RC_R = 4'd0;
    localparam logic [3:0] RC_HMSG = 4'd1;
    localparam logic [3:0] RC_FORS_LEAF = 4'd2;
    localparam logic [3:0] RC_FORS_PARENT = 4'd3;
    localparam logic [3:0] RC_FORS_TL = 4'd4;
    localparam logic [3:0] RC_WOTS_CHAIN = 4'd5;
    localparam logic [3:0] RC_WOTS_TL = 4'd6;
    localparam logic [3:0] RC_XMSS_PARENT = 4'd7;

    logic [4:0] state;
    logic [3:0] return_code;
    logic [31:0] message_length;
    logic [MAX_MESSAGE_BYTES*8-1:0] message_buffer;
    logic [7:0] message_received;
    logic [127:0] sk_seed, sk_prf, pk_seed, pk_root, opt_rand;
    logic [127:0] randomizer;
    logic [199:0] message_digest;
    logic [63:0] tree_index;
    logic [2:0] leaf_index;
    logic [127:0] current_message;

    logic [5:0] fors_tree;
    logic [5:0] fors_selected;
    logic [6:0] leaf_base;
    logic [5:0] parent_base;
    logic [6:0] parent_count;
    logic [2:0] tree_height;
    logic [4:0] layer;
    logic [3:0] xmss_leaf;
    logic [5:0] chain_base;

    logic [1:0] active_mask;
    logic [1:0] pending_mask;
    logic [2:0] task_kind;
    logic [4:0] task_layer;
    logic [63:0] task_tree;
    logic [2:0] task_type;
    logic [2:0] task_keypair;
    logic [5:0] task_word6 [0:1];
    logic [11:0] task_word7 [0:1];
    logic [127:0] task_left [0:1];
    logic [127:0] task_right [0:1];
    logic [4:0] task_chain_count [0:1];
    logic task_capture [0:1];
    logic [4:0] task_capture_after [0:1];
    logic [2:0] block_index;
    logic [3:0] append_beat;
    logic [4:0] tl_block_word;
    logic [127:0] tl_append_buffer;
    logic [271:0] result_digest [0:1];
    logic [127:0] result_capture [0:1];

    wire [1:0] lane_context_ready;
    wire [1:0] lane_block_ready;
    wire [1:0] lane_response_valid;
    wire [1:0] lane_capture_valid;
    wire [1:0] lane_error;
    wire [271:0] lane_response_digest [0:1];
    wire [127:0] lane_capture_digest [0:1];
    logic [127:0] lane_block_data [0:1];
    wire contexts_fire = &(~active_mask | lane_context_ready);
    wire blocks_fire = &(~active_mask | lane_block_ready);

    logic [11:0] output_address;
    logic [127:0] emit_word0, emit_word1;
    logic emit_two_words;
    logic [1:0] emit_beat;
    logic [4:0] emit_return_state;

    wire [4:0] fors_leaf_return_state =
        leaf_base + active_mask[0] + active_mask[1] >= 64
            ? S_FORS_AUTH : S_PREP_FORS_LEAF;
    wire [4:0] wots_chain_return_state =
        chain_base + active_mask[0] + active_mask[1] < 35
            ? S_PREP_WOTS_CHAIN
            : (layer == 21 && xmss_leaf == leaf_index
                ? (xmss_leaf == 7 ? S_XMSS_AUTH : S_PREP_WOTS_CHAIN)
                : S_PREP_WOTS_TL);

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
    logic [5:0] endpoint_read_address;
    wire [127:0] endpoint_read_data;
    logic [6:0] tl_absolute_word_comb, tl_payload_word_comb;

    integer byte_index;
    integer lane_index;
    integer compose_lane;
    integer digest_index;
    integer checksum_work;
    integer bit_position;
    logic [5:0] selected_calc;
    logic [11:0] wots_checksum;
    logic [3:0] checksum_byte;

    function automatic [7:0] key_byte(
        input [127:0] value, input integer index
    );
        // μHBS job ports use the same little-slice byte convention as the
        // message and output streams: byte zero occupies bits [7:0].
        key_byte = value[index*8 +: 8];
    endfunction

    function automatic [7:0] stream_byte(
        input [127:0] value, input integer index
    );
        stream_byte = value[index*8 +: 8];
    endfunction

    function automatic [7:0] address_byte(
        input [31:0] a_layer,
        input [63:0] a_tree,
        input [31:0] a_type,
        input [31:0] a_keypair,
        input [31:0] a_word6,
        input [31:0] a_word7,
        input integer index
    );
        reg [31:0] word_value;
        begin
            case (index >> 2)
                0: word_value = a_layer;
                1: word_value = 32'd0;
                2: word_value = a_tree[63:32];
                3: word_value = a_tree[31:0];
                4: word_value = a_type;
                5: word_value = a_keypair;
                6: word_value = a_word6;
                default: word_value = a_word7;
            endcase
            case (index & 3)
                0: address_byte = word_value[31:24];
                1: address_byte = word_value[23:16];
                2: address_byte = word_value[15:8];
                default: address_byte = word_value[7:0];
            endcase
        end
    endfunction

    function automatic [4:0] wots_digit(input integer digit_index);
        reg [7:0] message_octet;
        begin
            if (digit_index < 32) begin
                message_octet = stream_byte(current_message, digit_index >> 1);
                wots_digit = digit_index[0]
                    ? {1'b0, message_octet[3:0]}
                    : {1'b0, message_octet[7:4]};
            end else begin
                case (digit_index)
                    32: wots_digit = wots_checksum[11:8];
                    33: wots_digit = wots_checksum[7:4];
                    default: wots_digit = wots_checksum[3:0];
                endcase
            end
        end
    endfunction

    function automatic [31:0] pack_be32(input [31:0] value);
        begin
            pack_be32 = {value[7:0], value[15:8],
                         value[23:16], value[31:24]};
        end
    endfunction

    function automatic [127:0] make_single_beat(
        input integer lane_number, input [3:0] beat
    );
        reg [127:0] value;
        integer p;
        integer absolute_byte;
        integer message_offset;
        integer input_length;
        begin
            value = 0;
            message_offset = 0;
            input_length = 0;
            if (task_kind == TK_PRF_MSG) begin
                message_offset = 32;
                input_length = 32 + message_length;
                if (beat == 0) value = sk_prf;
                else if (beat == 1) value = opt_rand;
            end else if (task_kind == TK_H_MSG) begin
                message_offset = 48;
                input_length = 48 + message_length;
                if (beat == 0) value = randomizer;
                else if (beat == 1) value = pk_seed;
                else if (beat == 2) value = pk_root;
            end else begin
                input_length = task_kind == TK_H ? 80 : 64;
                case (beat)
                    0: value = pk_seed;
                    1: value = {
                        pack_be32(task_tree[31:0]),
                        pack_be32(task_tree[63:32]),
                        32'd0, pack_be32(task_layer)};
                    2: value = {
                        pack_be32(task_word7[lane_number]),
                        pack_be32(task_word6[lane_number]),
                        pack_be32(task_keypair),
                        pack_be32(task_type)};
                    3: value = task_kind == TK_H
                        ? task_left[lane_number] : sk_seed;
                    4: if (task_kind == TK_H)
                        value = task_right[lane_number];
                    default: value = 0;
                endcase
            end
            for (p = 0; p < 16; p = p + 1) begin
                absolute_byte = beat * 16 + p;
                if ((task_kind == TK_PRF_MSG || task_kind == TK_H_MSG)
                    && absolute_byte >= message_offset
                    && absolute_byte < input_length)
                    value[p*8 +: 8] = message_buffer[
                        (absolute_byte-message_offset)*8 +: 8];
                if (absolute_byte == input_length)
                    value[p*8 +: 8] = 8'h1f;
            end
            if (beat == 8)
                value[63] = 1'b1;
            make_single_beat = value;
        end
    endfunction

    function automatic [63:0] tl_source_word(
        input integer rate_index, input integer rate_word
    );
        integer absolute_word;
        integer payload_word;
        reg [63:0] value;
        begin
            absolute_word = rate_index * 17 + rate_word;
            value = 0;
            case (absolute_word)
                0: value = pk_seed[63:0];
                1: value = pk_seed[127:64];
                2: value = {pack_be32(32'd0),
                            pack_be32(task_layer)};
                3: value = {pack_be32(task_tree[31:0]),
                            pack_be32(task_tree[63:32])};
                4: value = {pack_be32(task_keypair),
                            pack_be32(task_type)};
                5: value = 64'd0;
                default: begin
                    payload_word = absolute_word - 6;
                    if (task_kind == TK_TL_FORS) begin
                        if (payload_word < 66)
                            value = payload_word[0]
                                ? endpoint_read_data[127:64]
                                : endpoint_read_data[63:0];
                        else if (absolute_word == 72)
                            value = 64'h000000000000001f;
                    end else begin
                        if (payload_word < 70)
                            value = payload_word[0]
                                ? endpoint_read_data[127:64]
                                : endpoint_read_data[63:0];
                        else if (absolute_word == 76)
                            value = 64'h000000000000001f;
                    end
                end
            endcase
            if (rate_index == 4 && rate_word == 16)
                value[63] = 1'b1;
            tl_source_word = value;
        end
    endfunction

    always_comb begin
        for (compose_lane = 0; compose_lane < 2;
             compose_lane = compose_lane + 1)
            if (task_kind == TK_TL_FORS || task_kind == TK_TL_WOTS)
                lane_block_data[compose_lane] = tl_append_buffer;
            else
                lane_block_data[compose_lane] = make_single_beat(
                    compose_lane, append_beat);
    end

    genvar lane;
    generate for (lane = 0; lane < 2; lane = lane + 1) begin : hash_lanes
        (* keep_hierarchy = "yes" *)
        micro_hbs_compact_shake_context_lane #(.UNROLL(UNROLL)) hash_lane (
            .clk, .rst_n,
            .context_valid(state == S_CONTEXT && active_mask[lane]),
            .context_ready(lane_context_ready[lane]),
            .chain_enable(task_kind == TK_FORS_LEAF
                || task_kind == TK_WOTS_CHAIN),
            .chain_prefix(task_kind == TK_FORS_LEAF
                || task_kind == TK_WOTS_CHAIN),
            .chain_prefix_preserve_counter(task_kind == TK_FORS_LEAF),
            .chain_prefix_domain(task_kind == TK_FORS_LEAF ? 3'd3 : 3'd0),
            .chain_count(task_chain_count[lane][4:0]),
            .capture_enable(task_capture[lane]),
            .capture_after(task_capture_after[lane][4:0]),
            .block_valid(state == S_BLOCK && active_mask[lane]),
            .block_ready(lane_block_ready[lane]),
            .block_data(lane_block_data[lane]),
            .block_last(block_index == 4
                || (task_kind != TK_TL_FORS && task_kind != TK_TL_WOTS)),
            .response_valid(lane_response_valid[lane]),
            .response_digest(lane_response_digest[lane]),
            .capture_digest(lane_capture_digest[lane]),
            .capture_valid(lane_capture_valid[lane]),
            .error(lane_error[lane])
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

    micro_hbs_local_array128_1r endpoint_store (
        .clk,
        .write0_valid(endpoint_write0_valid),
        .write0_address(endpoint_write0_address),
        .write0_data(endpoint_write0_data),
        .write1_valid(endpoint_write1_valid),
        .write1_address(endpoint_write1_address),
        .write1_data(endpoint_write1_data),
        .read_address(endpoint_read_address), .read_data(endpoint_read_data)
    );

    assign job_ready = state == S_IDLE;
    assign message_ready = state == S_MESSAGE
        && message_received < message_length;
    assign busy = state != S_IDLE;
    assign out_valid = state == S_OUTPUT;
    assign out_data = emit_beat == 0 ? emit_word0[63:0]
        : emit_beat == 1 ? emit_word0[127:64]
        : emit_beat == 2 ? emit_word1[63:0]
        : emit_word1[127:64];
    assign out_keep = 8'hff;
    assign out_last = output_address == SIGNATURE_BEATS-1;

    always_comb begin
        node_write0_valid = 1'b0;
        node_write1_valid = 1'b0;
        node_write0_address = 6'd0;
        node_write1_address = 6'd0;
        node_write0_data = 128'd0;
        node_write1_data = 128'd0;
        endpoint_write0_valid = 1'b0;
        endpoint_write1_valid = 1'b0;
        endpoint_write0_address = 6'd0;
        endpoint_write1_address = 6'd0;
        endpoint_write0_data = 128'd0;
        endpoint_write1_data = 128'd0;

        node_read0_address = 6'd0;
        node_read1_address = 6'd0;
        node_read2_address = 6'd0;
        node_read3_address = 6'd0;
        tl_absolute_word_comb = block_index * 7'd17 + tl_block_word;
        tl_payload_word_comb = tl_absolute_word_comb >= 7'd6
            ? tl_absolute_word_comb - 7'd6 : 7'd0;
        endpoint_read_address = tl_payload_word_comb[6:1];

        if (state == S_PREP_FORS_PARENT || state == S_PREP_XMSS_PARENT) begin
            node_read0_address = {parent_base[4:0], 1'b0};
            node_read1_address = {parent_base[4:0], 1'b0} + 1'b1;
            node_read2_address = {parent_base[4:0], 1'b0} + 2'd2;
            node_read3_address = {parent_base[4:0], 1'b0} + 2'd3;
        end else if (state == S_FORS_AUTH) begin
            node_read0_address = (fors_selected >> (tree_height-1)) ^ 1'b1;
        end else if (state == S_XMSS_AUTH) begin
            node_read0_address = (leaf_index >> (tree_height-1)) ^ 1'b1;
        end

        if (state == S_COMMIT) begin
            case (return_code)
                RC_R: begin end
                RC_FORS_LEAF: begin
                    node_write0_valid = 1'b1;
                    node_write0_address = leaf_base[5:0];
                    node_write0_data = result_digest[0];
                    node_write1_valid = active_mask[1];
                    node_write1_address = leaf_base[5:0] + 1'b1;
                    node_write1_data = result_digest[1];
                end
                RC_FORS_PARENT: begin
                    node_write0_valid = 1'b1;
                    node_write0_address = parent_base;
                    node_write0_data = result_digest[0];
                    node_write1_valid = active_mask[1];
                    node_write1_address = parent_base + 1'b1;
                    node_write1_data = result_digest[1];
                    if (tree_height == 6) begin
                        endpoint_write0_valid = 1'b1;
                        endpoint_write0_address = fors_tree;
                        endpoint_write0_data = result_digest[0];
                    end
                end
                RC_WOTS_CHAIN: begin
                    endpoint_write0_valid = 1'b1;
                    endpoint_write0_address = chain_base;
                    endpoint_write0_data = result_digest[0];
                    endpoint_write1_valid = active_mask[1];
                    endpoint_write1_address = chain_base + 1'b1;
                    endpoint_write1_data = result_digest[1];
                end
                RC_WOTS_TL: begin
                    node_write0_valid = 1'b1;
                    node_write0_address = xmss_leaf;
                    node_write0_data = result_digest[0];
                end
                RC_XMSS_PARENT: begin
                    node_write0_valid = 1'b1;
                    node_write0_address = parent_base;
                    node_write0_data = result_digest[0];
                    node_write1_valid = active_mask[1];
                    node_write1_address = parent_base + 1'b1;
                    node_write1_data = result_digest[1];
                end
                default: begin end
            endcase
        end
    end

    task automatic set_common_task(input integer target_lane);
        begin
            task_layer <= layer;
            task_tree <= tree_index;
            task_type <= 0;
            task_keypair <= xmss_leaf;
            task_word6[target_lane] <= 0;
            task_word7[target_lane] <= 0;
            task_left[target_lane] <= 0;
            task_right[target_lane] <= 0;
            task_chain_count[target_lane] <= 1;
            task_capture[target_lane] <= 0;
            task_capture_after[target_lane] <= 0;
        end
    endtask

    task automatic fail(input [15:0] code);
        begin
            error <= 1'b1;
            error_code <= code;
            state <= S_ERROR;
        end
    endtask

    task automatic start_emit(
        input [127:0] word0,
        input [127:0] word1,
        input two_words,
        input [4:0] return_state
    );
        begin
            emit_word0 <= word0;
            emit_word1 <= word1;
            emit_two_words <= two_words;
            emit_beat <= 0;
            emit_return_state <= return_state;
            state <= S_OUTPUT;
        end
    endtask

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= S_IDLE;
            return_code <= 0;
            message_length <= 0;
            message_buffer <= 0;
            message_received <= 0;
            sk_seed <= 0; sk_prf <= 0; pk_seed <= 0; pk_root <= 0;
            opt_rand <= 0; randomizer <= 0; message_digest <= 0;
            tree_index <= 0; leaf_index <= 0; current_message <= 0;
            fors_tree <= 0; fors_selected <= 0; leaf_base <= 0;
            parent_base <= 0; parent_count <= 0; tree_height <= 0;
            layer <= 0; xmss_leaf <= 0; chain_base <= 0;
            active_mask <= 0; pending_mask <= 0;
            block_index <= 0; append_beat <= 0; tl_block_word <= 0;
            tl_append_buffer <= 0;
            wots_checksum <= 0; checksum_byte <= 0;
            result_digest[0] <= 0; result_digest[1] <= 0;
            result_capture[0] <= 0; result_capture[1] <= 0;
            output_address <= 0;
            emit_two_words <= 0; emit_beat <= 0; emit_return_state <= S_IDLE;
            done <= 0; error <= 0; error_code <= 0;
            hash_contexts <= 0; keccak_permutations <= 0;
            lane0_active_cycles <= 0; lane1_active_cycles <= 0;
            for (lane_index = 0; lane_index < 2; lane_index = lane_index + 1) begin
                task_word6[lane_index] <= 0;
                task_word7[lane_index] <= 0; task_left[lane_index] <= 0;
                task_right[lane_index] <= 0; task_chain_count[lane_index] <= 0;
                task_capture[lane_index] <= 0;
                task_capture_after[lane_index] <= 0;
            end
            task_kind <= 0; task_layer <= 0; task_tree <= 0;
            task_type <= 0; task_keypair <= 0;
        end else begin
            done <= 1'b0;
            if (PROFILE_ENABLE && state == S_WAIT) begin
                if (pending_mask[0]) lane0_active_cycles <= lane0_active_cycles + 1'b1;
                if (pending_mask[1]) lane1_active_cycles <= lane1_active_cycles + 1'b1;
            end
            if (lane_error != 0)
                fail(ERR_LANE);
            else case (state)
                S_IDLE: begin
                    error <= 1'b0;
                    error_code <= 0;
                    if (job_valid) begin
                        if (job_message_length == 0
                            || job_message_length > MAX_MESSAGE_BYTES)
                            fail(ERR_MESSAGE);
                        else begin
                            message_length <= job_message_length;
                            message_buffer <= 0;
                            message_received <= 0;
                            sk_seed <= job_sk_seed;
                            sk_prf <= job_sk_prf;
                            pk_seed <= job_pk_seed;
                            pk_root <= job_pk_root;
                            opt_rand <= job_opt_rand;
                            hash_contexts <= 0;
                            keccak_permutations <= 0;
                            lane0_active_cycles <= 0;
                            lane1_active_cycles <= 0;
                            output_address <= 0;
                            state <= S_MESSAGE;
                        end
                    end
                end
                S_MESSAGE: if (message_valid && message_ready) begin
                    for (byte_index = 0; byte_index < 8; byte_index = byte_index + 1)
                        if (message_keep[byte_index]
                            && message_received + byte_index < message_length)
                            message_buffer[(message_received+byte_index)*8 +: 8]
                                <= message_data[byte_index*8 +: 8];
                    message_received <= message_received
                        + message_keep[0] + message_keep[1] + message_keep[2]
                        + message_keep[3] + message_keep[4] + message_keep[5]
                        + message_keep[6] + message_keep[7];
                    if (message_last) begin
                        if (message_received
                            + message_keep[0] + message_keep[1] + message_keep[2]
                            + message_keep[3] + message_keep[4] + message_keep[5]
                            + message_keep[6] + message_keep[7] != message_length)
                            fail(ERR_MESSAGE);
                        else state <= S_PREP_R;
                    end
                end
                S_PREP_R: begin
                    set_common_task(0);
                    task_kind <= TK_PRF_MSG;
                    active_mask <= 2'b01;
                    return_code <= RC_R;
                    block_index <= 0;
                    state <= S_CONTEXT;
                end
                S_PREP_HMSG: begin
                    set_common_task(0);
                    task_kind <= TK_H_MSG;
                    active_mask <= 2'b01;
                    return_code <= RC_HMSG;
                    block_index <= 0;
                    state <= S_CONTEXT;
                end
                S_PREP_FORS_LEAF: begin
                    for (lane_index = 0; lane_index < 2; lane_index = lane_index + 1) begin
                        set_common_task(lane_index);
                        task_kind <= TK_FORS_LEAF;
                        task_layer <= 0;
                        task_tree <= tree_index;
                        task_type <= 6;
                        task_keypair <= leaf_index;
                        task_word7[lane_index]
                            <= fors_tree * 64 + leaf_base + lane_index;
                        task_chain_count[lane_index] <= 2;
                        task_capture[lane_index]
                            <= leaf_base + lane_index == fors_selected;
                        task_capture_after[lane_index] <= 1;
                    end
                    active_mask <= leaf_base == 63 ? 2'b01 : 2'b11;
                    return_code <= RC_FORS_LEAF;
                    block_index <= 0;
                    state <= S_CONTEXT;
                end
                S_FORS_AUTH: begin
                    parent_base <= 0;
                    parent_count <= 64 >> tree_height;
                    start_emit(node_read0_data, 128'd0, 1'b0,
                        S_PREP_FORS_PARENT);
                end
                S_PREP_FORS_PARENT: begin
                    for (lane_index = 0; lane_index < 2; lane_index = lane_index + 1) begin
                        set_common_task(lane_index);
                        task_kind <= TK_H;
                        task_layer <= 0;
                        task_tree <= tree_index;
                        task_type <= 3;
                        task_keypair <= leaf_index;
                        task_word6[lane_index] <= tree_height;
                        task_word7[lane_index] <= (fors_tree * 64
                            >> tree_height) + parent_base + lane_index;
                        task_left[lane_index] <= lane_index == 0
                            ? node_read0_data : node_read2_data;
                        task_right[lane_index] <= lane_index == 0
                            ? node_read1_data : node_read3_data;
                    end
                    active_mask <= parent_base + 1 < parent_count
                        ? 2'b11 : 2'b01;
                    return_code <= RC_FORS_PARENT;
                    block_index <= 0;
                    state <= S_CONTEXT;
                end
                S_PREP_FORS_TL: begin
                    set_common_task(0);
                    task_kind <= TK_TL_FORS;
                    task_layer <= 0;
                    task_tree <= tree_index;
                    task_type <= 4;
                    task_keypair <= leaf_index;
                    active_mask <= 2'b01;
                    return_code <= RC_FORS_TL;
                    block_index <= 0;
                    state <= S_CONTEXT;
                end
                S_PREP_WOTS_CHAIN: begin
                    for (lane_index = 0; lane_index < 2; lane_index = lane_index + 1) begin
                        set_common_task(lane_index);
                        task_kind <= TK_WOTS_CHAIN;
                        task_layer <= layer;
                        task_tree <= tree_index;
                        task_type <= 5;
                        task_keypair <= xmss_leaf;
                        task_word6[lane_index] <= chain_base + lane_index;
                        task_word7[lane_index] <= 0;
                        task_chain_count[lane_index] <= (layer == 21
                            && xmss_leaf == leaf_index)
                            ? wots_digit(chain_base+lane_index) + 1'b1 : 16;
                        task_capture[lane_index] <= xmss_leaf == leaf_index;
                        task_capture_after[lane_index]
                            <= wots_digit(chain_base+lane_index) + 1'b1;
                    end
                    active_mask <= chain_base == 34 ? 2'b01 : 2'b11;
                    return_code <= RC_WOTS_CHAIN;
                    block_index <= 0;
                    state <= S_CONTEXT;
                end
                S_PREP_WOTS_TL: begin
                    set_common_task(0);
                    task_kind <= TK_TL_WOTS;
                    task_layer <= layer;
                    task_tree <= tree_index;
                    task_type <= 1;
                    task_keypair <= xmss_leaf;
                    active_mask <= 2'b01;
                    return_code <= RC_WOTS_TL;
                    block_index <= 0;
                    state <= S_CONTEXT;
                end
                S_XMSS_AUTH: begin
                    parent_base <= 0;
                    parent_count <= 8 >> tree_height;
                    start_emit(node_read0_data, 128'd0, 1'b0,
                        S_PREP_XMSS_PARENT);
                end
                S_PREP_XMSS_PARENT: begin
                    // On the final hypertree layer the root is not consumed.
                    // Skip the one parent on the selected path at each level;
                    // all sibling-subtree nodes needed by the signature remain.
                    if (layer == 21
                        && parent_base == (leaf_index >> tree_height)) begin
                        if (parent_base + 1 >= parent_count) begin
                            if (tree_height == 3) begin
                                state <= S_DONE;
                            end else begin
                                tree_height <= tree_height + 1'b1;
                                state <= S_XMSS_AUTH;
                            end
                        end else begin
                            parent_base <= parent_base + 1'b1;
                        end
                    end else begin
                        for (lane_index = 0; lane_index < 2; lane_index = lane_index + 1) begin
                            set_common_task(lane_index);
                            task_kind <= TK_H;
                            task_layer <= layer;
                            task_tree <= tree_index;
                            task_type <= 2;
                            task_keypair <= 0;
                            task_word6[lane_index] <= tree_height;
                            task_word7[lane_index] <= parent_base + lane_index;
                            task_left[lane_index] <= lane_index == 0
                                ? node_read0_data : node_read2_data;
                            task_right[lane_index] <= lane_index == 0
                                ? node_read1_data : node_read3_data;
                        end
                        // Do not pair across the skipped selected-path parent.
                        active_mask <= (parent_base + 1 < parent_count
                            && !(layer == 21 && parent_base + 1
                                 == (leaf_index >> tree_height)))
                            ? 2'b11 : 2'b01;
                        return_code <= RC_XMSS_PARENT;
                        block_index <= 0;
                        state <= S_CONTEXT;
                    end
                end
                S_CONTEXT: if (contexts_fire) begin
                    pending_mask <= active_mask;
                    if (PROFILE_ENABLE) begin
                        hash_contexts <= hash_contexts
                            + active_mask[0] + active_mask[1];
                        keccak_permutations <= keccak_permutations
                            + (active_mask[0]
                                ? ((task_kind == TK_TL_FORS
                                    || task_kind == TK_TL_WOTS)
                                   ? 5 : task_chain_count[0]) : 0)
                            + (active_mask[1]
                                ? ((task_kind == TK_TL_FORS
                                    || task_kind == TK_TL_WOTS)
                                   ? 5 : task_chain_count[1]) : 0);
                    end
                    if (task_kind == TK_TL_FORS
                        || task_kind == TK_TL_WOTS) begin
                        tl_block_word <= 0;
                        tl_append_buffer <= 0;
                        append_beat <= 0;
                        state <= S_TL_BUILD;
                    end else begin
                        append_beat <= 0;
                        state <= S_BLOCK;
                    end
                end
                S_TL_BUILD: begin
                    if (!tl_block_word[0])
                        tl_append_buffer[63:0]
                            <= tl_source_word(block_index, tl_block_word);
                    else
                        tl_append_buffer[127:64]
                            <= tl_source_word(block_index, tl_block_word);
                    if (tl_block_word == 16) begin
                        tl_append_buffer[127:64] <= 0;
                        state <= S_BLOCK;
                    end else if (tl_block_word[0]) begin
                        state <= S_BLOCK;
                    end else begin
                        tl_block_word <= tl_block_word + 1'b1;
                    end
                end
                S_BLOCK: if (blocks_fire) begin
                    if (append_beat == 8) begin
                        if ((task_kind == TK_TL_FORS
                             || task_kind == TK_TL_WOTS)
                            && block_index < 4) begin
                            block_index <= block_index + 1'b1;
                            append_beat <= 0;
                            tl_block_word <= 0;
                            tl_append_buffer <= 0;
                            state <= S_TL_BUILD;
                        end else
                            state <= S_WAIT;
                    end else begin
                        append_beat <= append_beat + 1'b1;
                        if (task_kind == TK_TL_FORS
                            || task_kind == TK_TL_WOTS) begin
                            tl_block_word <= tl_block_word + 1'b1;
                            tl_append_buffer <= 0;
                            state <= S_TL_BUILD;
                        end
                    end
                end
                S_WAIT: begin
                    for (lane_index = 0; lane_index < 2; lane_index = lane_index + 1)
                        if (lane_response_valid[lane_index]) begin
                            pending_mask[lane_index] <= 1'b0;
                            result_digest[lane_index]
                                <= lane_response_digest[lane_index];
                            result_capture[lane_index]
                                <= lane_capture_digest[lane_index];
                        end
                    if ((pending_mask & ~lane_response_valid) == 0)
                        state <= S_COMMIT;
                end
                S_COMMIT: case (return_code)
                    RC_R: begin
                        randomizer <= result_digest[0];
                        start_emit(result_digest[0][127:0], 128'd0, 1'b0,
                            S_PREP_HMSG);
                    end
                    RC_HMSG: begin
                        message_digest <= result_digest[0][199:0];
                        tree_index <= {
                            result_digest[0][8*25 +: 8] & 8'h7f,
                            result_digest[0][8*26 +: 8],
                            result_digest[0][8*27 +: 8],
                            result_digest[0][8*28 +: 8],
                            result_digest[0][8*29 +: 8],
                            result_digest[0][8*30 +: 8],
                            result_digest[0][8*31 +: 8],
                            result_digest[0][8*32 +: 8]};
                        leaf_index <= result_digest[0][8*33 +: 8] & 3'd7;
                        fors_tree <= 0;
                        selected_calc = 0;
                        for (bit_position = 0; bit_position < 6;
                             bit_position = bit_position + 1)
                            selected_calc = (selected_calc << 1)
                                | result_digest[0][8*(bit_position>>3)
                                    + 7-(bit_position&7)];
                        fors_selected <= selected_calc;
                        leaf_base <= 0;
                        state <= S_PREP_FORS_LEAF;
                    end
                    RC_FORS_LEAF: begin
                        if (leaf_base + active_mask[0] + active_mask[1] >= 64) begin
                            tree_height <= 1;
                            state <= S_FORS_AUTH;
                        end else begin
                            leaf_base <= leaf_base + active_mask[0] + active_mask[1];
                            state <= S_PREP_FORS_LEAF;
                        end
                        if (leaf_base == fors_selected)
                            start_emit(result_capture[0], 128'd0, 1'b0,
                                fors_leaf_return_state);
                        else if (active_mask[1]
                                 && leaf_base + 1'b1 == fors_selected)
                            start_emit(result_capture[1], 128'd0, 1'b0,
                                fors_leaf_return_state);
                    end
                    RC_FORS_PARENT: begin
                        if (parent_base + active_mask[0] + active_mask[1]
                            >= parent_count) begin
                            if (tree_height == 6) begin
                                if (fors_tree == 32)
                                    state <= S_PREP_FORS_TL;
                                else begin
                                    fors_tree <= fors_tree + 1'b1;
                                    selected_calc = 0;
                                    for (bit_position = 0; bit_position < 6;
                                         bit_position = bit_position + 1)
                                        selected_calc = (selected_calc << 1)
                                            | message_digest[
                                                8*((((fors_tree+1)*6)+bit_position)>>3)
                                                + 7-((((fors_tree+1)*6)+bit_position)&7)];
                                    fors_selected <= selected_calc;
                                    leaf_base <= 0;
                                    state <= S_PREP_FORS_LEAF;
                                end
                            end else begin
                                tree_height <= tree_height + 1'b1;
                                state <= S_FORS_AUTH;
                            end
                        end else begin
                            parent_base <= parent_base + active_mask[0]
                                + active_mask[1];
                            state <= S_PREP_FORS_PARENT;
                        end
                    end
                    RC_FORS_TL: begin
                        current_message <= result_digest[0];
                        layer <= 0;
                        xmss_leaf <= 0;
                        chain_base <= 0;
                        wots_checksum <= 0;
                        checksum_byte <= 0;
                        state <= S_WOTS_CHECKSUM;
                    end
                    RC_WOTS_CHAIN: begin
                        if (chain_base + active_mask[0] + active_mask[1] >= 35) begin
                            if (layer == 21 && xmss_leaf == leaf_index) begin
                                if (xmss_leaf == 7) begin
                                    tree_height <= 1;
                                    state <= S_XMSS_AUTH;
                                end else begin
                                    xmss_leaf <= xmss_leaf + 1'b1;
                                    chain_base <= 0;
                                    state <= S_PREP_WOTS_CHAIN;
                                end
                            end else state <= S_PREP_WOTS_TL;
                        end else begin
                            chain_base <= chain_base + active_mask[0]
                                + active_mask[1];
                            state <= S_PREP_WOTS_CHAIN;
                        end
                        if (xmss_leaf == leaf_index)
                            start_emit(result_capture[0], result_capture[1],
                                active_mask[1], wots_chain_return_state);
                    end
                    RC_WOTS_TL: begin
                        if (xmss_leaf == 7) begin
                            tree_height <= 1;
                            state <= S_XMSS_AUTH;
                        end else begin
                            xmss_leaf <= xmss_leaf + 1'b1;
                            chain_base <= 0;
                            state <= S_PREP_WOTS_CHAIN;
                        end
                    end
                    RC_XMSS_PARENT: begin
                        if (parent_base + active_mask[0] + active_mask[1]
                            >= parent_count) begin
                            if (tree_height == 3) begin
                                current_message <= result_digest[0];
                                if (layer == 21) begin
                                    state <= S_DONE;
                                end else begin
                                    leaf_index <= tree_index[2:0];
                                    tree_index <= tree_index >> 3;
                                    layer <= layer + 1'b1;
                                    xmss_leaf <= 0;
                                    chain_base <= 0;
                                    wots_checksum <= 0;
                                    checksum_byte <= 0;
                                    state <= S_WOTS_CHECKSUM;
                                end
                            end else begin
                                tree_height <= tree_height + 1'b1;
                                state <= S_XMSS_AUTH;
                            end
                        end else begin
                            parent_base <= parent_base + active_mask[0]
                                + active_mask[1];
                            state <= S_PREP_XMSS_PARENT;
                        end
                    end
                    default: fail(ERR_LANE);
                endcase
                S_WOTS_CHECKSUM: begin
                    wots_checksum <= wots_checksum + 30
                        - current_message[checksum_byte*8 +: 4]
                        - current_message[checksum_byte*8+4 +: 4];
                    if (checksum_byte == 15)
                        state <= S_PREP_WOTS_CHAIN;
                    else
                        checksum_byte <= checksum_byte + 1'b1;
                end
                S_OUTPUT: if (out_ready) begin
                    output_address <= output_address + 1'b1;
                    if ((!emit_two_words && emit_beat == 1)
                        || (emit_two_words && emit_beat == 3))
                        state <= emit_return_state;
                    else
                        emit_beat <= emit_beat + 1'b1;
                end
                S_DONE: begin
                    done <= 1'b1;
                    state <= S_IDLE;
                end
                S_ERROR: if (!job_valid) state <= S_IDLE;
                default: fail(ERR_LANE);
            endcase
        end
    end
endmodule

`default_nettype wire
