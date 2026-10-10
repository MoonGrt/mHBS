`timescale 1ns/1ps
`default_nettype none
// ABI 4 byte recipes and local chain feedback. Both physical lanes use this
// module. The dispatcher keeps all request fields stable through response.
module recipe #(
    parameter integer N = 16,
    parameter integer DIGEST_BYTES = N==16 ? 34 : 32, INDEX_BITS = 7,
    parameter integer UNROLL = 2, PIPELINE = 1,
    parameter integer MAX_MESSAGE_BYTES = 87,
    parameter [15:0] RECIPE_MASK = 16'hffff,
    parameter bit SHARED_STATE=0, PROFILE_ENABLE = 0,
    localparam integer TAG_BITS=PIPELINE>1 ? $clog2(PIPELINE) : 1
) (
    input wire clk, rst,
    input wire batch_mode,batch_request_valid,output wire batch_request_ready,
    input wire [TAG_BITS-1:0] batch_request_tag,
    input wire [4:0] batch_steps,batch_capture_after,input wire batch_capture_enable,
    input wire [19:0] batch_leaf,input wire [7:0] batch_a,input wire [31:0] batch_b,
    input wire [1:0] batch_family,input wire batch_no_seed,
    input wire [3:0] batch_start,input wire [255:0] batch_initial_value,
    input wire [3:0] batch_fixed_shape,input wire batch_pair,input wire [255:0] batch_right,
    input wire [7:0] batch_seed_domain,batch_step_domain,
    output wire batch_response_valid,input wire batch_response_ready,
    output wire [TAG_BITS-1:0] batch_response_tag,
    output wire [255:0] batch_response_digest,batch_response_capture,
    input wire [TAG_BITS-1:0] batch_read_tag,
    output wire [255:0] batch_read_digest,batch_read_capture,
    output wire [63:0] batch_hashes,batch_permutations,
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
    input wire [19:0] request_leaf,
    input wire [INDEX_BITS-1:0] request_a,
    input wire [31:0] request_b,
    input wire [N*8-1:0] request_left, request_right,
    output wire [INDEX_BITS-1:0] list_index0, list_index1,list_next_index0,
    input wire [N*8-1:0] list_data0, list_data1,
    output wire response_valid, input wire response_ready,
    output wire [DIGEST_BYTES*8-1:0] response_value,
    output wire [N*8-1:0] response_capture,
    output logic error,
    output logic [63:0] hash_count, permutation_count
);
    localparam [3:0] ADDRESS_SEED=1, ADDRESS_VALUE=2, MESSAGE_PRF=3,
        MESSAGE_DIGEST=4, INDEX_PRF=5, ROOT_MESSAGE=6, MASKED_SEED=7,
        MASKED_VALUE=8, PREFIX_SEED=9, PREFIX_VALUE=10, PREFIX_MESSAGE=11,
        ADDRESS_LIST=12, PREFIX_LIST=13, PREFIX_LEAF=14, PREFIX_PARENT=15;
    localparam bit UNIFIED_FIXED=PIPELINE==4 && UNROLL==1;
    localparam bit LEGACY_MASKED=RECIPE_MASK[MASKED_VALUE] && !UNIFIED_FIXED;
    typedef enum logic [2:0] {IDLE, START, STREAM, WAIT_HASH, RESPONSE,FIXED_ISSUE,FIXED_WAIT} state_t;
    state_t state;
    wire chain_feedback_valid;
    wire [3:0] chain_feedback_counter;
    logic seed_phase;
    logic [4:0] iteration;
    logic [1:0] compound;
    // Masked legacy recipes need a value across intermediate hashes. SLH
    // chains instead reuse the sponge's retained digest at the next START.
    logic [N*8-1:0] legacy_value, temporary_key, mask0, mask1;
    wire [N*8-1:0] current_value = LEGACY_MASKED ? legacy_value
        : seed_phase ? request_left : digest[N*8-1:0];
    localparam bit STREAM_ENABLE = (RECIPE_MASK & 16'h3858)!=0;
    logic [4:0] rate_block;
    logic [3:0] beat;
    logic stream_half;
    wire [63:0] recipe = request_chain && !seed_phase
        ? request_step_recipe : request_recipe;
    wire [3:0] shape = recipe[59:56];
    logic [15:0] seed_shapes,step_shapes;
    logic [12:0] seed_length,step_length;
    logic [2:0] stream_node_words;
    wire [15:0] shapes=request_chain && !seed_phase ? step_shapes : seed_shapes;
    // Decode lengths once in the existing request stage. In particular the
    // ADDRESS_LIST arity/24-byte-node addition must not feed every padding
    // byte comparator during STREAM. Request fields remain stable until the
    // response, but their registered decode cuts that wide data-path cone.
    function automatic [12:0] decode_length(input [63:0] desc);
        reg [12:0] nodes;
        begin
            nodes=node_bytes==16 ? {1'b0,desc[47:40],4'b0}
                : node_bytes==24 ? ({1'b0,desc[47:40],4'b0}+{2'b0,desc[47:40],3'b0})
                : {desc[47:40],5'b0};
            if(!STREAM_ENABLE || !RECIPE_MASK[desc[59:56]]) decode_length=0;
            else case(desc[59:56])
                ADDRESS_SEED: decode_length=node_bytes+32+node_bytes;
                ADDRESS_VALUE,ADDRESS_LIST: decode_length=node_bytes+32+nodes;
                MESSAGE_PRF: decode_length=2*node_bytes+message_length;
                MESSAGE_DIGEST: decode_length=3*node_bytes+message_length;
                INDEX_PRF: decode_length=96;
                ROOT_MESSAGE: decode_length=128+message_length;
                MASKED_SEED: decode_length=128;
                MASKED_VALUE: decode_length=13'd64+{desc[47:40],5'd0};
                PREFIX_SEED,PREFIX_VALUE: decode_length=55;
                PREFIX_MESSAGE: decode_length=54+message_length;
                PREFIX_LIST: decode_length=13'd22+{desc[47:40],5'd0};
                PREFIX_LEAF: decode_length=54;
                PREFIX_PARENT: decode_length=86;
                default: decode_length=0;
            endcase
        end
    endfunction
    always_ff @(posedge clk) begin
        if(!rst && state==IDLE && request_valid) begin
            seed_shapes<=(16'b1 << request_recipe[59:56]) & RECIPE_MASK;
            step_shapes<=(16'b1 << request_step_recipe[59:56]) & RECIPE_MASK;
            seed_length<=decode_length(request_recipe);
            step_length<=decode_length(request_step_recipe);
            stream_node_words<=node_bytes[5:3];
        end
    end
    wire [7:0] domain = recipe[55:48];
    wire [7:0] arity = recipe[47:40];
    wire compact_chain = !UNIFIED_FIXED && RECIPE_MASK[ADDRESS_SEED] && request_chain && request_recipe[59:56] == ADDRESS_SEED;
    wire [31:0] a = request_a;
    wire [31:0] b = chain_feedback_valid
        ? (request_step_recipe[55:48]==3 ? request_b : {28'd0,chain_feedback_counter})
        : request_chain && !seed_phase
        ? (request_step_recipe[55:48] == 3 && request_step_recipe[59:56] == ADDRESS_VALUE
            ? request_b : {27'd0, iteration}) : request_b;
    wire [N*8-1:0] left_value = request_chain ? current_value : request_left;
    wire [7:0] address_domain=chain_feedback_valid ? request_step_recipe[55:48] : domain;
    wire [31:0] leaf = {12'd0, request_leaf};
    wire [12:0] input_length = LEGACY_MASKED && shapes[MASKED_VALUE]
        && compound < arity+1 ? 13'd96
        : request_chain && !seed_phase ? step_length : seed_length;
    wire [5:0] stream_node_bytes={stream_node_words,3'b0};
    logic [1087:0] fast_block;
    logic [127:0] stream_data;
    logic [255:0] address, masked_address;
    wire fixed_block = !UNIFIED_FIXED && ((RECIPE_MASK & 16'h3858)==0 || shapes[ADDRESS_SEED] || shapes[ADDRESS_VALUE]
        || shapes[INDEX_PRF] || shapes[MASKED_SEED] || shapes[MASKED_VALUE]
        || shapes[PREFIX_SEED] || shapes[PREFIX_VALUE]
        || shapes[PREFIX_LEAF] || shapes[PREFIX_PARENT]);
    wire [12:0] rate_offset = ({8'd0,rate_block} << 7)+({8'd0,rate_block} << 3);
    wire [12:0] recipe_limit = ({7'd0,recipe[29:24]} << 7)+({7'd0,recipe[29:24]} << 3);
    wire stream_last = rate_offset+13'd136 > input_length;
    wire hash_ready, block_ready, fast_ready, finish_valid;
    wire [DIGEST_BYTES*8-1:0] digest, finish_digest;
    wire [N*8-1:0] compact_capture;
    logic hash_error;
    wire completed = finish_valid;
    wire [DIGEST_BYTES*8-1:0] completed_value = finish_digest;
    assign response_value=bridge_response ? {{(DIGEST_BYTES*8-N*8){1'b0}},engine_digest[N*8-1:0]} : digest;
    assign response_capture=UNIFIED_FIXED ? engine_capture[N*8-1:0] : compact_capture;
    // Capture both chain modes in the sponge's existing register bank, on
    // the same final-round edge used by the former lane-local copy.
    wire capture_single = request_capture
        && !(LEGACY_MASKED && shapes[MASKED_VALUE] && compound < arity+1)
        && (seed_phase ? request_capture_after==0 : request_capture_after==iteration+1);
    wire [7:0] prefix_bytes = shapes[ADDRESS_LIST] ? stream_node_bytes+32 : 22;
    logic staged_valid, staged_last;
    logic [127:0] staged_data;
    wire stream_accept = !staged_valid || block_ready;
    // P4 emits sixteen bytes per STREAM cycle, then the final eight bytes
    // of the 136-byte rate. Other configurations retain eight-byte beats.
    // Keeping a cursor avoids a rate_block*136 + beat*16 adder chain
    // ahead of the source selector and each padding-byte comparator.
    logic [12:0] position;
    wire [12:0] list_offset = position >= prefix_bytes ? position-prefix_bytes : 0;
    logic [INDEX_BITS-1:0] list_cursor;
    logic [5:0] list_remainder;
    wire [4:0] stream_advance = UNIFIED_FIXED && beat!=8 ? 5'd16 : 5'd8;
    wire [6:0] next_remainder = {1'b0,list_remainder}+stream_advance;
    assign list_index0 = list_cursor;
    assign list_next_index0=state==IDLE && request_valid ? INDEX_BITS'(0)
        : state==STREAM && stream_accept && position>=prefix_bytes && next_remainder>=stream_node_bytes ? list_cursor+1'b1 : list_cursor;
    assign list_index1 = list_index0+1'b1;
    assign request_ready = state == IDLE;
    assign response_valid = state == RESPONSE;

    function automatic [31:0] be32(input [31:0] value);
        be32 = {value[7:0],value[15:8],value[23:16],value[31:24]};
    endfunction
    // All sponge beats start on an eight-byte boundary. Select two words
    // directly instead of shifting a maximum-size concatenated message frame.
    wire [2:0] node_words=stream_node_words;
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
    // Select a source and a small word address BEFORE the wide data mux.
    // All recipes share the same message/seed selectors instead of each
    // recipe instantiating its own variable 64-bit extraction network.
    function automatic [63:0] source_word(input [5:0] index,input bit lms_only);
        reg [2:0] source;
        reg [5:0] selected_index;
        reg [63:0] literal;
        begin
            source=0;selected_index=index;literal=0;
            (* parallel_case *) case(1'b1)
                shapes[MESSAGE_PRF]: if(!lms_only && RECIPE_MASK[MESSAGE_PRF]) begin
                    if(index<node_words) source=1;
                    else if(index<2*node_words) begin source=2;selected_index=index-node_words;end
                    else begin source=5;selected_index=index-2*node_words;end
                end
                shapes[MESSAGE_DIGEST]: if(!lms_only && RECIPE_MASK[MESSAGE_DIGEST]) begin
                    if(index<node_words) source=2;
                    else if(index<2*node_words) begin source=3;selected_index=index-node_words;end
                    else if(index<3*node_words) begin source=4;selected_index=index-2*node_words;end
                    else begin source=5;selected_index=index-3*node_words;end
                end
                shapes[ROOT_MESSAGE]: if(!lms_only && RECIPE_MASK[ROOT_MESSAGE]) begin
                    if(index==3) literal=64'h0200000000000000;
                    else if(index<4) literal=0;
                    else if(index<8) begin source=2;selected_index=index-4;end
                    else if(index<12) begin source=4;selected_index=index-8;end
                    else if(index==15) literal={be32(leaf),32'd0};
                    else if(index>=16) begin source=5;selected_index=index-16;end
                end
                shapes[PREFIX_MESSAGE]: if(RECIPE_MASK[PREFIX_MESSAGE]) begin
                    // Unaligned 22-byte prefix: assemble three aligned words,
                    // then retain the fixed window starting two bytes later.
                    if(index>=3 && index<7) begin source=2;selected_index=index-3;end
                    else if(index>=7) begin source=5;selected_index=index-7;end
                end
                shapes[ADDRESS_LIST]: if(!lms_only && RECIPE_MASK[ADDRESS_LIST]) begin
                    if(index<node_words) source=3;
                    else if(index<node_words+4) begin source=6;selected_index=index-node_words;end
                    else begin source=7;selected_index=index-node_words-4;end
                end
                shapes[PREFIX_LIST]: if(!lms_only && RECIPE_MASK[PREFIX_LIST]) begin
                    case(index)
                        0:literal=identifier[63:0];1:literal=identifier[127:64];
                        2:literal={list_data0[15:0],16'h8080,be32(leaf)};
                        3:literal=list_data0[79:16];default:literal=0;
                    endcase
                end
                default:begin end
            endcase
            case(source)
                1:source_word=node_word(secret_prf,selected_index);
                2:source_word=node_word(randomizer,selected_index);
                3:source_word=node_word(public_seed,selected_index);
                4:source_word=node_word(root,selected_index);
                5:source_word=message_word(selected_index);
                6:source_word=node_word(address,selected_index);
                7:source_word=node_word(list_data0,selected_index);
                default:source_word=literal;
            endcase
        end
    endfunction
    logic [511:0] list_pair;
    always @* begin
        case(stream_node_bytes)
            16:list_pair={256'd0,list_data1[127:0],list_data0[127:0]};
            24:list_pair={128'd0,list_data1[191:0],list_data0[191:0]};
            default:list_pair={list_data1,list_data0};
        endcase
    end
    // Legal list offsets are whole 64-bit words (SLH), or two bytes
    // beyond a word (LMS's 22-byte prefix). No general byte barrel shifter.
    logic [143:0] list_word_window;
    always @* begin
        case(list_remainder[4:3])
            0:list_word_window=list_pair[143:0];
            1:list_word_window=list_pair[207:64];
            2:list_word_window=list_pair[271:128];
            default:list_word_window=list_pair[335:192];
        endcase
    end
    // SLH nodes and prefixes are eight-byte aligned. A beat never crosses
    // a node boundary; do not retain the legacy two-node byte window.
    wire [127:0] list_window=RECIPE_MASK[PREFIX_LIST]
        ? (list_remainder[1] ? (UNIFIED_FIXED ? list_word_window[143:16] : {64'd0,list_word_window[79:16]}) : (UNIFIED_FIXED ? list_word_window[127:0] : {64'd0,list_word_window[63:0]}))
        : {64'd0,node_word(list_data0,{4'd0,list_remainder[4:3]})};
    wire [5:0] stream_word_index=position[8:3];
    logic [127:0] stream_payload;
    logic [191:0] source_window;
    always_comb begin
        source_window={source_word(stream_word_index+6'd2,1'b1),
            source_word(stream_word_index+6'd1,!UNIFIED_FIXED),source_word(stream_word_index,1'b0)};
        stream_payload=UNIFIED_FIXED ? source_window[127:0] : {64'd0,source_window[63:0]};
        if(shapes[PREFIX_MESSAGE]) begin
            stream_payload=UNIFIED_FIXED ? source_window[143:16] : {64'd0,source_window[79:16]};
            if(position==0)stream_payload=UNIFIED_FIXED ? identifier : {64'd0,identifier[63:0]};
            else if(!UNIFIED_FIXED && position==8)stream_payload[63:0]=identifier[127:64];
            else if(position==16)stream_payload[47:0]={16'h8181,be32(leaf)};
        end else if((shapes[ADDRESS_LIST] || shapes[PREFIX_LIST]) && position>=prefix_bytes)
            stream_payload=list_window;
    end

    integer i, absolute;
    always @* begin
        address = {be32(b),be32(a),be32(leaf),be32({24'd0,address_domain}),
            be32(request_tree[31:0]),be32(request_tree[63:32]),32'd0,be32(request_layer)};
        masked_address = {be32(compound),be32(b),be32(a),be32(leaf),be32(domain),96'd0};
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
        (* parallel_case *) case(1'b1)
            shapes[ADDRESS_SEED],shapes[ADDRESS_VALUE]: if(RECIPE_MASK[ADDRESS_SEED] || RECIPE_MASK[ADDRESS_VALUE]) begin
                frame_layout=0;frame0=public_seed;frame1=address;
                frame2=chain_feedback_valid ? finish_digest[N*8-1:0] : shapes[ADDRESS_SEED] ? secret_seed : left_value;
                frame_two=!chain_feedback_valid && shapes[ADDRESS_VALUE] && arity==2;
                frame3=frame_two ? request_right : 256'd0;
            end
            shapes[INDEX_PRF]: if(RECIPE_MASK[INDEX_PRF]) begin
                frame_layout=1;frame_domain=3;frame1=secret_prf;frame2={be32(leaf),224'd0};
            end
            shapes[MASKED_SEED]: if(RECIPE_MASK[MASKED_SEED]) begin
                frame_layout=2;frame_domain=4;frame1=secret_seed;frame2=public_seed;frame3=masked_address;
            end
            shapes[MASKED_VALUE]: if(LEGACY_MASKED) begin
                if(compound<arity+1) begin
                    frame_layout=1;frame_domain=3;frame1=public_seed;frame2=masked_address;
                end else begin
                    frame_layout=3;frame_domain=arity-1'b1;frame1=temporary_key;
                    frame2=left_value^mask0;frame_two=arity==2;
                    frame3=frame_two ? request_right^mask1 : 256'd0;
                end
            end
            shapes[PREFIX_SEED],shapes[PREFIX_VALUE]: if(RECIPE_MASK[PREFIX_SEED] || RECIPE_MASK[PREFIX_VALUE]) begin
                frame_layout=4;
                frame_prefix={shapes[PREFIX_SEED] ? 8'hff : b[7:0],8'(request_a),8'd0,be32(leaf),identifier};
                frame1=shapes[PREFIX_SEED] ? secret_seed : left_value;
            end
            shapes[PREFIX_LEAF],shapes[PREFIX_PARENT]: if(RECIPE_MASK[PREFIX_LEAF] || RECIPE_MASK[PREFIX_PARENT]) begin
                frame_layout=5;
                frame_prefix={8'd0,shapes[PREFIX_LEAF] ? 16'h8282 : 16'h8383,be32(request_b),identifier};
                frame1=left_value;frame_two=shapes[PREFIX_PARENT];
                frame2=frame_two ? request_right : 256'd0;
            end
            default:begin end
        endcase
    end
    always @* begin
        fast_block=0;
        if(!UNIFIED_FIXED)case(node_bytes)
            16: begin
                fast_block[0 +:128]=public_seed[127:0];
                fast_block[128 +:256]=address;
                fast_block[384 +:128]=chain_feedback_valid ? finish_digest[127:0] : shapes[ADDRESS_SEED] ? secret_seed[127:0] : left_value[127:0];
                if(shapes[ADDRESS_VALUE] && arity==2) begin
                    fast_block[512 +:128]=request_right[127:0];
                    fast_block[640 +:8]=8'h1f;
                end else fast_block[512 +:8]=8'h1f;
            end
            24: begin
                fast_block[0 +:192]=public_seed[191:0];
                fast_block[192 +:256]=address;
                fast_block[448 +:192]=chain_feedback_valid ? finish_digest[191:0] : shapes[ADDRESS_SEED] ? secret_seed[191:0] : left_value[191:0];
                if(shapes[ADDRESS_VALUE] && arity==2) begin
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
            if ((UNIFIED_FIXED || i<8) && beat*16+(UNIFIED_FIXED ? 0 : stream_half*8)+i < 136) begin
                if (absolute >= input_length) stream_data[i*8 +: 8] = 0;
                if (absolute == input_length) stream_data[i*8 +: 8] = 8'h1f;
                if (stream_last && beat*16+(UNIFIED_FIXED ? 0 : stream_half*8)+i == 135) stream_data[i*8+7] = 1'b1;
            end else stream_data[i*8 +: 8] = 0;
        end
    end

    wire batch_perm_valid,batch_perm_ready,batch_perm_done;
    wire [1599:0] batch_perm_state,batch_perm_digest;
    wire [TAG_BITS-1:0] batch_perm_tag,batch_perm_result_tag;
    logic bridge_response;
    wire scalar_bridge=UNIFIED_FIXED && bridge_response;
    wire engine_mode=batch_mode || scalar_bridge;
    wire engine_ready,engine_valid;
    wire [255:0] engine_digest,engine_capture;
    wire [3:0] scalar_shape=request_recipe[59:56];
    wire scalar_fixed=UNIFIED_FIXED && RECIPE_MASK[scalar_shape]
        && (scalar_shape==1 || scalar_shape==2 || scalar_shape==5 || scalar_shape==7 || scalar_shape==8
            || scalar_shape==9 || scalar_shape==10 || scalar_shape==14 || scalar_shape==15);
    wire scalar_no_seed=!(request_chain && (scalar_shape==1 || scalar_shape==7 || scalar_shape==9))
        && scalar_shape!=7;
    wire [1:0] scalar_family=(scalar_shape==1 || scalar_shape==2) ? 2'd0
        : (scalar_shape==9 || scalar_shape==10 || scalar_shape==14 || scalar_shape==15) ? 2'd2 : 2'd1;
    assign batch_request_ready=engine_ready && !scalar_bridge;
    assign batch_response_valid=engine_valid && !scalar_bridge;
    assign batch_read_digest=engine_digest;
    assign batch_read_capture=engine_capture;
    generate if(PIPELINE>1)begin: chain_pipeline
        pipeline #(.PIPELINE(PIPELINE),.PROFILE_ENABLE(PROFILE_ENABLE),.UNIFIED_FIXED(UNIFIED_FIXED)) engine(
            .clk,.rst,.node_bytes,
            .request_valid(scalar_bridge ? state==FIXED_ISSUE : batch_request_valid),.request_ready(engine_ready),
            .request_tag(scalar_bridge ? TAG_BITS'(0) : batch_request_tag),
            .request_steps(scalar_bridge ? (request_chain ? request_steps : 5'd0) : batch_steps),
            .request_capture_after(scalar_bridge ? (request_chain ? request_capture_after : scalar_no_seed ? 5'd1 : 5'd0) : batch_capture_after),
            .request_capture(scalar_bridge ? request_capture : batch_capture_enable),.secret_seed,.public_seed,
            .request_family(scalar_bridge ? scalar_family : batch_family),
            .request_no_seed(scalar_bridge ? scalar_no_seed : batch_no_seed),
            .request_start(scalar_bridge ? 4'd0 : batch_start),
            .request_fixed_shape(scalar_bridge ? (request_chain ? 4'd0 : scalar_shape) : batch_fixed_shape),
            .request_pair(scalar_bridge ? request_recipe[47:40]==2 : batch_pair),
            .request_right(scalar_bridge ? 256'(request_right) : batch_right),
            .request_initial_value(scalar_bridge ? (scalar_shape==5 ? 256'(secret_prf) : 256'(request_left)) : batch_initial_value),.identifier,
            .request_layer,.request_tree,
            .request_leaf(scalar_bridge ? request_leaf : batch_leaf),
            .request_a(scalar_bridge ? 8'(request_a) : batch_a),.request_b(scalar_bridge ? request_b : batch_b),
            .seed_domain(scalar_bridge ? request_recipe[55:48] : batch_seed_domain),
            .step_domain(scalar_bridge ? (request_chain ? request_step_recipe[55:48] : request_recipe[55:48]) : batch_step_domain),
            .response_valid(engine_valid),.response_ready(scalar_bridge ? state==FIXED_WAIT : batch_response_ready),
            .response_tag(batch_response_tag),.response_digest(),.response_capture(),
            .read_tag(scalar_bridge ? TAG_BITS'(0) : batch_read_tag),.read_digest(engine_digest),.read_capture(engine_capture),
            .perm_valid(batch_perm_valid),.perm_ready(batch_perm_ready),.perm_state(batch_perm_state),.perm_tag(batch_perm_tag),
            .perm_done(batch_perm_done),.perm_digest(batch_perm_digest),.perm_result_tag(batch_perm_result_tag),
            .hash_count(batch_hashes),.permutation_count(batch_permutations));
        assign batch_response_digest=engine_digest;assign batch_response_capture=engine_capture;
    end else begin
        assign batch_perm_valid=0;assign batch_perm_state=0;assign batch_perm_tag=0;
        assign engine_ready=0;assign engine_valid=0;assign batch_response_tag=0;
        assign engine_digest=0;assign engine_capture=0;
        assign batch_response_digest=0;assign batch_response_capture=0;
        assign batch_hashes=0;assign batch_permutations=0;
    end endgenerate
    // Direct Keccak datapath and absorb/chain control.
    localparam logic [1:0] HASH_IDLE = 2'd0;
    localparam logic [1:0] HASH_WAIT_BLOCK = 2'd1;
    localparam logic [1:0] HASH_RUN = 2'd2;

    logic [1:0] hash_state;
    logic saved_chain_enable;
    logic saved_chain_prefix;
    logic saved_chain_prefix_preserve_counter;
    logic [4:0] saved_chain_count;
    logic saved_capture_enable;
    logic [4:0] saved_capture_after;
    logic first_block;
    logic running_last;
    logic [3:0] append_index;

    wire [24:0] state_write_enable;
    wire [1599:0] state_write_data;
    logic [1599:0] sponge_state;
    logic [4:0] chains_remaining;
    logic [3:0] chain_counter;
    logic [4:0] chain_iteration;
    logic [N*8-1:0] captured_value;
    logic [4:0] round_index;
    wire [1599:0] advanced_state;
    wire round_complete;
    wire round_update;
    wire [3:0] counter_next = chain_counter + 1'b1;
    wire [3:0] transition_counter =
        saved_chain_prefix && chain_iteration == 1
            ? chain_counter : counter_next;

    // One P-stage datapath for both serial and interleaved execution. P1
    // writes its sole state through the sponge word enables, without launch
    // or return bubbles. P>1 carries valid/round/tag through the same stages.
    localparam integer ROUNDS=UNROLL*PIPELINE;
    logic [1599:0] state_reg [0:PIPELINE-1];
    logic [PIPELINE-1:0] stage_valid;
    logic [4:0] stage_base [0:PIPELINE-1];
    logic [TAG_BITS-1:0] stage_tag [0:PIPELINE-1];
    logic sent;
    wire recycle=PIPELINE>1 && stage_valid[PIPELINE-1]
        && stage_base[PIPELINE-1]+ROUNDS<24;
    wire ready=!rst && !recycle;
    wire finished=PIPELINE>1 && !rst && stage_valid[PIPELINE-1] && !recycle;
    wire normal_valid=hash_state==HASH_RUN && !sent;
    wire issue_valid=engine_mode ? batch_perm_valid : normal_valid;
    wire [1599:0] issue_state=engine_mode ? batch_perm_state : sponge_state;
    wire [TAG_BITS-1:0] issue_tag=engine_mode ? batch_perm_tag : '0;
    wire [1599:0] finished_state=state_reg[PIPELINE-1];
    wire [1599:0] stage_result[0:PIPELINE-1];
    for(genvar s=0;s<PIPELINE;s=s+1)begin: stages
        wire [1599:0] rounds[0:UNROLL];
        wire [4:0] start_round;
        wire [TAG_BITS-1:0] source_tag;
        wire source_valid;
        if(s==0)begin: input_stage
            assign rounds[0]=PIPELINE==1 ? sponge_state
                : recycle ? state_reg[PIPELINE-1] : issue_state;
            assign start_round=PIPELINE==1 ? round_index
                : recycle ? stage_base[PIPELINE-1]+5'(ROUNDS) : 5'd0;
            assign source_tag=recycle ? stage_tag[PIPELINE-1] : issue_tag;
            assign source_valid=PIPELINE>1 && (recycle || issue_valid);
        end else begin: following_stage
            assign rounds[0]=state_reg[s-1];
            assign start_round=stage_base[s-1];
            assign source_tag=stage_tag[s-1];
            assign source_valid=stage_valid[s-1];
        end
        for(genvar r=0;r<UNROLL;r=r+1)begin: unrolled
            (* keep_hierarchy="yes" *) keccak round_logic(.state_in(rounds[r]),
                .round_index(start_round+5'(s*UNROLL+r)),.state_out(rounds[r+1]));
        end
        assign stage_result[s]=rounds[UNROLL];
        for(genvar w=0;w<25;w=w+1)begin: words
            always_ff @(posedge clk)if(!rst)begin
                if((PIPELINE==1 || (SHARED_STATE && s==PIPELINE-1)) && state_write_enable[w])
                    state_reg[s][64*w +:64]<=state_write_data[64*w +:64];
                else if(source_valid)state_reg[s][64*w +:64]<=rounds[UNROLL][64*w +:64];
            end
        end
        always_ff @(posedge clk)begin
            if(rst)stage_valid[s]<=0;
            else begin
                stage_valid[s]<=source_valid;
                if(source_valid)begin stage_base[s]<=start_round;stage_tag[s]<=source_tag;end
            end
        end
    end
    assign batch_perm_ready=PIPELINE>1 && engine_mode && ready;
    assign batch_perm_done=PIPELINE>1 && engine_mode && finished;
    assign batch_perm_digest=PIPELINE>1 ? finished_state : 1600'd0;
    assign batch_perm_result_tag=PIPELINE>1 ? stage_tag[PIPELINE-1] : '0;
    if(PIPELINE==1 || SHARED_STATE)assign sponge_state=finished_state;
    assign advanced_state=PIPELINE==1 ? stage_result[0] : finished_state;
    assign round_complete=PIPELINE==1 ? round_index+UNROLL>=24 : !engine_mode && finished;
    assign round_update=hash_state==HASH_RUN && (PIPELINE==1 || round_complete);
    always_ff @(posedge clk)begin
        if(rst)sent<=0;
        else if(!engine_mode)begin
            if(normal_valid && ready)sent<=1;
            if(finished)sent<=0;
        end
    end
    // synthesis translate_off
    always @(posedge clk)if(!rst && PIPELINE>1 && SHARED_STATE && |state_write_enable)
        if(|(stage_valid & ~(finished ? PIPELINE'(1 << (PIPELINE-1)) : {PIPELINE{1'b0}})))$fatal(1,"sponge write while pipeline occupied");
    // synthesis translate_on
    wire permutation_complete=hash_state==HASH_RUN && round_complete;

    assign hash_ready = hash_state == HASH_IDLE;
    assign block_ready = hash_state == HASH_WAIT_BLOCK;
    assign fast_ready = (hash_state == HASH_IDLE && (state == START))
        || (hash_state == HASH_WAIT_BLOCK && first_block && append_index == 0);
    assign digest = sponge_state[DIGEST_BYTES*8-1:0];
    assign finish_valid = hash_state == HASH_RUN
        && round_complete
        && (!saved_chain_enable || chains_remaining <= 1)
        && running_last;
    assign finish_digest = advanced_state[DIGEST_BYTES*8-1:0];
    assign compact_capture = captured_value;

    initial begin
        if (UNROLL < 1 || PIPELINE < 1 || PIPELINE > 12 || ROUNDS > 24 || (24 % ROUNDS) != 0)
            $error("recipe lane requires positive U/P and U*P dividing 24");
    end

    // Mutually exclusive word updates expose one data mux instead of a
    // priority network for whole-state loads mixed with partial absorption.
    wire take_fast=(hash_state==HASH_IDLE && (state == START) && (state == START && fixed_block))
        || (hash_state==HASH_WAIT_BLOCK && (state == START && fixed_block) && fast_ready);
    wire take_stream=hash_state==HASH_WAIT_BLOCK && !take_fast && staged_valid;
    wire clear_stream=take_stream && first_block && append_index==0;
    wire take_feedback=hash_state==HASH_RUN && round_complete
        && saved_chain_enable && chains_remaining>1;
    assign chain_feedback_valid=take_feedback;
    assign chain_feedback_counter=transition_counter;
    // One selected rate pair is absorbed per stream beat. Share that XOR
    // before distributing the result to the enabled state words.
    logic [127:0] previous_rate;
    always @* begin
        case(append_index)
            0:previous_rate=sponge_state[0 +:128];
            1:previous_rate=sponge_state[128 +:128];
            2:previous_rate=sponge_state[256 +:128];
            3:previous_rate=sponge_state[384 +:128];
            4:previous_rate=sponge_state[512 +:128];
            5:previous_rate=sponge_state[640 +:128];
            6:previous_rate=sponge_state[768 +:128];
            7:previous_rate=sponge_state[896 +:128];
            default:previous_rate={64'd0,sponge_state[1024 +:64]};
        endcase
    end
    wire [127:0] absorbed_block=staged_data ^ (previous_rate & {128{!clear_stream}});
    genvar word_index;
    generate for(word_index=0;word_index<25;word_index=word_index+1) begin: state_words
        wire select_stream=word_index<17 && take_stream && append_index==word_index/2;
        wire [63:0] fast_word;
        if(word_index<17) assign fast_word=fast_block[word_index*64 +:64];
        else assign fast_word=64'd0;
        // The register enable suppresses idle cycles. The default data can
        // therefore be the permutation result without a 1,600-bit HASH_RUN mask.
        wire [63:0] round_or_clear=(clear_stream || (SHARED_STATE && PIPELINE>1)) ? 64'd0
            : advanced_state[word_index*64 +:64];
        wire [63:0] absorb_word=word_index%2==0 ? absorbed_block[63:0] : absorbed_block[127:64];
        wire [63:0] next_word;
            assign next_word=(take_fast || take_feedback) ? fast_word
                : select_stream ? absorb_word : round_or_clear;
        assign state_write_data[word_index*64 +:64]=next_word;
        // A completed permutation already resides in the shared register.
        // Only absorption, initialization or a new chain block needs a write.
        assign state_write_enable[word_index]=!rst &&
            (((SHARED_STATE && PIPELINE>1) ? take_feedback : round_update) || take_fast || select_stream || clear_stream);
        if(!SHARED_STATE && PIPELINE>1)begin: private_state
            always_ff @(posedge clk)
                if(state_write_enable[word_index])sponge_state[word_index*64 +:64]<=next_word;
        end
    end endgenerate

    always_ff @(posedge clk) begin
        if (rst) begin
            hash_state <= HASH_IDLE;
            saved_chain_enable <= 1'b0;
            saved_chain_prefix <= 1'b0;
            saved_chain_prefix_preserve_counter <= 1'b0;
            saved_chain_count <= '0;
            saved_capture_enable <= 1'b0;
            saved_capture_after <= '0;
            first_block <= 1'b1;
            running_last <= 1'b0;
            append_index <= 0;
            chains_remaining <= '0;
            chain_counter <= '0;
            chain_iteration <= '0;
            round_index <= '0;
            hash_error <= 1'b0;
        end else begin
            hash_error <= 1'b0;
            case (hash_state)
                HASH_IDLE: if ((state == START)) begin
                    saved_chain_enable <= compact_chain;
                    saved_chain_prefix <= compact_chain;
                    saved_chain_prefix_preserve_counter
                        <= (request_step_recipe[55:48] == 3);
                    saved_chain_count <= (request_steps+5'd1);
                    saved_capture_enable <= (compact_chain ? request_capture : capture_single);
                    saved_capture_after <= (compact_chain ? request_capture_after+5'd1 : 5'd1);
                    first_block <= 1'b1;
                    append_index <= 0;
                    if ((state == START && fixed_block)) begin
                        running_last <= 1'b1;
                        chains_remaining <= compact_chain
                            ? (request_steps+5'd1) : 5'd1;
                        chain_counter <= 0;
                        chain_iteration <= 1;
                        round_index <= 0;
                        hash_state <= HASH_RUN;
                    end else
                        hash_state <= HASH_WAIT_BLOCK;
                end
                HASH_WAIT_BLOCK: if ((state == START && fixed_block) && fast_ready) begin
                    // Generic pre-padded one-rate-block path.  The recipe
                    // executor builds fixed-format blocks while this lane is
                    // idle, avoiding nine serial append cycles per context.
                    running_last <= 1'b1;
                    chains_remaining <= saved_chain_enable
                        ? saved_chain_count : 5'd1;
                    chain_counter <= 0;
                    chain_iteration <= 1;
                    round_index <= 0;
                    hash_state <= HASH_RUN;
                end else if (staged_valid) begin
                    if (append_index == 8) begin
                        running_last <= staged_last;
                        append_index <= 0;
                        if (saved_chain_enable && !staged_last) begin
                            hash_error <= 1'b1;
                            hash_state <= HASH_IDLE;
                        end else begin
                            chains_remaining <= saved_chain_enable
                                ? saved_chain_count : 5'd1;
                            chain_counter <= 0;
                            chain_iteration <= 1;
                            round_index <= 0;
                            hash_state <= HASH_RUN;
                        end
                    end else begin
                        append_index <= append_index + 1'b1;
                    end
                end
                HASH_RUN: begin
                    if (round_complete) begin
                        if (saved_capture_enable
                            && saved_capture_after == chain_iteration)
                            captured_value <= advanced_state[N*8-1:0];
                        if (saved_chain_enable && chains_remaining > 1) begin
                            chains_remaining <= chains_remaining - 1'b1;
                            if (!saved_chain_prefix_preserve_counter
                                && !(saved_chain_prefix
                                     && chain_iteration == 1))
                                chain_counter <= chain_counter + 1'b1;
                            chain_iteration <= chain_iteration + 1'b1;
                            round_index <= 0;
                        end else begin
                            if (running_last) begin
                                hash_state <= HASH_IDLE;
                            end else begin
                                first_block <= 1'b0;
                                hash_state <= HASH_WAIT_BLOCK;
                            end
                        end
                    end else if(PIPELINE==1) begin
                        round_index <= round_index + UNROLL;
                    end
                end
                default: hash_state <= HASH_IDLE;
            endcase
        end
    end


    always_ff @(posedge clk) begin
        if (rst) begin
            staged_valid<=0; staged_last<=0; staged_data<=0;
            position<=0;
            list_cursor<=0; list_remainder<=0;
            bridge_response<=0;state <= IDLE; error <= 0; hash_count <= 0; permutation_count <= 0;
            seed_phase <= 1; iteration <= 0; compound <= 0; rate_block <= 0; beat <= 0; stream_half<=0;
        end else begin
            if(STREAM_ENABLE && staged_valid && block_ready) staged_valid<=0;
            if (hash_error) begin error <= 1; state <= RESPONSE; end
            else case (state)
                IDLE: if (request_valid) begin
                    staged_valid<=0;
                    position<=0;
                    list_cursor<=0; list_remainder<=0;
                    error <= 0; seed_phase <= 1; iteration <= 0; compound <= 0;
                    legacy_value <= request_left;
                    rate_block <= 0; beat <= 0; stream_half<=0;
                    bridge_response<=scalar_fixed;
                    state <= scalar_fixed ? FIXED_ISSUE : START;
                end
                FIXED_ISSUE:if(engine_ready)state<=FIXED_WAIT;
                FIXED_WAIT:if(engine_valid)state<=RESPONSE;
                START: if (hash_ready) begin
                    if (PROFILE_ENABLE) begin
                        hash_count <= hash_count+(compact_chain ? request_steps+1 : 1);
                        if (fixed_block) permutation_count <= permutation_count+(compact_chain ? request_steps+1 : 1);
                    end
                    state <= fixed_block ? WAIT_HASH : STREAM;
                end
                STREAM: if (STREAM_ENABLE && stream_accept) begin
                    position<=position+13'(stream_advance);
                    if(UNIFIED_FIXED)staged_data<=stream_data;
                    else if(stream_half) staged_data[127:64]<=stream_data[63:0];
                    else staged_data[63:0]<=stream_data[63:0];
                    staged_valid<=UNIFIED_FIXED || stream_half || beat==8;
                    staged_last<=stream_last;
                    if(beat==8) staged_data[127:64]<=0;
                    stream_half<=UNIFIED_FIXED || beat==8 ? 1'b0 : !stream_half;
                    begin
                        if(position < prefix_bytes) begin
                            if(position+stream_advance >= prefix_bytes)
                                list_remainder <= position+stream_advance-prefix_bytes;
                        end else if(next_remainder >= stream_node_bytes) begin
                            list_remainder <= next_remainder-stream_node_bytes;
                            list_cursor <= list_cursor+1'b1;
                        end else list_remainder <= next_remainder;
                    end
                    if (beat == 8) begin
                        beat <= 0;
                        if (PROFILE_ENABLE) permutation_count <= permutation_count+1;
                        if (stream_last) state <= WAIT_HASH;
                        else rate_block <= rate_block+1'b1;
                    end else if(UNIFIED_FIXED || stream_half) beat <= beat+1'b1;
                end
                WAIT_HASH: if (completed) begin
                    if (compact_chain) begin
                        state <= RESPONSE;
                    end else if (LEGACY_MASKED && shapes[MASKED_VALUE] && compound < arity+1) begin
                        case (compound)
                            0: temporary_key <= completed_value[N*8-1:0];
                            1: mask0 <= completed_value[N*8-1:0];
                            default: mask1 <= completed_value[N*8-1:0];
                        endcase
                        compound <= compound+1'b1;
                        state <= START;
                    end else begin
                        compound <= 0;
                        legacy_value <= completed_value[N*8-1:0];
                        if (request_chain && (seed_phase ? request_steps != 0 : iteration+1 < request_steps)) begin
                            seed_phase <= 0;
                            if (!seed_phase) iteration <= iteration+1'b1;
                            state <= START;
                        end else begin
                            state <= RESPONSE;
                        end
                    end
                end
                RESPONSE: if (response_ready)begin bridge_response<=0;state <= IDLE;end
                default: state <= IDLE;
            endcase
        end
    end
endmodule
`default_nettype wire
