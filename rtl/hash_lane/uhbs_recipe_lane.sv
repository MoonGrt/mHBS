`timescale 1ns/1ps
`default_nettype none
// ABI 4 byte recipes and local chain feedback. Both physical lanes use this
// module. The dispatcher keeps all request fields stable through response.
module uhbs_recipe_lane #(
    parameter integer N = 16,
    parameter integer DIGEST_BYTES = N==16 ? 34 : 32, INDEX_BITS = 7,
    parameter integer UNROLL = 2,
    parameter integer MAX_MESSAGE_BYTES = 87,
    parameter [15:0] RECIPE_MASK = 16'hffff,
    parameter bit PROFILE_ENABLE = 0
) (
    input wire clk, rst_n,
    input wire [5:0] node_bytes,
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
    input wire [INDEX_BITS-1:0] request_a,
    input wire [31:0] request_b,
    input wire [N*8-1:0] request_left, request_right,
    output wire [INDEX_BITS-1:0] list_index0, list_index1,
    input wire [N*8-1:0] list_data0, list_data1,
    output wire response_valid, input wire response_ready,
    output wire [DIGEST_BYTES*8-1:0] response_value,
    output wire [N*8-1:0] response_capture,
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
    wire compact_chain = RECIPE_MASK[ADDRESS_SEED] && request_chain && request_recipe[59:56] == ADDRESS_SEED;
    wire [31:0] a = request_a;
    wire [31:0] b = request_chain && !seed_phase
        ? (request_step_recipe[55:48] == 3 && request_step_recipe[59:56] == ADDRESS_VALUE
            ? request_b : {27'd0, iteration}) : request_b;
    wire [N*8-1:0] left_value = request_chain ? current_value : request_left;
    wire [31:0] leaf = {22'd0, request_leaf};
    // A node is 16, 24 or 32 bytes. Explicit shifts avoid generic multipliers.
    wire [12:0] list_bytes = node_bytes==16 ? {1'b0,arity,4'b0}
        : node_bytes==24 ? ({1'b0,arity,4'b0}+{2'b0,arity,3'b0})
        : {arity,5'b0};
    logic [12:0] input_length;
    logic [1087:0] fast_block;
    logic [127:0] stream_data;
    logic [255:0] address, masked_address;
    wire fixed_block = (RECIPE_MASK & 16'h3858)==0 || shape == ADDRESS_SEED || shape == ADDRESS_VALUE
        || shape == INDEX_PRF || shape == MASKED_SEED || shape == MASKED_VALUE
        || shape == PREFIX_SEED || shape == PREFIX_VALUE
        || shape == PREFIX_LEAF || shape == PREFIX_PARENT;
    wire [12:0] rate_offset = ({8'd0,rate_block} << 7)+({8'd0,rate_block} << 3);
    wire [12:0] recipe_limit = ({7'd0,recipe[29:24]} << 7)+({7'd0,recipe[29:24]} << 3);
    wire stream_last = rate_offset+13'd136 > input_length;
    wire hash_ready, block_ready, fast_ready, digest_valid, finish_valid;
    wire [DIGEST_BYTES*8-1:0] digest, finish_digest;
    wire [N*8-1:0] compact_capture;
    wire compact_capture_valid, hash_error;
    wire completed = finish_valid;
    wire [DIGEST_BYTES*8-1:0] completed_value = finish_digest;
    logic [N*8-1:0] saved_capture;
    assign response_value=digest;
    assign response_capture=compact_chain ? compact_capture : saved_capture;
    wire [7:0] prefix_bytes = shape == ADDRESS_LIST ? node_bytes+32 : 22;
    logic staged_valid, staged_last;
    logic [127:0] staged_data;
    wire stream_accept = !staged_valid || block_ready;
    wire [12:0] position = rate_offset+{5'd0,beat,4'd0};
    wire [12:0] list_offset = position >= prefix_bytes ? position-prefix_bytes : 0;
    logic [INDEX_BITS-1:0] list_cursor;
    logic [5:0] list_remainder;
    wire [4:0] stream_advance = beat==8 ? 5'd8 : 5'd16;
    wire [6:0] next_remainder = {1'b0,list_remainder}+stream_advance;
    assign list_index0 = list_cursor;
    assign list_index1 = list_index0+1'b1;
    assign request_ready = state == IDLE;
    assign response_valid = state == RESPONSE;

    function automatic [31:0] be32(input [31:0] value);
        be32 = {value[7:0],value[15:8],value[23:16],value[31:24]};
    endfunction
    // All sponge beats start on an eight-byte boundary. Select two words
    // directly instead of shifting a maximum-size concatenated message frame.
    wire [2:0] node_words=node_bytes[5:3];
    wire [703:0] padded_message={8'd0,message_buffer};
    function automatic [63:0] node_word(input [255:0] data,input [5:0] index);
        begin
            case(index)
                0:node_word=data[63:0];1:node_word=data[127:64];
                2:node_word=data[191:128];3:node_word=data[255:192];
                default:node_word=0;
            endcase
        end
    endfunction
    function automatic [63:0] message_word(input [5:0] index);
        begin
            message_word=index<11 ? padded_message[index*64 +:64] : 64'd0;
        end
    endfunction
    function automatic [63:0] prefix_message_word(input [5:0] index);
        begin
            prefix_message_word=index<4 ? node_word(randomizer,index)
                : message_word(index-4);
        end
    endfunction
    function automatic [63:0] source_word(input [5:0] index);
        reg [63:0] lower_word,upper_word;
        begin
            source_word=0;lower_word=0;upper_word=0;
            case(shape)
                MESSAGE_PRF: if(RECIPE_MASK[MESSAGE_PRF]) begin
                    if(index<node_words) source_word=node_word(secret_prf,index);
                    else if(index<2*node_words) source_word=node_word(randomizer,index-node_words);
                    else source_word=message_word(index-2*node_words);
                end
                MESSAGE_DIGEST: if(RECIPE_MASK[MESSAGE_DIGEST]) begin
                    if(index<node_words) source_word=node_word(randomizer,index);
                    else if(index<2*node_words) source_word=node_word(public_seed,index-node_words);
                    else if(index<3*node_words) source_word=node_word(root,index-2*node_words);
                    else source_word=message_word(index-3*node_words);
                end
                ROOT_MESSAGE: if(RECIPE_MASK[ROOT_MESSAGE]) begin
                    if(index==4-1) source_word=64'h0200000000000000;
                    else if(index<4) source_word=0;
                    else if(index<8) source_word=node_word(randomizer,index-4);
                    else if(index<12) source_word=node_word(root,index-8);
                    else if(index==16-1) source_word={be32(leaf),32'd0};
                    else if(index>=16) source_word=message_word(index-16);
                end
                PREFIX_MESSAGE: if(RECIPE_MASK[PREFIX_MESSAGE]) begin
                    lower_word=prefix_message_word(index-3);
                    upper_word=prefix_message_word(index-2);
                    if(index<2) source_word=index[0] ? identifier[127:64] : identifier[63:0];
                    else if(index==2) source_word={upper_word[15:0],16'h8181,be32(leaf)};
                    else source_word={upper_word[15:0],lower_word[63:16]};
                end
                ADDRESS_LIST: if(RECIPE_MASK[ADDRESS_LIST]) begin
                    if(index<node_words) source_word=node_word(public_seed,index);
                    else if(index<node_words+4) source_word=node_word(address,index-node_words);
                    else source_word=node_word(list_data0,index-node_words-4);
                end
                PREFIX_LIST: if(RECIPE_MASK[PREFIX_LIST]) begin
                    case(index)
                        0:source_word=identifier[63:0];1:source_word=identifier[127:64];
                        2:source_word={list_data0[15:0],16'h8080,be32(leaf)};
                        3:source_word=list_data0[79:16];default:source_word=0;
                    endcase
                end
                default:source_word=0;
            endcase
        end
    endfunction
    logic [511:0] list_pair;
    always @* begin
        case(node_bytes)
            16:list_pair={256'd0,list_data1[127:0],list_data0[127:0]};
            24:list_pair={128'd0,list_data1[191:0],list_data0[191:0]};
            default:list_pair={list_data1,list_data0};
        endcase
    end
    wire [127:0] list_window=list_pair >> {list_remainder,3'b0};
    wire [5:0] stream_word_index=position[8:3];
    logic [127:0] stream_payload;
    always_comb begin
        stream_payload=(shape==ADDRESS_LIST || shape==PREFIX_LIST) && position>=prefix_bytes
            ? list_window : {source_word(stream_word_index+6'd1),source_word(stream_word_index)};
    end

    integer i, absolute;
    always @* begin
        address = {be32(b),be32(a),be32(leaf),be32(domain),
            be32(request_tree[31:0]),be32(request_tree[63:32]),32'd0,be32(request_layer)};
        masked_address = {be32(compound),be32(b),be32(a),be32(leaf),be32(domain),96'd0};
        case (shape)
            ADDRESS_SEED, ADDRESS_VALUE: input_length = node_bytes+32+(shape == ADDRESS_SEED ? node_bytes : list_bytes);
            MESSAGE_PRF: input_length = 2*node_bytes+message_length;
            MESSAGE_DIGEST: input_length = 3*node_bytes+message_length;
            INDEX_PRF: input_length = 96;
            ROOT_MESSAGE: input_length = 128+message_length;
            MASKED_SEED: input_length = 128;
            MASKED_VALUE: input_length = compound < arity+1 ? 13'd96 : 13'd64+{arity,5'd0};
            PREFIX_SEED, PREFIX_VALUE: input_length = 55;
            PREFIX_MESSAGE: input_length = 54+message_length;
            ADDRESS_LIST: input_length = node_bytes+32+list_bytes;
            PREFIX_LIST: input_length = 13'd22+{arity,5'd0};
            PREFIX_LEAF: input_length = 54;
            PREFIX_PARENT: input_length = 86;
            default: input_length = 0;
        endcase
    end
    // Select shared frame fields before alignment. This avoids replicating
    // every seed/value/key/mask selector for all three node lengths.
    logic [255:0] frame0,frame1,frame2,frame3;
    logic [183:0] frame_prefix;
    logic [7:0] frame_domain;
    logic frame_two;
    logic [2:0] frame_layout;
    always @* begin
        frame0=0;frame1=0;frame2=0;frame3=0;frame_prefix=0;
        frame_domain=0;frame_two=0;frame_layout=7;
        case(shape)
            ADDRESS_SEED,ADDRESS_VALUE: if(RECIPE_MASK[ADDRESS_SEED] || RECIPE_MASK[ADDRESS_VALUE]) begin
                frame_layout=0;frame0=public_seed;frame1=address;
                frame2=shape==ADDRESS_SEED ? secret_seed : left_value;
                frame_two=shape==ADDRESS_VALUE && arity==2;
                frame3=frame_two ? request_right : 256'd0;
            end
            INDEX_PRF: if(RECIPE_MASK[INDEX_PRF]) begin
                frame_layout=1;frame_domain=3;frame1=secret_prf;frame2={be32(leaf),224'd0};
            end
            MASKED_SEED: if(RECIPE_MASK[MASKED_SEED]) begin
                frame_layout=2;frame_domain=4;frame1=secret_seed;frame2=public_seed;frame3=masked_address;
            end
            MASKED_VALUE: if(RECIPE_MASK[MASKED_VALUE]) begin
                if(compound<arity+1) begin
                    frame_layout=1;frame_domain=3;frame1=public_seed;frame2=masked_address;
                end else begin
                    frame_layout=3;frame_domain=arity-1'b1;frame1=temporary_key;
                    frame2=left_value^mask0;frame_two=arity==2;
                    frame3=frame_two ? request_right^mask1 : 256'd0;
                end
            end
            PREFIX_SEED,PREFIX_VALUE: if(RECIPE_MASK[PREFIX_SEED] || RECIPE_MASK[PREFIX_VALUE]) begin
                frame_layout=4;
                frame_prefix={shape==PREFIX_SEED ? 8'hff : b[7:0],8'(request_a),8'd0,be32(leaf),identifier};
                frame1=shape==PREFIX_SEED ? secret_seed : left_value;
            end
            PREFIX_LEAF,PREFIX_PARENT: if(RECIPE_MASK[PREFIX_LEAF] || RECIPE_MASK[PREFIX_PARENT]) begin
                frame_layout=5;
                frame_prefix={8'd0,shape==PREFIX_LEAF ? 16'h8282 : 16'h8383,be32(request_b),identifier};
                frame1=left_value;frame_two=shape==PREFIX_PARENT;
                frame2=frame_two ? request_right : 256'd0;
            end
            default:begin end
        endcase
    end
    always @* begin
        fast_block=0;
        case(node_bytes)
            16: begin
                fast_block[0 +:128]=public_seed[127:0];
                fast_block[128 +:256]=address;
                fast_block[384 +:128]=shape==ADDRESS_SEED ? secret_seed[127:0] : left_value[127:0];
                if(shape==ADDRESS_VALUE && arity==2) begin
                    fast_block[512 +:128]=request_right[127:0];
                    fast_block[640 +:8]=8'h1f;
                end else fast_block[512 +:8]=8'h1f;
            end
            24: begin
                fast_block[0 +:192]=public_seed[191:0];
                fast_block[192 +:256]=address;
                fast_block[448 +:192]=shape==ADDRESS_SEED ? secret_seed[191:0] : left_value[191:0];
                if(shape==ADDRESS_VALUE && arity==2) begin
                    fast_block[640 +:192]=request_right[191:0];
                    fast_block[832 +:8]=8'h1f;
                end else fast_block[640 +:8]=8'h1f;
            end
            32: case(frame_layout)
                0: begin
                    fast_block[0 +:256]=frame0[255:0];
                    fast_block[256 +:256]=frame1;
                    fast_block[512 +:256]=frame2[255:0];
                    fast_block[768 +:256]=frame3[255:0];
                    if(frame_two) fast_block[1024 +:8]=8'h1f;
                    else fast_block[768 +:8]=8'h1f;
                end
                1: begin
                    fast_block[248 +:8]=frame_domain;
                    fast_block[256 +:256]=frame1[255:0];
                    fast_block[512 +:256]=frame2;
                    fast_block[768 +:8]=8'h1f;
                end
                2: begin
                    fast_block[248 +:8]=frame_domain;
                    fast_block[256 +:256]=frame1[255:0];
                    fast_block[512 +:256]=frame2[255:0];
                    fast_block[768 +:256]=frame3;
                    fast_block[1024 +:8]=8'h1f;
                end
                3: begin
                    fast_block[248 +:8]=frame_domain;
                    fast_block[256 +:256]=frame1[255:0];
                    fast_block[512 +:256]=frame2[255:0];
                    fast_block[768 +:256]=frame3[255:0];
                    if(frame_two) fast_block[1024 +:8]=8'h1f;
                    else fast_block[768 +:8]=8'h1f;
                end
                4: begin
                    fast_block[183:0]=frame_prefix;
                    fast_block[184 +:256]=frame1[255:0];
                    fast_block[440 +:8]=8'h1f;
                end
                5: begin
                    fast_block[175:0]=frame_prefix[175:0];
                    fast_block[176 +:256]=frame1[255:0];
                    fast_block[432 +:256]=frame2[255:0];
                    if(frame_two) fast_block[688 +:8]=8'h1f;
                    else fast_block[432 +:8]=8'h1f;
                end
                default:begin end
            endcase
            default:begin end
        endcase
        fast_block[1087]=1'b1;
    end
    always_comb begin
        stream_data = stream_payload;
        for (i=0; i<16; i=i+1) begin
            absolute = position+i;
            if (beat*16+i < 136) begin
                if (absolute >= input_length) stream_data[i*8 +: 8] = 0;
                if (absolute == input_length) stream_data[i*8 +: 8] = 8'h1f;
                if (stream_last && beat*16+i == 135) stream_data[i*8+7] = 1'b1;
            end else stream_data[i*8 +: 8] = 0;
        end
    end

    logic [(N+32)*8-1:0] live_chain_prefix;
    always @* begin
        live_chain_prefix=0;
        case(node_bytes)
            16:live_chain_prefix[383:0]={address,public_seed[127:0]};
            24:live_chain_prefix[447:0]={address,public_seed[191:0]};
            default:live_chain_prefix[511:0]={address,public_seed};
        endcase
    end
    uhbs_compact_shake_context_lane #(.UNROLL(UNROLL),.N(N),.DIGEST_BYTES(DIGEST_BYTES),.STREAM_CHAIN_ENABLE(0)) sponge (
        .clk, .rst_n, .node_bytes, .chain_prefix_data(live_chain_prefix), .context_valid(state == START), .context_ready(hash_ready),
        .fast_block_valid(state == START && fixed_block), .fast_block_ready(fast_ready),
        .fast_block_data(fast_block), .chain_enable(compact_chain),
        .chain_prefix(compact_chain),
        .chain_prefix_preserve_counter(request_step_recipe[55:48] == 3),
        .chain_prefix_domain(request_step_recipe[50:48]),
        .chain_count(request_steps+5'd1),
        .capture_enable(compact_chain && request_capture),
        .capture_after(request_capture_after+5'd1),
        .block_valid(staged_valid), .block_ready, .block_data(staged_data),
        .block_last(staged_last), .response_valid(digest_valid), .response_digest(digest),
        .finish_valid, .finish_digest, .capture_digest(compact_capture),
        .capture_valid(compact_capture_valid), .error(hash_error)
    );

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            staged_valid<=0; staged_last<=0; staged_data<=0;
            list_cursor<=0; list_remainder<=0;
            state <= IDLE; error <= 0; hash_count <= 0; permutation_count <= 0;
            seed_phase <= 1; iteration <= 0; compound <= 0; rate_block <= 0; beat <= 0;
        end else begin
            if(staged_valid && block_ready) staged_valid<=0;
            if (hash_error) begin error <= 1; state <= RESPONSE; end
            else case (state)
                IDLE: if (request_valid) begin
                    staged_valid<=0;
                    list_cursor<=0; list_remainder<=0;
                    error <= 0; seed_phase <= 1; iteration <= 0; compound <= 0;
                    current_value <= request_left;
                    rate_block <= 0; beat <= 0;
                    if (request_recipe[63:60] != 1 || request_recipe[59:56] == 0
                            || !RECIPE_MASK[request_recipe[59:56]]
                            || (node_bytes!=32 && !(request_recipe[59:56]==1 || request_recipe[59:56]==2 || request_recipe[59:56]==3 || request_recipe[59:56]==4 || request_recipe[59:56]==12))
                            || request_steps > 15) begin error <= 1; state <= RESPONSE; end
                    else state <= START;
                end
                START: if (hash_ready) begin
                    if (PROFILE_ENABLE) begin
                        hash_count <= hash_count+(compact_chain ? request_steps+1 : 1);
                        if (fixed_block) permutation_count <= permutation_count+(compact_chain ? request_steps+1 : 1);
                    end
                    if (input_length >= recipe_limit || recipe[29:24] == 0) begin
                        error <= 1; state <= RESPONSE;
                    end else state <= fixed_block ? WAIT_HASH : STREAM;
                end
                STREAM: if (stream_accept) begin
                    staged_valid<=1; staged_data<=stream_data; staged_last<=stream_last;
                    begin
                        if(position < prefix_bytes) begin
                            if(position+stream_advance >= prefix_bytes)
                                list_remainder <= position+stream_advance-prefix_bytes;
                        end else if(next_remainder >= node_bytes) begin
                            list_remainder <= next_remainder-node_bytes;
                            list_cursor <= list_cursor+1'b1;
                        end else list_remainder <= next_remainder;
                    end
                    if (beat == 8) begin
                        beat <= 0;
                        if (PROFILE_ENABLE) permutation_count <= permutation_count+1;
                        if (stream_last) state <= WAIT_HASH;
                        else rate_block <= rate_block+1'b1;
                    end else beat <= beat+1'b1;
                end
                WAIT_HASH: if (completed) begin
                    if (compact_chain) begin
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
                            saved_capture <= completed_value[N*8-1:0];
                        if (request_chain && (seed_phase ? request_steps != 0 : iteration+1 < request_steps)) begin
                            seed_phase <= 0;
                            if (!seed_phase) iteration <= iteration+1'b1;
                            state <= START;
                        end else begin
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
