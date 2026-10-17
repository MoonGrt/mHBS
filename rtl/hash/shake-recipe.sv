`timescale 1ns/1ps
`default_nettype none

// SLH-DSA SHAKE byte recipes. Each accepted request performs exactly one
// complete hash. Fields stay stable until its response is consumed. A caller
// may present a new request on that same edge; the lane never creates one.
module recipe #(
    parameter integer N = 32,
    parameter integer DIGEST_BYTES = 49, INDEX_BITS = 7,
    parameter integer UNROLL = 1,
    parameter integer MAX_MESSAGE_BYTES = 87,
    parameter [15:0] RECIPE_MASK = 16'h101e,
    parameter bit PROFILE_ENABLE = 0
) (
    input wire clk, rst,
    input wire [5:0] node_bytes,
    input wire request_valid,
    output wire request_ready,
    input wire [63:0] request_recipe,
    input wire [N*8-1:0] secret_seed, secret_prf, public_seed, root, randomizer,
    output wire [3:0] message_word_address,
    input wire [63:0] message_word_data,
    input wire [6:0] message_length,
    input wire [4:0] request_layer,
    input wire [63:0] request_tree,
    input wire [9:0] request_leaf,
    input wire [INDEX_BITS-1:0] request_a,
    input wire [31:0] request_b,
    input wire [N*8-1:0] request_left, request_right,
    output wire [INDEX_BITS-1:0] list_index0, list_index1,
    input wire [N*8-1:0] list_data0, list_data1,
    output wire response_valid,
    input wire response_ready,
    output wire [DIGEST_BYTES*8-1:0] response_value,
    output logic error,
    output logic [31:0] hash_count, permutation_count
);
    localparam [3:0] ADDRESS_SEED=1, ADDRESS_VALUE=2, MESSAGE_PRF=3,
        MESSAGE_DIGEST=4, ADDRESS_LIST=12;
    localparam bit STREAM_ENABLE=(RECIPE_MASK & 16'h1018)!=0;
    typedef enum logic [1:0] {IDLE, STREAM, WAIT_HASH, RESPONSE} state_t;
    state_t state;
    wire [3:0] shape=request_recipe[59:56];
    wire [7:0] arity=request_recipe[47:40];
    logic [12:0] input_length;
    logic [2:0] node_words;
    logic [12:0] position;
    logic [4:0] beat;
    logic [INDEX_BITS-1:0] list_cursor;
    logic [4:0] list_remainder;
    wire fixed_block=shape==ADDRESS_SEED || shape==ADDRESS_VALUE;
    // Only the seventeenth word can finish a rate block. At that word the
    // absolute cursor already gives its end; no second block-base counter
    // is needed. block_last is consumed only with that final beat.
    wire stream_last=position+13'd8>input_length;
    wire [5:0] stream_node_bytes={node_words,3'b0};
    wire [6:0] prefix_bytes={1'b0,stream_node_bytes}+7'd32;
    wire [5:0] next_remainder={1'b0,list_remainder}+6'd8;
    // The interface admits only these three node sizes. Use fixed shifts
    // rather than synthesizing an arbitrary 8-by-6-bit length multiplier.
    wire [12:0] list_length=node_bytes==16 ? 13'd48+{1'b0,arity,4'b0}
        : node_bytes==24 ? 13'd56+{1'b0,arity,4'b0}+{2'b0,arity,3'b0}
        : 13'd64+{arity,5'b0};
    wire [6:0] message_prefix=node_bytes==16 ? (shape==MESSAGE_PRF ? 7'd32 : 7'd48)
        : node_bytes==24 ? (shape==MESSAGE_PRF ? 7'd48 : 7'd72)
        : (shape==MESSAGE_PRF ? 7'd64 : 7'd96);
    wire hash_ready, fast_ready, block_ready, digest_valid;
    // Absorb each source word directly into the SHAKE state. The private
    // 64-bit port avoids a second copy of the low word in a staging register.
    // Later rate blocks wait for permutation completion before their first word.
    wire stream_emit=STREAM_ENABLE && state==STREAM;
    wire stream_accept=!stream_emit || block_ready;
    wire [63:0] stream_block_data=STREAM_ENABLE ? stream_data : 64'd0;
    wire valid_shape=shape==ADDRESS_SEED || shape==ADDRESS_VALUE
        || shape==MESSAGE_PRF || shape==MESSAGE_DIGEST || shape==ADDRESS_LIST;
    wire bad_request=!valid_shape || !RECIPE_MASK[shape]
        || !(node_bytes==16 || node_bytes==24 || node_bytes==32) || 32'(node_bytes)>N
        || (shape==ADDRESS_VALUE && arity!=1 && arity!=2)
        || (shape==ADDRESS_LIST && (arity==0 || 32'(arity)>(1<<INDEX_BITS)))
        || ((shape==MESSAGE_PRF || shape==MESSAGE_DIGEST) && 32'(message_length)>MAX_MESSAGE_BYTES);

    assign request_ready=hash_ready && (state==IDLE || (response_valid && response_ready));
    // The SHAKE state already retains the digest. Expose completion directly,
    // then retain only the valid flag when the consumer applies backpressure.
    assign response_valid=state==RESPONSE || (state==WAIT_HASH && digest_valid);
    assign list_index0=list_cursor;
    assign list_index1=list_cursor+1'b1;
    function automatic [31:0] be32(input [31:0] value);
        be32={value[7:0],value[15:8],value[23:16],value[31:24]};
    endfunction
    wire [255:0] address={be32(request_b),be32(32'(request_a)),
        be32({22'd0,request_leaf}),be32({24'd0,request_recipe[55:48]}),
        be32(request_tree[31:0]),be32(request_tree[63:32]),32'd0,
        be32({27'd0,request_layer})};
    function automatic [63:0] node_word(input [255:0] data,input [9:0] index);
        case(index)
            0:node_word=data[63:0];
            1:node_word=data[127:64];
            2:node_word=data[191:128];
            3:node_word=data[255:192];
            default:node_word=0;
        endcase
    endfunction
    localparam integer MESSAGE_WORDS=(MAX_MESSAGE_BYTES+7)/8;
    wire [9:0] message_prefix_words=shape==MESSAGE_PRF ? 2*10'(node_words) : 3*10'(node_words);
    wire [9:0] message_word_index=position[12:3]-message_prefix_words;
    assign message_word_address=message_word_index[3:0];
    function automatic [63:0] source_word(input [9:0] index);
        reg [2:0] source;
        reg [9:0] selected_index;
        begin
            source=0;
            selected_index=index;
            case(shape)
                MESSAGE_PRF: if(RECIPE_MASK[MESSAGE_PRF]) begin
                    if(index<10'(node_words)) source=1;
                    else if(index<2*10'(node_words)) begin source=2;selected_index=index-10'(node_words);end
                end
                MESSAGE_DIGEST: if(RECIPE_MASK[MESSAGE_DIGEST]) begin
                    if(index<10'(node_words)) source=2;
                    else if(index<2*10'(node_words)) begin source=3;selected_index=index-10'(node_words);end
                    else if(index<3*10'(node_words)) begin source=4;selected_index=index-2*10'(node_words);end
                end
                ADDRESS_LIST: if(RECIPE_MASK[ADDRESS_LIST]) begin
                    if(index<10'(node_words)) source=3;
                    else if(index<10'(node_words)+10'd4) begin source=6;selected_index=index-10'(node_words);end
                end
                default:begin end
            endcase
            case(source)
                1:source_word=node_word(256'(secret_prf),selected_index);
                2:source_word=node_word(256'(randomizer),selected_index);
                3:source_word=node_word(256'(public_seed),selected_index);
                4:source_word=node_word(256'(root),selected_index);
                6:source_word=node_word(address,selected_index);
                default:source_word=0;
            endcase
        end
    endfunction

    logic [1087:0] fast_block;
    always @* begin
        fast_block=0;
        case(node_bytes)
            16:begin
                fast_block[0 +:128]=public_seed[127:0];
                fast_block[128 +:256]=address;
                fast_block[384 +:128]=shape==ADDRESS_SEED ? secret_seed[127:0] : request_left[127:0];
                if(shape==ADDRESS_VALUE && arity==2) begin
                    fast_block[512 +:128]=request_right[127:0];
                    fast_block[640 +:8]=8'h1f;
                end else fast_block[512 +:8]=8'h1f;
            end
            24:begin
                fast_block[0 +:192]=192'(public_seed);
                fast_block[192 +:256]=address;
                fast_block[448 +:192]=shape==ADDRESS_SEED ? 192'(secret_seed) : 192'(request_left);
                if(shape==ADDRESS_VALUE && arity==2) begin
                    fast_block[640 +:192]=192'(request_right);
                    fast_block[832 +:8]=8'h1f;
                end else fast_block[640 +:8]=8'h1f;
            end
            default:begin
                fast_block[0 +:256]=256'(public_seed);
                fast_block[256 +:256]=address;
                fast_block[512 +:256]=shape==ADDRESS_SEED ? 256'(secret_seed) : 256'(request_left);
                if(shape==ADDRESS_VALUE && arity==2) begin
                    fast_block[768 +:256]=256'(request_right);
                    fast_block[1024 +:8]=8'h1f;
                end else fast_block[768 +:8]=8'h1f;
            end
        endcase
        fast_block[1087]=1;
    end
    logic [63:0] stream_data;
    integer i;
    wire at_end_word=position[12:3]==input_length[12:3];
    wire past_end_word=position[12:3]>input_length[12:3];
    always @* begin
        stream_data=source_word(position[12:3]);
        if((shape==MESSAGE_PRF || shape==MESSAGE_DIGEST)
            && position[12:3]>=message_prefix_words && 32'(message_word_index)<MESSAGE_WORDS)
            stream_data=message_word_data;
        if(shape==ADDRESS_LIST && position>=13'(prefix_bytes))
            stream_data=node_word(256'(list_data0),{8'd0,list_remainder[4:3]});
        for(i=0;i<8;i=i+1) begin
            if(past_end_word || (at_end_word && 3'(i)>=input_length[2:0]))
                stream_data[i*8 +:8]=0;
            if(at_end_word && 3'(i)==input_length[2:0]) stream_data[i*8 +:8]=8'h1f;
            if(stream_last && beat==16 && i==7) stream_data[i*8+7]=1;
        end
    end
    shake_context #(.UNROLL(UNROLL),.DIGEST_BYTES(DIGEST_BYTES)) sponge (
        .clk,.rst,.context_valid(request_valid && request_ready && !bad_request),.context_ready(hash_ready),
        .fast_block_valid(request_valid && request_ready && !bad_request && fixed_block),.fast_block_ready(fast_ready),
        .fast_block_data(fast_block),.block_valid(stream_emit),.block_ready,
        .block_data(stream_block_data),.block_last(STREAM_ENABLE && stream_last),
        .response_valid(digest_valid),.response_digest(response_value)
    );
    always_ff @(posedge clk) begin
        if(rst) begin
            state<=IDLE;
            error<=0;
            hash_count<=0;
            permutation_count<=0;
            input_length<=0;
            node_words<=0;
            position<=0;
            beat<=0;
            list_cursor<=0;
            list_remainder<=0;
        end else begin
            // Accepting a new caller request has priority over draining the
            // old response. Its digest is observed before this edge updates
            // the sponge, so local feedback needs no extra result register.
            if(request_valid && request_ready) begin
                error<=bad_request;
                position<=0;
                beat<=0;
                list_cursor<=0;
                list_remainder<=0;
                node_words<=node_bytes[5:3];
                case(shape)
                    ADDRESS_LIST:input_length<=list_length;
                    MESSAGE_PRF,MESSAGE_DIGEST:input_length<=13'(message_prefix)+13'(message_length);
                    default:input_length<=0;
                endcase
                if(PROFILE_ENABLE && !bad_request) begin
                    hash_count<=hash_count+1'b1;
                    if(fixed_block) permutation_count<=permutation_count+1'b1;
                end
                state<=bad_request ? RESPONSE : fixed_block ? WAIT_HASH : STREAM;
            end else case(state)
                STREAM: if(STREAM_ENABLE && stream_accept) begin
                    position<=position+13'd8;
                    if(position<13'(prefix_bytes)) begin
                        if(position+13'd8>=13'(prefix_bytes))
                            list_remainder<=5'(position+13'd8-13'(prefix_bytes));
                    end else if(next_remainder>=stream_node_bytes) begin
                        list_remainder<=5'(next_remainder-stream_node_bytes);
                        list_cursor<=list_cursor+1'b1;
                    end else list_remainder<=next_remainder[4:0];
                    if(beat==16) begin
                        beat<=0;
                        if(PROFILE_ENABLE) permutation_count<=permutation_count+1'b1;
                        if(stream_last) state<=WAIT_HASH;
                    end else beat<=beat+1'b1;
                end
                WAIT_HASH:if(digest_valid) state<=response_ready ? IDLE : RESPONSE;
                RESPONSE:if(response_ready) state<=IDLE;
                default:state<=IDLE;
            endcase
        end
    end
endmodule
`default_nettype wire

`timescale 1ns/1ps
`default_nettype none

// One SHAKE256 context per request. A context can absorb multiple rate blocks,
// but completion never starts another hash. The retained state is also the
// result register, so the caller can route a result back into a later request.
module shake_context #(
    parameter integer UNROLL = 1,
    parameter integer DIGEST_BYTES = 49
) (
    input wire clk, rst,
    input wire context_valid,
    output wire context_ready,
    input wire fast_block_valid,
    output wire fast_block_ready,
    input wire [1087:0] fast_block_data,
    input wire block_valid,
    output wire block_ready,
    input wire [63:0] block_data,
    input wire block_last,
    output logic response_valid,
    output wire [DIGEST_BYTES*8-1:0] response_digest
);
    localparam [1:0] IDLE=0, WAIT_BLOCK=1, RUN=2;
    logic [1:0] state;
    logic first_block, running_last;
    logic [4:0] append_index;
    logic [4:0] round_index;
    logic [1599:0] sponge_state;
    wire [1599:0] round_state [0:UNROLL];
    wire [1599:0] advanced_state=round_state[UNROLL];

    assign context_ready=state==IDLE;
    assign block_ready=state==WAIT_BLOCK;
    assign fast_block_ready=(state==IDLE && context_valid)
        || (state==WAIT_BLOCK && first_block && append_index==0);
    assign response_digest=sponge_state[DIGEST_BYTES*8-1:0];
    assign round_state[0]=sponge_state;
    genvar round_step;
    generate for(round_step=0;round_step<UNROLL;round_step=round_step+1) begin: rounds
        localparam [4:0] ROUND_OFFSET=round_step;
        (* keep_hierarchy="yes" *) keccak round_logic (
            .state_in(round_state[round_step]),
            .round_index(round_index+ROUND_OFFSET),
            .state_out(round_state[round_step+1])
        );
    end endgenerate

    wire take_fast=fast_block_valid && fast_block_ready;
    wire take_stream=block_valid && block_ready && !take_fast;
    wire clear_stream=take_stream && first_block && append_index==0;
    genvar word_index;
    generate for(word_index=0;word_index<25;word_index=word_index+1) begin: words
        wire select_stream=word_index<17 && take_stream && append_index==5'(word_index);
        wire [63:0] fast_word;
        if(word_index<17) assign fast_word=fast_block_data[word_index*64 +:64];
        else assign fast_word=64'd0;
        // Absorb directly into one selected word; the lane supplies one
        // 64-bit word per accepting edge, for seventeen edges per rate block.
        wire [63:0] input_word=block_data;
        // Only word zero is selected on the first streaming beat. Every
        // later rate word has already been cleared at that edge.
        wire [63:0] absorb_word=input_word
            ^ (sponge_state[word_index*64 +:64]
                & {64{word_index>=2 || !clear_stream}});
        if(word_index>=17) begin: capacity
            // Both input forms clear the capacity; use the FF clear input
            // rather than carrying a zero alternative through its data mux.
            always_ff @(posedge clk)
                if(!rst) begin
                    if(take_fast || clear_stream)
                        sponge_state[word_index*64 +:64]<=64'd0;
                    else if(state==RUN)
                        sponge_state[word_index*64 +:64]<=advanced_state[word_index*64 +:64];
                end
        end else begin: rate
            wire [63:0] next_word=take_fast ? fast_word
                : select_stream ? absorb_word : advanced_state[word_index*64 +:64];
            always_ff @(posedge clk)
                if(!rst) begin
                    if(clear_stream && !select_stream)
                        sponge_state[word_index*64 +:64]<=64'd0;
                    else if(state==RUN || take_fast || select_stream)
                        sponge_state[word_index*64 +:64]<=next_word;
                end
        end
    end endgenerate

    initial begin
        if(UNROLL<1 || UNROLL>24 || 24%UNROLL!=0)
            $error("single SHAKE context UNROLL must divide 24");
        if(DIGEST_BYTES<1 || DIGEST_BYTES>136)
            $error("single SHAKE context digest must fit one rate block");
    end
    always_ff @(posedge clk) begin
        if(rst) begin
            state<=IDLE;
            first_block<=1;
            running_last<=0;
            append_index<=0;
            round_index<=0;
            response_valid<=0;
        end else begin
            response_valid<=0;
            case(state)
                IDLE: if(context_valid) begin
                    first_block<=1;
                    append_index<=0;
                    if(take_fast) begin
                        running_last<=1;
                        round_index<=0;
                        state<=RUN;
                    end else state<=WAIT_BLOCK;
                end
                WAIT_BLOCK: if(take_fast) begin
                    running_last<=1;
                    round_index<=0;
                    state<=RUN;
                end else if(take_stream) begin
                    if(append_index==16) begin
                        append_index<=0;
                        running_last<=block_last;
                        round_index<=0;
                        state<=RUN;
                    end else append_index<=append_index+1'b1;
                end
                RUN: if(32'(round_index)+UNROLL>=24) begin
                    if(running_last) begin
                        response_valid<=1;
                        state<=IDLE;
                    end else begin
                        first_block<=0;
                        state<=WAIT_BLOCK;
                    end
                end else round_index<=round_index+5'(UNROLL);
                default:state<=IDLE;
            endcase
        end
    end
endmodule
`default_nettype wire
