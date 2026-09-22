`timescale 1ns/1ps
`default_nettype none
// ABI 3 byte recipes and local chain feedback. Both physical lanes use this
// module. The dispatcher keeps all request fields stable through response.
module uhbs_recipe_lane #(
    parameter integer N = 16,
    parameter integer UNROLL = 2,
    parameter integer MAX_MESSAGE_BYTES = 87,
    parameter [15:0] RECIPE_MASK = 16'hffff,
    parameter bit PROFILE_ENABLE = 0
) (
    input wire clk, rst_n,
    input wire request_valid, output wire request_ready,
    input wire [63:0] request_recipe, request_step_recipe,
    input wire request_chain,
    input wire [4:0] request_steps, request_capture_after,
    input wire request_capture,
    input wire [N*8-1:0] secret_seed, secret_prf, public_seed, root, randomizer,
    input wire [127:0] identifier,
    input wire [MAX_MESSAGE_BYTES*8-1:0] message_buffer,
    input wire [6:0] message_length,
    input wire [4:0] request_layer,
    input wire [63:0] request_tree,
    input wire [9:0] request_leaf,
    input wire [6:0] request_a,
    input wire [31:0] request_b,
    input wire [N*8-1:0] request_left, request_right,
    output wire [6:0] list_index0, list_index1,
    input wire [N*8-1:0] list_data0, list_data1,
    output wire response_valid, input wire response_ready,
    output logic [271:0] response_value,
    output logic [N*8-1:0] response_capture,
    output logic error,
    output logic [31:0] hash_count, permutation_count
);
    localparam [3:0] ADDRESS_SEED=1, ADDRESS_VALUE=2, MESSAGE_PRF=3,
        MESSAGE_DIGEST=4, INDEX_PRF=5, ROOT_MESSAGE=6, MASKED_SEED=7,
        MASKED_VALUE=8, PREFIX_SEED=9, PREFIX_VALUE=10, PREFIX_MESSAGE=11,
        ADDRESS_LIST=12, PREFIX_LIST=13, PREFIX_LEAF=14, PREFIX_PARENT=15;
    typedef enum logic [2:0] {IDLE, START, STREAM, WAIT_HASH, RESPONSE} state_t;
    state_t state;
    logic seed_phase;
    logic [4:0] iteration;
    logic [1:0] compound;
    logic [N*8-1:0] current_value, temporary_key, mask0, mask1;
    logic [4:0] rate_block;
    logic [3:0] beat;
    wire [63:0] recipe = request_chain && !seed_phase
        ? request_step_recipe : request_recipe;
    wire [3:0] shape = recipe[59:56];
    wire [7:0] domain = recipe[55:48];
    wire [7:0] arity = recipe[47:40];
    wire compact_chain = N == 16 && request_chain;
    wire [31:0] a = request_a;
    wire [31:0] b = request_chain && !seed_phase
        ? (request_step_recipe[55:48] == 3 && N == 16
            ? request_b : {27'd0, iteration}) : request_b;
    wire [N*8-1:0] left_value = N==32 && request_chain ? current_value : request_left;
    wire [31:0] leaf = {22'd0, request_leaf};
    logic [11:0] input_length;
    logic [1087:0] fast_block;
    logic [127:0] stream_data;
    logic [255:0] address, masked_address;
    wire fixed_block = shape == ADDRESS_SEED || shape == ADDRESS_VALUE
        || shape == INDEX_PRF || shape == MASKED_SEED || shape == MASKED_VALUE
        || shape == PREFIX_SEED || shape == PREFIX_VALUE
        || shape == PREFIX_LEAF || shape == PREFIX_PARENT;
    wire [11:0] rate_offset = ({7'd0,rate_block} << 7)+({7'd0,rate_block} << 3);
    wire [11:0] recipe_limit = ({7'd0,recipe[28:24]} << 7)+({7'd0,recipe[28:24]} << 3);
    wire stream_last = rate_offset+12'd136 > input_length;
    wire hash_ready, block_ready, fast_ready, digest_valid, finish_valid;
    wire [271:0] digest, finish_digest;
    wire [127:0] compact_capture;
    wire compact_capture_valid, hash_error;
    wire completed = compact_chain ? digest_valid : finish_valid;
    wire [271:0] completed_value = compact_chain ? digest : finish_digest;
    wire [7:0] prefix_bytes = shape == ADDRESS_LIST ? N+32 : 22;
    wire [11:0] position = rate_offset+{4'd0,beat,4'd0};
    wire [11:0] list_offset = position >= prefix_bytes ? position-prefix_bytes : 0;
    assign list_index0 = list_offset / N;
    assign list_index1 = list_index0+1'b1;
    assign request_ready = state == IDLE;
    assign response_valid = state == RESPONSE;

    function automatic [31:0] be32(input [31:0] value);
        be32 = {value[7:0],value[15:8],value[23:16],value[31:24]};
    endfunction
    // Assemble each source once, then extract a beat with one shared shift.
    // Per-byte variable indexing replicated the address and selection networks.
    localparam integer STREAM_BITS=(MAX_MESSAGE_BYTES+4*N>3*N+32
        ? MAX_MESSAGE_BYTES+4*N : 3*N+32)*8;
    logic [STREAM_BITS-1:0] stream_source;
    logic [11:0] stream_offset;
    always @* begin
        stream_source=0;
        stream_offset=position;
        case(shape)
            MESSAGE_PRF: if(RECIPE_MASK[MESSAGE_PRF]) begin
                stream_source[0 +: N*8]=secret_prf;
                stream_source[N*8 +: N*8]=randomizer;
                stream_source[2*N*8 +: MAX_MESSAGE_BYTES*8]=message_buffer;
            end
            MESSAGE_DIGEST: if(RECIPE_MASK[MESSAGE_DIGEST]) begin
                stream_source[0 +: N*8]=randomizer;
                stream_source[N*8 +: N*8]=public_seed;
                stream_source[2*N*8 +: N*8]=root;
                stream_source[3*N*8 +: MAX_MESSAGE_BYTES*8]=message_buffer;
            end
            ROOT_MESSAGE: if(RECIPE_MASK[ROOT_MESSAGE]) begin
                stream_source[(N-1)*8 +: 8]=2;
                stream_source[N*8 +: N*8]=randomizer;
                stream_source[2*N*8 +: N*8]=root;
                stream_source[(4*N-4)*8 +: 32]=be32(leaf);
                stream_source[4*N*8 +: MAX_MESSAGE_BYTES*8]=message_buffer;
            end
            PREFIX_MESSAGE: if(RECIPE_MASK[PREFIX_MESSAGE]) begin
                stream_source[0 +: 128]=identifier;
                stream_source[128 +: 32]=be32(leaf);
                stream_source[160 +: 16]=16'h8181;
                stream_source[176 +: N*8]=randomizer;
                stream_source[(22+N)*8 +: MAX_MESSAGE_BYTES*8]=message_buffer;
            end
            ADDRESS_LIST, PREFIX_LIST: if(RECIPE_MASK[ADDRESS_LIST] || RECIPE_MASK[PREFIX_LIST]) begin
                if(position<prefix_bytes) begin
                    if(shape==ADDRESS_LIST) begin
                        stream_source[0 +: N*8]=public_seed;
                        stream_source[N*8 +: 256]=address;
                        stream_source[(N+32)*8 +: 2*N*8]={list_data1,list_data0};
                    end else begin
                        stream_source[0 +: 128]=identifier;
                        stream_source[128 +: 32]=be32(leaf);
                        stream_source[160 +: 16]=16'h8080;
                        stream_source[176 +: 2*N*8]={list_data1,list_data0};
                    end
                end else begin
                    stream_source[0 +: 2*N*8]={list_data1,list_data0};
                    stream_offset=list_offset % N;
                end
            end
            default: begin end
        endcase
    end

    integer i, absolute;
    always @* begin
        address = {be32(b),be32(a),be32(leaf),be32(domain),
            be32(request_tree[31:0]),be32(request_tree[63:32]),32'd0,be32(request_layer)};
        masked_address = {be32(compound),be32(b),be32(a),be32(leaf),be32(domain),96'd0};
        case (shape)
            ADDRESS_SEED, ADDRESS_VALUE: input_length = N+32+(shape == ADDRESS_SEED ? N : N*arity);
            MESSAGE_PRF: input_length = 2*N+message_length;
            MESSAGE_DIGEST: input_length = 3*N+message_length;
            INDEX_PRF: input_length = 2*N+32;
            ROOT_MESSAGE: input_length = 4*N+message_length;
            MASKED_SEED: input_length = 3*N+32;
            MASKED_VALUE: input_length = compound < arity+1 ? 2*N+32 : (2+arity)*N;
            PREFIX_SEED, PREFIX_VALUE: input_length = 23+N;
            PREFIX_MESSAGE: input_length = 22+N+message_length;
            ADDRESS_LIST: input_length = N+32+N*arity;
            PREFIX_LIST: input_length = 22+N*arity;
            PREFIX_LEAF: input_length = 22+N;
            PREFIX_PARENT: input_length = 22+2*N;
            default: input_length = 0;
        endcase
    end
    always @* begin
        fast_block = 0;
        case (shape)
            ADDRESS_SEED, ADDRESS_VALUE: if(RECIPE_MASK[ADDRESS_SEED] || RECIPE_MASK[ADDRESS_VALUE]) begin
                fast_block[0 +: N*8] = public_seed;
                fast_block[N*8 +: 256] = address;
                fast_block[(N+32)*8 +: N*8] = shape == ADDRESS_SEED ? secret_seed : left_value;
                if (shape == ADDRESS_VALUE && arity == 2)
                    fast_block[(2*N+32)*8 +: N*8] = request_right;
                if (shape == ADDRESS_VALUE && arity == 2)
                    fast_block[(3*N+32)*8 +: 8] = 8'h1f;
                else fast_block[(2*N+32)*8 +: 8] = 8'h1f;
            end
            INDEX_PRF: if(RECIPE_MASK[INDEX_PRF]) begin
                fast_block[(N-1)*8 +: 8] = 3;
                fast_block[N*8 +: N*8] = secret_prf;
                fast_block[(2*N+28)*8 +: 32] = be32(leaf);
                fast_block[(2*N+32)*8 +: 8] = 8'h1f;
            end
            MASKED_SEED: if(RECIPE_MASK[MASKED_SEED]) begin
                fast_block[(N-1)*8 +: 8] = 4;
                fast_block[N*8 +: N*8] = secret_seed;
                fast_block[2*N*8 +: N*8] = public_seed;
                fast_block[3*N*8 +: 256] = masked_address;
                fast_block[(3*N+32)*8 +: 8] = 8'h1f;
            end
            MASKED_VALUE: if(RECIPE_MASK[MASKED_VALUE]) begin
                if (compound < arity+1) begin
                    fast_block[(N-1)*8 +: 8] = 3;
                    fast_block[N*8 +: N*8] = public_seed;
                    fast_block[2*N*8 +: 256] = masked_address;
                    fast_block[(2*N+32)*8 +: 8] = 8'h1f;
                end else begin
                    fast_block[(N-1)*8 +: 8] = arity-1'b1;
                    fast_block[N*8 +: N*8] = temporary_key;
                    fast_block[2*N*8 +: N*8] = left_value ^ mask0;
                    if (arity == 2) fast_block[3*N*8 +: N*8] = request_right ^ mask1;
                    if (arity == 2) fast_block[4*N*8 +: 8] = 8'h1f;
                    else fast_block[3*N*8 +: 8] = 8'h1f;
                end
            end
            PREFIX_SEED, PREFIX_VALUE: if(RECIPE_MASK[PREFIX_SEED] || RECIPE_MASK[PREFIX_VALUE]) begin
                fast_block[0 +: 128] = identifier;
                fast_block[128 +: 32] = be32(leaf);
                fast_block[20*8 +: 16] = {1'b0,request_a,8'd0};
                fast_block[22*8 +: 8] = shape == PREFIX_SEED ? 8'hff : b[7:0];
                fast_block[23*8 +: N*8] = shape == PREFIX_SEED ? secret_seed : left_value;
                fast_block[(23+N)*8 +: 8] = 8'h1f;
            end
            PREFIX_LEAF, PREFIX_PARENT: if(RECIPE_MASK[PREFIX_LEAF] || RECIPE_MASK[PREFIX_PARENT]) begin
                fast_block[0 +: 128] = identifier;
                fast_block[128 +: 32] = be32(request_b);
                fast_block[20*8 +: 16] = shape == PREFIX_LEAF ? 16'h8282 : 16'h8383;
                fast_block[22*8 +: N*8] = left_value;
                if (shape == PREFIX_PARENT) fast_block[(22+N)*8 +: N*8] = request_right;
                if (shape == PREFIX_PARENT) fast_block[(22+2*N)*8 +: 8] = 8'h1f;
                else fast_block[(22+N)*8 +: 8] = 8'h1f;
            end
            default: begin end
        endcase
        // Padding is placed at constant offsets above. A variable part-select
        // write here creates a wide barrel-write mux at every sponge input.
        fast_block[1087] = 1'b1;
    end
    always_comb begin
        stream_data = stream_source >> (stream_offset*8);
        for (i=0; i<16; i=i+1) begin
            absolute = position+i;
            if (beat*16+i < 136) begin
                if (absolute >= input_length) stream_data[i*8 +: 8] = 0;
                if (absolute == input_length) stream_data[i*8 +: 8] = 8'h1f;
                if (stream_last && beat*16+i == 135) stream_data[i*8+7] = 1'b1;
            end else stream_data[i*8 +: 8] = 0;
        end
    end

    uhbs_compact_shake_context_lane #(.UNROLL(UNROLL)) sponge (
        .clk, .rst_n, .context_valid(state == START), .context_ready(hash_ready),
        .fast_block_valid(state == START && fixed_block), .fast_block_ready(fast_ready),
        .fast_block_data(fast_block), .chain_enable(compact_chain),
        .chain_prefix(compact_chain),
        .chain_prefix_preserve_counter(request_step_recipe[55:48] == 3),
        .chain_prefix_domain(request_step_recipe[50:48]),
        .chain_count(request_steps+5'd1),
        .capture_enable(compact_chain && request_capture),
        .capture_after(request_capture_after+5'd1),
        .block_valid(state == STREAM), .block_ready, .block_data(stream_data),
        .block_last(stream_last), .response_valid(digest_valid), .response_digest(digest),
        .finish_valid, .finish_digest, .capture_digest(compact_capture),
        .capture_valid(compact_capture_valid), .error(hash_error)
    );

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= IDLE; error <= 0; hash_count <= 0; permutation_count <= 0;
            seed_phase <= 1; iteration <= 0; compound <= 0; rate_block <= 0; beat <= 0;
        end else begin
            if (hash_error) begin error <= 1; state <= RESPONSE; end
            else case (state)
                IDLE: if (request_valid) begin
                    error <= 0; seed_phase <= 1; iteration <= 0; compound <= 0;
                    current_value <= request_left;
                    rate_block <= 0; beat <= 0;
                    if (request_recipe[63:60] != 1 || request_recipe[59:56] == 0
                            || !RECIPE_MASK[request_recipe[59:56]]
                            || request_steps > 15) begin error <= 1; state <= RESPONSE; end
                    else state <= START;
                end
                START: if (hash_ready) begin
                    if (PROFILE_ENABLE) begin
                        hash_count <= hash_count+(compact_chain ? request_steps+1 : 1);
                        if (fixed_block) permutation_count <= permutation_count+(compact_chain ? request_steps+1 : 1);
                    end
                    if (input_length >= recipe_limit || recipe[28:24] == 0) begin
                        error <= 1; state <= RESPONSE;
                    end else state <= fixed_block ? WAIT_HASH : STREAM;
                end
                STREAM: if (block_ready) begin
                    if (beat == 8) begin
                        beat <= 0;
                        if (PROFILE_ENABLE) permutation_count <= permutation_count+1;
                        if (stream_last) state <= WAIT_HASH;
                        else rate_block <= rate_block+1'b1;
                    end else beat <= beat+1'b1;
                end
                WAIT_HASH: if (completed) begin
                    if (compact_chain) begin
                        response_value <= completed_value;
                        response_capture <= compact_capture;
                        state <= RESPONSE;
                    end else if (RECIPE_MASK[MASKED_VALUE] && shape == MASKED_VALUE && compound < arity+1) begin
                        case (compound)
                            0: temporary_key <= completed_value[N*8-1:0];
                            1: mask0 <= completed_value[N*8-1:0];
                            default: mask1 <= completed_value[N*8-1:0];
                        endcase
                        compound <= compound+1'b1;
                        state <= START;
                    end else begin
                        compound <= 0;
                        current_value <= completed_value[N*8-1:0];
                        if (request_capture && (seed_phase ? request_capture_after == 0
                            : request_capture_after == iteration+1))
                            response_capture <= completed_value[N*8-1:0];
                        if (request_chain && (seed_phase ? request_steps != 0 : iteration+1 < request_steps)) begin
                            seed_phase <= 0;
                            if (!seed_phase) iteration <= iteration+1'b1;
                            state <= START;
                        end else begin
                            response_value <= completed_value;
                            state <= RESPONSE;
                        end
                    end
                end
                RESPONSE: if (response_ready) state <= IDLE;
                default: state <= IDLE;
            endcase
        end
    end
endmodule
`default_nettype wire
