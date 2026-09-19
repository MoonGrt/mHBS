`timescale 1ns/1ps
`default_nettype none

// Descriptor-selected n=32 recipe executor.  Recipe names describe byte-flow
// shapes rather than signature algorithms, so two identical instances can
// execute every operation required by both stateful profiles.
module micro_hbs_stateful_recipe_lane #(
    parameter integer UNROLL = 2,
    parameter integer MAX_MESSAGE_BYTES = 87,
    parameter bit EXTERNAL_SHAKE = 1'b0
) (
    input  wire         clk,
    input  wire         rst_n,
    input  wire         request_valid,
    output wire         request_ready,
    input  wire [3:0]   request_recipe,
    input  wire [255:0] request_secret_seed,
    input  wire [255:0] request_secret_prf,
    input  wire [255:0] request_public_seed,
    input  wire [255:0] request_root,
    input  wire [127:0] request_identifier,
    input  wire [255:0] request_randomizer,
    input  wire [MAX_MESSAGE_BYTES*8-1:0] request_message,
    input  wire [6:0]   request_message_length,
    input  wire [9:0]   request_q,
    input  wire [6:0]   request_item,
    input  wire [4:0]   request_steps,
    input  wire [255:0] request_address,
    input  wire [255:0] request_left,
    input  wire [255:0] request_right,
    output logic [6:0]   endpoint_read_index,
    input  wire [255:0] endpoint_read_data,
    output wire         response_valid,
    input  wire         response_ready,
    output logic [255:0] response_value,
    output logic        error,
    output logic [31:0] hash_contexts,
    output logic [31:0] permutations,
    output logic [31:0] active_cycles,

    // Primitive SHAKE service.  In the unified product these ports connect
    // both recipe frontends to the same two physical U2 lanes used by SLH.
    output wire         external_context_valid,
    input  wire         external_context_ready,
    output wire         external_fast_block_valid,
    input  wire         external_fast_block_ready,
    output wire [1087:0] external_fast_block_data,
    output wire         external_block_valid,
    input  wire         external_block_ready,
    output wire [127:0] external_block_data,
    output wire         external_block_last,
    input  wire         external_response_valid,
    input  wire [271:0] external_response_digest,
    input  wire         external_finish_valid,
    input  wire [271:0] external_finish_digest,
    input  wire         external_error
);
    // Public recipe ABI used by descriptor image v2.
    localparam logic [3:0] R_PRF_INDEX       = 4'd1;
    localparam logic [3:0] R_MESSAGE_ROOT    = 4'd2;
    localparam logic [3:0] R_MASKED_CHAIN    = 4'd3;
    localparam logic [3:0] R_MASKED_PARENT   = 4'd4;
    localparam logic [3:0] R_PREFIX_MESSAGE  = 4'd5;
    localparam logic [3:0] R_PREFIX_CHAIN    = 4'd6;
    localparam logic [3:0] R_PREFIX_LIST     = 4'd7;
    localparam logic [3:0] R_PREFIX_LEAF     = 4'd8;
    localparam logic [3:0] R_PREFIX_PARENT   = 4'd9;

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

    typedef enum logic [3:0] {
        S_IDLE, S_START, S_BLOCK, S_WAIT, S_RESPONSE, S_ERROR,
        S_LIST_READ, S_LIST_FILL, S_FAST
    } state_t;
    state_t state;

    logic [3:0] primitive_kind;
    // The dispatcher holds every request field stable until response_valid.
    // Do not duplicate the job and descriptor registers in each physical lane;
    // only feedback and compound-stage values below are lane-local state.
    wire [3:0] recipe = request_recipe;
    wire [255:0] secret_seed = request_secret_seed;
    wire [255:0] secret_prf = request_secret_prf;
    wire [255:0] public_seed = request_public_seed;
    wire [255:0] root = request_root;
    wire [127:0] identifier = request_identifier;
    wire [255:0] randomizer = request_randomizer;
    wire [MAX_MESSAGE_BYTES*8-1:0] message = request_message;
    wire [6:0] message_length = request_message_length;
    wire [9:0] q = request_q;
    wire [6:0] item = request_item;
    wire [4:0] requested_steps = request_steps;
    wire [255:0] address = request_address;
    wire [255:0] left_value = request_left;
    wire [255:0] right_value = request_right;
    logic [255:0] current_value, temporary_key;
    logic [255:0] mask0, mask1;
    logic [4:0] chain_step;
    logic [1:0] compound_stage;
    logic [11:0] primitive_length;
    logic [4:0] block_index;
    logic [3:0] append_index;
    logic [3:0] list_fill_index;
    logic [127:0] list_beat_buffer;

    wire hash_ready, block_ready, fast_block_ready, digest_valid, hash_error;
    wire finish_valid;
    wire [271:0] digest_wide;
    wire [271:0] finish_digest_wide;
    wire [255:0] digest = digest_wide[255:0];
    wire digest_available = digest_valid || finish_valid;
    wire [255:0] completed_digest = finish_valid
        ? finish_digest_wide[255:0] : digest;
    logic hash_start, block_valid;
    logic [127:0] block_data;
    logic [127:0] source_beat;
    logic [1087:0] fast_block_data;
    logic block_last;
    // 136 = 128 + 8.  Spell this as shifts so synthesis cannot consume a DSP
    // for a tiny rate-block address calculation.
    wire [11:0] block_offset = ({8'b0, block_index} << 7)
        + ({8'b0, block_index} << 3);
    wire [11:0] bytes_remaining = primitive_length - block_offset;
    wire [11:0] append_offset = ({8'b0, append_index} << 4);
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

    function automatic [7:0] be_q_byte(input integer index);
        begin
            case (index)
                0: be_q_byte = {6'b0, q[9:8]};
                1: be_q_byte = q[7:0];
                default: be_q_byte = 8'b0;
            endcase
        end
    endfunction

    function automatic [7:0] u32_q_byte(input integer index);
        begin
            case (index)
                0, 1: u32_q_byte = 8'b0;
                2: u32_q_byte = {6'b0, q[9:8]};
                3: u32_q_byte = q[7:0];
                default: u32_q_byte = 8'b0;
            endcase
        end
    endfunction

    function automatic [7:0] address_byte(
        input integer index, input [7:0] key_mask, input [7:0] step
    );
        begin
            if (index >= 24 && index < 28 && recipe == R_MASKED_CHAIN)
                address_byte = index == 27 ? step : 8'b0;
            else if (index >= 28 && index < 32)
                address_byte = index == 31 ? key_mask : 8'b0;
            else
                address_byte = address[index*8 +: 8];
        end
    endfunction

    function automatic [7:0] list_prefix_byte(input integer absolute_index);
        begin
            list_prefix_byte = 8'b0;
            if (absolute_index < 16)
                list_prefix_byte = vec128_byte(identifier, absolute_index);
            else if (absolute_index < 20)
                list_prefix_byte = u32_q_byte(absolute_index-16);
            else if (absolute_index < 22)
                list_prefix_byte = 8'h80;
        end
    endfunction

    integer compose_byte;
    logic [11:0] compose_absolute;
    logic [7:0] compose_rate_byte;
    logic [4:0] list_target_bytes;
    logic [4:0] list_available_bytes;
    logic [4:0] list_fill_bytes;
    integer list_copy_byte;
    wire fast_eligible = primitive_kind != P_MESSAGE_ROOT
        && primitive_kind != P_PREFIX_MESSAGE
        && primitive_kind != P_PREFIX_LIST;

    always_comb begin
        fast_block_data = '0;
        case (primitive_kind)
            P_PRF_INDEX: begin
                fast_block_data[31*8 +: 8] = 8'd3;
                fast_block_data[32*8 +: 256] = secret_prf;
                fast_block_data[94*8 +: 8] = {6'b0, q[9:8]};
                fast_block_data[95*8 +: 8] = q[7:0];
                fast_block_data[96*8 +: 8] = 8'h1f;
            end
            P_SEED_ADDRESS: begin
                fast_block_data[31*8 +: 8] = 8'd4;
                fast_block_data[32*8 +: 256] = secret_seed;
                fast_block_data[64*8 +: 256] = public_seed;
                fast_block_data[96*8 +: 256] = address;
                fast_block_data[128*8 +: 8] = 8'h1f;
            end
            P_ADDRESS_PRF: begin
                fast_block_data[31*8 +: 8] = 8'd3;
                fast_block_data[32*8 +: 256] = public_seed;
                fast_block_data[64*8 +: 256] = address;
                if (recipe == R_MASKED_CHAIN) begin
                    fast_block_data[88*8 +: 24] = 24'b0;
                    fast_block_data[91*8 +: 8] = {3'b0, chain_step};
                end
                fast_block_data[92*8 +: 24] = 24'b0;
                fast_block_data[95*8 +: 8] = {6'b0, compound_stage};
                fast_block_data[96*8 +: 8] = 8'h1f;
            end
            P_MASKED_F: begin
                fast_block_data[32*8 +: 256] = temporary_key;
                fast_block_data[64*8 +: 256] = current_value ^ mask0;
                fast_block_data[96*8 +: 8] = 8'h1f;
            end
            P_MASKED_H: begin
                fast_block_data[31*8 +: 8] = 8'd1;
                fast_block_data[32*8 +: 256] = temporary_key;
                fast_block_data[64*8 +: 256] = left_value ^ mask0;
                fast_block_data[96*8 +: 256] = right_value ^ mask1;
                fast_block_data[128*8 +: 8] = 8'h1f;
            end
            P_PREFIX_PRIVATE: begin
                fast_block_data[0 +: 128] = identifier;
                fast_block_data[18*8 +: 8] = {6'b0, q[9:8]};
                fast_block_data[19*8 +: 8] = q[7:0];
                fast_block_data[21*8 +: 8] = item;
                fast_block_data[22*8 +: 8] = 8'hff;
                fast_block_data[23*8 +: 256] = secret_seed;
                fast_block_data[55*8 +: 8] = 8'h1f;
            end
            P_PREFIX_CHAIN: begin
                fast_block_data[0 +: 128] = identifier;
                fast_block_data[18*8 +: 8] = {6'b0, q[9:8]};
                fast_block_data[19*8 +: 8] = q[7:0];
                fast_block_data[21*8 +: 8] = item;
                fast_block_data[22*8 +: 8] = {3'b0, chain_step};
                fast_block_data[23*8 +: 256] = current_value;
                fast_block_data[55*8 +: 8] = 8'h1f;
            end
            P_PREFIX_LEAF: begin
                fast_block_data[0 +: 128] = identifier;
                fast_block_data[18*8 +: 8] = 8'd4 + {6'b0, q[9:8]};
                fast_block_data[19*8 +: 8] = q[7:0];
                fast_block_data[20*8 +: 16] = 16'h8282;
                fast_block_data[22*8 +: 256] = current_value;
                fast_block_data[54*8 +: 8] = 8'h1f;
            end
            P_PREFIX_PARENT: begin
                fast_block_data[0 +: 128] = identifier;
                fast_block_data[16*8 +: 32] = address[31:0];
                fast_block_data[20*8 +: 16] = 16'h8383;
                fast_block_data[22*8 +: 256] = left_value;
                fast_block_data[54*8 +: 256] = right_value;
                fast_block_data[86*8 +: 8] = 8'h1f;
            end
            default: fast_block_data = '0;
        endcase
        fast_block_data[1087] = 1'b1;
    end
    // The two variable-length message recipes have fixed prefixes and at
    // most two rate blocks.  Map whole 128-bit beats explicitly instead of
    // instantiating sixteen independent variable byte selectors per beat.
    always_comb begin
        source_beat = '0;
        case (primitive_kind)
            P_MESSAGE_ROOT: begin
                if (block_index == 0) begin
                    case (append_index)
                        1: source_beat[15*8 +: 8] = 8'd2;
                        2: source_beat = randomizer[0 +: 128];
                        3: source_beat = randomizer[128 +: 128];
                        4: source_beat = root[0 +: 128];
                        5: source_beat = root[128 +: 128];
                        7: begin
                            source_beat[14*8 +: 8] = {6'b0, q[9:8]};
                            source_beat[15*8 +: 8] = q[7:0];
                        end
                        8: source_beat[0 +: 64] = message[0 +: 64];
                        default: source_beat = '0;
                    endcase
                end else begin
                    case (append_index)
                        0: source_beat = message[8*8 +: 128];
                        1: source_beat = message[24*8 +: 128];
                        2: source_beat = message[40*8 +: 128];
                        3: source_beat = message[56*8 +: 128];
                        4: source_beat[0 +: 120] = message[72*8 +: 120];
                        default: source_beat = '0;
                    endcase
                end
            end
            P_PREFIX_MESSAGE: begin
                if (block_index == 0) begin
                    case (append_index)
                        0: source_beat = identifier;
                        1: begin
                            source_beat[2*8 +: 8] = {6'b0, q[9:8]};
                            source_beat[3*8 +: 8] = q[7:0];
                            source_beat[4*8 +: 16] = 16'h8181;
                            source_beat[6*8 +: 80] = randomizer[0 +: 80];
                        end
                        2: source_beat = randomizer[10*8 +: 128];
                        3: begin
                            source_beat[0 +: 48] = randomizer[26*8 +: 48];
                            source_beat[6*8 +: 80] = message[0 +: 80];
                        end
                        4: source_beat = message[10*8 +: 128];
                        5: source_beat = message[26*8 +: 128];
                        6: source_beat = message[42*8 +: 128];
                        7: source_beat = message[58*8 +: 128];
                        8: source_beat[0 +: 64] = message[74*8 +: 64];
                        default: source_beat = '0;
                    endcase
                end else if (append_index == 0)
                    source_beat[0 +: 40] = message[82*8 +: 40];
            end
            default: source_beat = '0;
        endcase
    end

    always_comb begin
        block_data = '0;
        compose_absolute = 0;
        compose_rate_byte = 0;
        block_last = bytes_remaining <= 135;
        endpoint_read_index = list_absolute >= 22
            && list_absolute < primitive_length
            ? (list_absolute - 22) >> 5 : 0;
        list_target_bytes = append_index == 8 ? 8 : 16;
        list_available_bytes = list_target_bytes - list_fill_index;
        if (list_absolute < 22 && list_absolute + list_available_bytes > 22)
            list_available_bytes = 22 - list_absolute;
        else if (list_absolute >= 22
                 && list_absolute + list_available_bytes < primitive_length
                 && ((list_absolute - 22) & 12'd31)
                    + list_available_bytes > 32)
            list_available_bytes = 32 - ((list_absolute - 22) & 12'd31);
        if (list_absolute + list_available_bytes > primitive_length)
            list_available_bytes = primitive_length - list_absolute;
        list_fill_bytes = list_available_bytes > 0
            ? list_available_bytes : list_target_bytes - list_fill_index;
        for (compose_byte = 0; compose_byte < 16;
             compose_byte = compose_byte + 1) begin
            compose_rate_byte = append_index * 16 + compose_byte;
            compose_absolute = block_offset + compose_rate_byte;
            if (compose_rate_byte < 136) begin
                if (primitive_kind == P_PREFIX_LIST)
                    block_data[compose_byte*8 +: 8]
                        = list_beat_buffer[compose_byte*8 +: 8];
                else if (compose_absolute < primitive_length)
                    block_data[compose_byte*8 +: 8]
                        = source_beat[compose_byte*8 +: 8];
                if (block_last && compose_absolute == primitive_length)
                    block_data[compose_byte*8 +: 8]
                        = block_data[compose_byte*8 +: 8] ^ 8'h1f;
                if (block_last && compose_rate_byte == 135)
                    block_data[compose_byte*8 +: 8]
                        = block_data[compose_byte*8 +: 8] ^ 8'h80;
            end
        end
    end

    assign request_ready = state == S_IDLE;
    assign response_valid = state == S_RESPONSE || state == S_ERROR;
    always_comb begin
        hash_start = state == S_START;
        block_valid = state == S_BLOCK;
    end

    assign external_context_valid = hash_start;
    assign external_fast_block_valid = state == S_START && fast_eligible;
    assign external_fast_block_data = fast_block_data;
    assign external_block_valid = block_valid;
    assign external_block_data = block_data;
    assign external_block_last = block_last;

    generate if (!EXTERNAL_SHAKE) begin : local_shake_service
        micro_hbs_compact_shake_context_lane #(.UNROLL(UNROLL)) shake (
            .clk, .rst_n, .context_valid(hash_start),
            .context_ready(hash_ready),
            .fast_block_valid(state == S_START && fast_eligible),
            .fast_block_ready,
            .fast_block_data(fast_block_data),
            .chain_enable(1'b0), .chain_prefix(1'b0),
            .chain_prefix_preserve_counter(1'b0),
            .chain_prefix_domain(3'b0), .chain_count(5'd1),
            .capture_enable(1'b0), .capture_after(5'b0),
            .block_valid, .block_ready, .block_data, .block_last,
            .response_valid(digest_valid), .response_digest(digest_wide),
            .finish_valid, .finish_digest(finish_digest_wide),
            .capture_digest(), .capture_valid(), .error(hash_error)
        );
    end else begin : shared_shake_service
        assign hash_ready = external_context_ready;
        assign fast_block_ready = external_fast_block_ready;
        assign block_ready = external_block_ready;
        assign digest_valid = external_response_valid;
        assign digest_wide = external_response_digest;
        assign finish_valid = external_finish_valid;
        assign finish_digest_wide = external_finish_digest;
        assign hash_error = external_error;
    end endgenerate

    task automatic set_primitive(
        input logic [3:0] next_primitive,
        input logic [11:0] next_length
    );
        begin
            primitive_kind <= next_primitive;
            primitive_length <= next_length;
            block_index <= '0;
            append_index <= '0;
            list_fill_index <= '0;
            state <= S_START;
        end
    endtask

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= S_IDLE;
            error <= 1'b0;
            hash_contexts <= '0;
            permutations <= '0;
            active_cycles <= '0;
        end else begin
            if (state != S_IDLE)
                active_cycles <= active_cycles + 1'b1;
            if (hash_error) begin
                error <= 1'b1;
                state <= S_ERROR;
            end else case (state)
                S_IDLE: begin
                    if (request_valid) begin
                        chain_step <= '0;
                        compound_stage <= '0;
                        error <= 1'b0;
                        case (request_recipe)
                            R_PRF_INDEX: begin
                                set_primitive(P_PRF_INDEX, 12'd96);
                            end
                            R_MESSAGE_ROOT:
                                set_primitive(P_MESSAGE_ROOT,
                                              12'd128+request_message_length);
                            R_MASKED_CHAIN: begin
                                set_primitive(P_SEED_ADDRESS, 12'd128);
                            end
                            R_MASKED_PARENT: begin
                                compound_stage <= 0;
                                set_primitive(P_ADDRESS_PRF, 12'd96);
                            end
                            R_PREFIX_MESSAGE:
                                set_primitive(P_PREFIX_MESSAGE,
                                              12'd54+request_message_length);
                            R_PREFIX_CHAIN: begin
                                set_primitive(P_PREFIX_PRIVATE, 12'd55);
                            end
                            R_PREFIX_LIST:
                                set_primitive(P_PREFIX_LIST, 12'd2166);
                            R_PREFIX_LEAF: begin
                                current_value <= request_left;
                                set_primitive(P_PREFIX_LEAF, 12'd54);
                            end
                            R_PREFIX_PARENT: begin
                                set_primitive(P_PREFIX_PARENT, 12'd86);
                            end
                            default: begin
                                error <= 1'b1;
                                state <= S_ERROR;
                            end
                        endcase
                    end
                end
                S_START: begin
                    if (hash_ready) begin
                        hash_contexts <= hash_contexts + 1'b1;
                        if (primitive_kind == P_PREFIX_LIST)
                            state <= S_LIST_READ;
                        else if (fast_eligible) begin
                            permutations <= permutations + 1'b1;
                            state <= S_WAIT;
                        end else
                            state <= S_BLOCK;
                    end
                end
                S_BLOCK: begin
                    if (block_ready) begin
                        if (append_index == 8) begin
                            permutations <= permutations + 1'b1;
                            append_index <= 0;
                            if (block_last)
                                state <= S_WAIT;
                            else begin
                                block_index <= block_index + 1'b1;
                                state <= primitive_kind == P_PREFIX_LIST
                                    ? S_LIST_READ : S_BLOCK;
                            end
                        end else begin
                            append_index <= append_index + 1'b1;
                            if (primitive_kind == P_PREFIX_LIST) begin
                                list_fill_index <= 0;
                                state <= S_LIST_READ;
                            end
                        end
                    end
                end
                S_LIST_READ: state <= S_LIST_FILL;
                S_LIST_FILL: begin
                    for (list_copy_byte = 0; list_copy_byte < 16;
                         list_copy_byte = list_copy_byte + 1)
                        if (list_copy_byte >= list_fill_index
                            && list_copy_byte
                               < list_fill_index + list_fill_bytes) begin
                            if (block_offset + append_offset + list_copy_byte
                                >= primitive_length)
                                list_beat_buffer[list_copy_byte*8 +: 8] <= 0;
                            else if (block_offset + append_offset
                                     + list_copy_byte
                                     < 22)
                                list_beat_buffer[list_copy_byte*8 +: 8]
                                    <= list_prefix_byte(
                                        block_offset + append_offset
                                        + list_copy_byte);
                            else
                                list_beat_buffer[list_copy_byte*8 +: 8]
                                    <= endpoint_read_data[
                                        ((block_offset + append_offset
                                          + list_copy_byte - 22) & 12'd31)*8
                                        +: 8];
                        end
                    if (list_fill_index + list_fill_bytes
                        >= list_target_bytes) begin
                        list_fill_index <= 0;
                        state <= S_BLOCK;
                    end else begin
                        list_fill_index <= list_fill_index + list_fill_bytes;
                        state <= S_LIST_READ;
                    end
                end
                S_WAIT: begin
                    if (digest_available) begin
                        case (recipe)
                            R_MASKED_CHAIN: begin
                                if (primitive_kind == P_SEED_ADDRESS) begin
                                    current_value <= completed_digest;
                                    if (requested_steps == 0) begin
                                        response_value <= completed_digest;
                                        state <= S_RESPONSE;
                                    end else begin
                                        compound_stage <= 0;
                                        set_primitive(P_ADDRESS_PRF, 12'd96);
                                    end
                                end else if (primitive_kind == P_ADDRESS_PRF) begin
                                    if (compound_stage == 0) begin
                                        temporary_key <= completed_digest;
                                        compound_stage <= 1;
                                        set_primitive(P_ADDRESS_PRF, 12'd96);
                                    end else begin
                                        mask0 <= completed_digest;
                                        set_primitive(P_MASKED_F, 12'd96);
                                    end
                                end else begin
                                    current_value <= completed_digest;
                                    if (chain_step + 1'b1 >= requested_steps) begin
                                        response_value <= completed_digest;
                                        state <= S_RESPONSE;
                                    end else begin
                                        chain_step <= chain_step + 1'b1;
                                        compound_stage <= 0;
                                        set_primitive(P_ADDRESS_PRF, 12'd96);
                                    end
                                end
                            end
                            R_MASKED_PARENT: begin
                                if (primitive_kind == P_ADDRESS_PRF) begin
                                    case (compound_stage)
                                        0: begin
                                            temporary_key <= completed_digest;
                                            compound_stage <= 1;
                                            set_primitive(P_ADDRESS_PRF, 12'd96);
                                        end
                                        1: begin
                                            mask0 <= completed_digest;
                                            compound_stage <= 2;
                                            set_primitive(P_ADDRESS_PRF, 12'd96);
                                        end
                                        default: begin
                                            mask1 <= completed_digest;
                                            set_primitive(P_MASKED_H, 12'd128);
                                        end
                                    endcase
                                end else begin
                                    response_value <= completed_digest;
                                    state <= S_RESPONSE;
                                end
                            end
                            R_PREFIX_CHAIN: begin
                                current_value <= completed_digest;
                                if (primitive_kind == P_PREFIX_PRIVATE) begin
                                    if (requested_steps == 0) begin
                                        response_value <= completed_digest;
                                        state <= S_RESPONSE;
                                    end else begin
                                        set_primitive(P_PREFIX_CHAIN, 12'd55);
                                    end
                                end else if (chain_step + 1'b1 >= requested_steps) begin
                                    response_value <= completed_digest;
                                    state <= S_RESPONSE;
                                end else begin
                                    chain_step <= chain_step + 1'b1;
                                    set_primitive(P_PREFIX_CHAIN, 12'd55);
                                end
                            end
                            default: begin
                                response_value <= completed_digest;
                                state <= S_RESPONSE;
                            end
                        endcase
                    end
                end
                S_RESPONSE: if (response_ready) state <= S_IDLE;
                S_ERROR: if (response_ready) state <= S_IDLE;
                default: state <= S_ERROR;
            endcase
        end
    end
endmodule

`default_nettype wire
