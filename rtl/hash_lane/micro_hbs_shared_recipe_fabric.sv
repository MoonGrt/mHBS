`timescale 1ns/1ps
`default_nettype none

// Two independent recipe controllers sharing one wide rate-block composer.
// Only the small feedback/stage state is duplicated; every template, patch,
// message and endpoint mux is physically present once.
module micro_hbs_shared_recipe_fabric #(
    parameter integer MAX_MESSAGE_BYTES = 87
) (
    input  wire         clk,
    input  wire         rst_n,
    input  wire [1:0]   request_valid,
    output wire [1:0]   request_ready,
    input  wire [3:0]   request_recipe [0:1],
    input  wire [255:0] request_secret_seed,
    input  wire [255:0] request_secret_prf,
    input  wire [255:0] request_public_seed,
    input  wire [255:0] request_root,
    input  wire [127:0] request_identifier,
    input  wire [255:0] request_randomizer [0:1],
    input  wire [MAX_MESSAGE_BYTES*8-1:0] request_message,
    input  wire [6:0]   request_message_length,
    input  wire [9:0]   request_q [0:1],
    input  wire [6:0]   request_item [0:1],
    input  wire [4:0]   request_steps [0:1],
    input  wire [255:0] request_address [0:1],
    input  wire [255:0] request_left [0:1],
    input  wire [255:0] request_right [0:1],
    output logic [6:0]  endpoint_read_index,
    input  wire [255:0] endpoint_read_data,
    output wire [1:0]   response_valid,
    input  wire [1:0]   response_ready,
    output wire [255:0] response_value [0:1],
    output wire [1:0]   error,
    output logic [31:0] hash_contexts [0:1],
    output logic [31:0] permutations [0:1],
    output logic [31:0] active_cycles [0:1],

    output logic [1:0]  external_context_valid,
    input  wire [1:0]   external_context_ready,
    output logic [1:0]  external_fast_block_valid,
    input  wire [1:0]   external_fast_block_ready,
    output logic [2175:0] external_fast_block_data,
    output logic [1:0]  external_block_valid,
    input  wire [1:0]   external_block_ready,
    output logic [255:0] external_block_data,
    output logic [1:0]  external_block_last,
    input  wire [1:0]   external_response_valid,
    input  wire [543:0] external_response_digest,
    input  wire [1:0]   external_finish_valid,
    input  wire [543:0] external_finish_digest,
    input  wire [1:0]   external_error
);
    localparam logic [3:0] R_MASKED_CHAIN    = 4'd3;

    localparam logic [3:0] P_PRF_INDEX       = 4'd1;
    localparam logic [3:0] P_MESSAGE_ROOT    = 4'd2;
    localparam logic [3:0] P_SEED_ADDRESS    = 4'd3;
    localparam logic [3:0] P_ADDRESS_PRF     = 4'd4;
    localparam logic [3:0] P_MASKED_F        = 4'd5;
    localparam logic [3:0] P_MASKED_H        = 4'd6;
    localparam logic [3:0] P_PREFIX_MESSAGE  = 4'd7;
    localparam logic [3:0] P_PREFIX_PRIVATE  = 4'd8;
    localparam logic [3:0] P_PREFIX_CHAIN    = 4'd9;
    localparam logic [3:0] P_PREFIX_LIST     = 4'd10;
    localparam logic [3:0] P_PREFIX_LEAF     = 4'd11;
    localparam logic [3:0] P_PREFIX_PARENT   = 4'd12;

    wire [1:0] compose_valid, compose_accept, controller_active;
    wire [3:0] compose_recipe [0:1];
    wire [3:0] compose_primitive [0:1];
    wire [11:0] compose_length [0:1];
    wire [4:0] compose_chain_step [0:1];
    wire [1:0] compose_stage [0:1];
    wire [255:0] compose_current [0:1];
    wire [255:0] compose_key [0:1];
    wire [255:0] compose_mask0 [0:1];
    wire [255:0] compose_mask1 [0:1];
    wire [1:0] digest_valid;
    wire [255:0] digest_value [0:1];

    genvar controller_lane;
    generate for (controller_lane = 0; controller_lane < 2;
                  controller_lane = controller_lane + 1) begin : controllers
        assign digest_valid[controller_lane]
            = external_response_valid[controller_lane]
              || external_finish_valid[controller_lane];
        assign digest_value[controller_lane]
            = external_finish_valid[controller_lane]
              ? external_finish_digest[controller_lane*272 +: 256]
              : external_response_digest[controller_lane*272 +: 256];
        micro_hbs_recipe_lane_controller controller (
            .clk, .rst_n,
            .request_valid(request_valid[controller_lane]),
            .request_ready(request_ready[controller_lane]),
            .request_recipe(request_recipe[controller_lane]),
            .request_steps(request_steps[controller_lane]),
            .request_left(request_left[controller_lane]),
            .compose_valid(compose_valid[controller_lane]),
            .compose_accept(compose_accept[controller_lane]),
            .compose_recipe(compose_recipe[controller_lane]),
            .compose_primitive(compose_primitive[controller_lane]),
            .compose_length(compose_length[controller_lane]),
            .compose_chain_step(compose_chain_step[controller_lane]),
            .compose_stage(compose_stage[controller_lane]),
            .compose_current(compose_current[controller_lane]),
            .compose_key(compose_key[controller_lane]),
            .compose_mask0(compose_mask0[controller_lane]),
            .compose_mask1(compose_mask1[controller_lane]),
            .digest_valid(digest_valid[controller_lane]),
            .digest_value(digest_value[controller_lane]),
            .primitive_error(external_error[controller_lane]),
            .response_valid(response_valid[controller_lane]),
            .response_ready(response_ready[controller_lane]),
            .response_value(response_value[controller_lane]),
            .error(error[controller_lane]),
            .active(controller_active[controller_lane])
        );
    end endgenerate

    logic issue_rr;
    logic issue_lane;
    logic stream_active, stream_lane;
    logic [4:0] block_index;
    logic [3:0] append_index, list_fill_index;
    logic [127:0] list_beat_buffer;
    typedef enum logic [1:0] {
        STREAM_BLOCK, STREAM_LIST_READ, STREAM_LIST_FILL
    } stream_state_t;
    stream_state_t stream_state;

    wire [3:0] selected_primitive = compose_primitive[issue_lane];
    wire selected_fast = selected_primitive != P_MESSAGE_ROOT
        && selected_primitive != P_PREFIX_MESSAGE
        && selected_primitive != P_PREFIX_LIST;
    wire selected_available = compose_valid[issue_lane];

    always_comb begin
        if (compose_valid[issue_rr])
            issue_lane = issue_rr;
        else
            issue_lane = ~issue_rr;
    end

    wire [3:0] stream_primitive = compose_primitive[stream_lane];
    wire [11:0] stream_base_length = compose_length[stream_lane];
    wire [11:0] stream_length = stream_base_length
        + ((stream_primitive == P_MESSAGE_ROOT
            || stream_primitive == P_PREFIX_MESSAGE)
           ? request_message_length : 0);
    wire [11:0] block_offset = ({7'b0, block_index} << 7)
        + ({7'b0, block_index} << 3);
    wire [11:0] append_offset = ({8'b0, append_index} << 4);
    wire [11:0] bytes_remaining = stream_length - block_offset;
    wire stream_block_last = bytes_remaining <= 135;
    wire [11:0] list_absolute = block_offset + append_offset
        + list_fill_index;

    function automatic [7:0] vec256_byte(
        input [255:0] value, input integer index
    );
        vec256_byte = value[index*8 +: 8];
    endfunction

    function automatic [7:0] vec128_byte(
        input [127:0] value, input integer index
    );
        vec128_byte = value[index*8 +: 8];
    endfunction

    function automatic [7:0] selected_u32_q_byte(
        input logic lane, input integer index
    );
        begin
            case (index)
                0, 1: selected_u32_q_byte = 8'b0;
                2: selected_u32_q_byte = {6'b0, request_q[lane][9:8]};
                3: selected_u32_q_byte = request_q[lane][7:0];
                default: selected_u32_q_byte = 8'b0;
            endcase
        end
    endfunction

    function automatic [7:0] list_prefix_byte(
        input logic lane, input integer absolute_index
    );
        begin
            list_prefix_byte = 8'b0;
            if (absolute_index < 16)
                list_prefix_byte = vec128_byte(
                    request_identifier, absolute_index);
            else if (absolute_index < 20)
                list_prefix_byte = selected_u32_q_byte(
                    lane, absolute_index-16);
            else if (absolute_index < 22)
                list_prefix_byte = 8'h80;
        end
    endfunction

    logic [1087:0] selected_fast_block;
    always_comb begin
        selected_fast_block = '0;
        case (selected_primitive)
            P_PRF_INDEX: begin
                selected_fast_block[31*8 +: 8] = 8'd3;
                selected_fast_block[32*8 +: 256] = request_secret_prf;
                selected_fast_block[94*8 +: 8]
                    = {6'b0, request_q[issue_lane][9:8]};
                selected_fast_block[95*8 +: 8]
                    = request_q[issue_lane][7:0];
                selected_fast_block[96*8 +: 8] = 8'h1f;
            end
            P_SEED_ADDRESS: begin
                selected_fast_block[31*8 +: 8] = 8'd4;
                selected_fast_block[32*8 +: 256] = request_secret_seed;
                selected_fast_block[64*8 +: 256] = request_public_seed;
                selected_fast_block[96*8 +: 256]
                    = request_address[issue_lane];
                selected_fast_block[128*8 +: 8] = 8'h1f;
            end
            P_ADDRESS_PRF: begin
                selected_fast_block[31*8 +: 8] = 8'd3;
                selected_fast_block[32*8 +: 256] = request_public_seed;
                selected_fast_block[64*8 +: 256]
                    = request_address[issue_lane];
                if (compose_recipe[issue_lane] == R_MASKED_CHAIN) begin
                    selected_fast_block[88*8 +: 24] = 24'b0;
                    selected_fast_block[91*8 +: 8]
                        = {3'b0, compose_chain_step[issue_lane]};
                end
                selected_fast_block[92*8 +: 24] = 24'b0;
                selected_fast_block[95*8 +: 8]
                    = {6'b0, compose_stage[issue_lane]};
                selected_fast_block[96*8 +: 8] = 8'h1f;
            end
            P_MASKED_F: begin
                selected_fast_block[32*8 +: 256]
                    = compose_key[issue_lane];
                selected_fast_block[64*8 +: 256]
                    = compose_current[issue_lane]
                      ^ compose_mask0[issue_lane];
                selected_fast_block[96*8 +: 8] = 8'h1f;
            end
            P_MASKED_H: begin
                selected_fast_block[31*8 +: 8] = 8'd1;
                selected_fast_block[32*8 +: 256]
                    = compose_key[issue_lane];
                selected_fast_block[64*8 +: 256]
                    = request_left[issue_lane] ^ compose_mask0[issue_lane];
                selected_fast_block[96*8 +: 256]
                    = request_right[issue_lane] ^ compose_mask1[issue_lane];
                selected_fast_block[128*8 +: 8] = 8'h1f;
            end
            P_PREFIX_PRIVATE: begin
                selected_fast_block[0 +: 128] = request_identifier;
                selected_fast_block[18*8 +: 8]
                    = {6'b0, request_q[issue_lane][9:8]};
                selected_fast_block[19*8 +: 8]
                    = request_q[issue_lane][7:0];
                selected_fast_block[21*8 +: 8]
                    = request_item[issue_lane];
                selected_fast_block[22*8 +: 8] = 8'hff;
                selected_fast_block[23*8 +: 256] = request_secret_seed;
                selected_fast_block[55*8 +: 8] = 8'h1f;
            end
            P_PREFIX_CHAIN: begin
                selected_fast_block[0 +: 128] = request_identifier;
                selected_fast_block[18*8 +: 8]
                    = {6'b0, request_q[issue_lane][9:8]};
                selected_fast_block[19*8 +: 8]
                    = request_q[issue_lane][7:0];
                selected_fast_block[21*8 +: 8]
                    = request_item[issue_lane];
                selected_fast_block[22*8 +: 8]
                    = {3'b0, compose_chain_step[issue_lane]};
                selected_fast_block[23*8 +: 256]
                    = compose_current[issue_lane];
                selected_fast_block[55*8 +: 8] = 8'h1f;
            end
            P_PREFIX_LEAF: begin
                selected_fast_block[0 +: 128] = request_identifier;
                selected_fast_block[18*8 +: 8]
                    = 8'd4 + {6'b0, request_q[issue_lane][9:8]};
                selected_fast_block[19*8 +: 8]
                    = request_q[issue_lane][7:0];
                selected_fast_block[20*8 +: 16] = 16'h8282;
                selected_fast_block[22*8 +: 256]
                    = compose_current[issue_lane];
                selected_fast_block[54*8 +: 8] = 8'h1f;
            end
            P_PREFIX_PARENT: begin
                selected_fast_block[0 +: 128] = request_identifier;
                selected_fast_block[16*8 +: 32]
                    = request_address[issue_lane][31:0];
                selected_fast_block[20*8 +: 16] = 16'h8383;
                selected_fast_block[22*8 +: 256]
                    = request_left[issue_lane];
                selected_fast_block[54*8 +: 256]
                    = request_right[issue_lane];
                selected_fast_block[86*8 +: 8] = 8'h1f;
            end
            default: selected_fast_block = '0;
        endcase
        selected_fast_block[1087] = 1'b1;
    end

    logic [127:0] stream_source_beat, stream_block_data;
    integer compose_byte;
    logic [11:0] compose_absolute;
    logic [7:0] compose_rate_byte;
    logic [4:0] list_target_bytes, list_available_bytes, list_fill_bytes;
    integer list_copy_byte;

    always_comb begin
        stream_source_beat = '0;
        case (stream_primitive)
            P_MESSAGE_ROOT: begin
                if (block_index == 0) begin
                    case (append_index)
                        1: stream_source_beat[15*8 +: 8] = 8'd2;
                        2: stream_source_beat
                            = request_randomizer[stream_lane][0 +: 128];
                        3: stream_source_beat
                            = request_randomizer[stream_lane][128 +: 128];
                        4: stream_source_beat = request_root[0 +: 128];
                        5: stream_source_beat = request_root[128 +: 128];
                        7: begin
                            stream_source_beat[14*8 +: 8]
                                = {6'b0, request_q[stream_lane][9:8]};
                            stream_source_beat[15*8 +: 8]
                                = request_q[stream_lane][7:0];
                        end
                        8: stream_source_beat[0 +: 64]
                            = request_message[0 +: 64];
                        default: stream_source_beat = '0;
                    endcase
                end else begin
                    case (append_index)
                        0: stream_source_beat = request_message[8*8 +: 128];
                        1: stream_source_beat = request_message[24*8 +: 128];
                        2: stream_source_beat = request_message[40*8 +: 128];
                        3: stream_source_beat = request_message[56*8 +: 128];
                        4: stream_source_beat[0 +: 120]
                            = request_message[72*8 +: 120];
                        default: stream_source_beat = '0;
                    endcase
                end
            end
            P_PREFIX_MESSAGE: begin
                if (block_index == 0) begin
                    case (append_index)
                        0: stream_source_beat = request_identifier;
                        1: begin
                            stream_source_beat[2*8 +: 8]
                                = {6'b0, request_q[stream_lane][9:8]};
                            stream_source_beat[3*8 +: 8]
                                = request_q[stream_lane][7:0];
                            stream_source_beat[4*8 +: 16] = 16'h8181;
                            stream_source_beat[6*8 +: 80]
                                = request_randomizer[stream_lane][0 +: 80];
                        end
                        2: stream_source_beat
                            = request_randomizer[stream_lane][10*8 +: 128];
                        3: begin
                            stream_source_beat[0 +: 48]
                                = request_randomizer[stream_lane][26*8 +: 48];
                            stream_source_beat[6*8 +: 80]
                                = request_message[0 +: 80];
                        end
                        4: stream_source_beat = request_message[10*8 +: 128];
                        5: stream_source_beat = request_message[26*8 +: 128];
                        6: stream_source_beat = request_message[42*8 +: 128];
                        7: stream_source_beat = request_message[58*8 +: 128];
                        8: stream_source_beat[0 +: 64]
                            = request_message[74*8 +: 64];
                        default: stream_source_beat = '0;
                    endcase
                end else if (append_index == 0)
                    stream_source_beat[0 +: 40]
                        = request_message[82*8 +: 40];
            end
            default: stream_source_beat = '0;
        endcase
    end

    always_comb begin
        stream_block_data = '0;
        compose_absolute = 0;
        compose_rate_byte = 0;
        endpoint_read_index = list_absolute >= 22
            && list_absolute < stream_length
            ? (list_absolute - 22) >> 5 : 0;
        list_target_bytes = append_index == 8 ? 8 : 16;
        list_available_bytes = list_target_bytes - list_fill_index;
        if (list_absolute < 22 && list_absolute + list_available_bytes > 22)
            list_available_bytes = 22 - list_absolute;
        else if (list_absolute >= 22
                 && list_absolute + list_available_bytes < stream_length
                 && ((list_absolute - 22) & 12'd31)
                    + list_available_bytes > 32)
            list_available_bytes = 32 - ((list_absolute - 22) & 12'd31);
        if (list_absolute + list_available_bytes > stream_length)
            list_available_bytes = stream_length - list_absolute;
        list_fill_bytes = list_available_bytes > 0
            ? list_available_bytes : list_target_bytes - list_fill_index;
        for (compose_byte = 0; compose_byte < 16;
             compose_byte = compose_byte + 1) begin
            compose_rate_byte = append_index * 16 + compose_byte;
            compose_absolute = block_offset + compose_rate_byte;
            if (compose_rate_byte < 136) begin
                if (stream_primitive == P_PREFIX_LIST)
                    stream_block_data[compose_byte*8 +: 8]
                        = list_beat_buffer[compose_byte*8 +: 8];
                else if (compose_absolute < stream_length)
                    stream_block_data[compose_byte*8 +: 8]
                        = stream_source_beat[compose_byte*8 +: 8];
                if (stream_block_last && compose_absolute == stream_length)
                    stream_block_data[compose_byte*8 +: 8]
                        = stream_block_data[compose_byte*8 +: 8] ^ 8'h1f;
                if (stream_block_last && compose_rate_byte == 135)
                    stream_block_data[compose_byte*8 +: 8]
                        = stream_block_data[compose_byte*8 +: 8] ^ 8'h80;
            end
        end
    end

    always_comb begin
        external_context_valid = 0;
        external_fast_block_valid = 0;
        external_fast_block_data = 0;
        external_block_valid = 0;
        external_block_data = 0;
        external_block_last = 0;
        if (!stream_active && selected_available) begin
            external_context_valid[issue_lane] = 1'b1;
            if (selected_fast) begin
                external_fast_block_valid[issue_lane] = 1'b1;
                external_fast_block_data[issue_lane*1088 +: 1088]
                    = selected_fast_block;
            end
        end
        if (stream_active && stream_state == STREAM_BLOCK) begin
            external_block_valid[stream_lane] = 1'b1;
            external_block_data[stream_lane*128 +: 128]
                = stream_block_data;
            external_block_last[stream_lane] = stream_block_last;
        end
    end

    assign compose_accept[0] = !stream_active && issue_lane == 0
        && selected_available && external_context_ready[0]
        && (!selected_fast || external_fast_block_ready[0]);
    assign compose_accept[1] = !stream_active && issue_lane == 1
        && selected_available && external_context_ready[1]
        && (!selected_fast || external_fast_block_ready[1]);

    integer lane;
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            issue_rr <= 0;
            stream_active <= 0;
            stream_lane <= 0;
            stream_state <= STREAM_BLOCK;
            block_index <= 0;
            append_index <= 0;
            list_fill_index <= 0;
            for (lane = 0; lane < 2; lane = lane + 1) begin
                hash_contexts[lane] <= 0;
                permutations[lane] <= 0;
                active_cycles[lane] <= 0;
            end
        end else begin
            for (lane = 0; lane < 2; lane = lane + 1) begin
                if (controller_active[lane])
                    active_cycles[lane] <= active_cycles[lane] + 1'b1;
                if (compose_accept[lane]) begin
                    hash_contexts[lane] <= hash_contexts[lane] + 1'b1;
                    if (selected_fast)
                        permutations[lane] <= permutations[lane] + 1'b1;
                end
            end
            if (compose_accept != 0) begin
                issue_rr <= ~issue_lane;
                if (!selected_fast) begin
                    stream_active <= 1;
                    stream_lane <= issue_lane;
                    block_index <= 0;
                    append_index <= 0;
                    list_fill_index <= 0;
                    stream_state <= selected_primitive == P_PREFIX_LIST
                        ? STREAM_LIST_READ : STREAM_BLOCK;
                end
            end
            if (stream_active) begin
                case (stream_state)
                    STREAM_BLOCK: if (external_block_ready[stream_lane]) begin
                        if (append_index == 8) begin
                            permutations[stream_lane]
                                <= permutations[stream_lane] + 1'b1;
                            append_index <= 0;
                            if (stream_block_last)
                                stream_active <= 0;
                            else begin
                                block_index <= block_index + 1'b1;
                                stream_state
                                    <= stream_primitive == P_PREFIX_LIST
                                       ? STREAM_LIST_READ : STREAM_BLOCK;
                            end
                        end else begin
                            append_index <= append_index + 1'b1;
                            if (stream_primitive == P_PREFIX_LIST) begin
                                list_fill_index <= 0;
                                stream_state <= STREAM_LIST_READ;
                            end
                        end
                    end
                    STREAM_LIST_READ:
                        stream_state <= STREAM_LIST_FILL;
                    STREAM_LIST_FILL: begin
                        for (list_copy_byte = 0; list_copy_byte < 16;
                             list_copy_byte = list_copy_byte + 1)
                            if (list_copy_byte >= list_fill_index
                                && list_copy_byte
                                   < list_fill_index + list_fill_bytes) begin
                                if (block_offset + append_offset
                                    + list_copy_byte >= stream_length)
                                    list_beat_buffer[list_copy_byte*8 +: 8]
                                        <= 0;
                                else if (block_offset + append_offset
                                         + list_copy_byte < 22)
                                    list_beat_buffer[list_copy_byte*8 +: 8]
                                        <= list_prefix_byte(stream_lane,
                                            block_offset + append_offset
                                            + list_copy_byte);
                                else
                                    list_beat_buffer[list_copy_byte*8 +: 8]
                                        <= endpoint_read_data[
                                            ((block_offset + append_offset
                                              + list_copy_byte - 22)
                                             & 12'd31)*8 +: 8];
                            end
                        if (list_fill_index + list_fill_bytes
                            >= list_target_bytes) begin
                            list_fill_index <= 0;
                            stream_state <= STREAM_BLOCK;
                        end else begin
                            list_fill_index
                                <= list_fill_index + list_fill_bytes;
                            stream_state <= STREAM_LIST_READ;
                        end
                    end
                    default: stream_state <= STREAM_BLOCK;
                endcase
            end
        end
    end
endmodule

`default_nettype wire
