`timescale 1ns/1ps
`default_nettype none

// Typed HBS SHAKE byte recipes. Each accepted request performs exactly one
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
    input wire [19:0] request_leaf,
    input wire [1:0] request_address_type,
    input wire [31:0] request_index,
    input wire [127:0] request_identifier,
    input wire [N*8-1:0] request_key,
    input wire [INDEX_BITS-1:0] request_a,
    input wire [31:0] request_b,
    input wire [N*8-1:0] request_left, request_right,
    output wire [INDEX_BITS-1:0] list_index0, list_index1,
    input wire [N*8-1:0] list_data0, list_data1,
    output wire response_valid,
    input wire response_ready,
    output wire [DIGEST_BYTES*8-1:0] response_value,
    output logic error,
    output logic [63:0] hash_count, permutation_count
);
    localparam [3:0] ADDRESS_SEED=1, ADDRESS_VALUE=2, MESSAGE_PRF=3,
        MESSAGE_DIGEST=4, XMSS_PRF=5, XMSS_F=6, XMSS_H=7, XMSS_MESSAGE=8,
        LMS_SECRET=9, LMS_CHAIN=10, LMS_MESSAGE=11, ADDRESS_LIST=12,
        LMS_LEAF=13, LMS_PARENT=14, LMS_PUBLIC=15;
    localparam bit STREAM_ENABLE=(RECIPE_MASK & 16'h9918)!=0;
    typedef enum logic [1:0] {IDLE, STREAM, WAIT_HASH, RESPONSE} state_t;
    state_t state;
    wire [3:0] shape=request_recipe[59:56];
    wire [7:0] domain=request_recipe[55:48];
    wire [7:0] arity=request_recipe[47:40];
    logic [12:0] input_length;
    logic [2:0] node_words;
    logic [12:0] position;
    logic [4:0] beat;
    logic [INDEX_BITS-1:0] list_cursor;
    logic [4:0] list_remainder;
    logic [63:0] alignment_carry;
    wire fixed_block=shape==ADDRESS_SEED || shape==ADDRESS_VALUE
        || shape==XMSS_PRF || shape==XMSS_F || shape==XMSS_H
        || shape==LMS_SECRET || shape==LMS_CHAIN || shape==LMS_LEAF || shape==LMS_PARENT;
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
    wire new_shape=shape>=XMSS_PRF && shape!=ADDRESS_LIST;
    wire valid_shape=shape!=0;
    wire bad_request=!valid_shape || !RECIPE_MASK[shape]
        || !(node_bytes==16 || node_bytes==24 || node_bytes==32) || 32'(node_bytes)>N
        || (shape==ADDRESS_VALUE && arity!=1 && arity!=2)
        || (shape==ADDRESS_LIST && (arity==0 || 32'(arity)>(1<<INDEX_BITS)))
        || ((shape==MESSAGE_PRF || shape==MESSAGE_DIGEST) && 32'(message_length)>MAX_MESSAGE_BYTES);
    wire bad_standard_request=new_shape && (node_bytes!=32
        || ((shape==XMSS_PRF) && (domain>4 || arity!=1 || request_address_type>2))
        || ((shape==XMSS_F || shape==XMSS_MESSAGE || shape==LMS_SECRET
            || shape==LMS_CHAIN || shape==LMS_MESSAGE || shape==LMS_LEAF) && (domain!=0 || arity!=1))
        || ((shape==XMSS_H || shape==LMS_PARENT) && (domain!=0 || arity!=2))
        || (shape==LMS_PUBLIC && (domain!=0 || arity!=67))
        || ((shape==XMSS_MESSAGE || shape==LMS_MESSAGE) && 32'(message_length)>MAX_MESSAGE_BYTES));
    wire reject_request=bad_request || bad_standard_request;

    assign request_ready=hash_ready && (state==IDLE || (response_valid && response_ready));
    // The SHAKE state already retains the digest. Expose completion directly,
    // then retain only the valid flag when the consumer applies backpressure.
    assign response_valid=state==RESPONSE || (state==WAIT_HASH && digest_valid);
    wire [12:0] lms_list_last_offset=position>=13'd16 ? position-13'd15 : 13'd0;
    assign list_index0=shape==LMS_PUBLIC ? INDEX_BITS'(lms_list_last_offset>>5) : list_cursor;
    assign list_index1=list_index0+1'b1;
    function automatic [31:0] be32(input [31:0] value);
        be32={value[7:0],value[15:8],value[23:16],value[31:24]};
    endfunction
    wire [255:0] address={be32(request_b),be32(32'(request_a)),
        be32({12'd0,request_leaf}),be32({24'd0,request_recipe[55:48]}),
        be32(request_tree[31:0]),be32(request_tree[63:32]),32'd0,
        be32({27'd0,request_layer})};
    wire [31:0] xmss_keymask=domain>=2 ? {24'd0,domain}-32'd2 : 32'd0;
    wire [255:0] xmss_address={be32(xmss_keymask),be32(request_b),
        be32(32'(request_a)),be32(request_address_type==2 ? 32'd0 : {12'd0,request_leaf}),
        be32({30'd0,request_address_type}),be32(request_tree[31:0]),
        be32(request_tree[63:32]),be32({27'd0,request_layer})};
    wire [255:0] index_bytes={be32(request_index),224'd0};
    wire [31:0] lms_q=shape==LMS_MESSAGE ? request_index : {12'd0,request_leaf};
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
    wire [9:0] message_prefix_words=shape==XMSS_MESSAGE ? 10'd16
        : shape==LMS_MESSAGE ? 10'd6
        : shape==MESSAGE_PRF ? 2*10'(node_words) : 3*10'(node_words);
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
                XMSS_MESSAGE: if(RECIPE_MASK[XMSS_MESSAGE]) begin
                    if(index<4) begin source=7;selected_index=index;end
                    else if(index<8) begin source=2;selected_index=index-4;end
                    else if(index<12) begin source=4;selected_index=index-8;end
                    else if(index<16) begin source=5;selected_index=index-12;end
                end
                default:begin end
            endcase
            case(source)
                1:source_word=node_word(256'(secret_prf),selected_index);
                2:source_word=node_word(256'(randomizer),selected_index);
                3:source_word=node_word(256'(public_seed),selected_index);
                4:source_word=node_word(256'(root),selected_index);
                5:source_word=node_word(index_bytes,selected_index);
                6:source_word=node_word(address,selected_index);
                7:source_word=selected_index==3 ? 64'h0200000000000000 : 64'd0;
                default:source_word=0;
            endcase
        end
    endfunction

    // Fixed HBS frame layouts, transposed by source bit. This builds one
    // primitive frame, and adds no storage, traversal or Hash control.
    wire [255:0] frame_public=256'(public_seed),frame_secret=256'(secret_seed);
    wire [255:0] frame_prf=256'(secret_prf),frame_key=256'(request_key);
    wire [255:0] frame_left=256'(request_left),frame_right=256'(request_right);
    wire [255:0] frame_payload=shape==ADDRESS_SEED ? frame_secret : frame_left;
    wire [31:0] frame_lms_q=be32(lms_q),frame_heap=be32(request_b);
    wire [14:0] fast_layout;
    assign fast_layout[0]=(((shape==ADDRESS_SEED || shape==ADDRESS_VALUE) && node_bytes==6'd16 && !(shape==ADDRESS_VALUE && arity==2))); // slh16_1
    assign fast_layout[1]=(((shape==ADDRESS_SEED || shape==ADDRESS_VALUE) && node_bytes==6'd16 && (shape==ADDRESS_VALUE && arity==2))); // slh16_2
    assign fast_layout[2]=(((shape==ADDRESS_SEED || shape==ADDRESS_VALUE) && node_bytes==6'd24 && !(shape==ADDRESS_VALUE && arity==2))); // slh24_1
    assign fast_layout[3]=(((shape==ADDRESS_SEED || shape==ADDRESS_VALUE) && node_bytes==6'd24 && (shape==ADDRESS_VALUE && arity==2))); // slh24_2
    assign fast_layout[4]=(((shape==ADDRESS_SEED || shape==ADDRESS_VALUE) && node_bytes==6'd32 && !(shape==ADDRESS_VALUE && arity==2))); // slh32_1
    assign fast_layout[5]=(((shape==ADDRESS_SEED || shape==ADDRESS_VALUE) && node_bytes==6'd32 && (shape==ADDRESS_VALUE && arity==2))); // slh32_2
    assign fast_layout[6]=(shape==XMSS_PRF && domain==0); // xmss_keygen
    assign fast_layout[7]=(shape==XMSS_PRF && domain==1); // xmss_r
    assign fast_layout[8]=(shape==XMSS_PRF && domain>=2); // xmss_addr
    assign fast_layout[9]=(shape==XMSS_F); // xmss_f
    assign fast_layout[10]=(shape==XMSS_H); // xmss_h
    assign fast_layout[11]=(shape==LMS_SECRET); // lms_secret
    assign fast_layout[12]=(shape==LMS_CHAIN); // lms_chain
    assign fast_layout[13]=(shape==LMS_LEAF); // lms_leaf
    assign fast_layout[14]=(shape==LMS_PARENT); // lms_parent
    wire fast_select_0= fast_layout[0] | fast_layout[1] | fast_layout[2] | fast_layout[3] | fast_layout[4] | fast_layout[5];
    wire fast_select_1= fast_layout[11] | fast_layout[12] | fast_layout[13] | fast_layout[14];
    wire fast_select_2= fast_layout[0] | fast_layout[1];
    wire fast_select_3= fast_layout[2] | fast_layout[3] | fast_layout[4] | fast_layout[5];
    wire fast_select_4= fast_layout[11] | fast_layout[12];
    wire fast_select_5= fast_layout[13] | fast_layout[14];
    wire fast_select_6= fast_layout[2] | fast_layout[3];
    wire fast_select_7= fast_layout[4] | fast_layout[5];
    wire fast_select_8= fast_layout[7] | fast_layout[8] | fast_layout[10];
    wire fast_select_9= fast_layout[7] | fast_layout[8];
    wire fast_select_10= fast_layout[9] | fast_layout[10];
    wire fast_select_11= fast_layout[1] | fast_layout[2];
    wire fast_select_12= fast_layout[4] | fast_layout[7] | fast_layout[8] | fast_layout[9];
    wire fast_select_13= fast_layout[5] | fast_layout[10];
    wire fast_select_14= fast_layout[5] | fast_layout[6] | fast_layout[10];
    wire [1087:0] fast_block;
    assign fast_block[0]= (frame_public[0] & fast_select_0) | (request_identifier[0] & fast_select_1);
    assign fast_block[1]= (frame_public[1] & fast_select_0) | (request_identifier[1] & fast_select_1);
    assign fast_block[2]= (frame_public[2] & fast_select_0) | (request_identifier[2] & fast_select_1);
    assign fast_block[3]= (frame_public[3] & fast_select_0) | (request_identifier[3] & fast_select_1);
    assign fast_block[4]= (frame_public[4] & fast_select_0) | (request_identifier[4] & fast_select_1);
    assign fast_block[5]= (frame_public[5] & fast_select_0) | (request_identifier[5] & fast_select_1);
    assign fast_block[6]= (frame_public[6] & fast_select_0) | (request_identifier[6] & fast_select_1);
    assign fast_block[7]= (frame_public[7] & fast_select_0) | (request_identifier[7] & fast_select_1);
    assign fast_block[8]= (frame_public[8] & fast_select_0) | (request_identifier[8] & fast_select_1);
    assign fast_block[9]= (frame_public[9] & fast_select_0) | (request_identifier[9] & fast_select_1);
    assign fast_block[10]= (frame_public[10] & fast_select_0) | (request_identifier[10] & fast_select_1);
    assign fast_block[11]= (frame_public[11] & fast_select_0) | (request_identifier[11] & fast_select_1);
    assign fast_block[12]= (frame_public[12] & fast_select_0) | (request_identifier[12] & fast_select_1);
    assign fast_block[13]= (frame_public[13] & fast_select_0) | (request_identifier[13] & fast_select_1);
    assign fast_block[14]= (frame_public[14] & fast_select_0) | (request_identifier[14] & fast_select_1);
    assign fast_block[15]= (frame_public[15] & fast_select_0) | (request_identifier[15] & fast_select_1);
    assign fast_block[16]= (frame_public[16] & fast_select_0) | (request_identifier[16] & fast_select_1);
    assign fast_block[17]= (frame_public[17] & fast_select_0) | (request_identifier[17] & fast_select_1);
    assign fast_block[18]= (frame_public[18] & fast_select_0) | (request_identifier[18] & fast_select_1);
    assign fast_block[19]= (frame_public[19] & fast_select_0) | (request_identifier[19] & fast_select_1);
    assign fast_block[20]= (frame_public[20] & fast_select_0) | (request_identifier[20] & fast_select_1);
    assign fast_block[21]= (frame_public[21] & fast_select_0) | (request_identifier[21] & fast_select_1);
    assign fast_block[22]= (frame_public[22] & fast_select_0) | (request_identifier[22] & fast_select_1);
    assign fast_block[23]= (frame_public[23] & fast_select_0) | (request_identifier[23] & fast_select_1);
    assign fast_block[24]= (frame_public[24] & fast_select_0) | (request_identifier[24] & fast_select_1);
    assign fast_block[25]= (frame_public[25] & fast_select_0) | (request_identifier[25] & fast_select_1);
    assign fast_block[26]= (frame_public[26] & fast_select_0) | (request_identifier[26] & fast_select_1);
    assign fast_block[27]= (frame_public[27] & fast_select_0) | (request_identifier[27] & fast_select_1);
    assign fast_block[28]= (frame_public[28] & fast_select_0) | (request_identifier[28] & fast_select_1);
    assign fast_block[29]= (frame_public[29] & fast_select_0) | (request_identifier[29] & fast_select_1);
    assign fast_block[30]= (frame_public[30] & fast_select_0) | (request_identifier[30] & fast_select_1);
    assign fast_block[31]= (frame_public[31] & fast_select_0) | (request_identifier[31] & fast_select_1);
    assign fast_block[32]= (frame_public[32] & fast_select_0) | (request_identifier[32] & fast_select_1);
    assign fast_block[33]= (frame_public[33] & fast_select_0) | (request_identifier[33] & fast_select_1);
    assign fast_block[34]= (frame_public[34] & fast_select_0) | (request_identifier[34] & fast_select_1);
    assign fast_block[35]= (frame_public[35] & fast_select_0) | (request_identifier[35] & fast_select_1);
    assign fast_block[36]= (frame_public[36] & fast_select_0) | (request_identifier[36] & fast_select_1);
    assign fast_block[37]= (frame_public[37] & fast_select_0) | (request_identifier[37] & fast_select_1);
    assign fast_block[38]= (frame_public[38] & fast_select_0) | (request_identifier[38] & fast_select_1);
    assign fast_block[39]= (frame_public[39] & fast_select_0) | (request_identifier[39] & fast_select_1);
    assign fast_block[40]= (frame_public[40] & fast_select_0) | (request_identifier[40] & fast_select_1);
    assign fast_block[41]= (frame_public[41] & fast_select_0) | (request_identifier[41] & fast_select_1);
    assign fast_block[42]= (frame_public[42] & fast_select_0) | (request_identifier[42] & fast_select_1);
    assign fast_block[43]= (frame_public[43] & fast_select_0) | (request_identifier[43] & fast_select_1);
    assign fast_block[44]= (frame_public[44] & fast_select_0) | (request_identifier[44] & fast_select_1);
    assign fast_block[45]= (frame_public[45] & fast_select_0) | (request_identifier[45] & fast_select_1);
    assign fast_block[46]= (frame_public[46] & fast_select_0) | (request_identifier[46] & fast_select_1);
    assign fast_block[47]= (frame_public[47] & fast_select_0) | (request_identifier[47] & fast_select_1);
    assign fast_block[48]= (frame_public[48] & fast_select_0) | (request_identifier[48] & fast_select_1);
    assign fast_block[49]= (frame_public[49] & fast_select_0) | (request_identifier[49] & fast_select_1);
    assign fast_block[50]= (frame_public[50] & fast_select_0) | (request_identifier[50] & fast_select_1);
    assign fast_block[51]= (frame_public[51] & fast_select_0) | (request_identifier[51] & fast_select_1);
    assign fast_block[52]= (frame_public[52] & fast_select_0) | (request_identifier[52] & fast_select_1);
    assign fast_block[53]= (frame_public[53] & fast_select_0) | (request_identifier[53] & fast_select_1);
    assign fast_block[54]= (frame_public[54] & fast_select_0) | (request_identifier[54] & fast_select_1);
    assign fast_block[55]= (frame_public[55] & fast_select_0) | (request_identifier[55] & fast_select_1);
    assign fast_block[56]= (frame_public[56] & fast_select_0) | (request_identifier[56] & fast_select_1);
    assign fast_block[57]= (frame_public[57] & fast_select_0) | (request_identifier[57] & fast_select_1);
    assign fast_block[58]= (frame_public[58] & fast_select_0) | (request_identifier[58] & fast_select_1);
    assign fast_block[59]= (frame_public[59] & fast_select_0) | (request_identifier[59] & fast_select_1);
    assign fast_block[60]= (frame_public[60] & fast_select_0) | (request_identifier[60] & fast_select_1);
    assign fast_block[61]= (frame_public[61] & fast_select_0) | (request_identifier[61] & fast_select_1);
    assign fast_block[62]= (frame_public[62] & fast_select_0) | (request_identifier[62] & fast_select_1);
    assign fast_block[63]= (frame_public[63] & fast_select_0) | (request_identifier[63] & fast_select_1);
    assign fast_block[64]= (frame_public[64] & fast_select_0) | (request_identifier[64] & fast_select_1);
    assign fast_block[65]= (frame_public[65] & fast_select_0) | (request_identifier[65] & fast_select_1);
    assign fast_block[66]= (frame_public[66] & fast_select_0) | (request_identifier[66] & fast_select_1);
    assign fast_block[67]= (frame_public[67] & fast_select_0) | (request_identifier[67] & fast_select_1);
    assign fast_block[68]= (frame_public[68] & fast_select_0) | (request_identifier[68] & fast_select_1);
    assign fast_block[69]= (frame_public[69] & fast_select_0) | (request_identifier[69] & fast_select_1);
    assign fast_block[70]= (frame_public[70] & fast_select_0) | (request_identifier[70] & fast_select_1);
    assign fast_block[71]= (frame_public[71] & fast_select_0) | (request_identifier[71] & fast_select_1);
    assign fast_block[72]= (frame_public[72] & fast_select_0) | (request_identifier[72] & fast_select_1);
    assign fast_block[73]= (frame_public[73] & fast_select_0) | (request_identifier[73] & fast_select_1);
    assign fast_block[74]= (frame_public[74] & fast_select_0) | (request_identifier[74] & fast_select_1);
    assign fast_block[75]= (frame_public[75] & fast_select_0) | (request_identifier[75] & fast_select_1);
    assign fast_block[76]= (frame_public[76] & fast_select_0) | (request_identifier[76] & fast_select_1);
    assign fast_block[77]= (frame_public[77] & fast_select_0) | (request_identifier[77] & fast_select_1);
    assign fast_block[78]= (frame_public[78] & fast_select_0) | (request_identifier[78] & fast_select_1);
    assign fast_block[79]= (frame_public[79] & fast_select_0) | (request_identifier[79] & fast_select_1);
    assign fast_block[80]= (frame_public[80] & fast_select_0) | (request_identifier[80] & fast_select_1);
    assign fast_block[81]= (frame_public[81] & fast_select_0) | (request_identifier[81] & fast_select_1);
    assign fast_block[82]= (frame_public[82] & fast_select_0) | (request_identifier[82] & fast_select_1);
    assign fast_block[83]= (frame_public[83] & fast_select_0) | (request_identifier[83] & fast_select_1);
    assign fast_block[84]= (frame_public[84] & fast_select_0) | (request_identifier[84] & fast_select_1);
    assign fast_block[85]= (frame_public[85] & fast_select_0) | (request_identifier[85] & fast_select_1);
    assign fast_block[86]= (frame_public[86] & fast_select_0) | (request_identifier[86] & fast_select_1);
    assign fast_block[87]= (frame_public[87] & fast_select_0) | (request_identifier[87] & fast_select_1);
    assign fast_block[88]= (frame_public[88] & fast_select_0) | (request_identifier[88] & fast_select_1);
    assign fast_block[89]= (frame_public[89] & fast_select_0) | (request_identifier[89] & fast_select_1);
    assign fast_block[90]= (frame_public[90] & fast_select_0) | (request_identifier[90] & fast_select_1);
    assign fast_block[91]= (frame_public[91] & fast_select_0) | (request_identifier[91] & fast_select_1);
    assign fast_block[92]= (frame_public[92] & fast_select_0) | (request_identifier[92] & fast_select_1);
    assign fast_block[93]= (frame_public[93] & fast_select_0) | (request_identifier[93] & fast_select_1);
    assign fast_block[94]= (frame_public[94] & fast_select_0) | (request_identifier[94] & fast_select_1);
    assign fast_block[95]= (frame_public[95] & fast_select_0) | (request_identifier[95] & fast_select_1);
    assign fast_block[96]= (frame_public[96] & fast_select_0) | (request_identifier[96] & fast_select_1);
    assign fast_block[97]= (frame_public[97] & fast_select_0) | (request_identifier[97] & fast_select_1);
    assign fast_block[98]= (frame_public[98] & fast_select_0) | (request_identifier[98] & fast_select_1);
    assign fast_block[99]= (frame_public[99] & fast_select_0) | (request_identifier[99] & fast_select_1);
    assign fast_block[100]= (frame_public[100] & fast_select_0) | (request_identifier[100] & fast_select_1);
    assign fast_block[101]= (frame_public[101] & fast_select_0) | (request_identifier[101] & fast_select_1);
    assign fast_block[102]= (frame_public[102] & fast_select_0) | (request_identifier[102] & fast_select_1);
    assign fast_block[103]= (frame_public[103] & fast_select_0) | (request_identifier[103] & fast_select_1);
    assign fast_block[104]= (frame_public[104] & fast_select_0) | (request_identifier[104] & fast_select_1);
    assign fast_block[105]= (frame_public[105] & fast_select_0) | (request_identifier[105] & fast_select_1);
    assign fast_block[106]= (frame_public[106] & fast_select_0) | (request_identifier[106] & fast_select_1);
    assign fast_block[107]= (frame_public[107] & fast_select_0) | (request_identifier[107] & fast_select_1);
    assign fast_block[108]= (frame_public[108] & fast_select_0) | (request_identifier[108] & fast_select_1);
    assign fast_block[109]= (frame_public[109] & fast_select_0) | (request_identifier[109] & fast_select_1);
    assign fast_block[110]= (frame_public[110] & fast_select_0) | (request_identifier[110] & fast_select_1);
    assign fast_block[111]= (frame_public[111] & fast_select_0) | (request_identifier[111] & fast_select_1);
    assign fast_block[112]= (frame_public[112] & fast_select_0) | (request_identifier[112] & fast_select_1);
    assign fast_block[113]= (frame_public[113] & fast_select_0) | (request_identifier[113] & fast_select_1);
    assign fast_block[114]= (frame_public[114] & fast_select_0) | (request_identifier[114] & fast_select_1);
    assign fast_block[115]= (frame_public[115] & fast_select_0) | (request_identifier[115] & fast_select_1);
    assign fast_block[116]= (frame_public[116] & fast_select_0) | (request_identifier[116] & fast_select_1);
    assign fast_block[117]= (frame_public[117] & fast_select_0) | (request_identifier[117] & fast_select_1);
    assign fast_block[118]= (frame_public[118] & fast_select_0) | (request_identifier[118] & fast_select_1);
    assign fast_block[119]= (frame_public[119] & fast_select_0) | (request_identifier[119] & fast_select_1);
    assign fast_block[120]= (frame_public[120] & fast_select_0) | (request_identifier[120] & fast_select_1);
    assign fast_block[121]= (frame_public[121] & fast_select_0) | (request_identifier[121] & fast_select_1);
    assign fast_block[122]= (frame_public[122] & fast_select_0) | (request_identifier[122] & fast_select_1);
    assign fast_block[123]= (frame_public[123] & fast_select_0) | (request_identifier[123] & fast_select_1);
    assign fast_block[124]= (frame_public[124] & fast_select_0) | (request_identifier[124] & fast_select_1);
    assign fast_block[125]= (frame_public[125] & fast_select_0) | (request_identifier[125] & fast_select_1);
    assign fast_block[126]= (frame_public[126] & fast_select_0) | (request_identifier[126] & fast_select_1);
    assign fast_block[127]= (frame_public[127] & fast_select_0) | (request_identifier[127] & fast_select_1);
    assign fast_block[128]= (address[0] & fast_select_2) | (frame_public[128] & fast_select_3) | (frame_lms_q[0] & fast_select_4) | (frame_heap[0] & fast_select_5);
    assign fast_block[129]= (address[1] & fast_select_2) | (frame_public[129] & fast_select_3) | (frame_lms_q[1] & fast_select_4) | (frame_heap[1] & fast_select_5);
    assign fast_block[130]= (address[2] & fast_select_2) | (frame_public[130] & fast_select_3) | (frame_lms_q[2] & fast_select_4) | (frame_heap[2] & fast_select_5);
    assign fast_block[131]= (address[3] & fast_select_2) | (frame_public[131] & fast_select_3) | (frame_lms_q[3] & fast_select_4) | (frame_heap[3] & fast_select_5);
    assign fast_block[132]= (address[4] & fast_select_2) | (frame_public[132] & fast_select_3) | (frame_lms_q[4] & fast_select_4) | (frame_heap[4] & fast_select_5);
    assign fast_block[133]= (address[5] & fast_select_2) | (frame_public[133] & fast_select_3) | (frame_lms_q[5] & fast_select_4) | (frame_heap[5] & fast_select_5);
    assign fast_block[134]= (address[6] & fast_select_2) | (frame_public[134] & fast_select_3) | (frame_lms_q[6] & fast_select_4) | (frame_heap[6] & fast_select_5);
    assign fast_block[135]= (address[7] & fast_select_2) | (frame_public[135] & fast_select_3) | (frame_lms_q[7] & fast_select_4) | (frame_heap[7] & fast_select_5);
    assign fast_block[136]= (address[8] & fast_select_2) | (frame_public[136] & fast_select_3) | (frame_lms_q[8] & fast_select_4) | (frame_heap[8] & fast_select_5);
    assign fast_block[137]= (address[9] & fast_select_2) | (frame_public[137] & fast_select_3) | (frame_lms_q[9] & fast_select_4) | (frame_heap[9] & fast_select_5);
    assign fast_block[138]= (address[10] & fast_select_2) | (frame_public[138] & fast_select_3) | (frame_lms_q[10] & fast_select_4) | (frame_heap[10] & fast_select_5);
    assign fast_block[139]= (address[11] & fast_select_2) | (frame_public[139] & fast_select_3) | (frame_lms_q[11] & fast_select_4) | (frame_heap[11] & fast_select_5);
    assign fast_block[140]= (address[12] & fast_select_2) | (frame_public[140] & fast_select_3) | (frame_lms_q[12] & fast_select_4) | (frame_heap[12] & fast_select_5);
    assign fast_block[141]= (address[13] & fast_select_2) | (frame_public[141] & fast_select_3) | (frame_lms_q[13] & fast_select_4) | (frame_heap[13] & fast_select_5);
    assign fast_block[142]= (address[14] & fast_select_2) | (frame_public[142] & fast_select_3) | (frame_lms_q[14] & fast_select_4) | (frame_heap[14] & fast_select_5);
    assign fast_block[143]= (address[15] & fast_select_2) | (frame_public[143] & fast_select_3) | (frame_lms_q[15] & fast_select_4) | (frame_heap[15] & fast_select_5);
    assign fast_block[144]= (address[16] & fast_select_2) | (frame_public[144] & fast_select_3) | (frame_lms_q[16] & fast_select_4) | (frame_heap[16] & fast_select_5);
    assign fast_block[145]= (address[17] & fast_select_2) | (frame_public[145] & fast_select_3) | (frame_lms_q[17] & fast_select_4) | (frame_heap[17] & fast_select_5);
    assign fast_block[146]= (address[18] & fast_select_2) | (frame_public[146] & fast_select_3) | (frame_lms_q[18] & fast_select_4) | (frame_heap[18] & fast_select_5);
    assign fast_block[147]= (address[19] & fast_select_2) | (frame_public[147] & fast_select_3) | (frame_lms_q[19] & fast_select_4) | (frame_heap[19] & fast_select_5);
    assign fast_block[148]= (address[20] & fast_select_2) | (frame_public[148] & fast_select_3) | (frame_lms_q[20] & fast_select_4) | (frame_heap[20] & fast_select_5);
    assign fast_block[149]= (address[21] & fast_select_2) | (frame_public[149] & fast_select_3) | (frame_lms_q[21] & fast_select_4) | (frame_heap[21] & fast_select_5);
    assign fast_block[150]= (address[22] & fast_select_2) | (frame_public[150] & fast_select_3) | (frame_lms_q[22] & fast_select_4) | (frame_heap[22] & fast_select_5);
    assign fast_block[151]= (address[23] & fast_select_2) | (frame_public[151] & fast_select_3) | (frame_lms_q[23] & fast_select_4) | (frame_heap[23] & fast_select_5);
    assign fast_block[152]= (address[24] & fast_select_2) | (frame_public[152] & fast_select_3) | (frame_lms_q[24] & fast_select_4) | (frame_heap[24] & fast_select_5);
    assign fast_block[153]= (address[25] & fast_select_2) | (frame_public[153] & fast_select_3) | (frame_lms_q[25] & fast_select_4) | (frame_heap[25] & fast_select_5);
    assign fast_block[154]= (address[26] & fast_select_2) | (frame_public[154] & fast_select_3) | (frame_lms_q[26] & fast_select_4) | (frame_heap[26] & fast_select_5);
    assign fast_block[155]= (address[27] & fast_select_2) | (frame_public[155] & fast_select_3) | (frame_lms_q[27] & fast_select_4) | (frame_heap[27] & fast_select_5);
    assign fast_block[156]= (address[28] & fast_select_2) | (frame_public[156] & fast_select_3) | (frame_lms_q[28] & fast_select_4) | (frame_heap[28] & fast_select_5);
    assign fast_block[157]= (address[29] & fast_select_2) | (frame_public[157] & fast_select_3) | (frame_lms_q[29] & fast_select_4) | (frame_heap[29] & fast_select_5);
    assign fast_block[158]= (address[30] & fast_select_2) | (frame_public[158] & fast_select_3) | (frame_lms_q[30] & fast_select_4) | (frame_heap[30] & fast_select_5);
    assign fast_block[159]= (address[31] & fast_select_2) | (frame_public[159] & fast_select_3) | (frame_lms_q[31] & fast_select_4) | (frame_heap[31] & fast_select_5);
    assign fast_block[160]= (address[32] & fast_select_2) | (frame_public[160] & fast_select_3) | fast_layout[14];
    assign fast_block[161]= (address[33] & fast_select_2) | (frame_public[161] & fast_select_3) | fast_select_5;
    assign fast_block[162]= (address[34] & fast_select_2) | (frame_public[162] & fast_select_3);
    assign fast_block[163]= (address[35] & fast_select_2) | (frame_public[163] & fast_select_3);
    assign fast_block[164]= (address[36] & fast_select_2) | (frame_public[164] & fast_select_3);
    assign fast_block[165]= (address[37] & fast_select_2) | (frame_public[165] & fast_select_3);
    assign fast_block[166]= (address[38] & fast_select_2) | (frame_public[166] & fast_select_3);
    assign fast_block[167]= (address[39] & fast_select_2) | (frame_public[167] & fast_select_3) | fast_select_5;
    assign fast_block[168]= (address[40] & fast_select_2) | (frame_public[168] & fast_select_3) | (request_a[0] & fast_select_4) | fast_layout[14];
    assign fast_block[169]= (address[41] & fast_select_2) | (frame_public[169] & fast_select_3) | (request_a[1] & fast_select_4) | fast_select_5;
    assign fast_block[170]= (address[42] & fast_select_2) | (frame_public[170] & fast_select_3) | (request_a[2] & fast_select_4);
    assign fast_block[171]= (address[43] & fast_select_2) | (frame_public[171] & fast_select_3) | (request_a[3] & fast_select_4);
    assign fast_block[172]= (address[44] & fast_select_2) | (frame_public[172] & fast_select_3) | (request_a[4] & fast_select_4);
    assign fast_block[173]= (address[45] & fast_select_2) | (frame_public[173] & fast_select_3) | (request_a[5] & fast_select_4);
    assign fast_block[174]= (address[46] & fast_select_2) | (frame_public[174] & fast_select_3) | (request_a[6] & fast_select_4);
    assign fast_block[175]= (address[47] & fast_select_2) | (frame_public[175] & fast_select_3) | fast_select_5;
    assign fast_block[176]= (address[48] & fast_select_2) | (frame_public[176] & fast_select_3) | fast_layout[11] | (request_b[0] & fast_layout[12]) | (frame_left[0] & fast_select_5);
    assign fast_block[177]= (address[49] & fast_select_2) | (frame_public[177] & fast_select_3) | fast_layout[11] | (request_b[1] & fast_layout[12]) | (frame_left[1] & fast_select_5);
    assign fast_block[178]= (address[50] & fast_select_2) | (frame_public[178] & fast_select_3) | fast_layout[11] | (request_b[2] & fast_layout[12]) | (frame_left[2] & fast_select_5);
    assign fast_block[179]= (address[51] & fast_select_2) | (frame_public[179] & fast_select_3) | fast_layout[11] | (request_b[3] & fast_layout[12]) | (frame_left[3] & fast_select_5);
    assign fast_block[180]= (address[52] & fast_select_2) | (frame_public[180] & fast_select_3) | fast_layout[11] | (request_b[4] & fast_layout[12]) | (frame_left[4] & fast_select_5);
    assign fast_block[181]= (address[53] & fast_select_2) | (frame_public[181] & fast_select_3) | fast_layout[11] | (request_b[5] & fast_layout[12]) | (frame_left[5] & fast_select_5);
    assign fast_block[182]= (address[54] & fast_select_2) | (frame_public[182] & fast_select_3) | fast_layout[11] | (request_b[6] & fast_layout[12]) | (frame_left[6] & fast_select_5);
    assign fast_block[183]= (address[55] & fast_select_2) | (frame_public[183] & fast_select_3) | fast_layout[11] | (request_b[7] & fast_layout[12]) | (frame_left[7] & fast_select_5);
    assign fast_block[184]= (address[56] & fast_select_2) | (frame_public[184] & fast_select_3) | (frame_secret[0] & fast_layout[11]) | (frame_left[0] & fast_layout[12]) | (frame_left[8] & fast_select_5);
    assign fast_block[185]= (address[57] & fast_select_2) | (frame_public[185] & fast_select_3) | (frame_secret[1] & fast_layout[11]) | (frame_left[1] & fast_layout[12]) | (frame_left[9] & fast_select_5);
    assign fast_block[186]= (address[58] & fast_select_2) | (frame_public[186] & fast_select_3) | (frame_secret[2] & fast_layout[11]) | (frame_left[2] & fast_layout[12]) | (frame_left[10] & fast_select_5);
    assign fast_block[187]= (address[59] & fast_select_2) | (frame_public[187] & fast_select_3) | (frame_secret[3] & fast_layout[11]) | (frame_left[3] & fast_layout[12]) | (frame_left[11] & fast_select_5);
    assign fast_block[188]= (address[60] & fast_select_2) | (frame_public[188] & fast_select_3) | (frame_secret[4] & fast_layout[11]) | (frame_left[4] & fast_layout[12]) | (frame_left[12] & fast_select_5);
    assign fast_block[189]= (address[61] & fast_select_2) | (frame_public[189] & fast_select_3) | (frame_secret[5] & fast_layout[11]) | (frame_left[5] & fast_layout[12]) | (frame_left[13] & fast_select_5);
    assign fast_block[190]= (address[62] & fast_select_2) | (frame_public[190] & fast_select_3) | (frame_secret[6] & fast_layout[11]) | (frame_left[6] & fast_layout[12]) | (frame_left[14] & fast_select_5);
    assign fast_block[191]= (address[63] & fast_select_2) | (frame_public[191] & fast_select_3) | (frame_secret[7] & fast_layout[11]) | (frame_left[7] & fast_layout[12]) | (frame_left[15] & fast_select_5);
    assign fast_block[192]= (address[64] & fast_select_2) | (address[0] & fast_select_6) | (frame_public[192] & fast_select_7) | (frame_secret[8] & fast_layout[11]) | (frame_left[8] & fast_layout[12]) | (frame_left[16] & fast_select_5);
    assign fast_block[193]= (address[65] & fast_select_2) | (address[1] & fast_select_6) | (frame_public[193] & fast_select_7) | (frame_secret[9] & fast_layout[11]) | (frame_left[9] & fast_layout[12]) | (frame_left[17] & fast_select_5);
    assign fast_block[194]= (address[66] & fast_select_2) | (address[2] & fast_select_6) | (frame_public[194] & fast_select_7) | (frame_secret[10] & fast_layout[11]) | (frame_left[10] & fast_layout[12]) | (frame_left[18] & fast_select_5);
    assign fast_block[195]= (address[67] & fast_select_2) | (address[3] & fast_select_6) | (frame_public[195] & fast_select_7) | (frame_secret[11] & fast_layout[11]) | (frame_left[11] & fast_layout[12]) | (frame_left[19] & fast_select_5);
    assign fast_block[196]= (address[68] & fast_select_2) | (address[4] & fast_select_6) | (frame_public[196] & fast_select_7) | (frame_secret[12] & fast_layout[11]) | (frame_left[12] & fast_layout[12]) | (frame_left[20] & fast_select_5);
    assign fast_block[197]= (address[69] & fast_select_2) | (address[5] & fast_select_6) | (frame_public[197] & fast_select_7) | (frame_secret[13] & fast_layout[11]) | (frame_left[13] & fast_layout[12]) | (frame_left[21] & fast_select_5);
    assign fast_block[198]= (address[70] & fast_select_2) | (address[6] & fast_select_6) | (frame_public[198] & fast_select_7) | (frame_secret[14] & fast_layout[11]) | (frame_left[14] & fast_layout[12]) | (frame_left[22] & fast_select_5);
    assign fast_block[199]= (address[71] & fast_select_2) | (address[7] & fast_select_6) | (frame_public[199] & fast_select_7) | (frame_secret[15] & fast_layout[11]) | (frame_left[15] & fast_layout[12]) | (frame_left[23] & fast_select_5);
    assign fast_block[200]= (address[72] & fast_select_2) | (address[8] & fast_select_6) | (frame_public[200] & fast_select_7) | (frame_secret[16] & fast_layout[11]) | (frame_left[16] & fast_layout[12]) | (frame_left[24] & fast_select_5);
    assign fast_block[201]= (address[73] & fast_select_2) | (address[9] & fast_select_6) | (frame_public[201] & fast_select_7) | (frame_secret[17] & fast_layout[11]) | (frame_left[17] & fast_layout[12]) | (frame_left[25] & fast_select_5);
    assign fast_block[202]= (address[74] & fast_select_2) | (address[10] & fast_select_6) | (frame_public[202] & fast_select_7) | (frame_secret[18] & fast_layout[11]) | (frame_left[18] & fast_layout[12]) | (frame_left[26] & fast_select_5);
    assign fast_block[203]= (address[75] & fast_select_2) | (address[11] & fast_select_6) | (frame_public[203] & fast_select_7) | (frame_secret[19] & fast_layout[11]) | (frame_left[19] & fast_layout[12]) | (frame_left[27] & fast_select_5);
    assign fast_block[204]= (address[76] & fast_select_2) | (address[12] & fast_select_6) | (frame_public[204] & fast_select_7) | (frame_secret[20] & fast_layout[11]) | (frame_left[20] & fast_layout[12]) | (frame_left[28] & fast_select_5);
    assign fast_block[205]= (address[77] & fast_select_2) | (address[13] & fast_select_6) | (frame_public[205] & fast_select_7) | (frame_secret[21] & fast_layout[11]) | (frame_left[21] & fast_layout[12]) | (frame_left[29] & fast_select_5);
    assign fast_block[206]= (address[78] & fast_select_2) | (address[14] & fast_select_6) | (frame_public[206] & fast_select_7) | (frame_secret[22] & fast_layout[11]) | (frame_left[22] & fast_layout[12]) | (frame_left[30] & fast_select_5);
    assign fast_block[207]= (address[79] & fast_select_2) | (address[15] & fast_select_6) | (frame_public[207] & fast_select_7) | (frame_secret[23] & fast_layout[11]) | (frame_left[23] & fast_layout[12]) | (frame_left[31] & fast_select_5);
    assign fast_block[208]= (address[80] & fast_select_2) | (address[16] & fast_select_6) | (frame_public[208] & fast_select_7) | (frame_secret[24] & fast_layout[11]) | (frame_left[24] & fast_layout[12]) | (frame_left[32] & fast_select_5);
    assign fast_block[209]= (address[81] & fast_select_2) | (address[17] & fast_select_6) | (frame_public[209] & fast_select_7) | (frame_secret[25] & fast_layout[11]) | (frame_left[25] & fast_layout[12]) | (frame_left[33] & fast_select_5);
    assign fast_block[210]= (address[82] & fast_select_2) | (address[18] & fast_select_6) | (frame_public[210] & fast_select_7) | (frame_secret[26] & fast_layout[11]) | (frame_left[26] & fast_layout[12]) | (frame_left[34] & fast_select_5);
    assign fast_block[211]= (address[83] & fast_select_2) | (address[19] & fast_select_6) | (frame_public[211] & fast_select_7) | (frame_secret[27] & fast_layout[11]) | (frame_left[27] & fast_layout[12]) | (frame_left[35] & fast_select_5);
    assign fast_block[212]= (address[84] & fast_select_2) | (address[20] & fast_select_6) | (frame_public[212] & fast_select_7) | (frame_secret[28] & fast_layout[11]) | (frame_left[28] & fast_layout[12]) | (frame_left[36] & fast_select_5);
    assign fast_block[213]= (address[85] & fast_select_2) | (address[21] & fast_select_6) | (frame_public[213] & fast_select_7) | (frame_secret[29] & fast_layout[11]) | (frame_left[29] & fast_layout[12]) | (frame_left[37] & fast_select_5);
    assign fast_block[214]= (address[86] & fast_select_2) | (address[22] & fast_select_6) | (frame_public[214] & fast_select_7) | (frame_secret[30] & fast_layout[11]) | (frame_left[30] & fast_layout[12]) | (frame_left[38] & fast_select_5);
    assign fast_block[215]= (address[87] & fast_select_2) | (address[23] & fast_select_6) | (frame_public[215] & fast_select_7) | (frame_secret[31] & fast_layout[11]) | (frame_left[31] & fast_layout[12]) | (frame_left[39] & fast_select_5);
    assign fast_block[216]= (address[88] & fast_select_2) | (address[24] & fast_select_6) | (frame_public[216] & fast_select_7) | (frame_secret[32] & fast_layout[11]) | (frame_left[32] & fast_layout[12]) | (frame_left[40] & fast_select_5);
    assign fast_block[217]= (address[89] & fast_select_2) | (address[25] & fast_select_6) | (frame_public[217] & fast_select_7) | (frame_secret[33] & fast_layout[11]) | (frame_left[33] & fast_layout[12]) | (frame_left[41] & fast_select_5);
    assign fast_block[218]= (address[90] & fast_select_2) | (address[26] & fast_select_6) | (frame_public[218] & fast_select_7) | (frame_secret[34] & fast_layout[11]) | (frame_left[34] & fast_layout[12]) | (frame_left[42] & fast_select_5);
    assign fast_block[219]= (address[91] & fast_select_2) | (address[27] & fast_select_6) | (frame_public[219] & fast_select_7) | (frame_secret[35] & fast_layout[11]) | (frame_left[35] & fast_layout[12]) | (frame_left[43] & fast_select_5);
    assign fast_block[220]= (address[92] & fast_select_2) | (address[28] & fast_select_6) | (frame_public[220] & fast_select_7) | (frame_secret[36] & fast_layout[11]) | (frame_left[36] & fast_layout[12]) | (frame_left[44] & fast_select_5);
    assign fast_block[221]= (address[93] & fast_select_2) | (address[29] & fast_select_6) | (frame_public[221] & fast_select_7) | (frame_secret[37] & fast_layout[11]) | (frame_left[37] & fast_layout[12]) | (frame_left[45] & fast_select_5);
    assign fast_block[222]= (address[94] & fast_select_2) | (address[30] & fast_select_6) | (frame_public[222] & fast_select_7) | (frame_secret[38] & fast_layout[11]) | (frame_left[38] & fast_layout[12]) | (frame_left[46] & fast_select_5);
    assign fast_block[223]= (address[95] & fast_select_2) | (address[31] & fast_select_6) | (frame_public[223] & fast_select_7) | (frame_secret[39] & fast_layout[11]) | (frame_left[39] & fast_layout[12]) | (frame_left[47] & fast_select_5);
    assign fast_block[224]= (address[96] & fast_select_2) | (address[32] & fast_select_6) | (frame_public[224] & fast_select_7) | (frame_secret[40] & fast_layout[11]) | (frame_left[40] & fast_layout[12]) | (frame_left[48] & fast_select_5);
    assign fast_block[225]= (address[97] & fast_select_2) | (address[33] & fast_select_6) | (frame_public[225] & fast_select_7) | (frame_secret[41] & fast_layout[11]) | (frame_left[41] & fast_layout[12]) | (frame_left[49] & fast_select_5);
    assign fast_block[226]= (address[98] & fast_select_2) | (address[34] & fast_select_6) | (frame_public[226] & fast_select_7) | (frame_secret[42] & fast_layout[11]) | (frame_left[42] & fast_layout[12]) | (frame_left[50] & fast_select_5);
    assign fast_block[227]= (address[99] & fast_select_2) | (address[35] & fast_select_6) | (frame_public[227] & fast_select_7) | (frame_secret[43] & fast_layout[11]) | (frame_left[43] & fast_layout[12]) | (frame_left[51] & fast_select_5);
    assign fast_block[228]= (address[100] & fast_select_2) | (address[36] & fast_select_6) | (frame_public[228] & fast_select_7) | (frame_secret[44] & fast_layout[11]) | (frame_left[44] & fast_layout[12]) | (frame_left[52] & fast_select_5);
    assign fast_block[229]= (address[101] & fast_select_2) | (address[37] & fast_select_6) | (frame_public[229] & fast_select_7) | (frame_secret[45] & fast_layout[11]) | (frame_left[45] & fast_layout[12]) | (frame_left[53] & fast_select_5);
    assign fast_block[230]= (address[102] & fast_select_2) | (address[38] & fast_select_6) | (frame_public[230] & fast_select_7) | (frame_secret[46] & fast_layout[11]) | (frame_left[46] & fast_layout[12]) | (frame_left[54] & fast_select_5);
    assign fast_block[231]= (address[103] & fast_select_2) | (address[39] & fast_select_6) | (frame_public[231] & fast_select_7) | (frame_secret[47] & fast_layout[11]) | (frame_left[47] & fast_layout[12]) | (frame_left[55] & fast_select_5);
    assign fast_block[232]= (address[104] & fast_select_2) | (address[40] & fast_select_6) | (frame_public[232] & fast_select_7) | (frame_secret[48] & fast_layout[11]) | (frame_left[48] & fast_layout[12]) | (frame_left[56] & fast_select_5);
    assign fast_block[233]= (address[105] & fast_select_2) | (address[41] & fast_select_6) | (frame_public[233] & fast_select_7) | (frame_secret[49] & fast_layout[11]) | (frame_left[49] & fast_layout[12]) | (frame_left[57] & fast_select_5);
    assign fast_block[234]= (address[106] & fast_select_2) | (address[42] & fast_select_6) | (frame_public[234] & fast_select_7) | (frame_secret[50] & fast_layout[11]) | (frame_left[50] & fast_layout[12]) | (frame_left[58] & fast_select_5);
    assign fast_block[235]= (address[107] & fast_select_2) | (address[43] & fast_select_6) | (frame_public[235] & fast_select_7) | (frame_secret[51] & fast_layout[11]) | (frame_left[51] & fast_layout[12]) | (frame_left[59] & fast_select_5);
    assign fast_block[236]= (address[108] & fast_select_2) | (address[44] & fast_select_6) | (frame_public[236] & fast_select_7) | (frame_secret[52] & fast_layout[11]) | (frame_left[52] & fast_layout[12]) | (frame_left[60] & fast_select_5);
    assign fast_block[237]= (address[109] & fast_select_2) | (address[45] & fast_select_6) | (frame_public[237] & fast_select_7) | (frame_secret[53] & fast_layout[11]) | (frame_left[53] & fast_layout[12]) | (frame_left[61] & fast_select_5);
    assign fast_block[238]= (address[110] & fast_select_2) | (address[46] & fast_select_6) | (frame_public[238] & fast_select_7) | (frame_secret[54] & fast_layout[11]) | (frame_left[54] & fast_layout[12]) | (frame_left[62] & fast_select_5);
    assign fast_block[239]= (address[111] & fast_select_2) | (address[47] & fast_select_6) | (frame_public[239] & fast_select_7) | (frame_secret[55] & fast_layout[11]) | (frame_left[55] & fast_layout[12]) | (frame_left[63] & fast_select_5);
    assign fast_block[240]= (address[112] & fast_select_2) | (address[48] & fast_select_6) | (frame_public[240] & fast_select_7) | (frame_secret[56] & fast_layout[11]) | (frame_left[56] & fast_layout[12]) | (frame_left[64] & fast_select_5);
    assign fast_block[241]= (address[113] & fast_select_2) | (address[49] & fast_select_6) | (frame_public[241] & fast_select_7) | (frame_secret[57] & fast_layout[11]) | (frame_left[57] & fast_layout[12]) | (frame_left[65] & fast_select_5);
    assign fast_block[242]= (address[114] & fast_select_2) | (address[50] & fast_select_6) | (frame_public[242] & fast_select_7) | (frame_secret[58] & fast_layout[11]) | (frame_left[58] & fast_layout[12]) | (frame_left[66] & fast_select_5);
    assign fast_block[243]= (address[115] & fast_select_2) | (address[51] & fast_select_6) | (frame_public[243] & fast_select_7) | (frame_secret[59] & fast_layout[11]) | (frame_left[59] & fast_layout[12]) | (frame_left[67] & fast_select_5);
    assign fast_block[244]= (address[116] & fast_select_2) | (address[52] & fast_select_6) | (frame_public[244] & fast_select_7) | (frame_secret[60] & fast_layout[11]) | (frame_left[60] & fast_layout[12]) | (frame_left[68] & fast_select_5);
    assign fast_block[245]= (address[117] & fast_select_2) | (address[53] & fast_select_6) | (frame_public[245] & fast_select_7) | (frame_secret[61] & fast_layout[11]) | (frame_left[61] & fast_layout[12]) | (frame_left[69] & fast_select_5);
    assign fast_block[246]= (address[118] & fast_select_2) | (address[54] & fast_select_6) | (frame_public[246] & fast_select_7) | (frame_secret[62] & fast_layout[11]) | (frame_left[62] & fast_layout[12]) | (frame_left[70] & fast_select_5);
    assign fast_block[247]= (address[119] & fast_select_2) | (address[55] & fast_select_6) | (frame_public[247] & fast_select_7) | (frame_secret[63] & fast_layout[11]) | (frame_left[63] & fast_layout[12]) | (frame_left[71] & fast_select_5);
    assign fast_block[248]= (address[120] & fast_select_2) | (address[56] & fast_select_6) | (frame_public[248] & fast_select_7) | fast_select_8 | (frame_secret[64] & fast_layout[11]) | (frame_left[64] & fast_layout[12]) | (frame_left[72] & fast_select_5);
    assign fast_block[249]= (address[121] & fast_select_2) | (address[57] & fast_select_6) | (frame_public[249] & fast_select_7) | fast_select_9 | (frame_secret[65] & fast_layout[11]) | (frame_left[65] & fast_layout[12]) | (frame_left[73] & fast_select_5);
    assign fast_block[250]= (address[122] & fast_select_2) | (address[58] & fast_select_6) | (frame_public[250] & fast_select_7) | fast_layout[6] | (frame_secret[66] & fast_layout[11]) | (frame_left[66] & fast_layout[12]) | (frame_left[74] & fast_select_5);
    assign fast_block[251]= (address[123] & fast_select_2) | (address[59] & fast_select_6) | (frame_public[251] & fast_select_7) | (frame_secret[67] & fast_layout[11]) | (frame_left[67] & fast_layout[12]) | (frame_left[75] & fast_select_5);
    assign fast_block[252]= (address[124] & fast_select_2) | (address[60] & fast_select_6) | (frame_public[252] & fast_select_7) | (frame_secret[68] & fast_layout[11]) | (frame_left[68] & fast_layout[12]) | (frame_left[76] & fast_select_5);
    assign fast_block[253]= (address[125] & fast_select_2) | (address[61] & fast_select_6) | (frame_public[253] & fast_select_7) | (frame_secret[69] & fast_layout[11]) | (frame_left[69] & fast_layout[12]) | (frame_left[77] & fast_select_5);
    assign fast_block[254]= (address[126] & fast_select_2) | (address[62] & fast_select_6) | (frame_public[254] & fast_select_7) | (frame_secret[70] & fast_layout[11]) | (frame_left[70] & fast_layout[12]) | (frame_left[78] & fast_select_5);
    assign fast_block[255]= (address[127] & fast_select_2) | (address[63] & fast_select_6) | (frame_public[255] & fast_select_7) | (frame_secret[71] & fast_layout[11]) | (frame_left[71] & fast_layout[12]) | (frame_left[79] & fast_select_5);
    assign fast_block[256]= (address[128] & fast_select_2) | (address[64] & fast_select_6) | (address[0] & fast_select_7) | (frame_secret[0] & fast_layout[6]) | (frame_prf[0] & fast_layout[7]) | (frame_public[0] & fast_layout[8]) | (frame_key[0] & fast_select_10) | (frame_secret[72] & fast_layout[11]) | (frame_left[72] & fast_layout[12]) | (frame_left[80] & fast_select_5);
    assign fast_block[257]= (address[129] & fast_select_2) | (address[65] & fast_select_6) | (address[1] & fast_select_7) | (frame_secret[1] & fast_layout[6]) | (frame_prf[1] & fast_layout[7]) | (frame_public[1] & fast_layout[8]) | (frame_key[1] & fast_select_10) | (frame_secret[73] & fast_layout[11]) | (frame_left[73] & fast_layout[12]) | (frame_left[81] & fast_select_5);
    assign fast_block[258]= (address[130] & fast_select_2) | (address[66] & fast_select_6) | (address[2] & fast_select_7) | (frame_secret[2] & fast_layout[6]) | (frame_prf[2] & fast_layout[7]) | (frame_public[2] & fast_layout[8]) | (frame_key[2] & fast_select_10) | (frame_secret[74] & fast_layout[11]) | (frame_left[74] & fast_layout[12]) | (frame_left[82] & fast_select_5);
    assign fast_block[259]= (address[131] & fast_select_2) | (address[67] & fast_select_6) | (address[3] & fast_select_7) | (frame_secret[3] & fast_layout[6]) | (frame_prf[3] & fast_layout[7]) | (frame_public[3] & fast_layout[8]) | (frame_key[3] & fast_select_10) | (frame_secret[75] & fast_layout[11]) | (frame_left[75] & fast_layout[12]) | (frame_left[83] & fast_select_5);
    assign fast_block[260]= (address[132] & fast_select_2) | (address[68] & fast_select_6) | (address[4] & fast_select_7) | (frame_secret[4] & fast_layout[6]) | (frame_prf[4] & fast_layout[7]) | (frame_public[4] & fast_layout[8]) | (frame_key[4] & fast_select_10) | (frame_secret[76] & fast_layout[11]) | (frame_left[76] & fast_layout[12]) | (frame_left[84] & fast_select_5);
    assign fast_block[261]= (address[133] & fast_select_2) | (address[69] & fast_select_6) | (address[5] & fast_select_7) | (frame_secret[5] & fast_layout[6]) | (frame_prf[5] & fast_layout[7]) | (frame_public[5] & fast_layout[8]) | (frame_key[5] & fast_select_10) | (frame_secret[77] & fast_layout[11]) | (frame_left[77] & fast_layout[12]) | (frame_left[85] & fast_select_5);
    assign fast_block[262]= (address[134] & fast_select_2) | (address[70] & fast_select_6) | (address[6] & fast_select_7) | (frame_secret[6] & fast_layout[6]) | (frame_prf[6] & fast_layout[7]) | (frame_public[6] & fast_layout[8]) | (frame_key[6] & fast_select_10) | (frame_secret[78] & fast_layout[11]) | (frame_left[78] & fast_layout[12]) | (frame_left[86] & fast_select_5);
    assign fast_block[263]= (address[135] & fast_select_2) | (address[71] & fast_select_6) | (address[7] & fast_select_7) | (frame_secret[7] & fast_layout[6]) | (frame_prf[7] & fast_layout[7]) | (frame_public[7] & fast_layout[8]) | (frame_key[7] & fast_select_10) | (frame_secret[79] & fast_layout[11]) | (frame_left[79] & fast_layout[12]) | (frame_left[87] & fast_select_5);
    assign fast_block[264]= (address[136] & fast_select_2) | (address[72] & fast_select_6) | (address[8] & fast_select_7) | (frame_secret[8] & fast_layout[6]) | (frame_prf[8] & fast_layout[7]) | (frame_public[8] & fast_layout[8]) | (frame_key[8] & fast_select_10) | (frame_secret[80] & fast_layout[11]) | (frame_left[80] & fast_layout[12]) | (frame_left[88] & fast_select_5);
    assign fast_block[265]= (address[137] & fast_select_2) | (address[73] & fast_select_6) | (address[9] & fast_select_7) | (frame_secret[9] & fast_layout[6]) | (frame_prf[9] & fast_layout[7]) | (frame_public[9] & fast_layout[8]) | (frame_key[9] & fast_select_10) | (frame_secret[81] & fast_layout[11]) | (frame_left[81] & fast_layout[12]) | (frame_left[89] & fast_select_5);
    assign fast_block[266]= (address[138] & fast_select_2) | (address[74] & fast_select_6) | (address[10] & fast_select_7) | (frame_secret[10] & fast_layout[6]) | (frame_prf[10] & fast_layout[7]) | (frame_public[10] & fast_layout[8]) | (frame_key[10] & fast_select_10) | (frame_secret[82] & fast_layout[11]) | (frame_left[82] & fast_layout[12]) | (frame_left[90] & fast_select_5);
    assign fast_block[267]= (address[139] & fast_select_2) | (address[75] & fast_select_6) | (address[11] & fast_select_7) | (frame_secret[11] & fast_layout[6]) | (frame_prf[11] & fast_layout[7]) | (frame_public[11] & fast_layout[8]) | (frame_key[11] & fast_select_10) | (frame_secret[83] & fast_layout[11]) | (frame_left[83] & fast_layout[12]) | (frame_left[91] & fast_select_5);
    assign fast_block[268]= (address[140] & fast_select_2) | (address[76] & fast_select_6) | (address[12] & fast_select_7) | (frame_secret[12] & fast_layout[6]) | (frame_prf[12] & fast_layout[7]) | (frame_public[12] & fast_layout[8]) | (frame_key[12] & fast_select_10) | (frame_secret[84] & fast_layout[11]) | (frame_left[84] & fast_layout[12]) | (frame_left[92] & fast_select_5);
    assign fast_block[269]= (address[141] & fast_select_2) | (address[77] & fast_select_6) | (address[13] & fast_select_7) | (frame_secret[13] & fast_layout[6]) | (frame_prf[13] & fast_layout[7]) | (frame_public[13] & fast_layout[8]) | (frame_key[13] & fast_select_10) | (frame_secret[85] & fast_layout[11]) | (frame_left[85] & fast_layout[12]) | (frame_left[93] & fast_select_5);
    assign fast_block[270]= (address[142] & fast_select_2) | (address[78] & fast_select_6) | (address[14] & fast_select_7) | (frame_secret[14] & fast_layout[6]) | (frame_prf[14] & fast_layout[7]) | (frame_public[14] & fast_layout[8]) | (frame_key[14] & fast_select_10) | (frame_secret[86] & fast_layout[11]) | (frame_left[86] & fast_layout[12]) | (frame_left[94] & fast_select_5);
    assign fast_block[271]= (address[143] & fast_select_2) | (address[79] & fast_select_6) | (address[15] & fast_select_7) | (frame_secret[15] & fast_layout[6]) | (frame_prf[15] & fast_layout[7]) | (frame_public[15] & fast_layout[8]) | (frame_key[15] & fast_select_10) | (frame_secret[87] & fast_layout[11]) | (frame_left[87] & fast_layout[12]) | (frame_left[95] & fast_select_5);
    assign fast_block[272]= (address[144] & fast_select_2) | (address[80] & fast_select_6) | (address[16] & fast_select_7) | (frame_secret[16] & fast_layout[6]) | (frame_prf[16] & fast_layout[7]) | (frame_public[16] & fast_layout[8]) | (frame_key[16] & fast_select_10) | (frame_secret[88] & fast_layout[11]) | (frame_left[88] & fast_layout[12]) | (frame_left[96] & fast_select_5);
    assign fast_block[273]= (address[145] & fast_select_2) | (address[81] & fast_select_6) | (address[17] & fast_select_7) | (frame_secret[17] & fast_layout[6]) | (frame_prf[17] & fast_layout[7]) | (frame_public[17] & fast_layout[8]) | (frame_key[17] & fast_select_10) | (frame_secret[89] & fast_layout[11]) | (frame_left[89] & fast_layout[12]) | (frame_left[97] & fast_select_5);
    assign fast_block[274]= (address[146] & fast_select_2) | (address[82] & fast_select_6) | (address[18] & fast_select_7) | (frame_secret[18] & fast_layout[6]) | (frame_prf[18] & fast_layout[7]) | (frame_public[18] & fast_layout[8]) | (frame_key[18] & fast_select_10) | (frame_secret[90] & fast_layout[11]) | (frame_left[90] & fast_layout[12]) | (frame_left[98] & fast_select_5);
    assign fast_block[275]= (address[147] & fast_select_2) | (address[83] & fast_select_6) | (address[19] & fast_select_7) | (frame_secret[19] & fast_layout[6]) | (frame_prf[19] & fast_layout[7]) | (frame_public[19] & fast_layout[8]) | (frame_key[19] & fast_select_10) | (frame_secret[91] & fast_layout[11]) | (frame_left[91] & fast_layout[12]) | (frame_left[99] & fast_select_5);
    assign fast_block[276]= (address[148] & fast_select_2) | (address[84] & fast_select_6) | (address[20] & fast_select_7) | (frame_secret[20] & fast_layout[6]) | (frame_prf[20] & fast_layout[7]) | (frame_public[20] & fast_layout[8]) | (frame_key[20] & fast_select_10) | (frame_secret[92] & fast_layout[11]) | (frame_left[92] & fast_layout[12]) | (frame_left[100] & fast_select_5);
    assign fast_block[277]= (address[149] & fast_select_2) | (address[85] & fast_select_6) | (address[21] & fast_select_7) | (frame_secret[21] & fast_layout[6]) | (frame_prf[21] & fast_layout[7]) | (frame_public[21] & fast_layout[8]) | (frame_key[21] & fast_select_10) | (frame_secret[93] & fast_layout[11]) | (frame_left[93] & fast_layout[12]) | (frame_left[101] & fast_select_5);
    assign fast_block[278]= (address[150] & fast_select_2) | (address[86] & fast_select_6) | (address[22] & fast_select_7) | (frame_secret[22] & fast_layout[6]) | (frame_prf[22] & fast_layout[7]) | (frame_public[22] & fast_layout[8]) | (frame_key[22] & fast_select_10) | (frame_secret[94] & fast_layout[11]) | (frame_left[94] & fast_layout[12]) | (frame_left[102] & fast_select_5);
    assign fast_block[279]= (address[151] & fast_select_2) | (address[87] & fast_select_6) | (address[23] & fast_select_7) | (frame_secret[23] & fast_layout[6]) | (frame_prf[23] & fast_layout[7]) | (frame_public[23] & fast_layout[8]) | (frame_key[23] & fast_select_10) | (frame_secret[95] & fast_layout[11]) | (frame_left[95] & fast_layout[12]) | (frame_left[103] & fast_select_5);
    assign fast_block[280]= (address[152] & fast_select_2) | (address[88] & fast_select_6) | (address[24] & fast_select_7) | (frame_secret[24] & fast_layout[6]) | (frame_prf[24] & fast_layout[7]) | (frame_public[24] & fast_layout[8]) | (frame_key[24] & fast_select_10) | (frame_secret[96] & fast_layout[11]) | (frame_left[96] & fast_layout[12]) | (frame_left[104] & fast_select_5);
    assign fast_block[281]= (address[153] & fast_select_2) | (address[89] & fast_select_6) | (address[25] & fast_select_7) | (frame_secret[25] & fast_layout[6]) | (frame_prf[25] & fast_layout[7]) | (frame_public[25] & fast_layout[8]) | (frame_key[25] & fast_select_10) | (frame_secret[97] & fast_layout[11]) | (frame_left[97] & fast_layout[12]) | (frame_left[105] & fast_select_5);
    assign fast_block[282]= (address[154] & fast_select_2) | (address[90] & fast_select_6) | (address[26] & fast_select_7) | (frame_secret[26] & fast_layout[6]) | (frame_prf[26] & fast_layout[7]) | (frame_public[26] & fast_layout[8]) | (frame_key[26] & fast_select_10) | (frame_secret[98] & fast_layout[11]) | (frame_left[98] & fast_layout[12]) | (frame_left[106] & fast_select_5);
    assign fast_block[283]= (address[155] & fast_select_2) | (address[91] & fast_select_6) | (address[27] & fast_select_7) | (frame_secret[27] & fast_layout[6]) | (frame_prf[27] & fast_layout[7]) | (frame_public[27] & fast_layout[8]) | (frame_key[27] & fast_select_10) | (frame_secret[99] & fast_layout[11]) | (frame_left[99] & fast_layout[12]) | (frame_left[107] & fast_select_5);
    assign fast_block[284]= (address[156] & fast_select_2) | (address[92] & fast_select_6) | (address[28] & fast_select_7) | (frame_secret[28] & fast_layout[6]) | (frame_prf[28] & fast_layout[7]) | (frame_public[28] & fast_layout[8]) | (frame_key[28] & fast_select_10) | (frame_secret[100] & fast_layout[11]) | (frame_left[100] & fast_layout[12]) | (frame_left[108] & fast_select_5);
    assign fast_block[285]= (address[157] & fast_select_2) | (address[93] & fast_select_6) | (address[29] & fast_select_7) | (frame_secret[29] & fast_layout[6]) | (frame_prf[29] & fast_layout[7]) | (frame_public[29] & fast_layout[8]) | (frame_key[29] & fast_select_10) | (frame_secret[101] & fast_layout[11]) | (frame_left[101] & fast_layout[12]) | (frame_left[109] & fast_select_5);
    assign fast_block[286]= (address[158] & fast_select_2) | (address[94] & fast_select_6) | (address[30] & fast_select_7) | (frame_secret[30] & fast_layout[6]) | (frame_prf[30] & fast_layout[7]) | (frame_public[30] & fast_layout[8]) | (frame_key[30] & fast_select_10) | (frame_secret[102] & fast_layout[11]) | (frame_left[102] & fast_layout[12]) | (frame_left[110] & fast_select_5);
    assign fast_block[287]= (address[159] & fast_select_2) | (address[95] & fast_select_6) | (address[31] & fast_select_7) | (frame_secret[31] & fast_layout[6]) | (frame_prf[31] & fast_layout[7]) | (frame_public[31] & fast_layout[8]) | (frame_key[31] & fast_select_10) | (frame_secret[103] & fast_layout[11]) | (frame_left[103] & fast_layout[12]) | (frame_left[111] & fast_select_5);
    assign fast_block[288]= (address[160] & fast_select_2) | (address[96] & fast_select_6) | (address[32] & fast_select_7) | (frame_secret[32] & fast_layout[6]) | (frame_prf[32] & fast_layout[7]) | (frame_public[32] & fast_layout[8]) | (frame_key[32] & fast_select_10) | (frame_secret[104] & fast_layout[11]) | (frame_left[104] & fast_layout[12]) | (frame_left[112] & fast_select_5);
    assign fast_block[289]= (address[161] & fast_select_2) | (address[97] & fast_select_6) | (address[33] & fast_select_7) | (frame_secret[33] & fast_layout[6]) | (frame_prf[33] & fast_layout[7]) | (frame_public[33] & fast_layout[8]) | (frame_key[33] & fast_select_10) | (frame_secret[105] & fast_layout[11]) | (frame_left[105] & fast_layout[12]) | (frame_left[113] & fast_select_5);
    assign fast_block[290]= (address[162] & fast_select_2) | (address[98] & fast_select_6) | (address[34] & fast_select_7) | (frame_secret[34] & fast_layout[6]) | (frame_prf[34] & fast_layout[7]) | (frame_public[34] & fast_layout[8]) | (frame_key[34] & fast_select_10) | (frame_secret[106] & fast_layout[11]) | (frame_left[106] & fast_layout[12]) | (frame_left[114] & fast_select_5);
    assign fast_block[291]= (address[163] & fast_select_2) | (address[99] & fast_select_6) | (address[35] & fast_select_7) | (frame_secret[35] & fast_layout[6]) | (frame_prf[35] & fast_layout[7]) | (frame_public[35] & fast_layout[8]) | (frame_key[35] & fast_select_10) | (frame_secret[107] & fast_layout[11]) | (frame_left[107] & fast_layout[12]) | (frame_left[115] & fast_select_5);
    assign fast_block[292]= (address[164] & fast_select_2) | (address[100] & fast_select_6) | (address[36] & fast_select_7) | (frame_secret[36] & fast_layout[6]) | (frame_prf[36] & fast_layout[7]) | (frame_public[36] & fast_layout[8]) | (frame_key[36] & fast_select_10) | (frame_secret[108] & fast_layout[11]) | (frame_left[108] & fast_layout[12]) | (frame_left[116] & fast_select_5);
    assign fast_block[293]= (address[165] & fast_select_2) | (address[101] & fast_select_6) | (address[37] & fast_select_7) | (frame_secret[37] & fast_layout[6]) | (frame_prf[37] & fast_layout[7]) | (frame_public[37] & fast_layout[8]) | (frame_key[37] & fast_select_10) | (frame_secret[109] & fast_layout[11]) | (frame_left[109] & fast_layout[12]) | (frame_left[117] & fast_select_5);
    assign fast_block[294]= (address[166] & fast_select_2) | (address[102] & fast_select_6) | (address[38] & fast_select_7) | (frame_secret[38] & fast_layout[6]) | (frame_prf[38] & fast_layout[7]) | (frame_public[38] & fast_layout[8]) | (frame_key[38] & fast_select_10) | (frame_secret[110] & fast_layout[11]) | (frame_left[110] & fast_layout[12]) | (frame_left[118] & fast_select_5);
    assign fast_block[295]= (address[167] & fast_select_2) | (address[103] & fast_select_6) | (address[39] & fast_select_7) | (frame_secret[39] & fast_layout[6]) | (frame_prf[39] & fast_layout[7]) | (frame_public[39] & fast_layout[8]) | (frame_key[39] & fast_select_10) | (frame_secret[111] & fast_layout[11]) | (frame_left[111] & fast_layout[12]) | (frame_left[119] & fast_select_5);
    assign fast_block[296]= (address[168] & fast_select_2) | (address[104] & fast_select_6) | (address[40] & fast_select_7) | (frame_secret[40] & fast_layout[6]) | (frame_prf[40] & fast_layout[7]) | (frame_public[40] & fast_layout[8]) | (frame_key[40] & fast_select_10) | (frame_secret[112] & fast_layout[11]) | (frame_left[112] & fast_layout[12]) | (frame_left[120] & fast_select_5);
    assign fast_block[297]= (address[169] & fast_select_2) | (address[105] & fast_select_6) | (address[41] & fast_select_7) | (frame_secret[41] & fast_layout[6]) | (frame_prf[41] & fast_layout[7]) | (frame_public[41] & fast_layout[8]) | (frame_key[41] & fast_select_10) | (frame_secret[113] & fast_layout[11]) | (frame_left[113] & fast_layout[12]) | (frame_left[121] & fast_select_5);
    assign fast_block[298]= (address[170] & fast_select_2) | (address[106] & fast_select_6) | (address[42] & fast_select_7) | (frame_secret[42] & fast_layout[6]) | (frame_prf[42] & fast_layout[7]) | (frame_public[42] & fast_layout[8]) | (frame_key[42] & fast_select_10) | (frame_secret[114] & fast_layout[11]) | (frame_left[114] & fast_layout[12]) | (frame_left[122] & fast_select_5);
    assign fast_block[299]= (address[171] & fast_select_2) | (address[107] & fast_select_6) | (address[43] & fast_select_7) | (frame_secret[43] & fast_layout[6]) | (frame_prf[43] & fast_layout[7]) | (frame_public[43] & fast_layout[8]) | (frame_key[43] & fast_select_10) | (frame_secret[115] & fast_layout[11]) | (frame_left[115] & fast_layout[12]) | (frame_left[123] & fast_select_5);
    assign fast_block[300]= (address[172] & fast_select_2) | (address[108] & fast_select_6) | (address[44] & fast_select_7) | (frame_secret[44] & fast_layout[6]) | (frame_prf[44] & fast_layout[7]) | (frame_public[44] & fast_layout[8]) | (frame_key[44] & fast_select_10) | (frame_secret[116] & fast_layout[11]) | (frame_left[116] & fast_layout[12]) | (frame_left[124] & fast_select_5);
    assign fast_block[301]= (address[173] & fast_select_2) | (address[109] & fast_select_6) | (address[45] & fast_select_7) | (frame_secret[45] & fast_layout[6]) | (frame_prf[45] & fast_layout[7]) | (frame_public[45] & fast_layout[8]) | (frame_key[45] & fast_select_10) | (frame_secret[117] & fast_layout[11]) | (frame_left[117] & fast_layout[12]) | (frame_left[125] & fast_select_5);
    assign fast_block[302]= (address[174] & fast_select_2) | (address[110] & fast_select_6) | (address[46] & fast_select_7) | (frame_secret[46] & fast_layout[6]) | (frame_prf[46] & fast_layout[7]) | (frame_public[46] & fast_layout[8]) | (frame_key[46] & fast_select_10) | (frame_secret[118] & fast_layout[11]) | (frame_left[118] & fast_layout[12]) | (frame_left[126] & fast_select_5);
    assign fast_block[303]= (address[175] & fast_select_2) | (address[111] & fast_select_6) | (address[47] & fast_select_7) | (frame_secret[47] & fast_layout[6]) | (frame_prf[47] & fast_layout[7]) | (frame_public[47] & fast_layout[8]) | (frame_key[47] & fast_select_10) | (frame_secret[119] & fast_layout[11]) | (frame_left[119] & fast_layout[12]) | (frame_left[127] & fast_select_5);
    assign fast_block[304]= (address[176] & fast_select_2) | (address[112] & fast_select_6) | (address[48] & fast_select_7) | (frame_secret[48] & fast_layout[6]) | (frame_prf[48] & fast_layout[7]) | (frame_public[48] & fast_layout[8]) | (frame_key[48] & fast_select_10) | (frame_secret[120] & fast_layout[11]) | (frame_left[120] & fast_layout[12]) | (frame_left[128] & fast_select_5);
    assign fast_block[305]= (address[177] & fast_select_2) | (address[113] & fast_select_6) | (address[49] & fast_select_7) | (frame_secret[49] & fast_layout[6]) | (frame_prf[49] & fast_layout[7]) | (frame_public[49] & fast_layout[8]) | (frame_key[49] & fast_select_10) | (frame_secret[121] & fast_layout[11]) | (frame_left[121] & fast_layout[12]) | (frame_left[129] & fast_select_5);
    assign fast_block[306]= (address[178] & fast_select_2) | (address[114] & fast_select_6) | (address[50] & fast_select_7) | (frame_secret[50] & fast_layout[6]) | (frame_prf[50] & fast_layout[7]) | (frame_public[50] & fast_layout[8]) | (frame_key[50] & fast_select_10) | (frame_secret[122] & fast_layout[11]) | (frame_left[122] & fast_layout[12]) | (frame_left[130] & fast_select_5);
    assign fast_block[307]= (address[179] & fast_select_2) | (address[115] & fast_select_6) | (address[51] & fast_select_7) | (frame_secret[51] & fast_layout[6]) | (frame_prf[51] & fast_layout[7]) | (frame_public[51] & fast_layout[8]) | (frame_key[51] & fast_select_10) | (frame_secret[123] & fast_layout[11]) | (frame_left[123] & fast_layout[12]) | (frame_left[131] & fast_select_5);
    assign fast_block[308]= (address[180] & fast_select_2) | (address[116] & fast_select_6) | (address[52] & fast_select_7) | (frame_secret[52] & fast_layout[6]) | (frame_prf[52] & fast_layout[7]) | (frame_public[52] & fast_layout[8]) | (frame_key[52] & fast_select_10) | (frame_secret[124] & fast_layout[11]) | (frame_left[124] & fast_layout[12]) | (frame_left[132] & fast_select_5);
    assign fast_block[309]= (address[181] & fast_select_2) | (address[117] & fast_select_6) | (address[53] & fast_select_7) | (frame_secret[53] & fast_layout[6]) | (frame_prf[53] & fast_layout[7]) | (frame_public[53] & fast_layout[8]) | (frame_key[53] & fast_select_10) | (frame_secret[125] & fast_layout[11]) | (frame_left[125] & fast_layout[12]) | (frame_left[133] & fast_select_5);
    assign fast_block[310]= (address[182] & fast_select_2) | (address[118] & fast_select_6) | (address[54] & fast_select_7) | (frame_secret[54] & fast_layout[6]) | (frame_prf[54] & fast_layout[7]) | (frame_public[54] & fast_layout[8]) | (frame_key[54] & fast_select_10) | (frame_secret[126] & fast_layout[11]) | (frame_left[126] & fast_layout[12]) | (frame_left[134] & fast_select_5);
    assign fast_block[311]= (address[183] & fast_select_2) | (address[119] & fast_select_6) | (address[55] & fast_select_7) | (frame_secret[55] & fast_layout[6]) | (frame_prf[55] & fast_layout[7]) | (frame_public[55] & fast_layout[8]) | (frame_key[55] & fast_select_10) | (frame_secret[127] & fast_layout[11]) | (frame_left[127] & fast_layout[12]) | (frame_left[135] & fast_select_5);
    assign fast_block[312]= (address[184] & fast_select_2) | (address[120] & fast_select_6) | (address[56] & fast_select_7) | (frame_secret[56] & fast_layout[6]) | (frame_prf[56] & fast_layout[7]) | (frame_public[56] & fast_layout[8]) | (frame_key[56] & fast_select_10) | (frame_secret[128] & fast_layout[11]) | (frame_left[128] & fast_layout[12]) | (frame_left[136] & fast_select_5);
    assign fast_block[313]= (address[185] & fast_select_2) | (address[121] & fast_select_6) | (address[57] & fast_select_7) | (frame_secret[57] & fast_layout[6]) | (frame_prf[57] & fast_layout[7]) | (frame_public[57] & fast_layout[8]) | (frame_key[57] & fast_select_10) | (frame_secret[129] & fast_layout[11]) | (frame_left[129] & fast_layout[12]) | (frame_left[137] & fast_select_5);
    assign fast_block[314]= (address[186] & fast_select_2) | (address[122] & fast_select_6) | (address[58] & fast_select_7) | (frame_secret[58] & fast_layout[6]) | (frame_prf[58] & fast_layout[7]) | (frame_public[58] & fast_layout[8]) | (frame_key[58] & fast_select_10) | (frame_secret[130] & fast_layout[11]) | (frame_left[130] & fast_layout[12]) | (frame_left[138] & fast_select_5);
    assign fast_block[315]= (address[187] & fast_select_2) | (address[123] & fast_select_6) | (address[59] & fast_select_7) | (frame_secret[59] & fast_layout[6]) | (frame_prf[59] & fast_layout[7]) | (frame_public[59] & fast_layout[8]) | (frame_key[59] & fast_select_10) | (frame_secret[131] & fast_layout[11]) | (frame_left[131] & fast_layout[12]) | (frame_left[139] & fast_select_5);
    assign fast_block[316]= (address[188] & fast_select_2) | (address[124] & fast_select_6) | (address[60] & fast_select_7) | (frame_secret[60] & fast_layout[6]) | (frame_prf[60] & fast_layout[7]) | (frame_public[60] & fast_layout[8]) | (frame_key[60] & fast_select_10) | (frame_secret[132] & fast_layout[11]) | (frame_left[132] & fast_layout[12]) | (frame_left[140] & fast_select_5);
    assign fast_block[317]= (address[189] & fast_select_2) | (address[125] & fast_select_6) | (address[61] & fast_select_7) | (frame_secret[61] & fast_layout[6]) | (frame_prf[61] & fast_layout[7]) | (frame_public[61] & fast_layout[8]) | (frame_key[61] & fast_select_10) | (frame_secret[133] & fast_layout[11]) | (frame_left[133] & fast_layout[12]) | (frame_left[141] & fast_select_5);
    assign fast_block[318]= (address[190] & fast_select_2) | (address[126] & fast_select_6) | (address[62] & fast_select_7) | (frame_secret[62] & fast_layout[6]) | (frame_prf[62] & fast_layout[7]) | (frame_public[62] & fast_layout[8]) | (frame_key[62] & fast_select_10) | (frame_secret[134] & fast_layout[11]) | (frame_left[134] & fast_layout[12]) | (frame_left[142] & fast_select_5);
    assign fast_block[319]= (address[191] & fast_select_2) | (address[127] & fast_select_6) | (address[63] & fast_select_7) | (frame_secret[63] & fast_layout[6]) | (frame_prf[63] & fast_layout[7]) | (frame_public[63] & fast_layout[8]) | (frame_key[63] & fast_select_10) | (frame_secret[135] & fast_layout[11]) | (frame_left[135] & fast_layout[12]) | (frame_left[143] & fast_select_5);
    assign fast_block[320]= (address[192] & fast_select_2) | (address[128] & fast_select_6) | (address[64] & fast_select_7) | (frame_secret[64] & fast_layout[6]) | (frame_prf[64] & fast_layout[7]) | (frame_public[64] & fast_layout[8]) | (frame_key[64] & fast_select_10) | (frame_secret[136] & fast_layout[11]) | (frame_left[136] & fast_layout[12]) | (frame_left[144] & fast_select_5);
    assign fast_block[321]= (address[193] & fast_select_2) | (address[129] & fast_select_6) | (address[65] & fast_select_7) | (frame_secret[65] & fast_layout[6]) | (frame_prf[65] & fast_layout[7]) | (frame_public[65] & fast_layout[8]) | (frame_key[65] & fast_select_10) | (frame_secret[137] & fast_layout[11]) | (frame_left[137] & fast_layout[12]) | (frame_left[145] & fast_select_5);
    assign fast_block[322]= (address[194] & fast_select_2) | (address[130] & fast_select_6) | (address[66] & fast_select_7) | (frame_secret[66] & fast_layout[6]) | (frame_prf[66] & fast_layout[7]) | (frame_public[66] & fast_layout[8]) | (frame_key[66] & fast_select_10) | (frame_secret[138] & fast_layout[11]) | (frame_left[138] & fast_layout[12]) | (frame_left[146] & fast_select_5);
    assign fast_block[323]= (address[195] & fast_select_2) | (address[131] & fast_select_6) | (address[67] & fast_select_7) | (frame_secret[67] & fast_layout[6]) | (frame_prf[67] & fast_layout[7]) | (frame_public[67] & fast_layout[8]) | (frame_key[67] & fast_select_10) | (frame_secret[139] & fast_layout[11]) | (frame_left[139] & fast_layout[12]) | (frame_left[147] & fast_select_5);
    assign fast_block[324]= (address[196] & fast_select_2) | (address[132] & fast_select_6) | (address[68] & fast_select_7) | (frame_secret[68] & fast_layout[6]) | (frame_prf[68] & fast_layout[7]) | (frame_public[68] & fast_layout[8]) | (frame_key[68] & fast_select_10) | (frame_secret[140] & fast_layout[11]) | (frame_left[140] & fast_layout[12]) | (frame_left[148] & fast_select_5);
    assign fast_block[325]= (address[197] & fast_select_2) | (address[133] & fast_select_6) | (address[69] & fast_select_7) | (frame_secret[69] & fast_layout[6]) | (frame_prf[69] & fast_layout[7]) | (frame_public[69] & fast_layout[8]) | (frame_key[69] & fast_select_10) | (frame_secret[141] & fast_layout[11]) | (frame_left[141] & fast_layout[12]) | (frame_left[149] & fast_select_5);
    assign fast_block[326]= (address[198] & fast_select_2) | (address[134] & fast_select_6) | (address[70] & fast_select_7) | (frame_secret[70] & fast_layout[6]) | (frame_prf[70] & fast_layout[7]) | (frame_public[70] & fast_layout[8]) | (frame_key[70] & fast_select_10) | (frame_secret[142] & fast_layout[11]) | (frame_left[142] & fast_layout[12]) | (frame_left[150] & fast_select_5);
    assign fast_block[327]= (address[199] & fast_select_2) | (address[135] & fast_select_6) | (address[71] & fast_select_7) | (frame_secret[71] & fast_layout[6]) | (frame_prf[71] & fast_layout[7]) | (frame_public[71] & fast_layout[8]) | (frame_key[71] & fast_select_10) | (frame_secret[143] & fast_layout[11]) | (frame_left[143] & fast_layout[12]) | (frame_left[151] & fast_select_5);
    assign fast_block[328]= (address[200] & fast_select_2) | (address[136] & fast_select_6) | (address[72] & fast_select_7) | (frame_secret[72] & fast_layout[6]) | (frame_prf[72] & fast_layout[7]) | (frame_public[72] & fast_layout[8]) | (frame_key[72] & fast_select_10) | (frame_secret[144] & fast_layout[11]) | (frame_left[144] & fast_layout[12]) | (frame_left[152] & fast_select_5);
    assign fast_block[329]= (address[201] & fast_select_2) | (address[137] & fast_select_6) | (address[73] & fast_select_7) | (frame_secret[73] & fast_layout[6]) | (frame_prf[73] & fast_layout[7]) | (frame_public[73] & fast_layout[8]) | (frame_key[73] & fast_select_10) | (frame_secret[145] & fast_layout[11]) | (frame_left[145] & fast_layout[12]) | (frame_left[153] & fast_select_5);
    assign fast_block[330]= (address[202] & fast_select_2) | (address[138] & fast_select_6) | (address[74] & fast_select_7) | (frame_secret[74] & fast_layout[6]) | (frame_prf[74] & fast_layout[7]) | (frame_public[74] & fast_layout[8]) | (frame_key[74] & fast_select_10) | (frame_secret[146] & fast_layout[11]) | (frame_left[146] & fast_layout[12]) | (frame_left[154] & fast_select_5);
    assign fast_block[331]= (address[203] & fast_select_2) | (address[139] & fast_select_6) | (address[75] & fast_select_7) | (frame_secret[75] & fast_layout[6]) | (frame_prf[75] & fast_layout[7]) | (frame_public[75] & fast_layout[8]) | (frame_key[75] & fast_select_10) | (frame_secret[147] & fast_layout[11]) | (frame_left[147] & fast_layout[12]) | (frame_left[155] & fast_select_5);
    assign fast_block[332]= (address[204] & fast_select_2) | (address[140] & fast_select_6) | (address[76] & fast_select_7) | (frame_secret[76] & fast_layout[6]) | (frame_prf[76] & fast_layout[7]) | (frame_public[76] & fast_layout[8]) | (frame_key[76] & fast_select_10) | (frame_secret[148] & fast_layout[11]) | (frame_left[148] & fast_layout[12]) | (frame_left[156] & fast_select_5);
    assign fast_block[333]= (address[205] & fast_select_2) | (address[141] & fast_select_6) | (address[77] & fast_select_7) | (frame_secret[77] & fast_layout[6]) | (frame_prf[77] & fast_layout[7]) | (frame_public[77] & fast_layout[8]) | (frame_key[77] & fast_select_10) | (frame_secret[149] & fast_layout[11]) | (frame_left[149] & fast_layout[12]) | (frame_left[157] & fast_select_5);
    assign fast_block[334]= (address[206] & fast_select_2) | (address[142] & fast_select_6) | (address[78] & fast_select_7) | (frame_secret[78] & fast_layout[6]) | (frame_prf[78] & fast_layout[7]) | (frame_public[78] & fast_layout[8]) | (frame_key[78] & fast_select_10) | (frame_secret[150] & fast_layout[11]) | (frame_left[150] & fast_layout[12]) | (frame_left[158] & fast_select_5);
    assign fast_block[335]= (address[207] & fast_select_2) | (address[143] & fast_select_6) | (address[79] & fast_select_7) | (frame_secret[79] & fast_layout[6]) | (frame_prf[79] & fast_layout[7]) | (frame_public[79] & fast_layout[8]) | (frame_key[79] & fast_select_10) | (frame_secret[151] & fast_layout[11]) | (frame_left[151] & fast_layout[12]) | (frame_left[159] & fast_select_5);
    assign fast_block[336]= (address[208] & fast_select_2) | (address[144] & fast_select_6) | (address[80] & fast_select_7) | (frame_secret[80] & fast_layout[6]) | (frame_prf[80] & fast_layout[7]) | (frame_public[80] & fast_layout[8]) | (frame_key[80] & fast_select_10) | (frame_secret[152] & fast_layout[11]) | (frame_left[152] & fast_layout[12]) | (frame_left[160] & fast_select_5);
    assign fast_block[337]= (address[209] & fast_select_2) | (address[145] & fast_select_6) | (address[81] & fast_select_7) | (frame_secret[81] & fast_layout[6]) | (frame_prf[81] & fast_layout[7]) | (frame_public[81] & fast_layout[8]) | (frame_key[81] & fast_select_10) | (frame_secret[153] & fast_layout[11]) | (frame_left[153] & fast_layout[12]) | (frame_left[161] & fast_select_5);
    assign fast_block[338]= (address[210] & fast_select_2) | (address[146] & fast_select_6) | (address[82] & fast_select_7) | (frame_secret[82] & fast_layout[6]) | (frame_prf[82] & fast_layout[7]) | (frame_public[82] & fast_layout[8]) | (frame_key[82] & fast_select_10) | (frame_secret[154] & fast_layout[11]) | (frame_left[154] & fast_layout[12]) | (frame_left[162] & fast_select_5);
    assign fast_block[339]= (address[211] & fast_select_2) | (address[147] & fast_select_6) | (address[83] & fast_select_7) | (frame_secret[83] & fast_layout[6]) | (frame_prf[83] & fast_layout[7]) | (frame_public[83] & fast_layout[8]) | (frame_key[83] & fast_select_10) | (frame_secret[155] & fast_layout[11]) | (frame_left[155] & fast_layout[12]) | (frame_left[163] & fast_select_5);
    assign fast_block[340]= (address[212] & fast_select_2) | (address[148] & fast_select_6) | (address[84] & fast_select_7) | (frame_secret[84] & fast_layout[6]) | (frame_prf[84] & fast_layout[7]) | (frame_public[84] & fast_layout[8]) | (frame_key[84] & fast_select_10) | (frame_secret[156] & fast_layout[11]) | (frame_left[156] & fast_layout[12]) | (frame_left[164] & fast_select_5);
    assign fast_block[341]= (address[213] & fast_select_2) | (address[149] & fast_select_6) | (address[85] & fast_select_7) | (frame_secret[85] & fast_layout[6]) | (frame_prf[85] & fast_layout[7]) | (frame_public[85] & fast_layout[8]) | (frame_key[85] & fast_select_10) | (frame_secret[157] & fast_layout[11]) | (frame_left[157] & fast_layout[12]) | (frame_left[165] & fast_select_5);
    assign fast_block[342]= (address[214] & fast_select_2) | (address[150] & fast_select_6) | (address[86] & fast_select_7) | (frame_secret[86] & fast_layout[6]) | (frame_prf[86] & fast_layout[7]) | (frame_public[86] & fast_layout[8]) | (frame_key[86] & fast_select_10) | (frame_secret[158] & fast_layout[11]) | (frame_left[158] & fast_layout[12]) | (frame_left[166] & fast_select_5);
    assign fast_block[343]= (address[215] & fast_select_2) | (address[151] & fast_select_6) | (address[87] & fast_select_7) | (frame_secret[87] & fast_layout[6]) | (frame_prf[87] & fast_layout[7]) | (frame_public[87] & fast_layout[8]) | (frame_key[87] & fast_select_10) | (frame_secret[159] & fast_layout[11]) | (frame_left[159] & fast_layout[12]) | (frame_left[167] & fast_select_5);
    assign fast_block[344]= (address[216] & fast_select_2) | (address[152] & fast_select_6) | (address[88] & fast_select_7) | (frame_secret[88] & fast_layout[6]) | (frame_prf[88] & fast_layout[7]) | (frame_public[88] & fast_layout[8]) | (frame_key[88] & fast_select_10) | (frame_secret[160] & fast_layout[11]) | (frame_left[160] & fast_layout[12]) | (frame_left[168] & fast_select_5);
    assign fast_block[345]= (address[217] & fast_select_2) | (address[153] & fast_select_6) | (address[89] & fast_select_7) | (frame_secret[89] & fast_layout[6]) | (frame_prf[89] & fast_layout[7]) | (frame_public[89] & fast_layout[8]) | (frame_key[89] & fast_select_10) | (frame_secret[161] & fast_layout[11]) | (frame_left[161] & fast_layout[12]) | (frame_left[169] & fast_select_5);
    assign fast_block[346]= (address[218] & fast_select_2) | (address[154] & fast_select_6) | (address[90] & fast_select_7) | (frame_secret[90] & fast_layout[6]) | (frame_prf[90] & fast_layout[7]) | (frame_public[90] & fast_layout[8]) | (frame_key[90] & fast_select_10) | (frame_secret[162] & fast_layout[11]) | (frame_left[162] & fast_layout[12]) | (frame_left[170] & fast_select_5);
    assign fast_block[347]= (address[219] & fast_select_2) | (address[155] & fast_select_6) | (address[91] & fast_select_7) | (frame_secret[91] & fast_layout[6]) | (frame_prf[91] & fast_layout[7]) | (frame_public[91] & fast_layout[8]) | (frame_key[91] & fast_select_10) | (frame_secret[163] & fast_layout[11]) | (frame_left[163] & fast_layout[12]) | (frame_left[171] & fast_select_5);
    assign fast_block[348]= (address[220] & fast_select_2) | (address[156] & fast_select_6) | (address[92] & fast_select_7) | (frame_secret[92] & fast_layout[6]) | (frame_prf[92] & fast_layout[7]) | (frame_public[92] & fast_layout[8]) | (frame_key[92] & fast_select_10) | (frame_secret[164] & fast_layout[11]) | (frame_left[164] & fast_layout[12]) | (frame_left[172] & fast_select_5);
    assign fast_block[349]= (address[221] & fast_select_2) | (address[157] & fast_select_6) | (address[93] & fast_select_7) | (frame_secret[93] & fast_layout[6]) | (frame_prf[93] & fast_layout[7]) | (frame_public[93] & fast_layout[8]) | (frame_key[93] & fast_select_10) | (frame_secret[165] & fast_layout[11]) | (frame_left[165] & fast_layout[12]) | (frame_left[173] & fast_select_5);
    assign fast_block[350]= (address[222] & fast_select_2) | (address[158] & fast_select_6) | (address[94] & fast_select_7) | (frame_secret[94] & fast_layout[6]) | (frame_prf[94] & fast_layout[7]) | (frame_public[94] & fast_layout[8]) | (frame_key[94] & fast_select_10) | (frame_secret[166] & fast_layout[11]) | (frame_left[166] & fast_layout[12]) | (frame_left[174] & fast_select_5);
    assign fast_block[351]= (address[223] & fast_select_2) | (address[159] & fast_select_6) | (address[95] & fast_select_7) | (frame_secret[95] & fast_layout[6]) | (frame_prf[95] & fast_layout[7]) | (frame_public[95] & fast_layout[8]) | (frame_key[95] & fast_select_10) | (frame_secret[167] & fast_layout[11]) | (frame_left[167] & fast_layout[12]) | (frame_left[175] & fast_select_5);
    assign fast_block[352]= (address[224] & fast_select_2) | (address[160] & fast_select_6) | (address[96] & fast_select_7) | (frame_secret[96] & fast_layout[6]) | (frame_prf[96] & fast_layout[7]) | (frame_public[96] & fast_layout[8]) | (frame_key[96] & fast_select_10) | (frame_secret[168] & fast_layout[11]) | (frame_left[168] & fast_layout[12]) | (frame_left[176] & fast_select_5);
    assign fast_block[353]= (address[225] & fast_select_2) | (address[161] & fast_select_6) | (address[97] & fast_select_7) | (frame_secret[97] & fast_layout[6]) | (frame_prf[97] & fast_layout[7]) | (frame_public[97] & fast_layout[8]) | (frame_key[97] & fast_select_10) | (frame_secret[169] & fast_layout[11]) | (frame_left[169] & fast_layout[12]) | (frame_left[177] & fast_select_5);
    assign fast_block[354]= (address[226] & fast_select_2) | (address[162] & fast_select_6) | (address[98] & fast_select_7) | (frame_secret[98] & fast_layout[6]) | (frame_prf[98] & fast_layout[7]) | (frame_public[98] & fast_layout[8]) | (frame_key[98] & fast_select_10) | (frame_secret[170] & fast_layout[11]) | (frame_left[170] & fast_layout[12]) | (frame_left[178] & fast_select_5);
    assign fast_block[355]= (address[227] & fast_select_2) | (address[163] & fast_select_6) | (address[99] & fast_select_7) | (frame_secret[99] & fast_layout[6]) | (frame_prf[99] & fast_layout[7]) | (frame_public[99] & fast_layout[8]) | (frame_key[99] & fast_select_10) | (frame_secret[171] & fast_layout[11]) | (frame_left[171] & fast_layout[12]) | (frame_left[179] & fast_select_5);
    assign fast_block[356]= (address[228] & fast_select_2) | (address[164] & fast_select_6) | (address[100] & fast_select_7) | (frame_secret[100] & fast_layout[6]) | (frame_prf[100] & fast_layout[7]) | (frame_public[100] & fast_layout[8]) | (frame_key[100] & fast_select_10) | (frame_secret[172] & fast_layout[11]) | (frame_left[172] & fast_layout[12]) | (frame_left[180] & fast_select_5);
    assign fast_block[357]= (address[229] & fast_select_2) | (address[165] & fast_select_6) | (address[101] & fast_select_7) | (frame_secret[101] & fast_layout[6]) | (frame_prf[101] & fast_layout[7]) | (frame_public[101] & fast_layout[8]) | (frame_key[101] & fast_select_10) | (frame_secret[173] & fast_layout[11]) | (frame_left[173] & fast_layout[12]) | (frame_left[181] & fast_select_5);
    assign fast_block[358]= (address[230] & fast_select_2) | (address[166] & fast_select_6) | (address[102] & fast_select_7) | (frame_secret[102] & fast_layout[6]) | (frame_prf[102] & fast_layout[7]) | (frame_public[102] & fast_layout[8]) | (frame_key[102] & fast_select_10) | (frame_secret[174] & fast_layout[11]) | (frame_left[174] & fast_layout[12]) | (frame_left[182] & fast_select_5);
    assign fast_block[359]= (address[231] & fast_select_2) | (address[167] & fast_select_6) | (address[103] & fast_select_7) | (frame_secret[103] & fast_layout[6]) | (frame_prf[103] & fast_layout[7]) | (frame_public[103] & fast_layout[8]) | (frame_key[103] & fast_select_10) | (frame_secret[175] & fast_layout[11]) | (frame_left[175] & fast_layout[12]) | (frame_left[183] & fast_select_5);
    assign fast_block[360]= (address[232] & fast_select_2) | (address[168] & fast_select_6) | (address[104] & fast_select_7) | (frame_secret[104] & fast_layout[6]) | (frame_prf[104] & fast_layout[7]) | (frame_public[104] & fast_layout[8]) | (frame_key[104] & fast_select_10) | (frame_secret[176] & fast_layout[11]) | (frame_left[176] & fast_layout[12]) | (frame_left[184] & fast_select_5);
    assign fast_block[361]= (address[233] & fast_select_2) | (address[169] & fast_select_6) | (address[105] & fast_select_7) | (frame_secret[105] & fast_layout[6]) | (frame_prf[105] & fast_layout[7]) | (frame_public[105] & fast_layout[8]) | (frame_key[105] & fast_select_10) | (frame_secret[177] & fast_layout[11]) | (frame_left[177] & fast_layout[12]) | (frame_left[185] & fast_select_5);
    assign fast_block[362]= (address[234] & fast_select_2) | (address[170] & fast_select_6) | (address[106] & fast_select_7) | (frame_secret[106] & fast_layout[6]) | (frame_prf[106] & fast_layout[7]) | (frame_public[106] & fast_layout[8]) | (frame_key[106] & fast_select_10) | (frame_secret[178] & fast_layout[11]) | (frame_left[178] & fast_layout[12]) | (frame_left[186] & fast_select_5);
    assign fast_block[363]= (address[235] & fast_select_2) | (address[171] & fast_select_6) | (address[107] & fast_select_7) | (frame_secret[107] & fast_layout[6]) | (frame_prf[107] & fast_layout[7]) | (frame_public[107] & fast_layout[8]) | (frame_key[107] & fast_select_10) | (frame_secret[179] & fast_layout[11]) | (frame_left[179] & fast_layout[12]) | (frame_left[187] & fast_select_5);
    assign fast_block[364]= (address[236] & fast_select_2) | (address[172] & fast_select_6) | (address[108] & fast_select_7) | (frame_secret[108] & fast_layout[6]) | (frame_prf[108] & fast_layout[7]) | (frame_public[108] & fast_layout[8]) | (frame_key[108] & fast_select_10) | (frame_secret[180] & fast_layout[11]) | (frame_left[180] & fast_layout[12]) | (frame_left[188] & fast_select_5);
    assign fast_block[365]= (address[237] & fast_select_2) | (address[173] & fast_select_6) | (address[109] & fast_select_7) | (frame_secret[109] & fast_layout[6]) | (frame_prf[109] & fast_layout[7]) | (frame_public[109] & fast_layout[8]) | (frame_key[109] & fast_select_10) | (frame_secret[181] & fast_layout[11]) | (frame_left[181] & fast_layout[12]) | (frame_left[189] & fast_select_5);
    assign fast_block[366]= (address[238] & fast_select_2) | (address[174] & fast_select_6) | (address[110] & fast_select_7) | (frame_secret[110] & fast_layout[6]) | (frame_prf[110] & fast_layout[7]) | (frame_public[110] & fast_layout[8]) | (frame_key[110] & fast_select_10) | (frame_secret[182] & fast_layout[11]) | (frame_left[182] & fast_layout[12]) | (frame_left[190] & fast_select_5);
    assign fast_block[367]= (address[239] & fast_select_2) | (address[175] & fast_select_6) | (address[111] & fast_select_7) | (frame_secret[111] & fast_layout[6]) | (frame_prf[111] & fast_layout[7]) | (frame_public[111] & fast_layout[8]) | (frame_key[111] & fast_select_10) | (frame_secret[183] & fast_layout[11]) | (frame_left[183] & fast_layout[12]) | (frame_left[191] & fast_select_5);
    assign fast_block[368]= (address[240] & fast_select_2) | (address[176] & fast_select_6) | (address[112] & fast_select_7) | (frame_secret[112] & fast_layout[6]) | (frame_prf[112] & fast_layout[7]) | (frame_public[112] & fast_layout[8]) | (frame_key[112] & fast_select_10) | (frame_secret[184] & fast_layout[11]) | (frame_left[184] & fast_layout[12]) | (frame_left[192] & fast_select_5);
    assign fast_block[369]= (address[241] & fast_select_2) | (address[177] & fast_select_6) | (address[113] & fast_select_7) | (frame_secret[113] & fast_layout[6]) | (frame_prf[113] & fast_layout[7]) | (frame_public[113] & fast_layout[8]) | (frame_key[113] & fast_select_10) | (frame_secret[185] & fast_layout[11]) | (frame_left[185] & fast_layout[12]) | (frame_left[193] & fast_select_5);
    assign fast_block[370]= (address[242] & fast_select_2) | (address[178] & fast_select_6) | (address[114] & fast_select_7) | (frame_secret[114] & fast_layout[6]) | (frame_prf[114] & fast_layout[7]) | (frame_public[114] & fast_layout[8]) | (frame_key[114] & fast_select_10) | (frame_secret[186] & fast_layout[11]) | (frame_left[186] & fast_layout[12]) | (frame_left[194] & fast_select_5);
    assign fast_block[371]= (address[243] & fast_select_2) | (address[179] & fast_select_6) | (address[115] & fast_select_7) | (frame_secret[115] & fast_layout[6]) | (frame_prf[115] & fast_layout[7]) | (frame_public[115] & fast_layout[8]) | (frame_key[115] & fast_select_10) | (frame_secret[187] & fast_layout[11]) | (frame_left[187] & fast_layout[12]) | (frame_left[195] & fast_select_5);
    assign fast_block[372]= (address[244] & fast_select_2) | (address[180] & fast_select_6) | (address[116] & fast_select_7) | (frame_secret[116] & fast_layout[6]) | (frame_prf[116] & fast_layout[7]) | (frame_public[116] & fast_layout[8]) | (frame_key[116] & fast_select_10) | (frame_secret[188] & fast_layout[11]) | (frame_left[188] & fast_layout[12]) | (frame_left[196] & fast_select_5);
    assign fast_block[373]= (address[245] & fast_select_2) | (address[181] & fast_select_6) | (address[117] & fast_select_7) | (frame_secret[117] & fast_layout[6]) | (frame_prf[117] & fast_layout[7]) | (frame_public[117] & fast_layout[8]) | (frame_key[117] & fast_select_10) | (frame_secret[189] & fast_layout[11]) | (frame_left[189] & fast_layout[12]) | (frame_left[197] & fast_select_5);
    assign fast_block[374]= (address[246] & fast_select_2) | (address[182] & fast_select_6) | (address[118] & fast_select_7) | (frame_secret[118] & fast_layout[6]) | (frame_prf[118] & fast_layout[7]) | (frame_public[118] & fast_layout[8]) | (frame_key[118] & fast_select_10) | (frame_secret[190] & fast_layout[11]) | (frame_left[190] & fast_layout[12]) | (frame_left[198] & fast_select_5);
    assign fast_block[375]= (address[247] & fast_select_2) | (address[183] & fast_select_6) | (address[119] & fast_select_7) | (frame_secret[119] & fast_layout[6]) | (frame_prf[119] & fast_layout[7]) | (frame_public[119] & fast_layout[8]) | (frame_key[119] & fast_select_10) | (frame_secret[191] & fast_layout[11]) | (frame_left[191] & fast_layout[12]) | (frame_left[199] & fast_select_5);
    assign fast_block[376]= (address[248] & fast_select_2) | (address[184] & fast_select_6) | (address[120] & fast_select_7) | (frame_secret[120] & fast_layout[6]) | (frame_prf[120] & fast_layout[7]) | (frame_public[120] & fast_layout[8]) | (frame_key[120] & fast_select_10) | (frame_secret[192] & fast_layout[11]) | (frame_left[192] & fast_layout[12]) | (frame_left[200] & fast_select_5);
    assign fast_block[377]= (address[249] & fast_select_2) | (address[185] & fast_select_6) | (address[121] & fast_select_7) | (frame_secret[121] & fast_layout[6]) | (frame_prf[121] & fast_layout[7]) | (frame_public[121] & fast_layout[8]) | (frame_key[121] & fast_select_10) | (frame_secret[193] & fast_layout[11]) | (frame_left[193] & fast_layout[12]) | (frame_left[201] & fast_select_5);
    assign fast_block[378]= (address[250] & fast_select_2) | (address[186] & fast_select_6) | (address[122] & fast_select_7) | (frame_secret[122] & fast_layout[6]) | (frame_prf[122] & fast_layout[7]) | (frame_public[122] & fast_layout[8]) | (frame_key[122] & fast_select_10) | (frame_secret[194] & fast_layout[11]) | (frame_left[194] & fast_layout[12]) | (frame_left[202] & fast_select_5);
    assign fast_block[379]= (address[251] & fast_select_2) | (address[187] & fast_select_6) | (address[123] & fast_select_7) | (frame_secret[123] & fast_layout[6]) | (frame_prf[123] & fast_layout[7]) | (frame_public[123] & fast_layout[8]) | (frame_key[123] & fast_select_10) | (frame_secret[195] & fast_layout[11]) | (frame_left[195] & fast_layout[12]) | (frame_left[203] & fast_select_5);
    assign fast_block[380]= (address[252] & fast_select_2) | (address[188] & fast_select_6) | (address[124] & fast_select_7) | (frame_secret[124] & fast_layout[6]) | (frame_prf[124] & fast_layout[7]) | (frame_public[124] & fast_layout[8]) | (frame_key[124] & fast_select_10) | (frame_secret[196] & fast_layout[11]) | (frame_left[196] & fast_layout[12]) | (frame_left[204] & fast_select_5);
    assign fast_block[381]= (address[253] & fast_select_2) | (address[189] & fast_select_6) | (address[125] & fast_select_7) | (frame_secret[125] & fast_layout[6]) | (frame_prf[125] & fast_layout[7]) | (frame_public[125] & fast_layout[8]) | (frame_key[125] & fast_select_10) | (frame_secret[197] & fast_layout[11]) | (frame_left[197] & fast_layout[12]) | (frame_left[205] & fast_select_5);
    assign fast_block[382]= (address[254] & fast_select_2) | (address[190] & fast_select_6) | (address[126] & fast_select_7) | (frame_secret[126] & fast_layout[6]) | (frame_prf[126] & fast_layout[7]) | (frame_public[126] & fast_layout[8]) | (frame_key[126] & fast_select_10) | (frame_secret[198] & fast_layout[11]) | (frame_left[198] & fast_layout[12]) | (frame_left[206] & fast_select_5);
    assign fast_block[383]= (address[255] & fast_select_2) | (address[191] & fast_select_6) | (address[127] & fast_select_7) | (frame_secret[127] & fast_layout[6]) | (frame_prf[127] & fast_layout[7]) | (frame_public[127] & fast_layout[8]) | (frame_key[127] & fast_select_10) | (frame_secret[199] & fast_layout[11]) | (frame_left[199] & fast_layout[12]) | (frame_left[207] & fast_select_5);
    assign fast_block[384]= (frame_payload[0] & fast_select_2) | (address[192] & fast_select_6) | (address[128] & fast_select_7) | (frame_secret[128] & fast_layout[6]) | (frame_prf[128] & fast_layout[7]) | (frame_public[128] & fast_layout[8]) | (frame_key[128] & fast_select_10) | (frame_secret[200] & fast_layout[11]) | (frame_left[200] & fast_layout[12]) | (frame_left[208] & fast_select_5);
    assign fast_block[385]= (frame_payload[1] & fast_select_2) | (address[193] & fast_select_6) | (address[129] & fast_select_7) | (frame_secret[129] & fast_layout[6]) | (frame_prf[129] & fast_layout[7]) | (frame_public[129] & fast_layout[8]) | (frame_key[129] & fast_select_10) | (frame_secret[201] & fast_layout[11]) | (frame_left[201] & fast_layout[12]) | (frame_left[209] & fast_select_5);
    assign fast_block[386]= (frame_payload[2] & fast_select_2) | (address[194] & fast_select_6) | (address[130] & fast_select_7) | (frame_secret[130] & fast_layout[6]) | (frame_prf[130] & fast_layout[7]) | (frame_public[130] & fast_layout[8]) | (frame_key[130] & fast_select_10) | (frame_secret[202] & fast_layout[11]) | (frame_left[202] & fast_layout[12]) | (frame_left[210] & fast_select_5);
    assign fast_block[387]= (frame_payload[3] & fast_select_2) | (address[195] & fast_select_6) | (address[131] & fast_select_7) | (frame_secret[131] & fast_layout[6]) | (frame_prf[131] & fast_layout[7]) | (frame_public[131] & fast_layout[8]) | (frame_key[131] & fast_select_10) | (frame_secret[203] & fast_layout[11]) | (frame_left[203] & fast_layout[12]) | (frame_left[211] & fast_select_5);
    assign fast_block[388]= (frame_payload[4] & fast_select_2) | (address[196] & fast_select_6) | (address[132] & fast_select_7) | (frame_secret[132] & fast_layout[6]) | (frame_prf[132] & fast_layout[7]) | (frame_public[132] & fast_layout[8]) | (frame_key[132] & fast_select_10) | (frame_secret[204] & fast_layout[11]) | (frame_left[204] & fast_layout[12]) | (frame_left[212] & fast_select_5);
    assign fast_block[389]= (frame_payload[5] & fast_select_2) | (address[197] & fast_select_6) | (address[133] & fast_select_7) | (frame_secret[133] & fast_layout[6]) | (frame_prf[133] & fast_layout[7]) | (frame_public[133] & fast_layout[8]) | (frame_key[133] & fast_select_10) | (frame_secret[205] & fast_layout[11]) | (frame_left[205] & fast_layout[12]) | (frame_left[213] & fast_select_5);
    assign fast_block[390]= (frame_payload[6] & fast_select_2) | (address[198] & fast_select_6) | (address[134] & fast_select_7) | (frame_secret[134] & fast_layout[6]) | (frame_prf[134] & fast_layout[7]) | (frame_public[134] & fast_layout[8]) | (frame_key[134] & fast_select_10) | (frame_secret[206] & fast_layout[11]) | (frame_left[206] & fast_layout[12]) | (frame_left[214] & fast_select_5);
    assign fast_block[391]= (frame_payload[7] & fast_select_2) | (address[199] & fast_select_6) | (address[135] & fast_select_7) | (frame_secret[135] & fast_layout[6]) | (frame_prf[135] & fast_layout[7]) | (frame_public[135] & fast_layout[8]) | (frame_key[135] & fast_select_10) | (frame_secret[207] & fast_layout[11]) | (frame_left[207] & fast_layout[12]) | (frame_left[215] & fast_select_5);
    assign fast_block[392]= (frame_payload[8] & fast_select_2) | (address[200] & fast_select_6) | (address[136] & fast_select_7) | (frame_secret[136] & fast_layout[6]) | (frame_prf[136] & fast_layout[7]) | (frame_public[136] & fast_layout[8]) | (frame_key[136] & fast_select_10) | (frame_secret[208] & fast_layout[11]) | (frame_left[208] & fast_layout[12]) | (frame_left[216] & fast_select_5);
    assign fast_block[393]= (frame_payload[9] & fast_select_2) | (address[201] & fast_select_6) | (address[137] & fast_select_7) | (frame_secret[137] & fast_layout[6]) | (frame_prf[137] & fast_layout[7]) | (frame_public[137] & fast_layout[8]) | (frame_key[137] & fast_select_10) | (frame_secret[209] & fast_layout[11]) | (frame_left[209] & fast_layout[12]) | (frame_left[217] & fast_select_5);
    assign fast_block[394]= (frame_payload[10] & fast_select_2) | (address[202] & fast_select_6) | (address[138] & fast_select_7) | (frame_secret[138] & fast_layout[6]) | (frame_prf[138] & fast_layout[7]) | (frame_public[138] & fast_layout[8]) | (frame_key[138] & fast_select_10) | (frame_secret[210] & fast_layout[11]) | (frame_left[210] & fast_layout[12]) | (frame_left[218] & fast_select_5);
    assign fast_block[395]= (frame_payload[11] & fast_select_2) | (address[203] & fast_select_6) | (address[139] & fast_select_7) | (frame_secret[139] & fast_layout[6]) | (frame_prf[139] & fast_layout[7]) | (frame_public[139] & fast_layout[8]) | (frame_key[139] & fast_select_10) | (frame_secret[211] & fast_layout[11]) | (frame_left[211] & fast_layout[12]) | (frame_left[219] & fast_select_5);
    assign fast_block[396]= (frame_payload[12] & fast_select_2) | (address[204] & fast_select_6) | (address[140] & fast_select_7) | (frame_secret[140] & fast_layout[6]) | (frame_prf[140] & fast_layout[7]) | (frame_public[140] & fast_layout[8]) | (frame_key[140] & fast_select_10) | (frame_secret[212] & fast_layout[11]) | (frame_left[212] & fast_layout[12]) | (frame_left[220] & fast_select_5);
    assign fast_block[397]= (frame_payload[13] & fast_select_2) | (address[205] & fast_select_6) | (address[141] & fast_select_7) | (frame_secret[141] & fast_layout[6]) | (frame_prf[141] & fast_layout[7]) | (frame_public[141] & fast_layout[8]) | (frame_key[141] & fast_select_10) | (frame_secret[213] & fast_layout[11]) | (frame_left[213] & fast_layout[12]) | (frame_left[221] & fast_select_5);
    assign fast_block[398]= (frame_payload[14] & fast_select_2) | (address[206] & fast_select_6) | (address[142] & fast_select_7) | (frame_secret[142] & fast_layout[6]) | (frame_prf[142] & fast_layout[7]) | (frame_public[142] & fast_layout[8]) | (frame_key[142] & fast_select_10) | (frame_secret[214] & fast_layout[11]) | (frame_left[214] & fast_layout[12]) | (frame_left[222] & fast_select_5);
    assign fast_block[399]= (frame_payload[15] & fast_select_2) | (address[207] & fast_select_6) | (address[143] & fast_select_7) | (frame_secret[143] & fast_layout[6]) | (frame_prf[143] & fast_layout[7]) | (frame_public[143] & fast_layout[8]) | (frame_key[143] & fast_select_10) | (frame_secret[215] & fast_layout[11]) | (frame_left[215] & fast_layout[12]) | (frame_left[223] & fast_select_5);
    assign fast_block[400]= (frame_payload[16] & fast_select_2) | (address[208] & fast_select_6) | (address[144] & fast_select_7) | (frame_secret[144] & fast_layout[6]) | (frame_prf[144] & fast_layout[7]) | (frame_public[144] & fast_layout[8]) | (frame_key[144] & fast_select_10) | (frame_secret[216] & fast_layout[11]) | (frame_left[216] & fast_layout[12]) | (frame_left[224] & fast_select_5);
    assign fast_block[401]= (frame_payload[17] & fast_select_2) | (address[209] & fast_select_6) | (address[145] & fast_select_7) | (frame_secret[145] & fast_layout[6]) | (frame_prf[145] & fast_layout[7]) | (frame_public[145] & fast_layout[8]) | (frame_key[145] & fast_select_10) | (frame_secret[217] & fast_layout[11]) | (frame_left[217] & fast_layout[12]) | (frame_left[225] & fast_select_5);
    assign fast_block[402]= (frame_payload[18] & fast_select_2) | (address[210] & fast_select_6) | (address[146] & fast_select_7) | (frame_secret[146] & fast_layout[6]) | (frame_prf[146] & fast_layout[7]) | (frame_public[146] & fast_layout[8]) | (frame_key[146] & fast_select_10) | (frame_secret[218] & fast_layout[11]) | (frame_left[218] & fast_layout[12]) | (frame_left[226] & fast_select_5);
    assign fast_block[403]= (frame_payload[19] & fast_select_2) | (address[211] & fast_select_6) | (address[147] & fast_select_7) | (frame_secret[147] & fast_layout[6]) | (frame_prf[147] & fast_layout[7]) | (frame_public[147] & fast_layout[8]) | (frame_key[147] & fast_select_10) | (frame_secret[219] & fast_layout[11]) | (frame_left[219] & fast_layout[12]) | (frame_left[227] & fast_select_5);
    assign fast_block[404]= (frame_payload[20] & fast_select_2) | (address[212] & fast_select_6) | (address[148] & fast_select_7) | (frame_secret[148] & fast_layout[6]) | (frame_prf[148] & fast_layout[7]) | (frame_public[148] & fast_layout[8]) | (frame_key[148] & fast_select_10) | (frame_secret[220] & fast_layout[11]) | (frame_left[220] & fast_layout[12]) | (frame_left[228] & fast_select_5);
    assign fast_block[405]= (frame_payload[21] & fast_select_2) | (address[213] & fast_select_6) | (address[149] & fast_select_7) | (frame_secret[149] & fast_layout[6]) | (frame_prf[149] & fast_layout[7]) | (frame_public[149] & fast_layout[8]) | (frame_key[149] & fast_select_10) | (frame_secret[221] & fast_layout[11]) | (frame_left[221] & fast_layout[12]) | (frame_left[229] & fast_select_5);
    assign fast_block[406]= (frame_payload[22] & fast_select_2) | (address[214] & fast_select_6) | (address[150] & fast_select_7) | (frame_secret[150] & fast_layout[6]) | (frame_prf[150] & fast_layout[7]) | (frame_public[150] & fast_layout[8]) | (frame_key[150] & fast_select_10) | (frame_secret[222] & fast_layout[11]) | (frame_left[222] & fast_layout[12]) | (frame_left[230] & fast_select_5);
    assign fast_block[407]= (frame_payload[23] & fast_select_2) | (address[215] & fast_select_6) | (address[151] & fast_select_7) | (frame_secret[151] & fast_layout[6]) | (frame_prf[151] & fast_layout[7]) | (frame_public[151] & fast_layout[8]) | (frame_key[151] & fast_select_10) | (frame_secret[223] & fast_layout[11]) | (frame_left[223] & fast_layout[12]) | (frame_left[231] & fast_select_5);
    assign fast_block[408]= (frame_payload[24] & fast_select_2) | (address[216] & fast_select_6) | (address[152] & fast_select_7) | (frame_secret[152] & fast_layout[6]) | (frame_prf[152] & fast_layout[7]) | (frame_public[152] & fast_layout[8]) | (frame_key[152] & fast_select_10) | (frame_secret[224] & fast_layout[11]) | (frame_left[224] & fast_layout[12]) | (frame_left[232] & fast_select_5);
    assign fast_block[409]= (frame_payload[25] & fast_select_2) | (address[217] & fast_select_6) | (address[153] & fast_select_7) | (frame_secret[153] & fast_layout[6]) | (frame_prf[153] & fast_layout[7]) | (frame_public[153] & fast_layout[8]) | (frame_key[153] & fast_select_10) | (frame_secret[225] & fast_layout[11]) | (frame_left[225] & fast_layout[12]) | (frame_left[233] & fast_select_5);
    assign fast_block[410]= (frame_payload[26] & fast_select_2) | (address[218] & fast_select_6) | (address[154] & fast_select_7) | (frame_secret[154] & fast_layout[6]) | (frame_prf[154] & fast_layout[7]) | (frame_public[154] & fast_layout[8]) | (frame_key[154] & fast_select_10) | (frame_secret[226] & fast_layout[11]) | (frame_left[226] & fast_layout[12]) | (frame_left[234] & fast_select_5);
    assign fast_block[411]= (frame_payload[27] & fast_select_2) | (address[219] & fast_select_6) | (address[155] & fast_select_7) | (frame_secret[155] & fast_layout[6]) | (frame_prf[155] & fast_layout[7]) | (frame_public[155] & fast_layout[8]) | (frame_key[155] & fast_select_10) | (frame_secret[227] & fast_layout[11]) | (frame_left[227] & fast_layout[12]) | (frame_left[235] & fast_select_5);
    assign fast_block[412]= (frame_payload[28] & fast_select_2) | (address[220] & fast_select_6) | (address[156] & fast_select_7) | (frame_secret[156] & fast_layout[6]) | (frame_prf[156] & fast_layout[7]) | (frame_public[156] & fast_layout[8]) | (frame_key[156] & fast_select_10) | (frame_secret[228] & fast_layout[11]) | (frame_left[228] & fast_layout[12]) | (frame_left[236] & fast_select_5);
    assign fast_block[413]= (frame_payload[29] & fast_select_2) | (address[221] & fast_select_6) | (address[157] & fast_select_7) | (frame_secret[157] & fast_layout[6]) | (frame_prf[157] & fast_layout[7]) | (frame_public[157] & fast_layout[8]) | (frame_key[157] & fast_select_10) | (frame_secret[229] & fast_layout[11]) | (frame_left[229] & fast_layout[12]) | (frame_left[237] & fast_select_5);
    assign fast_block[414]= (frame_payload[30] & fast_select_2) | (address[222] & fast_select_6) | (address[158] & fast_select_7) | (frame_secret[158] & fast_layout[6]) | (frame_prf[158] & fast_layout[7]) | (frame_public[158] & fast_layout[8]) | (frame_key[158] & fast_select_10) | (frame_secret[230] & fast_layout[11]) | (frame_left[230] & fast_layout[12]) | (frame_left[238] & fast_select_5);
    assign fast_block[415]= (frame_payload[31] & fast_select_2) | (address[223] & fast_select_6) | (address[159] & fast_select_7) | (frame_secret[159] & fast_layout[6]) | (frame_prf[159] & fast_layout[7]) | (frame_public[159] & fast_layout[8]) | (frame_key[159] & fast_select_10) | (frame_secret[231] & fast_layout[11]) | (frame_left[231] & fast_layout[12]) | (frame_left[239] & fast_select_5);
    assign fast_block[416]= (frame_payload[32] & fast_select_2) | (address[224] & fast_select_6) | (address[160] & fast_select_7) | (frame_secret[160] & fast_layout[6]) | (frame_prf[160] & fast_layout[7]) | (frame_public[160] & fast_layout[8]) | (frame_key[160] & fast_select_10) | (frame_secret[232] & fast_layout[11]) | (frame_left[232] & fast_layout[12]) | (frame_left[240] & fast_select_5);
    assign fast_block[417]= (frame_payload[33] & fast_select_2) | (address[225] & fast_select_6) | (address[161] & fast_select_7) | (frame_secret[161] & fast_layout[6]) | (frame_prf[161] & fast_layout[7]) | (frame_public[161] & fast_layout[8]) | (frame_key[161] & fast_select_10) | (frame_secret[233] & fast_layout[11]) | (frame_left[233] & fast_layout[12]) | (frame_left[241] & fast_select_5);
    assign fast_block[418]= (frame_payload[34] & fast_select_2) | (address[226] & fast_select_6) | (address[162] & fast_select_7) | (frame_secret[162] & fast_layout[6]) | (frame_prf[162] & fast_layout[7]) | (frame_public[162] & fast_layout[8]) | (frame_key[162] & fast_select_10) | (frame_secret[234] & fast_layout[11]) | (frame_left[234] & fast_layout[12]) | (frame_left[242] & fast_select_5);
    assign fast_block[419]= (frame_payload[35] & fast_select_2) | (address[227] & fast_select_6) | (address[163] & fast_select_7) | (frame_secret[163] & fast_layout[6]) | (frame_prf[163] & fast_layout[7]) | (frame_public[163] & fast_layout[8]) | (frame_key[163] & fast_select_10) | (frame_secret[235] & fast_layout[11]) | (frame_left[235] & fast_layout[12]) | (frame_left[243] & fast_select_5);
    assign fast_block[420]= (frame_payload[36] & fast_select_2) | (address[228] & fast_select_6) | (address[164] & fast_select_7) | (frame_secret[164] & fast_layout[6]) | (frame_prf[164] & fast_layout[7]) | (frame_public[164] & fast_layout[8]) | (frame_key[164] & fast_select_10) | (frame_secret[236] & fast_layout[11]) | (frame_left[236] & fast_layout[12]) | (frame_left[244] & fast_select_5);
    assign fast_block[421]= (frame_payload[37] & fast_select_2) | (address[229] & fast_select_6) | (address[165] & fast_select_7) | (frame_secret[165] & fast_layout[6]) | (frame_prf[165] & fast_layout[7]) | (frame_public[165] & fast_layout[8]) | (frame_key[165] & fast_select_10) | (frame_secret[237] & fast_layout[11]) | (frame_left[237] & fast_layout[12]) | (frame_left[245] & fast_select_5);
    assign fast_block[422]= (frame_payload[38] & fast_select_2) | (address[230] & fast_select_6) | (address[166] & fast_select_7) | (frame_secret[166] & fast_layout[6]) | (frame_prf[166] & fast_layout[7]) | (frame_public[166] & fast_layout[8]) | (frame_key[166] & fast_select_10) | (frame_secret[238] & fast_layout[11]) | (frame_left[238] & fast_layout[12]) | (frame_left[246] & fast_select_5);
    assign fast_block[423]= (frame_payload[39] & fast_select_2) | (address[231] & fast_select_6) | (address[167] & fast_select_7) | (frame_secret[167] & fast_layout[6]) | (frame_prf[167] & fast_layout[7]) | (frame_public[167] & fast_layout[8]) | (frame_key[167] & fast_select_10) | (frame_secret[239] & fast_layout[11]) | (frame_left[239] & fast_layout[12]) | (frame_left[247] & fast_select_5);
    assign fast_block[424]= (frame_payload[40] & fast_select_2) | (address[232] & fast_select_6) | (address[168] & fast_select_7) | (frame_secret[168] & fast_layout[6]) | (frame_prf[168] & fast_layout[7]) | (frame_public[168] & fast_layout[8]) | (frame_key[168] & fast_select_10) | (frame_secret[240] & fast_layout[11]) | (frame_left[240] & fast_layout[12]) | (frame_left[248] & fast_select_5);
    assign fast_block[425]= (frame_payload[41] & fast_select_2) | (address[233] & fast_select_6) | (address[169] & fast_select_7) | (frame_secret[169] & fast_layout[6]) | (frame_prf[169] & fast_layout[7]) | (frame_public[169] & fast_layout[8]) | (frame_key[169] & fast_select_10) | (frame_secret[241] & fast_layout[11]) | (frame_left[241] & fast_layout[12]) | (frame_left[249] & fast_select_5);
    assign fast_block[426]= (frame_payload[42] & fast_select_2) | (address[234] & fast_select_6) | (address[170] & fast_select_7) | (frame_secret[170] & fast_layout[6]) | (frame_prf[170] & fast_layout[7]) | (frame_public[170] & fast_layout[8]) | (frame_key[170] & fast_select_10) | (frame_secret[242] & fast_layout[11]) | (frame_left[242] & fast_layout[12]) | (frame_left[250] & fast_select_5);
    assign fast_block[427]= (frame_payload[43] & fast_select_2) | (address[235] & fast_select_6) | (address[171] & fast_select_7) | (frame_secret[171] & fast_layout[6]) | (frame_prf[171] & fast_layout[7]) | (frame_public[171] & fast_layout[8]) | (frame_key[171] & fast_select_10) | (frame_secret[243] & fast_layout[11]) | (frame_left[243] & fast_layout[12]) | (frame_left[251] & fast_select_5);
    assign fast_block[428]= (frame_payload[44] & fast_select_2) | (address[236] & fast_select_6) | (address[172] & fast_select_7) | (frame_secret[172] & fast_layout[6]) | (frame_prf[172] & fast_layout[7]) | (frame_public[172] & fast_layout[8]) | (frame_key[172] & fast_select_10) | (frame_secret[244] & fast_layout[11]) | (frame_left[244] & fast_layout[12]) | (frame_left[252] & fast_select_5);
    assign fast_block[429]= (frame_payload[45] & fast_select_2) | (address[237] & fast_select_6) | (address[173] & fast_select_7) | (frame_secret[173] & fast_layout[6]) | (frame_prf[173] & fast_layout[7]) | (frame_public[173] & fast_layout[8]) | (frame_key[173] & fast_select_10) | (frame_secret[245] & fast_layout[11]) | (frame_left[245] & fast_layout[12]) | (frame_left[253] & fast_select_5);
    assign fast_block[430]= (frame_payload[46] & fast_select_2) | (address[238] & fast_select_6) | (address[174] & fast_select_7) | (frame_secret[174] & fast_layout[6]) | (frame_prf[174] & fast_layout[7]) | (frame_public[174] & fast_layout[8]) | (frame_key[174] & fast_select_10) | (frame_secret[246] & fast_layout[11]) | (frame_left[246] & fast_layout[12]) | (frame_left[254] & fast_select_5);
    assign fast_block[431]= (frame_payload[47] & fast_select_2) | (address[239] & fast_select_6) | (address[175] & fast_select_7) | (frame_secret[175] & fast_layout[6]) | (frame_prf[175] & fast_layout[7]) | (frame_public[175] & fast_layout[8]) | (frame_key[175] & fast_select_10) | (frame_secret[247] & fast_layout[11]) | (frame_left[247] & fast_layout[12]) | (frame_left[255] & fast_select_5);
    assign fast_block[432]= (frame_payload[48] & fast_select_2) | (address[240] & fast_select_6) | (address[176] & fast_select_7) | (frame_secret[176] & fast_layout[6]) | (frame_prf[176] & fast_layout[7]) | (frame_public[176] & fast_layout[8]) | (frame_key[176] & fast_select_10) | (frame_secret[248] & fast_layout[11]) | (frame_left[248] & fast_layout[12]) | fast_layout[13] | (frame_right[0] & fast_layout[14]);
    assign fast_block[433]= (frame_payload[49] & fast_select_2) | (address[241] & fast_select_6) | (address[177] & fast_select_7) | (frame_secret[177] & fast_layout[6]) | (frame_prf[177] & fast_layout[7]) | (frame_public[177] & fast_layout[8]) | (frame_key[177] & fast_select_10) | (frame_secret[249] & fast_layout[11]) | (frame_left[249] & fast_layout[12]) | fast_layout[13] | (frame_right[1] & fast_layout[14]);
    assign fast_block[434]= (frame_payload[50] & fast_select_2) | (address[242] & fast_select_6) | (address[178] & fast_select_7) | (frame_secret[178] & fast_layout[6]) | (frame_prf[178] & fast_layout[7]) | (frame_public[178] & fast_layout[8]) | (frame_key[178] & fast_select_10) | (frame_secret[250] & fast_layout[11]) | (frame_left[250] & fast_layout[12]) | fast_layout[13] | (frame_right[2] & fast_layout[14]);
    assign fast_block[435]= (frame_payload[51] & fast_select_2) | (address[243] & fast_select_6) | (address[179] & fast_select_7) | (frame_secret[179] & fast_layout[6]) | (frame_prf[179] & fast_layout[7]) | (frame_public[179] & fast_layout[8]) | (frame_key[179] & fast_select_10) | (frame_secret[251] & fast_layout[11]) | (frame_left[251] & fast_layout[12]) | fast_layout[13] | (frame_right[3] & fast_layout[14]);
    assign fast_block[436]= (frame_payload[52] & fast_select_2) | (address[244] & fast_select_6) | (address[180] & fast_select_7) | (frame_secret[180] & fast_layout[6]) | (frame_prf[180] & fast_layout[7]) | (frame_public[180] & fast_layout[8]) | (frame_key[180] & fast_select_10) | (frame_secret[252] & fast_layout[11]) | (frame_left[252] & fast_layout[12]) | fast_layout[13] | (frame_right[4] & fast_layout[14]);
    assign fast_block[437]= (frame_payload[53] & fast_select_2) | (address[245] & fast_select_6) | (address[181] & fast_select_7) | (frame_secret[181] & fast_layout[6]) | (frame_prf[181] & fast_layout[7]) | (frame_public[181] & fast_layout[8]) | (frame_key[181] & fast_select_10) | (frame_secret[253] & fast_layout[11]) | (frame_left[253] & fast_layout[12]) | (frame_right[5] & fast_layout[14]);
    assign fast_block[438]= (frame_payload[54] & fast_select_2) | (address[246] & fast_select_6) | (address[182] & fast_select_7) | (frame_secret[182] & fast_layout[6]) | (frame_prf[182] & fast_layout[7]) | (frame_public[182] & fast_layout[8]) | (frame_key[182] & fast_select_10) | (frame_secret[254] & fast_layout[11]) | (frame_left[254] & fast_layout[12]) | (frame_right[6] & fast_layout[14]);
    assign fast_block[439]= (frame_payload[55] & fast_select_2) | (address[247] & fast_select_6) | (address[183] & fast_select_7) | (frame_secret[183] & fast_layout[6]) | (frame_prf[183] & fast_layout[7]) | (frame_public[183] & fast_layout[8]) | (frame_key[183] & fast_select_10) | (frame_secret[255] & fast_layout[11]) | (frame_left[255] & fast_layout[12]) | (frame_right[7] & fast_layout[14]);
    assign fast_block[440]= (frame_payload[56] & fast_select_2) | (address[248] & fast_select_6) | (address[184] & fast_select_7) | (frame_secret[184] & fast_layout[6]) | (frame_prf[184] & fast_layout[7]) | (frame_public[184] & fast_layout[8]) | (frame_key[184] & fast_select_10) | fast_select_4 | (frame_right[8] & fast_layout[14]);
    assign fast_block[441]= (frame_payload[57] & fast_select_2) | (address[249] & fast_select_6) | (address[185] & fast_select_7) | (frame_secret[185] & fast_layout[6]) | (frame_prf[185] & fast_layout[7]) | (frame_public[185] & fast_layout[8]) | (frame_key[185] & fast_select_10) | fast_select_4 | (frame_right[9] & fast_layout[14]);
    assign fast_block[442]= (frame_payload[58] & fast_select_2) | (address[250] & fast_select_6) | (address[186] & fast_select_7) | (frame_secret[186] & fast_layout[6]) | (frame_prf[186] & fast_layout[7]) | (frame_public[186] & fast_layout[8]) | (frame_key[186] & fast_select_10) | fast_select_4 | (frame_right[10] & fast_layout[14]);
    assign fast_block[443]= (frame_payload[59] & fast_select_2) | (address[251] & fast_select_6) | (address[187] & fast_select_7) | (frame_secret[187] & fast_layout[6]) | (frame_prf[187] & fast_layout[7]) | (frame_public[187] & fast_layout[8]) | (frame_key[187] & fast_select_10) | fast_select_4 | (frame_right[11] & fast_layout[14]);
    assign fast_block[444]= (frame_payload[60] & fast_select_2) | (address[252] & fast_select_6) | (address[188] & fast_select_7) | (frame_secret[188] & fast_layout[6]) | (frame_prf[188] & fast_layout[7]) | (frame_public[188] & fast_layout[8]) | (frame_key[188] & fast_select_10) | fast_select_4 | (frame_right[12] & fast_layout[14]);
    assign fast_block[445]= (frame_payload[61] & fast_select_2) | (address[253] & fast_select_6) | (address[189] & fast_select_7) | (frame_secret[189] & fast_layout[6]) | (frame_prf[189] & fast_layout[7]) | (frame_public[189] & fast_layout[8]) | (frame_key[189] & fast_select_10) | (frame_right[13] & fast_layout[14]);
    assign fast_block[446]= (frame_payload[62] & fast_select_2) | (address[254] & fast_select_6) | (address[190] & fast_select_7) | (frame_secret[190] & fast_layout[6]) | (frame_prf[190] & fast_layout[7]) | (frame_public[190] & fast_layout[8]) | (frame_key[190] & fast_select_10) | (frame_right[14] & fast_layout[14]);
    assign fast_block[447]= (frame_payload[63] & fast_select_2) | (address[255] & fast_select_6) | (address[191] & fast_select_7) | (frame_secret[191] & fast_layout[6]) | (frame_prf[191] & fast_layout[7]) | (frame_public[191] & fast_layout[8]) | (frame_key[191] & fast_select_10) | (frame_right[15] & fast_layout[14]);
    assign fast_block[448]= (frame_payload[64] & fast_select_2) | (frame_payload[0] & fast_select_6) | (address[192] & fast_select_7) | (frame_secret[192] & fast_layout[6]) | (frame_prf[192] & fast_layout[7]) | (frame_public[192] & fast_layout[8]) | (frame_key[192] & fast_select_10) | (frame_right[16] & fast_layout[14]);
    assign fast_block[449]= (frame_payload[65] & fast_select_2) | (frame_payload[1] & fast_select_6) | (address[193] & fast_select_7) | (frame_secret[193] & fast_layout[6]) | (frame_prf[193] & fast_layout[7]) | (frame_public[193] & fast_layout[8]) | (frame_key[193] & fast_select_10) | (frame_right[17] & fast_layout[14]);
    assign fast_block[450]= (frame_payload[66] & fast_select_2) | (frame_payload[2] & fast_select_6) | (address[194] & fast_select_7) | (frame_secret[194] & fast_layout[6]) | (frame_prf[194] & fast_layout[7]) | (frame_public[194] & fast_layout[8]) | (frame_key[194] & fast_select_10) | (frame_right[18] & fast_layout[14]);
    assign fast_block[451]= (frame_payload[67] & fast_select_2) | (frame_payload[3] & fast_select_6) | (address[195] & fast_select_7) | (frame_secret[195] & fast_layout[6]) | (frame_prf[195] & fast_layout[7]) | (frame_public[195] & fast_layout[8]) | (frame_key[195] & fast_select_10) | (frame_right[19] & fast_layout[14]);
    assign fast_block[452]= (frame_payload[68] & fast_select_2) | (frame_payload[4] & fast_select_6) | (address[196] & fast_select_7) | (frame_secret[196] & fast_layout[6]) | (frame_prf[196] & fast_layout[7]) | (frame_public[196] & fast_layout[8]) | (frame_key[196] & fast_select_10) | (frame_right[20] & fast_layout[14]);
    assign fast_block[453]= (frame_payload[69] & fast_select_2) | (frame_payload[5] & fast_select_6) | (address[197] & fast_select_7) | (frame_secret[197] & fast_layout[6]) | (frame_prf[197] & fast_layout[7]) | (frame_public[197] & fast_layout[8]) | (frame_key[197] & fast_select_10) | (frame_right[21] & fast_layout[14]);
    assign fast_block[454]= (frame_payload[70] & fast_select_2) | (frame_payload[6] & fast_select_6) | (address[198] & fast_select_7) | (frame_secret[198] & fast_layout[6]) | (frame_prf[198] & fast_layout[7]) | (frame_public[198] & fast_layout[8]) | (frame_key[198] & fast_select_10) | (frame_right[22] & fast_layout[14]);
    assign fast_block[455]= (frame_payload[71] & fast_select_2) | (frame_payload[7] & fast_select_6) | (address[199] & fast_select_7) | (frame_secret[199] & fast_layout[6]) | (frame_prf[199] & fast_layout[7]) | (frame_public[199] & fast_layout[8]) | (frame_key[199] & fast_select_10) | (frame_right[23] & fast_layout[14]);
    assign fast_block[456]= (frame_payload[72] & fast_select_2) | (frame_payload[8] & fast_select_6) | (address[200] & fast_select_7) | (frame_secret[200] & fast_layout[6]) | (frame_prf[200] & fast_layout[7]) | (frame_public[200] & fast_layout[8]) | (frame_key[200] & fast_select_10) | (frame_right[24] & fast_layout[14]);
    assign fast_block[457]= (frame_payload[73] & fast_select_2) | (frame_payload[9] & fast_select_6) | (address[201] & fast_select_7) | (frame_secret[201] & fast_layout[6]) | (frame_prf[201] & fast_layout[7]) | (frame_public[201] & fast_layout[8]) | (frame_key[201] & fast_select_10) | (frame_right[25] & fast_layout[14]);
    assign fast_block[458]= (frame_payload[74] & fast_select_2) | (frame_payload[10] & fast_select_6) | (address[202] & fast_select_7) | (frame_secret[202] & fast_layout[6]) | (frame_prf[202] & fast_layout[7]) | (frame_public[202] & fast_layout[8]) | (frame_key[202] & fast_select_10) | (frame_right[26] & fast_layout[14]);
    assign fast_block[459]= (frame_payload[75] & fast_select_2) | (frame_payload[11] & fast_select_6) | (address[203] & fast_select_7) | (frame_secret[203] & fast_layout[6]) | (frame_prf[203] & fast_layout[7]) | (frame_public[203] & fast_layout[8]) | (frame_key[203] & fast_select_10) | (frame_right[27] & fast_layout[14]);
    assign fast_block[460]= (frame_payload[76] & fast_select_2) | (frame_payload[12] & fast_select_6) | (address[204] & fast_select_7) | (frame_secret[204] & fast_layout[6]) | (frame_prf[204] & fast_layout[7]) | (frame_public[204] & fast_layout[8]) | (frame_key[204] & fast_select_10) | (frame_right[28] & fast_layout[14]);
    assign fast_block[461]= (frame_payload[77] & fast_select_2) | (frame_payload[13] & fast_select_6) | (address[205] & fast_select_7) | (frame_secret[205] & fast_layout[6]) | (frame_prf[205] & fast_layout[7]) | (frame_public[205] & fast_layout[8]) | (frame_key[205] & fast_select_10) | (frame_right[29] & fast_layout[14]);
    assign fast_block[462]= (frame_payload[78] & fast_select_2) | (frame_payload[14] & fast_select_6) | (address[206] & fast_select_7) | (frame_secret[206] & fast_layout[6]) | (frame_prf[206] & fast_layout[7]) | (frame_public[206] & fast_layout[8]) | (frame_key[206] & fast_select_10) | (frame_right[30] & fast_layout[14]);
    assign fast_block[463]= (frame_payload[79] & fast_select_2) | (frame_payload[15] & fast_select_6) | (address[207] & fast_select_7) | (frame_secret[207] & fast_layout[6]) | (frame_prf[207] & fast_layout[7]) | (frame_public[207] & fast_layout[8]) | (frame_key[207] & fast_select_10) | (frame_right[31] & fast_layout[14]);
    assign fast_block[464]= (frame_payload[80] & fast_select_2) | (frame_payload[16] & fast_select_6) | (address[208] & fast_select_7) | (frame_secret[208] & fast_layout[6]) | (frame_prf[208] & fast_layout[7]) | (frame_public[208] & fast_layout[8]) | (frame_key[208] & fast_select_10) | (frame_right[32] & fast_layout[14]);
    assign fast_block[465]= (frame_payload[81] & fast_select_2) | (frame_payload[17] & fast_select_6) | (address[209] & fast_select_7) | (frame_secret[209] & fast_layout[6]) | (frame_prf[209] & fast_layout[7]) | (frame_public[209] & fast_layout[8]) | (frame_key[209] & fast_select_10) | (frame_right[33] & fast_layout[14]);
    assign fast_block[466]= (frame_payload[82] & fast_select_2) | (frame_payload[18] & fast_select_6) | (address[210] & fast_select_7) | (frame_secret[210] & fast_layout[6]) | (frame_prf[210] & fast_layout[7]) | (frame_public[210] & fast_layout[8]) | (frame_key[210] & fast_select_10) | (frame_right[34] & fast_layout[14]);
    assign fast_block[467]= (frame_payload[83] & fast_select_2) | (frame_payload[19] & fast_select_6) | (address[211] & fast_select_7) | (frame_secret[211] & fast_layout[6]) | (frame_prf[211] & fast_layout[7]) | (frame_public[211] & fast_layout[8]) | (frame_key[211] & fast_select_10) | (frame_right[35] & fast_layout[14]);
    assign fast_block[468]= (frame_payload[84] & fast_select_2) | (frame_payload[20] & fast_select_6) | (address[212] & fast_select_7) | (frame_secret[212] & fast_layout[6]) | (frame_prf[212] & fast_layout[7]) | (frame_public[212] & fast_layout[8]) | (frame_key[212] & fast_select_10) | (frame_right[36] & fast_layout[14]);
    assign fast_block[469]= (frame_payload[85] & fast_select_2) | (frame_payload[21] & fast_select_6) | (address[213] & fast_select_7) | (frame_secret[213] & fast_layout[6]) | (frame_prf[213] & fast_layout[7]) | (frame_public[213] & fast_layout[8]) | (frame_key[213] & fast_select_10) | (frame_right[37] & fast_layout[14]);
    assign fast_block[470]= (frame_payload[86] & fast_select_2) | (frame_payload[22] & fast_select_6) | (address[214] & fast_select_7) | (frame_secret[214] & fast_layout[6]) | (frame_prf[214] & fast_layout[7]) | (frame_public[214] & fast_layout[8]) | (frame_key[214] & fast_select_10) | (frame_right[38] & fast_layout[14]);
    assign fast_block[471]= (frame_payload[87] & fast_select_2) | (frame_payload[23] & fast_select_6) | (address[215] & fast_select_7) | (frame_secret[215] & fast_layout[6]) | (frame_prf[215] & fast_layout[7]) | (frame_public[215] & fast_layout[8]) | (frame_key[215] & fast_select_10) | (frame_right[39] & fast_layout[14]);
    assign fast_block[472]= (frame_payload[88] & fast_select_2) | (frame_payload[24] & fast_select_6) | (address[216] & fast_select_7) | (frame_secret[216] & fast_layout[6]) | (frame_prf[216] & fast_layout[7]) | (frame_public[216] & fast_layout[8]) | (frame_key[216] & fast_select_10) | (frame_right[40] & fast_layout[14]);
    assign fast_block[473]= (frame_payload[89] & fast_select_2) | (frame_payload[25] & fast_select_6) | (address[217] & fast_select_7) | (frame_secret[217] & fast_layout[6]) | (frame_prf[217] & fast_layout[7]) | (frame_public[217] & fast_layout[8]) | (frame_key[217] & fast_select_10) | (frame_right[41] & fast_layout[14]);
    assign fast_block[474]= (frame_payload[90] & fast_select_2) | (frame_payload[26] & fast_select_6) | (address[218] & fast_select_7) | (frame_secret[218] & fast_layout[6]) | (frame_prf[218] & fast_layout[7]) | (frame_public[218] & fast_layout[8]) | (frame_key[218] & fast_select_10) | (frame_right[42] & fast_layout[14]);
    assign fast_block[475]= (frame_payload[91] & fast_select_2) | (frame_payload[27] & fast_select_6) | (address[219] & fast_select_7) | (frame_secret[219] & fast_layout[6]) | (frame_prf[219] & fast_layout[7]) | (frame_public[219] & fast_layout[8]) | (frame_key[219] & fast_select_10) | (frame_right[43] & fast_layout[14]);
    assign fast_block[476]= (frame_payload[92] & fast_select_2) | (frame_payload[28] & fast_select_6) | (address[220] & fast_select_7) | (frame_secret[220] & fast_layout[6]) | (frame_prf[220] & fast_layout[7]) | (frame_public[220] & fast_layout[8]) | (frame_key[220] & fast_select_10) | (frame_right[44] & fast_layout[14]);
    assign fast_block[477]= (frame_payload[93] & fast_select_2) | (frame_payload[29] & fast_select_6) | (address[221] & fast_select_7) | (frame_secret[221] & fast_layout[6]) | (frame_prf[221] & fast_layout[7]) | (frame_public[221] & fast_layout[8]) | (frame_key[221] & fast_select_10) | (frame_right[45] & fast_layout[14]);
    assign fast_block[478]= (frame_payload[94] & fast_select_2) | (frame_payload[30] & fast_select_6) | (address[222] & fast_select_7) | (frame_secret[222] & fast_layout[6]) | (frame_prf[222] & fast_layout[7]) | (frame_public[222] & fast_layout[8]) | (frame_key[222] & fast_select_10) | (frame_right[46] & fast_layout[14]);
    assign fast_block[479]= (frame_payload[95] & fast_select_2) | (frame_payload[31] & fast_select_6) | (address[223] & fast_select_7) | (frame_secret[223] & fast_layout[6]) | (frame_prf[223] & fast_layout[7]) | (frame_public[223] & fast_layout[8]) | (frame_key[223] & fast_select_10) | (frame_right[47] & fast_layout[14]);
    assign fast_block[480]= (frame_payload[96] & fast_select_2) | (frame_payload[32] & fast_select_6) | (address[224] & fast_select_7) | (frame_secret[224] & fast_layout[6]) | (frame_prf[224] & fast_layout[7]) | (frame_public[224] & fast_layout[8]) | (frame_key[224] & fast_select_10) | (frame_right[48] & fast_layout[14]);
    assign fast_block[481]= (frame_payload[97] & fast_select_2) | (frame_payload[33] & fast_select_6) | (address[225] & fast_select_7) | (frame_secret[225] & fast_layout[6]) | (frame_prf[225] & fast_layout[7]) | (frame_public[225] & fast_layout[8]) | (frame_key[225] & fast_select_10) | (frame_right[49] & fast_layout[14]);
    assign fast_block[482]= (frame_payload[98] & fast_select_2) | (frame_payload[34] & fast_select_6) | (address[226] & fast_select_7) | (frame_secret[226] & fast_layout[6]) | (frame_prf[226] & fast_layout[7]) | (frame_public[226] & fast_layout[8]) | (frame_key[226] & fast_select_10) | (frame_right[50] & fast_layout[14]);
    assign fast_block[483]= (frame_payload[99] & fast_select_2) | (frame_payload[35] & fast_select_6) | (address[227] & fast_select_7) | (frame_secret[227] & fast_layout[6]) | (frame_prf[227] & fast_layout[7]) | (frame_public[227] & fast_layout[8]) | (frame_key[227] & fast_select_10) | (frame_right[51] & fast_layout[14]);
    assign fast_block[484]= (frame_payload[100] & fast_select_2) | (frame_payload[36] & fast_select_6) | (address[228] & fast_select_7) | (frame_secret[228] & fast_layout[6]) | (frame_prf[228] & fast_layout[7]) | (frame_public[228] & fast_layout[8]) | (frame_key[228] & fast_select_10) | (frame_right[52] & fast_layout[14]);
    assign fast_block[485]= (frame_payload[101] & fast_select_2) | (frame_payload[37] & fast_select_6) | (address[229] & fast_select_7) | (frame_secret[229] & fast_layout[6]) | (frame_prf[229] & fast_layout[7]) | (frame_public[229] & fast_layout[8]) | (frame_key[229] & fast_select_10) | (frame_right[53] & fast_layout[14]);
    assign fast_block[486]= (frame_payload[102] & fast_select_2) | (frame_payload[38] & fast_select_6) | (address[230] & fast_select_7) | (frame_secret[230] & fast_layout[6]) | (frame_prf[230] & fast_layout[7]) | (frame_public[230] & fast_layout[8]) | (frame_key[230] & fast_select_10) | (frame_right[54] & fast_layout[14]);
    assign fast_block[487]= (frame_payload[103] & fast_select_2) | (frame_payload[39] & fast_select_6) | (address[231] & fast_select_7) | (frame_secret[231] & fast_layout[6]) | (frame_prf[231] & fast_layout[7]) | (frame_public[231] & fast_layout[8]) | (frame_key[231] & fast_select_10) | (frame_right[55] & fast_layout[14]);
    assign fast_block[488]= (frame_payload[104] & fast_select_2) | (frame_payload[40] & fast_select_6) | (address[232] & fast_select_7) | (frame_secret[232] & fast_layout[6]) | (frame_prf[232] & fast_layout[7]) | (frame_public[232] & fast_layout[8]) | (frame_key[232] & fast_select_10) | (frame_right[56] & fast_layout[14]);
    assign fast_block[489]= (frame_payload[105] & fast_select_2) | (frame_payload[41] & fast_select_6) | (address[233] & fast_select_7) | (frame_secret[233] & fast_layout[6]) | (frame_prf[233] & fast_layout[7]) | (frame_public[233] & fast_layout[8]) | (frame_key[233] & fast_select_10) | (frame_right[57] & fast_layout[14]);
    assign fast_block[490]= (frame_payload[106] & fast_select_2) | (frame_payload[42] & fast_select_6) | (address[234] & fast_select_7) | (frame_secret[234] & fast_layout[6]) | (frame_prf[234] & fast_layout[7]) | (frame_public[234] & fast_layout[8]) | (frame_key[234] & fast_select_10) | (frame_right[58] & fast_layout[14]);
    assign fast_block[491]= (frame_payload[107] & fast_select_2) | (frame_payload[43] & fast_select_6) | (address[235] & fast_select_7) | (frame_secret[235] & fast_layout[6]) | (frame_prf[235] & fast_layout[7]) | (frame_public[235] & fast_layout[8]) | (frame_key[235] & fast_select_10) | (frame_right[59] & fast_layout[14]);
    assign fast_block[492]= (frame_payload[108] & fast_select_2) | (frame_payload[44] & fast_select_6) | (address[236] & fast_select_7) | (frame_secret[236] & fast_layout[6]) | (frame_prf[236] & fast_layout[7]) | (frame_public[236] & fast_layout[8]) | (frame_key[236] & fast_select_10) | (frame_right[60] & fast_layout[14]);
    assign fast_block[493]= (frame_payload[109] & fast_select_2) | (frame_payload[45] & fast_select_6) | (address[237] & fast_select_7) | (frame_secret[237] & fast_layout[6]) | (frame_prf[237] & fast_layout[7]) | (frame_public[237] & fast_layout[8]) | (frame_key[237] & fast_select_10) | (frame_right[61] & fast_layout[14]);
    assign fast_block[494]= (frame_payload[110] & fast_select_2) | (frame_payload[46] & fast_select_6) | (address[238] & fast_select_7) | (frame_secret[238] & fast_layout[6]) | (frame_prf[238] & fast_layout[7]) | (frame_public[238] & fast_layout[8]) | (frame_key[238] & fast_select_10) | (frame_right[62] & fast_layout[14]);
    assign fast_block[495]= (frame_payload[111] & fast_select_2) | (frame_payload[47] & fast_select_6) | (address[239] & fast_select_7) | (frame_secret[239] & fast_layout[6]) | (frame_prf[239] & fast_layout[7]) | (frame_public[239] & fast_layout[8]) | (frame_key[239] & fast_select_10) | (frame_right[63] & fast_layout[14]);
    assign fast_block[496]= (frame_payload[112] & fast_select_2) | (frame_payload[48] & fast_select_6) | (address[240] & fast_select_7) | (frame_secret[240] & fast_layout[6]) | (frame_prf[240] & fast_layout[7]) | (frame_public[240] & fast_layout[8]) | (frame_key[240] & fast_select_10) | (frame_right[64] & fast_layout[14]);
    assign fast_block[497]= (frame_payload[113] & fast_select_2) | (frame_payload[49] & fast_select_6) | (address[241] & fast_select_7) | (frame_secret[241] & fast_layout[6]) | (frame_prf[241] & fast_layout[7]) | (frame_public[241] & fast_layout[8]) | (frame_key[241] & fast_select_10) | (frame_right[65] & fast_layout[14]);
    assign fast_block[498]= (frame_payload[114] & fast_select_2) | (frame_payload[50] & fast_select_6) | (address[242] & fast_select_7) | (frame_secret[242] & fast_layout[6]) | (frame_prf[242] & fast_layout[7]) | (frame_public[242] & fast_layout[8]) | (frame_key[242] & fast_select_10) | (frame_right[66] & fast_layout[14]);
    assign fast_block[499]= (frame_payload[115] & fast_select_2) | (frame_payload[51] & fast_select_6) | (address[243] & fast_select_7) | (frame_secret[243] & fast_layout[6]) | (frame_prf[243] & fast_layout[7]) | (frame_public[243] & fast_layout[8]) | (frame_key[243] & fast_select_10) | (frame_right[67] & fast_layout[14]);
    assign fast_block[500]= (frame_payload[116] & fast_select_2) | (frame_payload[52] & fast_select_6) | (address[244] & fast_select_7) | (frame_secret[244] & fast_layout[6]) | (frame_prf[244] & fast_layout[7]) | (frame_public[244] & fast_layout[8]) | (frame_key[244] & fast_select_10) | (frame_right[68] & fast_layout[14]);
    assign fast_block[501]= (frame_payload[117] & fast_select_2) | (frame_payload[53] & fast_select_6) | (address[245] & fast_select_7) | (frame_secret[245] & fast_layout[6]) | (frame_prf[245] & fast_layout[7]) | (frame_public[245] & fast_layout[8]) | (frame_key[245] & fast_select_10) | (frame_right[69] & fast_layout[14]);
    assign fast_block[502]= (frame_payload[118] & fast_select_2) | (frame_payload[54] & fast_select_6) | (address[246] & fast_select_7) | (frame_secret[246] & fast_layout[6]) | (frame_prf[246] & fast_layout[7]) | (frame_public[246] & fast_layout[8]) | (frame_key[246] & fast_select_10) | (frame_right[70] & fast_layout[14]);
    assign fast_block[503]= (frame_payload[119] & fast_select_2) | (frame_payload[55] & fast_select_6) | (address[247] & fast_select_7) | (frame_secret[247] & fast_layout[6]) | (frame_prf[247] & fast_layout[7]) | (frame_public[247] & fast_layout[8]) | (frame_key[247] & fast_select_10) | (frame_right[71] & fast_layout[14]);
    assign fast_block[504]= (frame_payload[120] & fast_select_2) | (frame_payload[56] & fast_select_6) | (address[248] & fast_select_7) | (frame_secret[248] & fast_layout[6]) | (frame_prf[248] & fast_layout[7]) | (frame_public[248] & fast_layout[8]) | (frame_key[248] & fast_select_10) | (frame_right[72] & fast_layout[14]);
    assign fast_block[505]= (frame_payload[121] & fast_select_2) | (frame_payload[57] & fast_select_6) | (address[249] & fast_select_7) | (frame_secret[249] & fast_layout[6]) | (frame_prf[249] & fast_layout[7]) | (frame_public[249] & fast_layout[8]) | (frame_key[249] & fast_select_10) | (frame_right[73] & fast_layout[14]);
    assign fast_block[506]= (frame_payload[122] & fast_select_2) | (frame_payload[58] & fast_select_6) | (address[250] & fast_select_7) | (frame_secret[250] & fast_layout[6]) | (frame_prf[250] & fast_layout[7]) | (frame_public[250] & fast_layout[8]) | (frame_key[250] & fast_select_10) | (frame_right[74] & fast_layout[14]);
    assign fast_block[507]= (frame_payload[123] & fast_select_2) | (frame_payload[59] & fast_select_6) | (address[251] & fast_select_7) | (frame_secret[251] & fast_layout[6]) | (frame_prf[251] & fast_layout[7]) | (frame_public[251] & fast_layout[8]) | (frame_key[251] & fast_select_10) | (frame_right[75] & fast_layout[14]);
    assign fast_block[508]= (frame_payload[124] & fast_select_2) | (frame_payload[60] & fast_select_6) | (address[252] & fast_select_7) | (frame_secret[252] & fast_layout[6]) | (frame_prf[252] & fast_layout[7]) | (frame_public[252] & fast_layout[8]) | (frame_key[252] & fast_select_10) | (frame_right[76] & fast_layout[14]);
    assign fast_block[509]= (frame_payload[125] & fast_select_2) | (frame_payload[61] & fast_select_6) | (address[253] & fast_select_7) | (frame_secret[253] & fast_layout[6]) | (frame_prf[253] & fast_layout[7]) | (frame_public[253] & fast_layout[8]) | (frame_key[253] & fast_select_10) | (frame_right[77] & fast_layout[14]);
    assign fast_block[510]= (frame_payload[126] & fast_select_2) | (frame_payload[62] & fast_select_6) | (address[254] & fast_select_7) | (frame_secret[254] & fast_layout[6]) | (frame_prf[254] & fast_layout[7]) | (frame_public[254] & fast_layout[8]) | (frame_key[254] & fast_select_10) | (frame_right[78] & fast_layout[14]);
    assign fast_block[511]= (frame_payload[127] & fast_select_2) | (frame_payload[63] & fast_select_6) | (address[255] & fast_select_7) | (frame_secret[255] & fast_layout[6]) | (frame_prf[255] & fast_layout[7]) | (frame_public[255] & fast_layout[8]) | (frame_key[255] & fast_select_10) | (frame_right[79] & fast_layout[14]);
    assign fast_block[512]= fast_layout[0] | (frame_right[0] & fast_layout[1]) | (frame_payload[64] & fast_select_6) | (frame_payload[0] & fast_select_7) | (frame_public[0] & fast_layout[6]) | (index_bytes[0] & fast_layout[7]) | (xmss_address[0] & fast_layout[8]) | (frame_left[0] & fast_select_10) | (frame_right[80] & fast_layout[14]);
    assign fast_block[513]= fast_layout[0] | (frame_right[1] & fast_layout[1]) | (frame_payload[65] & fast_select_6) | (frame_payload[1] & fast_select_7) | (frame_public[1] & fast_layout[6]) | (index_bytes[1] & fast_layout[7]) | (xmss_address[1] & fast_layout[8]) | (frame_left[1] & fast_select_10) | (frame_right[81] & fast_layout[14]);
    assign fast_block[514]= fast_layout[0] | (frame_right[2] & fast_layout[1]) | (frame_payload[66] & fast_select_6) | (frame_payload[2] & fast_select_7) | (frame_public[2] & fast_layout[6]) | (index_bytes[2] & fast_layout[7]) | (xmss_address[2] & fast_layout[8]) | (frame_left[2] & fast_select_10) | (frame_right[82] & fast_layout[14]);
    assign fast_block[515]= fast_layout[0] | (frame_right[3] & fast_layout[1]) | (frame_payload[67] & fast_select_6) | (frame_payload[3] & fast_select_7) | (frame_public[3] & fast_layout[6]) | (index_bytes[3] & fast_layout[7]) | (xmss_address[3] & fast_layout[8]) | (frame_left[3] & fast_select_10) | (frame_right[83] & fast_layout[14]);
    assign fast_block[516]= fast_layout[0] | (frame_right[4] & fast_layout[1]) | (frame_payload[68] & fast_select_6) | (frame_payload[4] & fast_select_7) | (frame_public[4] & fast_layout[6]) | (index_bytes[4] & fast_layout[7]) | (xmss_address[4] & fast_layout[8]) | (frame_left[4] & fast_select_10) | (frame_right[84] & fast_layout[14]);
    assign fast_block[517]= (frame_right[5] & fast_layout[1]) | (frame_payload[69] & fast_select_6) | (frame_payload[5] & fast_select_7) | (frame_public[5] & fast_layout[6]) | (index_bytes[5] & fast_layout[7]) | (xmss_address[5] & fast_layout[8]) | (frame_left[5] & fast_select_10) | (frame_right[85] & fast_layout[14]);
    assign fast_block[518]= (frame_right[6] & fast_layout[1]) | (frame_payload[70] & fast_select_6) | (frame_payload[6] & fast_select_7) | (frame_public[6] & fast_layout[6]) | (index_bytes[6] & fast_layout[7]) | (xmss_address[6] & fast_layout[8]) | (frame_left[6] & fast_select_10) | (frame_right[86] & fast_layout[14]);
    assign fast_block[519]= (frame_right[7] & fast_layout[1]) | (frame_payload[71] & fast_select_6) | (frame_payload[7] & fast_select_7) | (frame_public[7] & fast_layout[6]) | (index_bytes[7] & fast_layout[7]) | (xmss_address[7] & fast_layout[8]) | (frame_left[7] & fast_select_10) | (frame_right[87] & fast_layout[14]);
    assign fast_block[520]= (frame_right[8] & fast_layout[1]) | (frame_payload[72] & fast_select_6) | (frame_payload[8] & fast_select_7) | (frame_public[8] & fast_layout[6]) | (index_bytes[8] & fast_layout[7]) | (xmss_address[8] & fast_layout[8]) | (frame_left[8] & fast_select_10) | (frame_right[88] & fast_layout[14]);
    assign fast_block[521]= (frame_right[9] & fast_layout[1]) | (frame_payload[73] & fast_select_6) | (frame_payload[9] & fast_select_7) | (frame_public[9] & fast_layout[6]) | (index_bytes[9] & fast_layout[7]) | (xmss_address[9] & fast_layout[8]) | (frame_left[9] & fast_select_10) | (frame_right[89] & fast_layout[14]);
    assign fast_block[522]= (frame_right[10] & fast_layout[1]) | (frame_payload[74] & fast_select_6) | (frame_payload[10] & fast_select_7) | (frame_public[10] & fast_layout[6]) | (index_bytes[10] & fast_layout[7]) | (xmss_address[10] & fast_layout[8]) | (frame_left[10] & fast_select_10) | (frame_right[90] & fast_layout[14]);
    assign fast_block[523]= (frame_right[11] & fast_layout[1]) | (frame_payload[75] & fast_select_6) | (frame_payload[11] & fast_select_7) | (frame_public[11] & fast_layout[6]) | (index_bytes[11] & fast_layout[7]) | (xmss_address[11] & fast_layout[8]) | (frame_left[11] & fast_select_10) | (frame_right[91] & fast_layout[14]);
    assign fast_block[524]= (frame_right[12] & fast_layout[1]) | (frame_payload[76] & fast_select_6) | (frame_payload[12] & fast_select_7) | (frame_public[12] & fast_layout[6]) | (index_bytes[12] & fast_layout[7]) | (xmss_address[12] & fast_layout[8]) | (frame_left[12] & fast_select_10) | (frame_right[92] & fast_layout[14]);
    assign fast_block[525]= (frame_right[13] & fast_layout[1]) | (frame_payload[77] & fast_select_6) | (frame_payload[13] & fast_select_7) | (frame_public[13] & fast_layout[6]) | (index_bytes[13] & fast_layout[7]) | (xmss_address[13] & fast_layout[8]) | (frame_left[13] & fast_select_10) | (frame_right[93] & fast_layout[14]);
    assign fast_block[526]= (frame_right[14] & fast_layout[1]) | (frame_payload[78] & fast_select_6) | (frame_payload[14] & fast_select_7) | (frame_public[14] & fast_layout[6]) | (index_bytes[14] & fast_layout[7]) | (xmss_address[14] & fast_layout[8]) | (frame_left[14] & fast_select_10) | (frame_right[94] & fast_layout[14]);
    assign fast_block[527]= (frame_right[15] & fast_layout[1]) | (frame_payload[79] & fast_select_6) | (frame_payload[15] & fast_select_7) | (frame_public[15] & fast_layout[6]) | (index_bytes[15] & fast_layout[7]) | (xmss_address[15] & fast_layout[8]) | (frame_left[15] & fast_select_10) | (frame_right[95] & fast_layout[14]);
    assign fast_block[528]= (frame_right[16] & fast_layout[1]) | (frame_payload[80] & fast_select_6) | (frame_payload[16] & fast_select_7) | (frame_public[16] & fast_layout[6]) | (index_bytes[16] & fast_layout[7]) | (xmss_address[16] & fast_layout[8]) | (frame_left[16] & fast_select_10) | (frame_right[96] & fast_layout[14]);
    assign fast_block[529]= (frame_right[17] & fast_layout[1]) | (frame_payload[81] & fast_select_6) | (frame_payload[17] & fast_select_7) | (frame_public[17] & fast_layout[6]) | (index_bytes[17] & fast_layout[7]) | (xmss_address[17] & fast_layout[8]) | (frame_left[17] & fast_select_10) | (frame_right[97] & fast_layout[14]);
    assign fast_block[530]= (frame_right[18] & fast_layout[1]) | (frame_payload[82] & fast_select_6) | (frame_payload[18] & fast_select_7) | (frame_public[18] & fast_layout[6]) | (index_bytes[18] & fast_layout[7]) | (xmss_address[18] & fast_layout[8]) | (frame_left[18] & fast_select_10) | (frame_right[98] & fast_layout[14]);
    assign fast_block[531]= (frame_right[19] & fast_layout[1]) | (frame_payload[83] & fast_select_6) | (frame_payload[19] & fast_select_7) | (frame_public[19] & fast_layout[6]) | (index_bytes[19] & fast_layout[7]) | (xmss_address[19] & fast_layout[8]) | (frame_left[19] & fast_select_10) | (frame_right[99] & fast_layout[14]);
    assign fast_block[532]= (frame_right[20] & fast_layout[1]) | (frame_payload[84] & fast_select_6) | (frame_payload[20] & fast_select_7) | (frame_public[20] & fast_layout[6]) | (index_bytes[20] & fast_layout[7]) | (xmss_address[20] & fast_layout[8]) | (frame_left[20] & fast_select_10) | (frame_right[100] & fast_layout[14]);
    assign fast_block[533]= (frame_right[21] & fast_layout[1]) | (frame_payload[85] & fast_select_6) | (frame_payload[21] & fast_select_7) | (frame_public[21] & fast_layout[6]) | (index_bytes[21] & fast_layout[7]) | (xmss_address[21] & fast_layout[8]) | (frame_left[21] & fast_select_10) | (frame_right[101] & fast_layout[14]);
    assign fast_block[534]= (frame_right[22] & fast_layout[1]) | (frame_payload[86] & fast_select_6) | (frame_payload[22] & fast_select_7) | (frame_public[22] & fast_layout[6]) | (index_bytes[22] & fast_layout[7]) | (xmss_address[22] & fast_layout[8]) | (frame_left[22] & fast_select_10) | (frame_right[102] & fast_layout[14]);
    assign fast_block[535]= (frame_right[23] & fast_layout[1]) | (frame_payload[87] & fast_select_6) | (frame_payload[23] & fast_select_7) | (frame_public[23] & fast_layout[6]) | (index_bytes[23] & fast_layout[7]) | (xmss_address[23] & fast_layout[8]) | (frame_left[23] & fast_select_10) | (frame_right[103] & fast_layout[14]);
    assign fast_block[536]= (frame_right[24] & fast_layout[1]) | (frame_payload[88] & fast_select_6) | (frame_payload[24] & fast_select_7) | (frame_public[24] & fast_layout[6]) | (index_bytes[24] & fast_layout[7]) | (xmss_address[24] & fast_layout[8]) | (frame_left[24] & fast_select_10) | (frame_right[104] & fast_layout[14]);
    assign fast_block[537]= (frame_right[25] & fast_layout[1]) | (frame_payload[89] & fast_select_6) | (frame_payload[25] & fast_select_7) | (frame_public[25] & fast_layout[6]) | (index_bytes[25] & fast_layout[7]) | (xmss_address[25] & fast_layout[8]) | (frame_left[25] & fast_select_10) | (frame_right[105] & fast_layout[14]);
    assign fast_block[538]= (frame_right[26] & fast_layout[1]) | (frame_payload[90] & fast_select_6) | (frame_payload[26] & fast_select_7) | (frame_public[26] & fast_layout[6]) | (index_bytes[26] & fast_layout[7]) | (xmss_address[26] & fast_layout[8]) | (frame_left[26] & fast_select_10) | (frame_right[106] & fast_layout[14]);
    assign fast_block[539]= (frame_right[27] & fast_layout[1]) | (frame_payload[91] & fast_select_6) | (frame_payload[27] & fast_select_7) | (frame_public[27] & fast_layout[6]) | (index_bytes[27] & fast_layout[7]) | (xmss_address[27] & fast_layout[8]) | (frame_left[27] & fast_select_10) | (frame_right[107] & fast_layout[14]);
    assign fast_block[540]= (frame_right[28] & fast_layout[1]) | (frame_payload[92] & fast_select_6) | (frame_payload[28] & fast_select_7) | (frame_public[28] & fast_layout[6]) | (index_bytes[28] & fast_layout[7]) | (xmss_address[28] & fast_layout[8]) | (frame_left[28] & fast_select_10) | (frame_right[108] & fast_layout[14]);
    assign fast_block[541]= (frame_right[29] & fast_layout[1]) | (frame_payload[93] & fast_select_6) | (frame_payload[29] & fast_select_7) | (frame_public[29] & fast_layout[6]) | (index_bytes[29] & fast_layout[7]) | (xmss_address[29] & fast_layout[8]) | (frame_left[29] & fast_select_10) | (frame_right[109] & fast_layout[14]);
    assign fast_block[542]= (frame_right[30] & fast_layout[1]) | (frame_payload[94] & fast_select_6) | (frame_payload[30] & fast_select_7) | (frame_public[30] & fast_layout[6]) | (index_bytes[30] & fast_layout[7]) | (xmss_address[30] & fast_layout[8]) | (frame_left[30] & fast_select_10) | (frame_right[110] & fast_layout[14]);
    assign fast_block[543]= (frame_right[31] & fast_layout[1]) | (frame_payload[95] & fast_select_6) | (frame_payload[31] & fast_select_7) | (frame_public[31] & fast_layout[6]) | (index_bytes[31] & fast_layout[7]) | (xmss_address[31] & fast_layout[8]) | (frame_left[31] & fast_select_10) | (frame_right[111] & fast_layout[14]);
    assign fast_block[544]= (frame_right[32] & fast_layout[1]) | (frame_payload[96] & fast_select_6) | (frame_payload[32] & fast_select_7) | (frame_public[32] & fast_layout[6]) | (index_bytes[32] & fast_layout[7]) | (xmss_address[32] & fast_layout[8]) | (frame_left[32] & fast_select_10) | (frame_right[112] & fast_layout[14]);
    assign fast_block[545]= (frame_right[33] & fast_layout[1]) | (frame_payload[97] & fast_select_6) | (frame_payload[33] & fast_select_7) | (frame_public[33] & fast_layout[6]) | (index_bytes[33] & fast_layout[7]) | (xmss_address[33] & fast_layout[8]) | (frame_left[33] & fast_select_10) | (frame_right[113] & fast_layout[14]);
    assign fast_block[546]= (frame_right[34] & fast_layout[1]) | (frame_payload[98] & fast_select_6) | (frame_payload[34] & fast_select_7) | (frame_public[34] & fast_layout[6]) | (index_bytes[34] & fast_layout[7]) | (xmss_address[34] & fast_layout[8]) | (frame_left[34] & fast_select_10) | (frame_right[114] & fast_layout[14]);
    assign fast_block[547]= (frame_right[35] & fast_layout[1]) | (frame_payload[99] & fast_select_6) | (frame_payload[35] & fast_select_7) | (frame_public[35] & fast_layout[6]) | (index_bytes[35] & fast_layout[7]) | (xmss_address[35] & fast_layout[8]) | (frame_left[35] & fast_select_10) | (frame_right[115] & fast_layout[14]);
    assign fast_block[548]= (frame_right[36] & fast_layout[1]) | (frame_payload[100] & fast_select_6) | (frame_payload[36] & fast_select_7) | (frame_public[36] & fast_layout[6]) | (index_bytes[36] & fast_layout[7]) | (xmss_address[36] & fast_layout[8]) | (frame_left[36] & fast_select_10) | (frame_right[116] & fast_layout[14]);
    assign fast_block[549]= (frame_right[37] & fast_layout[1]) | (frame_payload[101] & fast_select_6) | (frame_payload[37] & fast_select_7) | (frame_public[37] & fast_layout[6]) | (index_bytes[37] & fast_layout[7]) | (xmss_address[37] & fast_layout[8]) | (frame_left[37] & fast_select_10) | (frame_right[117] & fast_layout[14]);
    assign fast_block[550]= (frame_right[38] & fast_layout[1]) | (frame_payload[102] & fast_select_6) | (frame_payload[38] & fast_select_7) | (frame_public[38] & fast_layout[6]) | (index_bytes[38] & fast_layout[7]) | (xmss_address[38] & fast_layout[8]) | (frame_left[38] & fast_select_10) | (frame_right[118] & fast_layout[14]);
    assign fast_block[551]= (frame_right[39] & fast_layout[1]) | (frame_payload[103] & fast_select_6) | (frame_payload[39] & fast_select_7) | (frame_public[39] & fast_layout[6]) | (index_bytes[39] & fast_layout[7]) | (xmss_address[39] & fast_layout[8]) | (frame_left[39] & fast_select_10) | (frame_right[119] & fast_layout[14]);
    assign fast_block[552]= (frame_right[40] & fast_layout[1]) | (frame_payload[104] & fast_select_6) | (frame_payload[40] & fast_select_7) | (frame_public[40] & fast_layout[6]) | (index_bytes[40] & fast_layout[7]) | (xmss_address[40] & fast_layout[8]) | (frame_left[40] & fast_select_10) | (frame_right[120] & fast_layout[14]);
    assign fast_block[553]= (frame_right[41] & fast_layout[1]) | (frame_payload[105] & fast_select_6) | (frame_payload[41] & fast_select_7) | (frame_public[41] & fast_layout[6]) | (index_bytes[41] & fast_layout[7]) | (xmss_address[41] & fast_layout[8]) | (frame_left[41] & fast_select_10) | (frame_right[121] & fast_layout[14]);
    assign fast_block[554]= (frame_right[42] & fast_layout[1]) | (frame_payload[106] & fast_select_6) | (frame_payload[42] & fast_select_7) | (frame_public[42] & fast_layout[6]) | (index_bytes[42] & fast_layout[7]) | (xmss_address[42] & fast_layout[8]) | (frame_left[42] & fast_select_10) | (frame_right[122] & fast_layout[14]);
    assign fast_block[555]= (frame_right[43] & fast_layout[1]) | (frame_payload[107] & fast_select_6) | (frame_payload[43] & fast_select_7) | (frame_public[43] & fast_layout[6]) | (index_bytes[43] & fast_layout[7]) | (xmss_address[43] & fast_layout[8]) | (frame_left[43] & fast_select_10) | (frame_right[123] & fast_layout[14]);
    assign fast_block[556]= (frame_right[44] & fast_layout[1]) | (frame_payload[108] & fast_select_6) | (frame_payload[44] & fast_select_7) | (frame_public[44] & fast_layout[6]) | (index_bytes[44] & fast_layout[7]) | (xmss_address[44] & fast_layout[8]) | (frame_left[44] & fast_select_10) | (frame_right[124] & fast_layout[14]);
    assign fast_block[557]= (frame_right[45] & fast_layout[1]) | (frame_payload[109] & fast_select_6) | (frame_payload[45] & fast_select_7) | (frame_public[45] & fast_layout[6]) | (index_bytes[45] & fast_layout[7]) | (xmss_address[45] & fast_layout[8]) | (frame_left[45] & fast_select_10) | (frame_right[125] & fast_layout[14]);
    assign fast_block[558]= (frame_right[46] & fast_layout[1]) | (frame_payload[110] & fast_select_6) | (frame_payload[46] & fast_select_7) | (frame_public[46] & fast_layout[6]) | (index_bytes[46] & fast_layout[7]) | (xmss_address[46] & fast_layout[8]) | (frame_left[46] & fast_select_10) | (frame_right[126] & fast_layout[14]);
    assign fast_block[559]= (frame_right[47] & fast_layout[1]) | (frame_payload[111] & fast_select_6) | (frame_payload[47] & fast_select_7) | (frame_public[47] & fast_layout[6]) | (index_bytes[47] & fast_layout[7]) | (xmss_address[47] & fast_layout[8]) | (frame_left[47] & fast_select_10) | (frame_right[127] & fast_layout[14]);
    assign fast_block[560]= (frame_right[48] & fast_layout[1]) | (frame_payload[112] & fast_select_6) | (frame_payload[48] & fast_select_7) | (frame_public[48] & fast_layout[6]) | (index_bytes[48] & fast_layout[7]) | (xmss_address[48] & fast_layout[8]) | (frame_left[48] & fast_select_10) | (frame_right[128] & fast_layout[14]);
    assign fast_block[561]= (frame_right[49] & fast_layout[1]) | (frame_payload[113] & fast_select_6) | (frame_payload[49] & fast_select_7) | (frame_public[49] & fast_layout[6]) | (index_bytes[49] & fast_layout[7]) | (xmss_address[49] & fast_layout[8]) | (frame_left[49] & fast_select_10) | (frame_right[129] & fast_layout[14]);
    assign fast_block[562]= (frame_right[50] & fast_layout[1]) | (frame_payload[114] & fast_select_6) | (frame_payload[50] & fast_select_7) | (frame_public[50] & fast_layout[6]) | (index_bytes[50] & fast_layout[7]) | (xmss_address[50] & fast_layout[8]) | (frame_left[50] & fast_select_10) | (frame_right[130] & fast_layout[14]);
    assign fast_block[563]= (frame_right[51] & fast_layout[1]) | (frame_payload[115] & fast_select_6) | (frame_payload[51] & fast_select_7) | (frame_public[51] & fast_layout[6]) | (index_bytes[51] & fast_layout[7]) | (xmss_address[51] & fast_layout[8]) | (frame_left[51] & fast_select_10) | (frame_right[131] & fast_layout[14]);
    assign fast_block[564]= (frame_right[52] & fast_layout[1]) | (frame_payload[116] & fast_select_6) | (frame_payload[52] & fast_select_7) | (frame_public[52] & fast_layout[6]) | (index_bytes[52] & fast_layout[7]) | (xmss_address[52] & fast_layout[8]) | (frame_left[52] & fast_select_10) | (frame_right[132] & fast_layout[14]);
    assign fast_block[565]= (frame_right[53] & fast_layout[1]) | (frame_payload[117] & fast_select_6) | (frame_payload[53] & fast_select_7) | (frame_public[53] & fast_layout[6]) | (index_bytes[53] & fast_layout[7]) | (xmss_address[53] & fast_layout[8]) | (frame_left[53] & fast_select_10) | (frame_right[133] & fast_layout[14]);
    assign fast_block[566]= (frame_right[54] & fast_layout[1]) | (frame_payload[118] & fast_select_6) | (frame_payload[54] & fast_select_7) | (frame_public[54] & fast_layout[6]) | (index_bytes[54] & fast_layout[7]) | (xmss_address[54] & fast_layout[8]) | (frame_left[54] & fast_select_10) | (frame_right[134] & fast_layout[14]);
    assign fast_block[567]= (frame_right[55] & fast_layout[1]) | (frame_payload[119] & fast_select_6) | (frame_payload[55] & fast_select_7) | (frame_public[55] & fast_layout[6]) | (index_bytes[55] & fast_layout[7]) | (xmss_address[55] & fast_layout[8]) | (frame_left[55] & fast_select_10) | (frame_right[135] & fast_layout[14]);
    assign fast_block[568]= (frame_right[56] & fast_layout[1]) | (frame_payload[120] & fast_select_6) | (frame_payload[56] & fast_select_7) | (frame_public[56] & fast_layout[6]) | (index_bytes[56] & fast_layout[7]) | (xmss_address[56] & fast_layout[8]) | (frame_left[56] & fast_select_10) | (frame_right[136] & fast_layout[14]);
    assign fast_block[569]= (frame_right[57] & fast_layout[1]) | (frame_payload[121] & fast_select_6) | (frame_payload[57] & fast_select_7) | (frame_public[57] & fast_layout[6]) | (index_bytes[57] & fast_layout[7]) | (xmss_address[57] & fast_layout[8]) | (frame_left[57] & fast_select_10) | (frame_right[137] & fast_layout[14]);
    assign fast_block[570]= (frame_right[58] & fast_layout[1]) | (frame_payload[122] & fast_select_6) | (frame_payload[58] & fast_select_7) | (frame_public[58] & fast_layout[6]) | (index_bytes[58] & fast_layout[7]) | (xmss_address[58] & fast_layout[8]) | (frame_left[58] & fast_select_10) | (frame_right[138] & fast_layout[14]);
    assign fast_block[571]= (frame_right[59] & fast_layout[1]) | (frame_payload[123] & fast_select_6) | (frame_payload[59] & fast_select_7) | (frame_public[59] & fast_layout[6]) | (index_bytes[59] & fast_layout[7]) | (xmss_address[59] & fast_layout[8]) | (frame_left[59] & fast_select_10) | (frame_right[139] & fast_layout[14]);
    assign fast_block[572]= (frame_right[60] & fast_layout[1]) | (frame_payload[124] & fast_select_6) | (frame_payload[60] & fast_select_7) | (frame_public[60] & fast_layout[6]) | (index_bytes[60] & fast_layout[7]) | (xmss_address[60] & fast_layout[8]) | (frame_left[60] & fast_select_10) | (frame_right[140] & fast_layout[14]);
    assign fast_block[573]= (frame_right[61] & fast_layout[1]) | (frame_payload[125] & fast_select_6) | (frame_payload[61] & fast_select_7) | (frame_public[61] & fast_layout[6]) | (index_bytes[61] & fast_layout[7]) | (xmss_address[61] & fast_layout[8]) | (frame_left[61] & fast_select_10) | (frame_right[141] & fast_layout[14]);
    assign fast_block[574]= (frame_right[62] & fast_layout[1]) | (frame_payload[126] & fast_select_6) | (frame_payload[62] & fast_select_7) | (frame_public[62] & fast_layout[6]) | (index_bytes[62] & fast_layout[7]) | (xmss_address[62] & fast_layout[8]) | (frame_left[62] & fast_select_10) | (frame_right[142] & fast_layout[14]);
    assign fast_block[575]= (frame_right[63] & fast_layout[1]) | (frame_payload[127] & fast_select_6) | (frame_payload[63] & fast_select_7) | (frame_public[63] & fast_layout[6]) | (index_bytes[63] & fast_layout[7]) | (xmss_address[63] & fast_layout[8]) | (frame_left[63] & fast_select_10) | (frame_right[143] & fast_layout[14]);
    assign fast_block[576]= (frame_right[64] & fast_layout[1]) | (frame_payload[128] & fast_select_6) | (frame_payload[64] & fast_select_7) | (frame_public[64] & fast_layout[6]) | (index_bytes[64] & fast_layout[7]) | (xmss_address[64] & fast_layout[8]) | (frame_left[64] & fast_select_10) | (frame_right[144] & fast_layout[14]);
    assign fast_block[577]= (frame_right[65] & fast_layout[1]) | (frame_payload[129] & fast_select_6) | (frame_payload[65] & fast_select_7) | (frame_public[65] & fast_layout[6]) | (index_bytes[65] & fast_layout[7]) | (xmss_address[65] & fast_layout[8]) | (frame_left[65] & fast_select_10) | (frame_right[145] & fast_layout[14]);
    assign fast_block[578]= (frame_right[66] & fast_layout[1]) | (frame_payload[130] & fast_select_6) | (frame_payload[66] & fast_select_7) | (frame_public[66] & fast_layout[6]) | (index_bytes[66] & fast_layout[7]) | (xmss_address[66] & fast_layout[8]) | (frame_left[66] & fast_select_10) | (frame_right[146] & fast_layout[14]);
    assign fast_block[579]= (frame_right[67] & fast_layout[1]) | (frame_payload[131] & fast_select_6) | (frame_payload[67] & fast_select_7) | (frame_public[67] & fast_layout[6]) | (index_bytes[67] & fast_layout[7]) | (xmss_address[67] & fast_layout[8]) | (frame_left[67] & fast_select_10) | (frame_right[147] & fast_layout[14]);
    assign fast_block[580]= (frame_right[68] & fast_layout[1]) | (frame_payload[132] & fast_select_6) | (frame_payload[68] & fast_select_7) | (frame_public[68] & fast_layout[6]) | (index_bytes[68] & fast_layout[7]) | (xmss_address[68] & fast_layout[8]) | (frame_left[68] & fast_select_10) | (frame_right[148] & fast_layout[14]);
    assign fast_block[581]= (frame_right[69] & fast_layout[1]) | (frame_payload[133] & fast_select_6) | (frame_payload[69] & fast_select_7) | (frame_public[69] & fast_layout[6]) | (index_bytes[69] & fast_layout[7]) | (xmss_address[69] & fast_layout[8]) | (frame_left[69] & fast_select_10) | (frame_right[149] & fast_layout[14]);
    assign fast_block[582]= (frame_right[70] & fast_layout[1]) | (frame_payload[134] & fast_select_6) | (frame_payload[70] & fast_select_7) | (frame_public[70] & fast_layout[6]) | (index_bytes[70] & fast_layout[7]) | (xmss_address[70] & fast_layout[8]) | (frame_left[70] & fast_select_10) | (frame_right[150] & fast_layout[14]);
    assign fast_block[583]= (frame_right[71] & fast_layout[1]) | (frame_payload[135] & fast_select_6) | (frame_payload[71] & fast_select_7) | (frame_public[71] & fast_layout[6]) | (index_bytes[71] & fast_layout[7]) | (xmss_address[71] & fast_layout[8]) | (frame_left[71] & fast_select_10) | (frame_right[151] & fast_layout[14]);
    assign fast_block[584]= (frame_right[72] & fast_layout[1]) | (frame_payload[136] & fast_select_6) | (frame_payload[72] & fast_select_7) | (frame_public[72] & fast_layout[6]) | (index_bytes[72] & fast_layout[7]) | (xmss_address[72] & fast_layout[8]) | (frame_left[72] & fast_select_10) | (frame_right[152] & fast_layout[14]);
    assign fast_block[585]= (frame_right[73] & fast_layout[1]) | (frame_payload[137] & fast_select_6) | (frame_payload[73] & fast_select_7) | (frame_public[73] & fast_layout[6]) | (index_bytes[73] & fast_layout[7]) | (xmss_address[73] & fast_layout[8]) | (frame_left[73] & fast_select_10) | (frame_right[153] & fast_layout[14]);
    assign fast_block[586]= (frame_right[74] & fast_layout[1]) | (frame_payload[138] & fast_select_6) | (frame_payload[74] & fast_select_7) | (frame_public[74] & fast_layout[6]) | (index_bytes[74] & fast_layout[7]) | (xmss_address[74] & fast_layout[8]) | (frame_left[74] & fast_select_10) | (frame_right[154] & fast_layout[14]);
    assign fast_block[587]= (frame_right[75] & fast_layout[1]) | (frame_payload[139] & fast_select_6) | (frame_payload[75] & fast_select_7) | (frame_public[75] & fast_layout[6]) | (index_bytes[75] & fast_layout[7]) | (xmss_address[75] & fast_layout[8]) | (frame_left[75] & fast_select_10) | (frame_right[155] & fast_layout[14]);
    assign fast_block[588]= (frame_right[76] & fast_layout[1]) | (frame_payload[140] & fast_select_6) | (frame_payload[76] & fast_select_7) | (frame_public[76] & fast_layout[6]) | (index_bytes[76] & fast_layout[7]) | (xmss_address[76] & fast_layout[8]) | (frame_left[76] & fast_select_10) | (frame_right[156] & fast_layout[14]);
    assign fast_block[589]= (frame_right[77] & fast_layout[1]) | (frame_payload[141] & fast_select_6) | (frame_payload[77] & fast_select_7) | (frame_public[77] & fast_layout[6]) | (index_bytes[77] & fast_layout[7]) | (xmss_address[77] & fast_layout[8]) | (frame_left[77] & fast_select_10) | (frame_right[157] & fast_layout[14]);
    assign fast_block[590]= (frame_right[78] & fast_layout[1]) | (frame_payload[142] & fast_select_6) | (frame_payload[78] & fast_select_7) | (frame_public[78] & fast_layout[6]) | (index_bytes[78] & fast_layout[7]) | (xmss_address[78] & fast_layout[8]) | (frame_left[78] & fast_select_10) | (frame_right[158] & fast_layout[14]);
    assign fast_block[591]= (frame_right[79] & fast_layout[1]) | (frame_payload[143] & fast_select_6) | (frame_payload[79] & fast_select_7) | (frame_public[79] & fast_layout[6]) | (index_bytes[79] & fast_layout[7]) | (xmss_address[79] & fast_layout[8]) | (frame_left[79] & fast_select_10) | (frame_right[159] & fast_layout[14]);
    assign fast_block[592]= (frame_right[80] & fast_layout[1]) | (frame_payload[144] & fast_select_6) | (frame_payload[80] & fast_select_7) | (frame_public[80] & fast_layout[6]) | (index_bytes[80] & fast_layout[7]) | (xmss_address[80] & fast_layout[8]) | (frame_left[80] & fast_select_10) | (frame_right[160] & fast_layout[14]);
    assign fast_block[593]= (frame_right[81] & fast_layout[1]) | (frame_payload[145] & fast_select_6) | (frame_payload[81] & fast_select_7) | (frame_public[81] & fast_layout[6]) | (index_bytes[81] & fast_layout[7]) | (xmss_address[81] & fast_layout[8]) | (frame_left[81] & fast_select_10) | (frame_right[161] & fast_layout[14]);
    assign fast_block[594]= (frame_right[82] & fast_layout[1]) | (frame_payload[146] & fast_select_6) | (frame_payload[82] & fast_select_7) | (frame_public[82] & fast_layout[6]) | (index_bytes[82] & fast_layout[7]) | (xmss_address[82] & fast_layout[8]) | (frame_left[82] & fast_select_10) | (frame_right[162] & fast_layout[14]);
    assign fast_block[595]= (frame_right[83] & fast_layout[1]) | (frame_payload[147] & fast_select_6) | (frame_payload[83] & fast_select_7) | (frame_public[83] & fast_layout[6]) | (index_bytes[83] & fast_layout[7]) | (xmss_address[83] & fast_layout[8]) | (frame_left[83] & fast_select_10) | (frame_right[163] & fast_layout[14]);
    assign fast_block[596]= (frame_right[84] & fast_layout[1]) | (frame_payload[148] & fast_select_6) | (frame_payload[84] & fast_select_7) | (frame_public[84] & fast_layout[6]) | (index_bytes[84] & fast_layout[7]) | (xmss_address[84] & fast_layout[8]) | (frame_left[84] & fast_select_10) | (frame_right[164] & fast_layout[14]);
    assign fast_block[597]= (frame_right[85] & fast_layout[1]) | (frame_payload[149] & fast_select_6) | (frame_payload[85] & fast_select_7) | (frame_public[85] & fast_layout[6]) | (index_bytes[85] & fast_layout[7]) | (xmss_address[85] & fast_layout[8]) | (frame_left[85] & fast_select_10) | (frame_right[165] & fast_layout[14]);
    assign fast_block[598]= (frame_right[86] & fast_layout[1]) | (frame_payload[150] & fast_select_6) | (frame_payload[86] & fast_select_7) | (frame_public[86] & fast_layout[6]) | (index_bytes[86] & fast_layout[7]) | (xmss_address[86] & fast_layout[8]) | (frame_left[86] & fast_select_10) | (frame_right[166] & fast_layout[14]);
    assign fast_block[599]= (frame_right[87] & fast_layout[1]) | (frame_payload[151] & fast_select_6) | (frame_payload[87] & fast_select_7) | (frame_public[87] & fast_layout[6]) | (index_bytes[87] & fast_layout[7]) | (xmss_address[87] & fast_layout[8]) | (frame_left[87] & fast_select_10) | (frame_right[167] & fast_layout[14]);
    assign fast_block[600]= (frame_right[88] & fast_layout[1]) | (frame_payload[152] & fast_select_6) | (frame_payload[88] & fast_select_7) | (frame_public[88] & fast_layout[6]) | (index_bytes[88] & fast_layout[7]) | (xmss_address[88] & fast_layout[8]) | (frame_left[88] & fast_select_10) | (frame_right[168] & fast_layout[14]);
    assign fast_block[601]= (frame_right[89] & fast_layout[1]) | (frame_payload[153] & fast_select_6) | (frame_payload[89] & fast_select_7) | (frame_public[89] & fast_layout[6]) | (index_bytes[89] & fast_layout[7]) | (xmss_address[89] & fast_layout[8]) | (frame_left[89] & fast_select_10) | (frame_right[169] & fast_layout[14]);
    assign fast_block[602]= (frame_right[90] & fast_layout[1]) | (frame_payload[154] & fast_select_6) | (frame_payload[90] & fast_select_7) | (frame_public[90] & fast_layout[6]) | (index_bytes[90] & fast_layout[7]) | (xmss_address[90] & fast_layout[8]) | (frame_left[90] & fast_select_10) | (frame_right[170] & fast_layout[14]);
    assign fast_block[603]= (frame_right[91] & fast_layout[1]) | (frame_payload[155] & fast_select_6) | (frame_payload[91] & fast_select_7) | (frame_public[91] & fast_layout[6]) | (index_bytes[91] & fast_layout[7]) | (xmss_address[91] & fast_layout[8]) | (frame_left[91] & fast_select_10) | (frame_right[171] & fast_layout[14]);
    assign fast_block[604]= (frame_right[92] & fast_layout[1]) | (frame_payload[156] & fast_select_6) | (frame_payload[92] & fast_select_7) | (frame_public[92] & fast_layout[6]) | (index_bytes[92] & fast_layout[7]) | (xmss_address[92] & fast_layout[8]) | (frame_left[92] & fast_select_10) | (frame_right[172] & fast_layout[14]);
    assign fast_block[605]= (frame_right[93] & fast_layout[1]) | (frame_payload[157] & fast_select_6) | (frame_payload[93] & fast_select_7) | (frame_public[93] & fast_layout[6]) | (index_bytes[93] & fast_layout[7]) | (xmss_address[93] & fast_layout[8]) | (frame_left[93] & fast_select_10) | (frame_right[173] & fast_layout[14]);
    assign fast_block[606]= (frame_right[94] & fast_layout[1]) | (frame_payload[158] & fast_select_6) | (frame_payload[94] & fast_select_7) | (frame_public[94] & fast_layout[6]) | (index_bytes[94] & fast_layout[7]) | (xmss_address[94] & fast_layout[8]) | (frame_left[94] & fast_select_10) | (frame_right[174] & fast_layout[14]);
    assign fast_block[607]= (frame_right[95] & fast_layout[1]) | (frame_payload[159] & fast_select_6) | (frame_payload[95] & fast_select_7) | (frame_public[95] & fast_layout[6]) | (index_bytes[95] & fast_layout[7]) | (xmss_address[95] & fast_layout[8]) | (frame_left[95] & fast_select_10) | (frame_right[175] & fast_layout[14]);
    assign fast_block[608]= (frame_right[96] & fast_layout[1]) | (frame_payload[160] & fast_select_6) | (frame_payload[96] & fast_select_7) | (frame_public[96] & fast_layout[6]) | (index_bytes[96] & fast_layout[7]) | (xmss_address[96] & fast_layout[8]) | (frame_left[96] & fast_select_10) | (frame_right[176] & fast_layout[14]);
    assign fast_block[609]= (frame_right[97] & fast_layout[1]) | (frame_payload[161] & fast_select_6) | (frame_payload[97] & fast_select_7) | (frame_public[97] & fast_layout[6]) | (index_bytes[97] & fast_layout[7]) | (xmss_address[97] & fast_layout[8]) | (frame_left[97] & fast_select_10) | (frame_right[177] & fast_layout[14]);
    assign fast_block[610]= (frame_right[98] & fast_layout[1]) | (frame_payload[162] & fast_select_6) | (frame_payload[98] & fast_select_7) | (frame_public[98] & fast_layout[6]) | (index_bytes[98] & fast_layout[7]) | (xmss_address[98] & fast_layout[8]) | (frame_left[98] & fast_select_10) | (frame_right[178] & fast_layout[14]);
    assign fast_block[611]= (frame_right[99] & fast_layout[1]) | (frame_payload[163] & fast_select_6) | (frame_payload[99] & fast_select_7) | (frame_public[99] & fast_layout[6]) | (index_bytes[99] & fast_layout[7]) | (xmss_address[99] & fast_layout[8]) | (frame_left[99] & fast_select_10) | (frame_right[179] & fast_layout[14]);
    assign fast_block[612]= (frame_right[100] & fast_layout[1]) | (frame_payload[164] & fast_select_6) | (frame_payload[100] & fast_select_7) | (frame_public[100] & fast_layout[6]) | (index_bytes[100] & fast_layout[7]) | (xmss_address[100] & fast_layout[8]) | (frame_left[100] & fast_select_10) | (frame_right[180] & fast_layout[14]);
    assign fast_block[613]= (frame_right[101] & fast_layout[1]) | (frame_payload[165] & fast_select_6) | (frame_payload[101] & fast_select_7) | (frame_public[101] & fast_layout[6]) | (index_bytes[101] & fast_layout[7]) | (xmss_address[101] & fast_layout[8]) | (frame_left[101] & fast_select_10) | (frame_right[181] & fast_layout[14]);
    assign fast_block[614]= (frame_right[102] & fast_layout[1]) | (frame_payload[166] & fast_select_6) | (frame_payload[102] & fast_select_7) | (frame_public[102] & fast_layout[6]) | (index_bytes[102] & fast_layout[7]) | (xmss_address[102] & fast_layout[8]) | (frame_left[102] & fast_select_10) | (frame_right[182] & fast_layout[14]);
    assign fast_block[615]= (frame_right[103] & fast_layout[1]) | (frame_payload[167] & fast_select_6) | (frame_payload[103] & fast_select_7) | (frame_public[103] & fast_layout[6]) | (index_bytes[103] & fast_layout[7]) | (xmss_address[103] & fast_layout[8]) | (frame_left[103] & fast_select_10) | (frame_right[183] & fast_layout[14]);
    assign fast_block[616]= (frame_right[104] & fast_layout[1]) | (frame_payload[168] & fast_select_6) | (frame_payload[104] & fast_select_7) | (frame_public[104] & fast_layout[6]) | (index_bytes[104] & fast_layout[7]) | (xmss_address[104] & fast_layout[8]) | (frame_left[104] & fast_select_10) | (frame_right[184] & fast_layout[14]);
    assign fast_block[617]= (frame_right[105] & fast_layout[1]) | (frame_payload[169] & fast_select_6) | (frame_payload[105] & fast_select_7) | (frame_public[105] & fast_layout[6]) | (index_bytes[105] & fast_layout[7]) | (xmss_address[105] & fast_layout[8]) | (frame_left[105] & fast_select_10) | (frame_right[185] & fast_layout[14]);
    assign fast_block[618]= (frame_right[106] & fast_layout[1]) | (frame_payload[170] & fast_select_6) | (frame_payload[106] & fast_select_7) | (frame_public[106] & fast_layout[6]) | (index_bytes[106] & fast_layout[7]) | (xmss_address[106] & fast_layout[8]) | (frame_left[106] & fast_select_10) | (frame_right[186] & fast_layout[14]);
    assign fast_block[619]= (frame_right[107] & fast_layout[1]) | (frame_payload[171] & fast_select_6) | (frame_payload[107] & fast_select_7) | (frame_public[107] & fast_layout[6]) | (index_bytes[107] & fast_layout[7]) | (xmss_address[107] & fast_layout[8]) | (frame_left[107] & fast_select_10) | (frame_right[187] & fast_layout[14]);
    assign fast_block[620]= (frame_right[108] & fast_layout[1]) | (frame_payload[172] & fast_select_6) | (frame_payload[108] & fast_select_7) | (frame_public[108] & fast_layout[6]) | (index_bytes[108] & fast_layout[7]) | (xmss_address[108] & fast_layout[8]) | (frame_left[108] & fast_select_10) | (frame_right[188] & fast_layout[14]);
    assign fast_block[621]= (frame_right[109] & fast_layout[1]) | (frame_payload[173] & fast_select_6) | (frame_payload[109] & fast_select_7) | (frame_public[109] & fast_layout[6]) | (index_bytes[109] & fast_layout[7]) | (xmss_address[109] & fast_layout[8]) | (frame_left[109] & fast_select_10) | (frame_right[189] & fast_layout[14]);
    assign fast_block[622]= (frame_right[110] & fast_layout[1]) | (frame_payload[174] & fast_select_6) | (frame_payload[110] & fast_select_7) | (frame_public[110] & fast_layout[6]) | (index_bytes[110] & fast_layout[7]) | (xmss_address[110] & fast_layout[8]) | (frame_left[110] & fast_select_10) | (frame_right[190] & fast_layout[14]);
    assign fast_block[623]= (frame_right[111] & fast_layout[1]) | (frame_payload[175] & fast_select_6) | (frame_payload[111] & fast_select_7) | (frame_public[111] & fast_layout[6]) | (index_bytes[111] & fast_layout[7]) | (xmss_address[111] & fast_layout[8]) | (frame_left[111] & fast_select_10) | (frame_right[191] & fast_layout[14]);
    assign fast_block[624]= (frame_right[112] & fast_layout[1]) | (frame_payload[176] & fast_select_6) | (frame_payload[112] & fast_select_7) | (frame_public[112] & fast_layout[6]) | (index_bytes[112] & fast_layout[7]) | (xmss_address[112] & fast_layout[8]) | (frame_left[112] & fast_select_10) | (frame_right[192] & fast_layout[14]);
    assign fast_block[625]= (frame_right[113] & fast_layout[1]) | (frame_payload[177] & fast_select_6) | (frame_payload[113] & fast_select_7) | (frame_public[113] & fast_layout[6]) | (index_bytes[113] & fast_layout[7]) | (xmss_address[113] & fast_layout[8]) | (frame_left[113] & fast_select_10) | (frame_right[193] & fast_layout[14]);
    assign fast_block[626]= (frame_right[114] & fast_layout[1]) | (frame_payload[178] & fast_select_6) | (frame_payload[114] & fast_select_7) | (frame_public[114] & fast_layout[6]) | (index_bytes[114] & fast_layout[7]) | (xmss_address[114] & fast_layout[8]) | (frame_left[114] & fast_select_10) | (frame_right[194] & fast_layout[14]);
    assign fast_block[627]= (frame_right[115] & fast_layout[1]) | (frame_payload[179] & fast_select_6) | (frame_payload[115] & fast_select_7) | (frame_public[115] & fast_layout[6]) | (index_bytes[115] & fast_layout[7]) | (xmss_address[115] & fast_layout[8]) | (frame_left[115] & fast_select_10) | (frame_right[195] & fast_layout[14]);
    assign fast_block[628]= (frame_right[116] & fast_layout[1]) | (frame_payload[180] & fast_select_6) | (frame_payload[116] & fast_select_7) | (frame_public[116] & fast_layout[6]) | (index_bytes[116] & fast_layout[7]) | (xmss_address[116] & fast_layout[8]) | (frame_left[116] & fast_select_10) | (frame_right[196] & fast_layout[14]);
    assign fast_block[629]= (frame_right[117] & fast_layout[1]) | (frame_payload[181] & fast_select_6) | (frame_payload[117] & fast_select_7) | (frame_public[117] & fast_layout[6]) | (index_bytes[117] & fast_layout[7]) | (xmss_address[117] & fast_layout[8]) | (frame_left[117] & fast_select_10) | (frame_right[197] & fast_layout[14]);
    assign fast_block[630]= (frame_right[118] & fast_layout[1]) | (frame_payload[182] & fast_select_6) | (frame_payload[118] & fast_select_7) | (frame_public[118] & fast_layout[6]) | (index_bytes[118] & fast_layout[7]) | (xmss_address[118] & fast_layout[8]) | (frame_left[118] & fast_select_10) | (frame_right[198] & fast_layout[14]);
    assign fast_block[631]= (frame_right[119] & fast_layout[1]) | (frame_payload[183] & fast_select_6) | (frame_payload[119] & fast_select_7) | (frame_public[119] & fast_layout[6]) | (index_bytes[119] & fast_layout[7]) | (xmss_address[119] & fast_layout[8]) | (frame_left[119] & fast_select_10) | (frame_right[199] & fast_layout[14]);
    assign fast_block[632]= (frame_right[120] & fast_layout[1]) | (frame_payload[184] & fast_select_6) | (frame_payload[120] & fast_select_7) | (frame_public[120] & fast_layout[6]) | (index_bytes[120] & fast_layout[7]) | (xmss_address[120] & fast_layout[8]) | (frame_left[120] & fast_select_10) | (frame_right[200] & fast_layout[14]);
    assign fast_block[633]= (frame_right[121] & fast_layout[1]) | (frame_payload[185] & fast_select_6) | (frame_payload[121] & fast_select_7) | (frame_public[121] & fast_layout[6]) | (index_bytes[121] & fast_layout[7]) | (xmss_address[121] & fast_layout[8]) | (frame_left[121] & fast_select_10) | (frame_right[201] & fast_layout[14]);
    assign fast_block[634]= (frame_right[122] & fast_layout[1]) | (frame_payload[186] & fast_select_6) | (frame_payload[122] & fast_select_7) | (frame_public[122] & fast_layout[6]) | (index_bytes[122] & fast_layout[7]) | (xmss_address[122] & fast_layout[8]) | (frame_left[122] & fast_select_10) | (frame_right[202] & fast_layout[14]);
    assign fast_block[635]= (frame_right[123] & fast_layout[1]) | (frame_payload[187] & fast_select_6) | (frame_payload[123] & fast_select_7) | (frame_public[123] & fast_layout[6]) | (index_bytes[123] & fast_layout[7]) | (xmss_address[123] & fast_layout[8]) | (frame_left[123] & fast_select_10) | (frame_right[203] & fast_layout[14]);
    assign fast_block[636]= (frame_right[124] & fast_layout[1]) | (frame_payload[188] & fast_select_6) | (frame_payload[124] & fast_select_7) | (frame_public[124] & fast_layout[6]) | (index_bytes[124] & fast_layout[7]) | (xmss_address[124] & fast_layout[8]) | (frame_left[124] & fast_select_10) | (frame_right[204] & fast_layout[14]);
    assign fast_block[637]= (frame_right[125] & fast_layout[1]) | (frame_payload[189] & fast_select_6) | (frame_payload[125] & fast_select_7) | (frame_public[125] & fast_layout[6]) | (index_bytes[125] & fast_layout[7]) | (xmss_address[125] & fast_layout[8]) | (frame_left[125] & fast_select_10) | (frame_right[205] & fast_layout[14]);
    assign fast_block[638]= (frame_right[126] & fast_layout[1]) | (frame_payload[190] & fast_select_6) | (frame_payload[126] & fast_select_7) | (frame_public[126] & fast_layout[6]) | (index_bytes[126] & fast_layout[7]) | (xmss_address[126] & fast_layout[8]) | (frame_left[126] & fast_select_10) | (frame_right[206] & fast_layout[14]);
    assign fast_block[639]= (frame_right[127] & fast_layout[1]) | (frame_payload[191] & fast_select_6) | (frame_payload[127] & fast_select_7) | (frame_public[127] & fast_layout[6]) | (index_bytes[127] & fast_layout[7]) | (xmss_address[127] & fast_layout[8]) | (frame_left[127] & fast_select_10) | (frame_right[207] & fast_layout[14]);
    assign fast_block[640]= fast_select_11 | (frame_right[0] & fast_layout[3]) | (frame_payload[128] & fast_select_7) | (frame_public[128] & fast_layout[6]) | (index_bytes[128] & fast_layout[7]) | (xmss_address[128] & fast_layout[8]) | (frame_left[128] & fast_select_10) | (frame_right[208] & fast_layout[14]);
    assign fast_block[641]= fast_select_11 | (frame_right[1] & fast_layout[3]) | (frame_payload[129] & fast_select_7) | (frame_public[129] & fast_layout[6]) | (index_bytes[129] & fast_layout[7]) | (xmss_address[129] & fast_layout[8]) | (frame_left[129] & fast_select_10) | (frame_right[209] & fast_layout[14]);
    assign fast_block[642]= fast_select_11 | (frame_right[2] & fast_layout[3]) | (frame_payload[130] & fast_select_7) | (frame_public[130] & fast_layout[6]) | (index_bytes[130] & fast_layout[7]) | (xmss_address[130] & fast_layout[8]) | (frame_left[130] & fast_select_10) | (frame_right[210] & fast_layout[14]);
    assign fast_block[643]= fast_select_11 | (frame_right[3] & fast_layout[3]) | (frame_payload[131] & fast_select_7) | (frame_public[131] & fast_layout[6]) | (index_bytes[131] & fast_layout[7]) | (xmss_address[131] & fast_layout[8]) | (frame_left[131] & fast_select_10) | (frame_right[211] & fast_layout[14]);
    assign fast_block[644]= fast_select_11 | (frame_right[4] & fast_layout[3]) | (frame_payload[132] & fast_select_7) | (frame_public[132] & fast_layout[6]) | (index_bytes[132] & fast_layout[7]) | (xmss_address[132] & fast_layout[8]) | (frame_left[132] & fast_select_10) | (frame_right[212] & fast_layout[14]);
    assign fast_block[645]= (frame_right[5] & fast_layout[3]) | (frame_payload[133] & fast_select_7) | (frame_public[133] & fast_layout[6]) | (index_bytes[133] & fast_layout[7]) | (xmss_address[133] & fast_layout[8]) | (frame_left[133] & fast_select_10) | (frame_right[213] & fast_layout[14]);
    assign fast_block[646]= (frame_right[6] & fast_layout[3]) | (frame_payload[134] & fast_select_7) | (frame_public[134] & fast_layout[6]) | (index_bytes[134] & fast_layout[7]) | (xmss_address[134] & fast_layout[8]) | (frame_left[134] & fast_select_10) | (frame_right[214] & fast_layout[14]);
    assign fast_block[647]= (frame_right[7] & fast_layout[3]) | (frame_payload[135] & fast_select_7) | (frame_public[135] & fast_layout[6]) | (index_bytes[135] & fast_layout[7]) | (xmss_address[135] & fast_layout[8]) | (frame_left[135] & fast_select_10) | (frame_right[215] & fast_layout[14]);
    assign fast_block[648]= (frame_right[8] & fast_layout[3]) | (frame_payload[136] & fast_select_7) | (frame_public[136] & fast_layout[6]) | (index_bytes[136] & fast_layout[7]) | (xmss_address[136] & fast_layout[8]) | (frame_left[136] & fast_select_10) | (frame_right[216] & fast_layout[14]);
    assign fast_block[649]= (frame_right[9] & fast_layout[3]) | (frame_payload[137] & fast_select_7) | (frame_public[137] & fast_layout[6]) | (index_bytes[137] & fast_layout[7]) | (xmss_address[137] & fast_layout[8]) | (frame_left[137] & fast_select_10) | (frame_right[217] & fast_layout[14]);
    assign fast_block[650]= (frame_right[10] & fast_layout[3]) | (frame_payload[138] & fast_select_7) | (frame_public[138] & fast_layout[6]) | (index_bytes[138] & fast_layout[7]) | (xmss_address[138] & fast_layout[8]) | (frame_left[138] & fast_select_10) | (frame_right[218] & fast_layout[14]);
    assign fast_block[651]= (frame_right[11] & fast_layout[3]) | (frame_payload[139] & fast_select_7) | (frame_public[139] & fast_layout[6]) | (index_bytes[139] & fast_layout[7]) | (xmss_address[139] & fast_layout[8]) | (frame_left[139] & fast_select_10) | (frame_right[219] & fast_layout[14]);
    assign fast_block[652]= (frame_right[12] & fast_layout[3]) | (frame_payload[140] & fast_select_7) | (frame_public[140] & fast_layout[6]) | (index_bytes[140] & fast_layout[7]) | (xmss_address[140] & fast_layout[8]) | (frame_left[140] & fast_select_10) | (frame_right[220] & fast_layout[14]);
    assign fast_block[653]= (frame_right[13] & fast_layout[3]) | (frame_payload[141] & fast_select_7) | (frame_public[141] & fast_layout[6]) | (index_bytes[141] & fast_layout[7]) | (xmss_address[141] & fast_layout[8]) | (frame_left[141] & fast_select_10) | (frame_right[221] & fast_layout[14]);
    assign fast_block[654]= (frame_right[14] & fast_layout[3]) | (frame_payload[142] & fast_select_7) | (frame_public[142] & fast_layout[6]) | (index_bytes[142] & fast_layout[7]) | (xmss_address[142] & fast_layout[8]) | (frame_left[142] & fast_select_10) | (frame_right[222] & fast_layout[14]);
    assign fast_block[655]= (frame_right[15] & fast_layout[3]) | (frame_payload[143] & fast_select_7) | (frame_public[143] & fast_layout[6]) | (index_bytes[143] & fast_layout[7]) | (xmss_address[143] & fast_layout[8]) | (frame_left[143] & fast_select_10) | (frame_right[223] & fast_layout[14]);
    assign fast_block[656]= (frame_right[16] & fast_layout[3]) | (frame_payload[144] & fast_select_7) | (frame_public[144] & fast_layout[6]) | (index_bytes[144] & fast_layout[7]) | (xmss_address[144] & fast_layout[8]) | (frame_left[144] & fast_select_10) | (frame_right[224] & fast_layout[14]);
    assign fast_block[657]= (frame_right[17] & fast_layout[3]) | (frame_payload[145] & fast_select_7) | (frame_public[145] & fast_layout[6]) | (index_bytes[145] & fast_layout[7]) | (xmss_address[145] & fast_layout[8]) | (frame_left[145] & fast_select_10) | (frame_right[225] & fast_layout[14]);
    assign fast_block[658]= (frame_right[18] & fast_layout[3]) | (frame_payload[146] & fast_select_7) | (frame_public[146] & fast_layout[6]) | (index_bytes[146] & fast_layout[7]) | (xmss_address[146] & fast_layout[8]) | (frame_left[146] & fast_select_10) | (frame_right[226] & fast_layout[14]);
    assign fast_block[659]= (frame_right[19] & fast_layout[3]) | (frame_payload[147] & fast_select_7) | (frame_public[147] & fast_layout[6]) | (index_bytes[147] & fast_layout[7]) | (xmss_address[147] & fast_layout[8]) | (frame_left[147] & fast_select_10) | (frame_right[227] & fast_layout[14]);
    assign fast_block[660]= (frame_right[20] & fast_layout[3]) | (frame_payload[148] & fast_select_7) | (frame_public[148] & fast_layout[6]) | (index_bytes[148] & fast_layout[7]) | (xmss_address[148] & fast_layout[8]) | (frame_left[148] & fast_select_10) | (frame_right[228] & fast_layout[14]);
    assign fast_block[661]= (frame_right[21] & fast_layout[3]) | (frame_payload[149] & fast_select_7) | (frame_public[149] & fast_layout[6]) | (index_bytes[149] & fast_layout[7]) | (xmss_address[149] & fast_layout[8]) | (frame_left[149] & fast_select_10) | (frame_right[229] & fast_layout[14]);
    assign fast_block[662]= (frame_right[22] & fast_layout[3]) | (frame_payload[150] & fast_select_7) | (frame_public[150] & fast_layout[6]) | (index_bytes[150] & fast_layout[7]) | (xmss_address[150] & fast_layout[8]) | (frame_left[150] & fast_select_10) | (frame_right[230] & fast_layout[14]);
    assign fast_block[663]= (frame_right[23] & fast_layout[3]) | (frame_payload[151] & fast_select_7) | (frame_public[151] & fast_layout[6]) | (index_bytes[151] & fast_layout[7]) | (xmss_address[151] & fast_layout[8]) | (frame_left[151] & fast_select_10) | (frame_right[231] & fast_layout[14]);
    assign fast_block[664]= (frame_right[24] & fast_layout[3]) | (frame_payload[152] & fast_select_7) | (frame_public[152] & fast_layout[6]) | (index_bytes[152] & fast_layout[7]) | (xmss_address[152] & fast_layout[8]) | (frame_left[152] & fast_select_10) | (frame_right[232] & fast_layout[14]);
    assign fast_block[665]= (frame_right[25] & fast_layout[3]) | (frame_payload[153] & fast_select_7) | (frame_public[153] & fast_layout[6]) | (index_bytes[153] & fast_layout[7]) | (xmss_address[153] & fast_layout[8]) | (frame_left[153] & fast_select_10) | (frame_right[233] & fast_layout[14]);
    assign fast_block[666]= (frame_right[26] & fast_layout[3]) | (frame_payload[154] & fast_select_7) | (frame_public[154] & fast_layout[6]) | (index_bytes[154] & fast_layout[7]) | (xmss_address[154] & fast_layout[8]) | (frame_left[154] & fast_select_10) | (frame_right[234] & fast_layout[14]);
    assign fast_block[667]= (frame_right[27] & fast_layout[3]) | (frame_payload[155] & fast_select_7) | (frame_public[155] & fast_layout[6]) | (index_bytes[155] & fast_layout[7]) | (xmss_address[155] & fast_layout[8]) | (frame_left[155] & fast_select_10) | (frame_right[235] & fast_layout[14]);
    assign fast_block[668]= (frame_right[28] & fast_layout[3]) | (frame_payload[156] & fast_select_7) | (frame_public[156] & fast_layout[6]) | (index_bytes[156] & fast_layout[7]) | (xmss_address[156] & fast_layout[8]) | (frame_left[156] & fast_select_10) | (frame_right[236] & fast_layout[14]);
    assign fast_block[669]= (frame_right[29] & fast_layout[3]) | (frame_payload[157] & fast_select_7) | (frame_public[157] & fast_layout[6]) | (index_bytes[157] & fast_layout[7]) | (xmss_address[157] & fast_layout[8]) | (frame_left[157] & fast_select_10) | (frame_right[237] & fast_layout[14]);
    assign fast_block[670]= (frame_right[30] & fast_layout[3]) | (frame_payload[158] & fast_select_7) | (frame_public[158] & fast_layout[6]) | (index_bytes[158] & fast_layout[7]) | (xmss_address[158] & fast_layout[8]) | (frame_left[158] & fast_select_10) | (frame_right[238] & fast_layout[14]);
    assign fast_block[671]= (frame_right[31] & fast_layout[3]) | (frame_payload[159] & fast_select_7) | (frame_public[159] & fast_layout[6]) | (index_bytes[159] & fast_layout[7]) | (xmss_address[159] & fast_layout[8]) | (frame_left[159] & fast_select_10) | (frame_right[239] & fast_layout[14]);
    assign fast_block[672]= (frame_right[32] & fast_layout[3]) | (frame_payload[160] & fast_select_7) | (frame_public[160] & fast_layout[6]) | (index_bytes[160] & fast_layout[7]) | (xmss_address[160] & fast_layout[8]) | (frame_left[160] & fast_select_10) | (frame_right[240] & fast_layout[14]);
    assign fast_block[673]= (frame_right[33] & fast_layout[3]) | (frame_payload[161] & fast_select_7) | (frame_public[161] & fast_layout[6]) | (index_bytes[161] & fast_layout[7]) | (xmss_address[161] & fast_layout[8]) | (frame_left[161] & fast_select_10) | (frame_right[241] & fast_layout[14]);
    assign fast_block[674]= (frame_right[34] & fast_layout[3]) | (frame_payload[162] & fast_select_7) | (frame_public[162] & fast_layout[6]) | (index_bytes[162] & fast_layout[7]) | (xmss_address[162] & fast_layout[8]) | (frame_left[162] & fast_select_10) | (frame_right[242] & fast_layout[14]);
    assign fast_block[675]= (frame_right[35] & fast_layout[3]) | (frame_payload[163] & fast_select_7) | (frame_public[163] & fast_layout[6]) | (index_bytes[163] & fast_layout[7]) | (xmss_address[163] & fast_layout[8]) | (frame_left[163] & fast_select_10) | (frame_right[243] & fast_layout[14]);
    assign fast_block[676]= (frame_right[36] & fast_layout[3]) | (frame_payload[164] & fast_select_7) | (frame_public[164] & fast_layout[6]) | (index_bytes[164] & fast_layout[7]) | (xmss_address[164] & fast_layout[8]) | (frame_left[164] & fast_select_10) | (frame_right[244] & fast_layout[14]);
    assign fast_block[677]= (frame_right[37] & fast_layout[3]) | (frame_payload[165] & fast_select_7) | (frame_public[165] & fast_layout[6]) | (index_bytes[165] & fast_layout[7]) | (xmss_address[165] & fast_layout[8]) | (frame_left[165] & fast_select_10) | (frame_right[245] & fast_layout[14]);
    assign fast_block[678]= (frame_right[38] & fast_layout[3]) | (frame_payload[166] & fast_select_7) | (frame_public[166] & fast_layout[6]) | (index_bytes[166] & fast_layout[7]) | (xmss_address[166] & fast_layout[8]) | (frame_left[166] & fast_select_10) | (frame_right[246] & fast_layout[14]);
    assign fast_block[679]= (frame_right[39] & fast_layout[3]) | (frame_payload[167] & fast_select_7) | (frame_public[167] & fast_layout[6]) | (index_bytes[167] & fast_layout[7]) | (xmss_address[167] & fast_layout[8]) | (frame_left[167] & fast_select_10) | (frame_right[247] & fast_layout[14]);
    assign fast_block[680]= (frame_right[40] & fast_layout[3]) | (frame_payload[168] & fast_select_7) | (frame_public[168] & fast_layout[6]) | (index_bytes[168] & fast_layout[7]) | (xmss_address[168] & fast_layout[8]) | (frame_left[168] & fast_select_10) | (frame_right[248] & fast_layout[14]);
    assign fast_block[681]= (frame_right[41] & fast_layout[3]) | (frame_payload[169] & fast_select_7) | (frame_public[169] & fast_layout[6]) | (index_bytes[169] & fast_layout[7]) | (xmss_address[169] & fast_layout[8]) | (frame_left[169] & fast_select_10) | (frame_right[249] & fast_layout[14]);
    assign fast_block[682]= (frame_right[42] & fast_layout[3]) | (frame_payload[170] & fast_select_7) | (frame_public[170] & fast_layout[6]) | (index_bytes[170] & fast_layout[7]) | (xmss_address[170] & fast_layout[8]) | (frame_left[170] & fast_select_10) | (frame_right[250] & fast_layout[14]);
    assign fast_block[683]= (frame_right[43] & fast_layout[3]) | (frame_payload[171] & fast_select_7) | (frame_public[171] & fast_layout[6]) | (index_bytes[171] & fast_layout[7]) | (xmss_address[171] & fast_layout[8]) | (frame_left[171] & fast_select_10) | (frame_right[251] & fast_layout[14]);
    assign fast_block[684]= (frame_right[44] & fast_layout[3]) | (frame_payload[172] & fast_select_7) | (frame_public[172] & fast_layout[6]) | (index_bytes[172] & fast_layout[7]) | (xmss_address[172] & fast_layout[8]) | (frame_left[172] & fast_select_10) | (frame_right[252] & fast_layout[14]);
    assign fast_block[685]= (frame_right[45] & fast_layout[3]) | (frame_payload[173] & fast_select_7) | (frame_public[173] & fast_layout[6]) | (index_bytes[173] & fast_layout[7]) | (xmss_address[173] & fast_layout[8]) | (frame_left[173] & fast_select_10) | (frame_right[253] & fast_layout[14]);
    assign fast_block[686]= (frame_right[46] & fast_layout[3]) | (frame_payload[174] & fast_select_7) | (frame_public[174] & fast_layout[6]) | (index_bytes[174] & fast_layout[7]) | (xmss_address[174] & fast_layout[8]) | (frame_left[174] & fast_select_10) | (frame_right[254] & fast_layout[14]);
    assign fast_block[687]= (frame_right[47] & fast_layout[3]) | (frame_payload[175] & fast_select_7) | (frame_public[175] & fast_layout[6]) | (index_bytes[175] & fast_layout[7]) | (xmss_address[175] & fast_layout[8]) | (frame_left[175] & fast_select_10) | (frame_right[255] & fast_layout[14]);
    assign fast_block[688]= (frame_right[48] & fast_layout[3]) | (frame_payload[176] & fast_select_7) | (frame_public[176] & fast_layout[6]) | (index_bytes[176] & fast_layout[7]) | (xmss_address[176] & fast_layout[8]) | (frame_left[176] & fast_select_10) | fast_layout[14];
    assign fast_block[689]= (frame_right[49] & fast_layout[3]) | (frame_payload[177] & fast_select_7) | (frame_public[177] & fast_layout[6]) | (index_bytes[177] & fast_layout[7]) | (xmss_address[177] & fast_layout[8]) | (frame_left[177] & fast_select_10) | fast_layout[14];
    assign fast_block[690]= (frame_right[50] & fast_layout[3]) | (frame_payload[178] & fast_select_7) | (frame_public[178] & fast_layout[6]) | (index_bytes[178] & fast_layout[7]) | (xmss_address[178] & fast_layout[8]) | (frame_left[178] & fast_select_10) | fast_layout[14];
    assign fast_block[691]= (frame_right[51] & fast_layout[3]) | (frame_payload[179] & fast_select_7) | (frame_public[179] & fast_layout[6]) | (index_bytes[179] & fast_layout[7]) | (xmss_address[179] & fast_layout[8]) | (frame_left[179] & fast_select_10) | fast_layout[14];
    assign fast_block[692]= (frame_right[52] & fast_layout[3]) | (frame_payload[180] & fast_select_7) | (frame_public[180] & fast_layout[6]) | (index_bytes[180] & fast_layout[7]) | (xmss_address[180] & fast_layout[8]) | (frame_left[180] & fast_select_10) | fast_layout[14];
    assign fast_block[693]= (frame_right[53] & fast_layout[3]) | (frame_payload[181] & fast_select_7) | (frame_public[181] & fast_layout[6]) | (index_bytes[181] & fast_layout[7]) | (xmss_address[181] & fast_layout[8]) | (frame_left[181] & fast_select_10);
    assign fast_block[694]= (frame_right[54] & fast_layout[3]) | (frame_payload[182] & fast_select_7) | (frame_public[182] & fast_layout[6]) | (index_bytes[182] & fast_layout[7]) | (xmss_address[182] & fast_layout[8]) | (frame_left[182] & fast_select_10);
    assign fast_block[695]= (frame_right[55] & fast_layout[3]) | (frame_payload[183] & fast_select_7) | (frame_public[183] & fast_layout[6]) | (index_bytes[183] & fast_layout[7]) | (xmss_address[183] & fast_layout[8]) | (frame_left[183] & fast_select_10);
    assign fast_block[696]= (frame_right[56] & fast_layout[3]) | (frame_payload[184] & fast_select_7) | (frame_public[184] & fast_layout[6]) | (index_bytes[184] & fast_layout[7]) | (xmss_address[184] & fast_layout[8]) | (frame_left[184] & fast_select_10);
    assign fast_block[697]= (frame_right[57] & fast_layout[3]) | (frame_payload[185] & fast_select_7) | (frame_public[185] & fast_layout[6]) | (index_bytes[185] & fast_layout[7]) | (xmss_address[185] & fast_layout[8]) | (frame_left[185] & fast_select_10);
    assign fast_block[698]= (frame_right[58] & fast_layout[3]) | (frame_payload[186] & fast_select_7) | (frame_public[186] & fast_layout[6]) | (index_bytes[186] & fast_layout[7]) | (xmss_address[186] & fast_layout[8]) | (frame_left[186] & fast_select_10);
    assign fast_block[699]= (frame_right[59] & fast_layout[3]) | (frame_payload[187] & fast_select_7) | (frame_public[187] & fast_layout[6]) | (index_bytes[187] & fast_layout[7]) | (xmss_address[187] & fast_layout[8]) | (frame_left[187] & fast_select_10);
    assign fast_block[700]= (frame_right[60] & fast_layout[3]) | (frame_payload[188] & fast_select_7) | (frame_public[188] & fast_layout[6]) | (index_bytes[188] & fast_layout[7]) | (xmss_address[188] & fast_layout[8]) | (frame_left[188] & fast_select_10);
    assign fast_block[701]= (frame_right[61] & fast_layout[3]) | (frame_payload[189] & fast_select_7) | (frame_public[189] & fast_layout[6]) | (index_bytes[189] & fast_layout[7]) | (xmss_address[189] & fast_layout[8]) | (frame_left[189] & fast_select_10);
    assign fast_block[702]= (frame_right[62] & fast_layout[3]) | (frame_payload[190] & fast_select_7) | (frame_public[190] & fast_layout[6]) | (index_bytes[190] & fast_layout[7]) | (xmss_address[190] & fast_layout[8]) | (frame_left[190] & fast_select_10);
    assign fast_block[703]= (frame_right[63] & fast_layout[3]) | (frame_payload[191] & fast_select_7) | (frame_public[191] & fast_layout[6]) | (index_bytes[191] & fast_layout[7]) | (xmss_address[191] & fast_layout[8]) | (frame_left[191] & fast_select_10);
    assign fast_block[704]= (frame_right[64] & fast_layout[3]) | (frame_payload[192] & fast_select_7) | (frame_public[192] & fast_layout[6]) | (index_bytes[192] & fast_layout[7]) | (xmss_address[192] & fast_layout[8]) | (frame_left[192] & fast_select_10);
    assign fast_block[705]= (frame_right[65] & fast_layout[3]) | (frame_payload[193] & fast_select_7) | (frame_public[193] & fast_layout[6]) | (index_bytes[193] & fast_layout[7]) | (xmss_address[193] & fast_layout[8]) | (frame_left[193] & fast_select_10);
    assign fast_block[706]= (frame_right[66] & fast_layout[3]) | (frame_payload[194] & fast_select_7) | (frame_public[194] & fast_layout[6]) | (index_bytes[194] & fast_layout[7]) | (xmss_address[194] & fast_layout[8]) | (frame_left[194] & fast_select_10);
    assign fast_block[707]= (frame_right[67] & fast_layout[3]) | (frame_payload[195] & fast_select_7) | (frame_public[195] & fast_layout[6]) | (index_bytes[195] & fast_layout[7]) | (xmss_address[195] & fast_layout[8]) | (frame_left[195] & fast_select_10);
    assign fast_block[708]= (frame_right[68] & fast_layout[3]) | (frame_payload[196] & fast_select_7) | (frame_public[196] & fast_layout[6]) | (index_bytes[196] & fast_layout[7]) | (xmss_address[196] & fast_layout[8]) | (frame_left[196] & fast_select_10);
    assign fast_block[709]= (frame_right[69] & fast_layout[3]) | (frame_payload[197] & fast_select_7) | (frame_public[197] & fast_layout[6]) | (index_bytes[197] & fast_layout[7]) | (xmss_address[197] & fast_layout[8]) | (frame_left[197] & fast_select_10);
    assign fast_block[710]= (frame_right[70] & fast_layout[3]) | (frame_payload[198] & fast_select_7) | (frame_public[198] & fast_layout[6]) | (index_bytes[198] & fast_layout[7]) | (xmss_address[198] & fast_layout[8]) | (frame_left[198] & fast_select_10);
    assign fast_block[711]= (frame_right[71] & fast_layout[3]) | (frame_payload[199] & fast_select_7) | (frame_public[199] & fast_layout[6]) | (index_bytes[199] & fast_layout[7]) | (xmss_address[199] & fast_layout[8]) | (frame_left[199] & fast_select_10);
    assign fast_block[712]= (frame_right[72] & fast_layout[3]) | (frame_payload[200] & fast_select_7) | (frame_public[200] & fast_layout[6]) | (index_bytes[200] & fast_layout[7]) | (xmss_address[200] & fast_layout[8]) | (frame_left[200] & fast_select_10);
    assign fast_block[713]= (frame_right[73] & fast_layout[3]) | (frame_payload[201] & fast_select_7) | (frame_public[201] & fast_layout[6]) | (index_bytes[201] & fast_layout[7]) | (xmss_address[201] & fast_layout[8]) | (frame_left[201] & fast_select_10);
    assign fast_block[714]= (frame_right[74] & fast_layout[3]) | (frame_payload[202] & fast_select_7) | (frame_public[202] & fast_layout[6]) | (index_bytes[202] & fast_layout[7]) | (xmss_address[202] & fast_layout[8]) | (frame_left[202] & fast_select_10);
    assign fast_block[715]= (frame_right[75] & fast_layout[3]) | (frame_payload[203] & fast_select_7) | (frame_public[203] & fast_layout[6]) | (index_bytes[203] & fast_layout[7]) | (xmss_address[203] & fast_layout[8]) | (frame_left[203] & fast_select_10);
    assign fast_block[716]= (frame_right[76] & fast_layout[3]) | (frame_payload[204] & fast_select_7) | (frame_public[204] & fast_layout[6]) | (index_bytes[204] & fast_layout[7]) | (xmss_address[204] & fast_layout[8]) | (frame_left[204] & fast_select_10);
    assign fast_block[717]= (frame_right[77] & fast_layout[3]) | (frame_payload[205] & fast_select_7) | (frame_public[205] & fast_layout[6]) | (index_bytes[205] & fast_layout[7]) | (xmss_address[205] & fast_layout[8]) | (frame_left[205] & fast_select_10);
    assign fast_block[718]= (frame_right[78] & fast_layout[3]) | (frame_payload[206] & fast_select_7) | (frame_public[206] & fast_layout[6]) | (index_bytes[206] & fast_layout[7]) | (xmss_address[206] & fast_layout[8]) | (frame_left[206] & fast_select_10);
    assign fast_block[719]= (frame_right[79] & fast_layout[3]) | (frame_payload[207] & fast_select_7) | (frame_public[207] & fast_layout[6]) | (index_bytes[207] & fast_layout[7]) | (xmss_address[207] & fast_layout[8]) | (frame_left[207] & fast_select_10);
    assign fast_block[720]= (frame_right[80] & fast_layout[3]) | (frame_payload[208] & fast_select_7) | (frame_public[208] & fast_layout[6]) | (index_bytes[208] & fast_layout[7]) | (xmss_address[208] & fast_layout[8]) | (frame_left[208] & fast_select_10);
    assign fast_block[721]= (frame_right[81] & fast_layout[3]) | (frame_payload[209] & fast_select_7) | (frame_public[209] & fast_layout[6]) | (index_bytes[209] & fast_layout[7]) | (xmss_address[209] & fast_layout[8]) | (frame_left[209] & fast_select_10);
    assign fast_block[722]= (frame_right[82] & fast_layout[3]) | (frame_payload[210] & fast_select_7) | (frame_public[210] & fast_layout[6]) | (index_bytes[210] & fast_layout[7]) | (xmss_address[210] & fast_layout[8]) | (frame_left[210] & fast_select_10);
    assign fast_block[723]= (frame_right[83] & fast_layout[3]) | (frame_payload[211] & fast_select_7) | (frame_public[211] & fast_layout[6]) | (index_bytes[211] & fast_layout[7]) | (xmss_address[211] & fast_layout[8]) | (frame_left[211] & fast_select_10);
    assign fast_block[724]= (frame_right[84] & fast_layout[3]) | (frame_payload[212] & fast_select_7) | (frame_public[212] & fast_layout[6]) | (index_bytes[212] & fast_layout[7]) | (xmss_address[212] & fast_layout[8]) | (frame_left[212] & fast_select_10);
    assign fast_block[725]= (frame_right[85] & fast_layout[3]) | (frame_payload[213] & fast_select_7) | (frame_public[213] & fast_layout[6]) | (index_bytes[213] & fast_layout[7]) | (xmss_address[213] & fast_layout[8]) | (frame_left[213] & fast_select_10);
    assign fast_block[726]= (frame_right[86] & fast_layout[3]) | (frame_payload[214] & fast_select_7) | (frame_public[214] & fast_layout[6]) | (index_bytes[214] & fast_layout[7]) | (xmss_address[214] & fast_layout[8]) | (frame_left[214] & fast_select_10);
    assign fast_block[727]= (frame_right[87] & fast_layout[3]) | (frame_payload[215] & fast_select_7) | (frame_public[215] & fast_layout[6]) | (index_bytes[215] & fast_layout[7]) | (xmss_address[215] & fast_layout[8]) | (frame_left[215] & fast_select_10);
    assign fast_block[728]= (frame_right[88] & fast_layout[3]) | (frame_payload[216] & fast_select_7) | (frame_public[216] & fast_layout[6]) | (index_bytes[216] & fast_layout[7]) | (xmss_address[216] & fast_layout[8]) | (frame_left[216] & fast_select_10);
    assign fast_block[729]= (frame_right[89] & fast_layout[3]) | (frame_payload[217] & fast_select_7) | (frame_public[217] & fast_layout[6]) | (index_bytes[217] & fast_layout[7]) | (xmss_address[217] & fast_layout[8]) | (frame_left[217] & fast_select_10);
    assign fast_block[730]= (frame_right[90] & fast_layout[3]) | (frame_payload[218] & fast_select_7) | (frame_public[218] & fast_layout[6]) | (index_bytes[218] & fast_layout[7]) | (xmss_address[218] & fast_layout[8]) | (frame_left[218] & fast_select_10);
    assign fast_block[731]= (frame_right[91] & fast_layout[3]) | (frame_payload[219] & fast_select_7) | (frame_public[219] & fast_layout[6]) | (index_bytes[219] & fast_layout[7]) | (xmss_address[219] & fast_layout[8]) | (frame_left[219] & fast_select_10);
    assign fast_block[732]= (frame_right[92] & fast_layout[3]) | (frame_payload[220] & fast_select_7) | (frame_public[220] & fast_layout[6]) | (index_bytes[220] & fast_layout[7]) | (xmss_address[220] & fast_layout[8]) | (frame_left[220] & fast_select_10);
    assign fast_block[733]= (frame_right[93] & fast_layout[3]) | (frame_payload[221] & fast_select_7) | (frame_public[221] & fast_layout[6]) | (index_bytes[221] & fast_layout[7]) | (xmss_address[221] & fast_layout[8]) | (frame_left[221] & fast_select_10);
    assign fast_block[734]= (frame_right[94] & fast_layout[3]) | (frame_payload[222] & fast_select_7) | (frame_public[222] & fast_layout[6]) | (index_bytes[222] & fast_layout[7]) | (xmss_address[222] & fast_layout[8]) | (frame_left[222] & fast_select_10);
    assign fast_block[735]= (frame_right[95] & fast_layout[3]) | (frame_payload[223] & fast_select_7) | (frame_public[223] & fast_layout[6]) | (index_bytes[223] & fast_layout[7]) | (xmss_address[223] & fast_layout[8]) | (frame_left[223] & fast_select_10);
    assign fast_block[736]= (frame_right[96] & fast_layout[3]) | (frame_payload[224] & fast_select_7) | (frame_public[224] & fast_layout[6]) | (index_bytes[224] & fast_layout[7]) | (xmss_address[224] & fast_layout[8]) | (frame_left[224] & fast_select_10);
    assign fast_block[737]= (frame_right[97] & fast_layout[3]) | (frame_payload[225] & fast_select_7) | (frame_public[225] & fast_layout[6]) | (index_bytes[225] & fast_layout[7]) | (xmss_address[225] & fast_layout[8]) | (frame_left[225] & fast_select_10);
    assign fast_block[738]= (frame_right[98] & fast_layout[3]) | (frame_payload[226] & fast_select_7) | (frame_public[226] & fast_layout[6]) | (index_bytes[226] & fast_layout[7]) | (xmss_address[226] & fast_layout[8]) | (frame_left[226] & fast_select_10);
    assign fast_block[739]= (frame_right[99] & fast_layout[3]) | (frame_payload[227] & fast_select_7) | (frame_public[227] & fast_layout[6]) | (index_bytes[227] & fast_layout[7]) | (xmss_address[227] & fast_layout[8]) | (frame_left[227] & fast_select_10);
    assign fast_block[740]= (frame_right[100] & fast_layout[3]) | (frame_payload[228] & fast_select_7) | (frame_public[228] & fast_layout[6]) | (index_bytes[228] & fast_layout[7]) | (xmss_address[228] & fast_layout[8]) | (frame_left[228] & fast_select_10);
    assign fast_block[741]= (frame_right[101] & fast_layout[3]) | (frame_payload[229] & fast_select_7) | (frame_public[229] & fast_layout[6]) | (index_bytes[229] & fast_layout[7]) | (xmss_address[229] & fast_layout[8]) | (frame_left[229] & fast_select_10);
    assign fast_block[742]= (frame_right[102] & fast_layout[3]) | (frame_payload[230] & fast_select_7) | (frame_public[230] & fast_layout[6]) | (index_bytes[230] & fast_layout[7]) | (xmss_address[230] & fast_layout[8]) | (frame_left[230] & fast_select_10);
    assign fast_block[743]= (frame_right[103] & fast_layout[3]) | (frame_payload[231] & fast_select_7) | (frame_public[231] & fast_layout[6]) | (index_bytes[231] & fast_layout[7]) | (xmss_address[231] & fast_layout[8]) | (frame_left[231] & fast_select_10);
    assign fast_block[744]= (frame_right[104] & fast_layout[3]) | (frame_payload[232] & fast_select_7) | (frame_public[232] & fast_layout[6]) | (index_bytes[232] & fast_layout[7]) | (xmss_address[232] & fast_layout[8]) | (frame_left[232] & fast_select_10);
    assign fast_block[745]= (frame_right[105] & fast_layout[3]) | (frame_payload[233] & fast_select_7) | (frame_public[233] & fast_layout[6]) | (index_bytes[233] & fast_layout[7]) | (xmss_address[233] & fast_layout[8]) | (frame_left[233] & fast_select_10);
    assign fast_block[746]= (frame_right[106] & fast_layout[3]) | (frame_payload[234] & fast_select_7) | (frame_public[234] & fast_layout[6]) | (index_bytes[234] & fast_layout[7]) | (xmss_address[234] & fast_layout[8]) | (frame_left[234] & fast_select_10);
    assign fast_block[747]= (frame_right[107] & fast_layout[3]) | (frame_payload[235] & fast_select_7) | (frame_public[235] & fast_layout[6]) | (index_bytes[235] & fast_layout[7]) | (xmss_address[235] & fast_layout[8]) | (frame_left[235] & fast_select_10);
    assign fast_block[748]= (frame_right[108] & fast_layout[3]) | (frame_payload[236] & fast_select_7) | (frame_public[236] & fast_layout[6]) | (index_bytes[236] & fast_layout[7]) | (xmss_address[236] & fast_layout[8]) | (frame_left[236] & fast_select_10);
    assign fast_block[749]= (frame_right[109] & fast_layout[3]) | (frame_payload[237] & fast_select_7) | (frame_public[237] & fast_layout[6]) | (index_bytes[237] & fast_layout[7]) | (xmss_address[237] & fast_layout[8]) | (frame_left[237] & fast_select_10);
    assign fast_block[750]= (frame_right[110] & fast_layout[3]) | (frame_payload[238] & fast_select_7) | (frame_public[238] & fast_layout[6]) | (index_bytes[238] & fast_layout[7]) | (xmss_address[238] & fast_layout[8]) | (frame_left[238] & fast_select_10);
    assign fast_block[751]= (frame_right[111] & fast_layout[3]) | (frame_payload[239] & fast_select_7) | (frame_public[239] & fast_layout[6]) | (index_bytes[239] & fast_layout[7]) | (xmss_address[239] & fast_layout[8]) | (frame_left[239] & fast_select_10);
    assign fast_block[752]= (frame_right[112] & fast_layout[3]) | (frame_payload[240] & fast_select_7) | (frame_public[240] & fast_layout[6]) | (index_bytes[240] & fast_layout[7]) | (xmss_address[240] & fast_layout[8]) | (frame_left[240] & fast_select_10);
    assign fast_block[753]= (frame_right[113] & fast_layout[3]) | (frame_payload[241] & fast_select_7) | (frame_public[241] & fast_layout[6]) | (index_bytes[241] & fast_layout[7]) | (xmss_address[241] & fast_layout[8]) | (frame_left[241] & fast_select_10);
    assign fast_block[754]= (frame_right[114] & fast_layout[3]) | (frame_payload[242] & fast_select_7) | (frame_public[242] & fast_layout[6]) | (index_bytes[242] & fast_layout[7]) | (xmss_address[242] & fast_layout[8]) | (frame_left[242] & fast_select_10);
    assign fast_block[755]= (frame_right[115] & fast_layout[3]) | (frame_payload[243] & fast_select_7) | (frame_public[243] & fast_layout[6]) | (index_bytes[243] & fast_layout[7]) | (xmss_address[243] & fast_layout[8]) | (frame_left[243] & fast_select_10);
    assign fast_block[756]= (frame_right[116] & fast_layout[3]) | (frame_payload[244] & fast_select_7) | (frame_public[244] & fast_layout[6]) | (index_bytes[244] & fast_layout[7]) | (xmss_address[244] & fast_layout[8]) | (frame_left[244] & fast_select_10);
    assign fast_block[757]= (frame_right[117] & fast_layout[3]) | (frame_payload[245] & fast_select_7) | (frame_public[245] & fast_layout[6]) | (index_bytes[245] & fast_layout[7]) | (xmss_address[245] & fast_layout[8]) | (frame_left[245] & fast_select_10);
    assign fast_block[758]= (frame_right[118] & fast_layout[3]) | (frame_payload[246] & fast_select_7) | (frame_public[246] & fast_layout[6]) | (index_bytes[246] & fast_layout[7]) | (xmss_address[246] & fast_layout[8]) | (frame_left[246] & fast_select_10);
    assign fast_block[759]= (frame_right[119] & fast_layout[3]) | (frame_payload[247] & fast_select_7) | (frame_public[247] & fast_layout[6]) | (index_bytes[247] & fast_layout[7]) | (xmss_address[247] & fast_layout[8]) | (frame_left[247] & fast_select_10);
    assign fast_block[760]= (frame_right[120] & fast_layout[3]) | (frame_payload[248] & fast_select_7) | (frame_public[248] & fast_layout[6]) | (index_bytes[248] & fast_layout[7]) | (xmss_address[248] & fast_layout[8]) | (frame_left[248] & fast_select_10);
    assign fast_block[761]= (frame_right[121] & fast_layout[3]) | (frame_payload[249] & fast_select_7) | (frame_public[249] & fast_layout[6]) | (index_bytes[249] & fast_layout[7]) | (xmss_address[249] & fast_layout[8]) | (frame_left[249] & fast_select_10);
    assign fast_block[762]= (frame_right[122] & fast_layout[3]) | (frame_payload[250] & fast_select_7) | (frame_public[250] & fast_layout[6]) | (index_bytes[250] & fast_layout[7]) | (xmss_address[250] & fast_layout[8]) | (frame_left[250] & fast_select_10);
    assign fast_block[763]= (frame_right[123] & fast_layout[3]) | (frame_payload[251] & fast_select_7) | (frame_public[251] & fast_layout[6]) | (index_bytes[251] & fast_layout[7]) | (xmss_address[251] & fast_layout[8]) | (frame_left[251] & fast_select_10);
    assign fast_block[764]= (frame_right[124] & fast_layout[3]) | (frame_payload[252] & fast_select_7) | (frame_public[252] & fast_layout[6]) | (index_bytes[252] & fast_layout[7]) | (xmss_address[252] & fast_layout[8]) | (frame_left[252] & fast_select_10);
    assign fast_block[765]= (frame_right[125] & fast_layout[3]) | (frame_payload[253] & fast_select_7) | (frame_public[253] & fast_layout[6]) | (index_bytes[253] & fast_layout[7]) | (xmss_address[253] & fast_layout[8]) | (frame_left[253] & fast_select_10);
    assign fast_block[766]= (frame_right[126] & fast_layout[3]) | (frame_payload[254] & fast_select_7) | (frame_public[254] & fast_layout[6]) | (index_bytes[254] & fast_layout[7]) | (xmss_address[254] & fast_layout[8]) | (frame_left[254] & fast_select_10);
    assign fast_block[767]= (frame_right[127] & fast_layout[3]) | (frame_payload[255] & fast_select_7) | (frame_public[255] & fast_layout[6]) | (index_bytes[255] & fast_layout[7]) | (xmss_address[255] & fast_layout[8]) | (frame_left[255] & fast_select_10);
    assign fast_block[768]= (frame_right[128] & fast_layout[3]) | fast_select_12 | (frame_right[0] & fast_select_13) | (xmss_address[0] & fast_layout[6]);
    assign fast_block[769]= (frame_right[129] & fast_layout[3]) | fast_select_12 | (frame_right[1] & fast_select_13) | (xmss_address[1] & fast_layout[6]);
    assign fast_block[770]= (frame_right[130] & fast_layout[3]) | fast_select_12 | (frame_right[2] & fast_select_13) | (xmss_address[2] & fast_layout[6]);
    assign fast_block[771]= (frame_right[131] & fast_layout[3]) | fast_select_12 | (frame_right[3] & fast_select_13) | (xmss_address[3] & fast_layout[6]);
    assign fast_block[772]= (frame_right[132] & fast_layout[3]) | fast_select_12 | (frame_right[4] & fast_select_13) | (xmss_address[4] & fast_layout[6]);
    assign fast_block[773]= (frame_right[133] & fast_layout[3]) | (frame_right[5] & fast_select_13) | (xmss_address[5] & fast_layout[6]);
    assign fast_block[774]= (frame_right[134] & fast_layout[3]) | (frame_right[6] & fast_select_13) | (xmss_address[6] & fast_layout[6]);
    assign fast_block[775]= (frame_right[135] & fast_layout[3]) | (frame_right[7] & fast_select_13) | (xmss_address[7] & fast_layout[6]);
    assign fast_block[776]= (frame_right[136] & fast_layout[3]) | (frame_right[8] & fast_select_13) | (xmss_address[8] & fast_layout[6]);
    assign fast_block[777]= (frame_right[137] & fast_layout[3]) | (frame_right[9] & fast_select_13) | (xmss_address[9] & fast_layout[6]);
    assign fast_block[778]= (frame_right[138] & fast_layout[3]) | (frame_right[10] & fast_select_13) | (xmss_address[10] & fast_layout[6]);
    assign fast_block[779]= (frame_right[139] & fast_layout[3]) | (frame_right[11] & fast_select_13) | (xmss_address[11] & fast_layout[6]);
    assign fast_block[780]= (frame_right[140] & fast_layout[3]) | (frame_right[12] & fast_select_13) | (xmss_address[12] & fast_layout[6]);
    assign fast_block[781]= (frame_right[141] & fast_layout[3]) | (frame_right[13] & fast_select_13) | (xmss_address[13] & fast_layout[6]);
    assign fast_block[782]= (frame_right[142] & fast_layout[3]) | (frame_right[14] & fast_select_13) | (xmss_address[14] & fast_layout[6]);
    assign fast_block[783]= (frame_right[143] & fast_layout[3]) | (frame_right[15] & fast_select_13) | (xmss_address[15] & fast_layout[6]);
    assign fast_block[784]= (frame_right[144] & fast_layout[3]) | (frame_right[16] & fast_select_13) | (xmss_address[16] & fast_layout[6]);
    assign fast_block[785]= (frame_right[145] & fast_layout[3]) | (frame_right[17] & fast_select_13) | (xmss_address[17] & fast_layout[6]);
    assign fast_block[786]= (frame_right[146] & fast_layout[3]) | (frame_right[18] & fast_select_13) | (xmss_address[18] & fast_layout[6]);
    assign fast_block[787]= (frame_right[147] & fast_layout[3]) | (frame_right[19] & fast_select_13) | (xmss_address[19] & fast_layout[6]);
    assign fast_block[788]= (frame_right[148] & fast_layout[3]) | (frame_right[20] & fast_select_13) | (xmss_address[20] & fast_layout[6]);
    assign fast_block[789]= (frame_right[149] & fast_layout[3]) | (frame_right[21] & fast_select_13) | (xmss_address[21] & fast_layout[6]);
    assign fast_block[790]= (frame_right[150] & fast_layout[3]) | (frame_right[22] & fast_select_13) | (xmss_address[22] & fast_layout[6]);
    assign fast_block[791]= (frame_right[151] & fast_layout[3]) | (frame_right[23] & fast_select_13) | (xmss_address[23] & fast_layout[6]);
    assign fast_block[792]= (frame_right[152] & fast_layout[3]) | (frame_right[24] & fast_select_13) | (xmss_address[24] & fast_layout[6]);
    assign fast_block[793]= (frame_right[153] & fast_layout[3]) | (frame_right[25] & fast_select_13) | (xmss_address[25] & fast_layout[6]);
    assign fast_block[794]= (frame_right[154] & fast_layout[3]) | (frame_right[26] & fast_select_13) | (xmss_address[26] & fast_layout[6]);
    assign fast_block[795]= (frame_right[155] & fast_layout[3]) | (frame_right[27] & fast_select_13) | (xmss_address[27] & fast_layout[6]);
    assign fast_block[796]= (frame_right[156] & fast_layout[3]) | (frame_right[28] & fast_select_13) | (xmss_address[28] & fast_layout[6]);
    assign fast_block[797]= (frame_right[157] & fast_layout[3]) | (frame_right[29] & fast_select_13) | (xmss_address[29] & fast_layout[6]);
    assign fast_block[798]= (frame_right[158] & fast_layout[3]) | (frame_right[30] & fast_select_13) | (xmss_address[30] & fast_layout[6]);
    assign fast_block[799]= (frame_right[159] & fast_layout[3]) | (frame_right[31] & fast_select_13) | (xmss_address[31] & fast_layout[6]);
    assign fast_block[800]= (frame_right[160] & fast_layout[3]) | (frame_right[32] & fast_select_13) | (xmss_address[32] & fast_layout[6]);
    assign fast_block[801]= (frame_right[161] & fast_layout[3]) | (frame_right[33] & fast_select_13) | (xmss_address[33] & fast_layout[6]);
    assign fast_block[802]= (frame_right[162] & fast_layout[3]) | (frame_right[34] & fast_select_13) | (xmss_address[34] & fast_layout[6]);
    assign fast_block[803]= (frame_right[163] & fast_layout[3]) | (frame_right[35] & fast_select_13) | (xmss_address[35] & fast_layout[6]);
    assign fast_block[804]= (frame_right[164] & fast_layout[3]) | (frame_right[36] & fast_select_13) | (xmss_address[36] & fast_layout[6]);
    assign fast_block[805]= (frame_right[165] & fast_layout[3]) | (frame_right[37] & fast_select_13) | (xmss_address[37] & fast_layout[6]);
    assign fast_block[806]= (frame_right[166] & fast_layout[3]) | (frame_right[38] & fast_select_13) | (xmss_address[38] & fast_layout[6]);
    assign fast_block[807]= (frame_right[167] & fast_layout[3]) | (frame_right[39] & fast_select_13) | (xmss_address[39] & fast_layout[6]);
    assign fast_block[808]= (frame_right[168] & fast_layout[3]) | (frame_right[40] & fast_select_13) | (xmss_address[40] & fast_layout[6]);
    assign fast_block[809]= (frame_right[169] & fast_layout[3]) | (frame_right[41] & fast_select_13) | (xmss_address[41] & fast_layout[6]);
    assign fast_block[810]= (frame_right[170] & fast_layout[3]) | (frame_right[42] & fast_select_13) | (xmss_address[42] & fast_layout[6]);
    assign fast_block[811]= (frame_right[171] & fast_layout[3]) | (frame_right[43] & fast_select_13) | (xmss_address[43] & fast_layout[6]);
    assign fast_block[812]= (frame_right[172] & fast_layout[3]) | (frame_right[44] & fast_select_13) | (xmss_address[44] & fast_layout[6]);
    assign fast_block[813]= (frame_right[173] & fast_layout[3]) | (frame_right[45] & fast_select_13) | (xmss_address[45] & fast_layout[6]);
    assign fast_block[814]= (frame_right[174] & fast_layout[3]) | (frame_right[46] & fast_select_13) | (xmss_address[46] & fast_layout[6]);
    assign fast_block[815]= (frame_right[175] & fast_layout[3]) | (frame_right[47] & fast_select_13) | (xmss_address[47] & fast_layout[6]);
    assign fast_block[816]= (frame_right[176] & fast_layout[3]) | (frame_right[48] & fast_select_13) | (xmss_address[48] & fast_layout[6]);
    assign fast_block[817]= (frame_right[177] & fast_layout[3]) | (frame_right[49] & fast_select_13) | (xmss_address[49] & fast_layout[6]);
    assign fast_block[818]= (frame_right[178] & fast_layout[3]) | (frame_right[50] & fast_select_13) | (xmss_address[50] & fast_layout[6]);
    assign fast_block[819]= (frame_right[179] & fast_layout[3]) | (frame_right[51] & fast_select_13) | (xmss_address[51] & fast_layout[6]);
    assign fast_block[820]= (frame_right[180] & fast_layout[3]) | (frame_right[52] & fast_select_13) | (xmss_address[52] & fast_layout[6]);
    assign fast_block[821]= (frame_right[181] & fast_layout[3]) | (frame_right[53] & fast_select_13) | (xmss_address[53] & fast_layout[6]);
    assign fast_block[822]= (frame_right[182] & fast_layout[3]) | (frame_right[54] & fast_select_13) | (xmss_address[54] & fast_layout[6]);
    assign fast_block[823]= (frame_right[183] & fast_layout[3]) | (frame_right[55] & fast_select_13) | (xmss_address[55] & fast_layout[6]);
    assign fast_block[824]= (frame_right[184] & fast_layout[3]) | (frame_right[56] & fast_select_13) | (xmss_address[56] & fast_layout[6]);
    assign fast_block[825]= (frame_right[185] & fast_layout[3]) | (frame_right[57] & fast_select_13) | (xmss_address[57] & fast_layout[6]);
    assign fast_block[826]= (frame_right[186] & fast_layout[3]) | (frame_right[58] & fast_select_13) | (xmss_address[58] & fast_layout[6]);
    assign fast_block[827]= (frame_right[187] & fast_layout[3]) | (frame_right[59] & fast_select_13) | (xmss_address[59] & fast_layout[6]);
    assign fast_block[828]= (frame_right[188] & fast_layout[3]) | (frame_right[60] & fast_select_13) | (xmss_address[60] & fast_layout[6]);
    assign fast_block[829]= (frame_right[189] & fast_layout[3]) | (frame_right[61] & fast_select_13) | (xmss_address[61] & fast_layout[6]);
    assign fast_block[830]= (frame_right[190] & fast_layout[3]) | (frame_right[62] & fast_select_13) | (xmss_address[62] & fast_layout[6]);
    assign fast_block[831]= (frame_right[191] & fast_layout[3]) | (frame_right[63] & fast_select_13) | (xmss_address[63] & fast_layout[6]);
    assign fast_block[832]= fast_layout[3] | (frame_right[64] & fast_select_13) | (xmss_address[64] & fast_layout[6]);
    assign fast_block[833]= fast_layout[3] | (frame_right[65] & fast_select_13) | (xmss_address[65] & fast_layout[6]);
    assign fast_block[834]= fast_layout[3] | (frame_right[66] & fast_select_13) | (xmss_address[66] & fast_layout[6]);
    assign fast_block[835]= fast_layout[3] | (frame_right[67] & fast_select_13) | (xmss_address[67] & fast_layout[6]);
    assign fast_block[836]= fast_layout[3] | (frame_right[68] & fast_select_13) | (xmss_address[68] & fast_layout[6]);
    assign fast_block[837]= (frame_right[69] & fast_select_13) | (xmss_address[69] & fast_layout[6]);
    assign fast_block[838]= (frame_right[70] & fast_select_13) | (xmss_address[70] & fast_layout[6]);
    assign fast_block[839]= (frame_right[71] & fast_select_13) | (xmss_address[71] & fast_layout[6]);
    assign fast_block[840]= (frame_right[72] & fast_select_13) | (xmss_address[72] & fast_layout[6]);
    assign fast_block[841]= (frame_right[73] & fast_select_13) | (xmss_address[73] & fast_layout[6]);
    assign fast_block[842]= (frame_right[74] & fast_select_13) | (xmss_address[74] & fast_layout[6]);
    assign fast_block[843]= (frame_right[75] & fast_select_13) | (xmss_address[75] & fast_layout[6]);
    assign fast_block[844]= (frame_right[76] & fast_select_13) | (xmss_address[76] & fast_layout[6]);
    assign fast_block[845]= (frame_right[77] & fast_select_13) | (xmss_address[77] & fast_layout[6]);
    assign fast_block[846]= (frame_right[78] & fast_select_13) | (xmss_address[78] & fast_layout[6]);
    assign fast_block[847]= (frame_right[79] & fast_select_13) | (xmss_address[79] & fast_layout[6]);
    assign fast_block[848]= (frame_right[80] & fast_select_13) | (xmss_address[80] & fast_layout[6]);
    assign fast_block[849]= (frame_right[81] & fast_select_13) | (xmss_address[81] & fast_layout[6]);
    assign fast_block[850]= (frame_right[82] & fast_select_13) | (xmss_address[82] & fast_layout[6]);
    assign fast_block[851]= (frame_right[83] & fast_select_13) | (xmss_address[83] & fast_layout[6]);
    assign fast_block[852]= (frame_right[84] & fast_select_13) | (xmss_address[84] & fast_layout[6]);
    assign fast_block[853]= (frame_right[85] & fast_select_13) | (xmss_address[85] & fast_layout[6]);
    assign fast_block[854]= (frame_right[86] & fast_select_13) | (xmss_address[86] & fast_layout[6]);
    assign fast_block[855]= (frame_right[87] & fast_select_13) | (xmss_address[87] & fast_layout[6]);
    assign fast_block[856]= (frame_right[88] & fast_select_13) | (xmss_address[88] & fast_layout[6]);
    assign fast_block[857]= (frame_right[89] & fast_select_13) | (xmss_address[89] & fast_layout[6]);
    assign fast_block[858]= (frame_right[90] & fast_select_13) | (xmss_address[90] & fast_layout[6]);
    assign fast_block[859]= (frame_right[91] & fast_select_13) | (xmss_address[91] & fast_layout[6]);
    assign fast_block[860]= (frame_right[92] & fast_select_13) | (xmss_address[92] & fast_layout[6]);
    assign fast_block[861]= (frame_right[93] & fast_select_13) | (xmss_address[93] & fast_layout[6]);
    assign fast_block[862]= (frame_right[94] & fast_select_13) | (xmss_address[94] & fast_layout[6]);
    assign fast_block[863]= (frame_right[95] & fast_select_13) | (xmss_address[95] & fast_layout[6]);
    assign fast_block[864]= (frame_right[96] & fast_select_13) | (xmss_address[96] & fast_layout[6]);
    assign fast_block[865]= (frame_right[97] & fast_select_13) | (xmss_address[97] & fast_layout[6]);
    assign fast_block[866]= (frame_right[98] & fast_select_13) | (xmss_address[98] & fast_layout[6]);
    assign fast_block[867]= (frame_right[99] & fast_select_13) | (xmss_address[99] & fast_layout[6]);
    assign fast_block[868]= (frame_right[100] & fast_select_13) | (xmss_address[100] & fast_layout[6]);
    assign fast_block[869]= (frame_right[101] & fast_select_13) | (xmss_address[101] & fast_layout[6]);
    assign fast_block[870]= (frame_right[102] & fast_select_13) | (xmss_address[102] & fast_layout[6]);
    assign fast_block[871]= (frame_right[103] & fast_select_13) | (xmss_address[103] & fast_layout[6]);
    assign fast_block[872]= (frame_right[104] & fast_select_13) | (xmss_address[104] & fast_layout[6]);
    assign fast_block[873]= (frame_right[105] & fast_select_13) | (xmss_address[105] & fast_layout[6]);
    assign fast_block[874]= (frame_right[106] & fast_select_13) | (xmss_address[106] & fast_layout[6]);
    assign fast_block[875]= (frame_right[107] & fast_select_13) | (xmss_address[107] & fast_layout[6]);
    assign fast_block[876]= (frame_right[108] & fast_select_13) | (xmss_address[108] & fast_layout[6]);
    assign fast_block[877]= (frame_right[109] & fast_select_13) | (xmss_address[109] & fast_layout[6]);
    assign fast_block[878]= (frame_right[110] & fast_select_13) | (xmss_address[110] & fast_layout[6]);
    assign fast_block[879]= (frame_right[111] & fast_select_13) | (xmss_address[111] & fast_layout[6]);
    assign fast_block[880]= (frame_right[112] & fast_select_13) | (xmss_address[112] & fast_layout[6]);
    assign fast_block[881]= (frame_right[113] & fast_select_13) | (xmss_address[113] & fast_layout[6]);
    assign fast_block[882]= (frame_right[114] & fast_select_13) | (xmss_address[114] & fast_layout[6]);
    assign fast_block[883]= (frame_right[115] & fast_select_13) | (xmss_address[115] & fast_layout[6]);
    assign fast_block[884]= (frame_right[116] & fast_select_13) | (xmss_address[116] & fast_layout[6]);
    assign fast_block[885]= (frame_right[117] & fast_select_13) | (xmss_address[117] & fast_layout[6]);
    assign fast_block[886]= (frame_right[118] & fast_select_13) | (xmss_address[118] & fast_layout[6]);
    assign fast_block[887]= (frame_right[119] & fast_select_13) | (xmss_address[119] & fast_layout[6]);
    assign fast_block[888]= (frame_right[120] & fast_select_13) | (xmss_address[120] & fast_layout[6]);
    assign fast_block[889]= (frame_right[121] & fast_select_13) | (xmss_address[121] & fast_layout[6]);
    assign fast_block[890]= (frame_right[122] & fast_select_13) | (xmss_address[122] & fast_layout[6]);
    assign fast_block[891]= (frame_right[123] & fast_select_13) | (xmss_address[123] & fast_layout[6]);
    assign fast_block[892]= (frame_right[124] & fast_select_13) | (xmss_address[124] & fast_layout[6]);
    assign fast_block[893]= (frame_right[125] & fast_select_13) | (xmss_address[125] & fast_layout[6]);
    assign fast_block[894]= (frame_right[126] & fast_select_13) | (xmss_address[126] & fast_layout[6]);
    assign fast_block[895]= (frame_right[127] & fast_select_13) | (xmss_address[127] & fast_layout[6]);
    assign fast_block[896]= (frame_right[128] & fast_select_13) | (xmss_address[128] & fast_layout[6]);
    assign fast_block[897]= (frame_right[129] & fast_select_13) | (xmss_address[129] & fast_layout[6]);
    assign fast_block[898]= (frame_right[130] & fast_select_13) | (xmss_address[130] & fast_layout[6]);
    assign fast_block[899]= (frame_right[131] & fast_select_13) | (xmss_address[131] & fast_layout[6]);
    assign fast_block[900]= (frame_right[132] & fast_select_13) | (xmss_address[132] & fast_layout[6]);
    assign fast_block[901]= (frame_right[133] & fast_select_13) | (xmss_address[133] & fast_layout[6]);
    assign fast_block[902]= (frame_right[134] & fast_select_13) | (xmss_address[134] & fast_layout[6]);
    assign fast_block[903]= (frame_right[135] & fast_select_13) | (xmss_address[135] & fast_layout[6]);
    assign fast_block[904]= (frame_right[136] & fast_select_13) | (xmss_address[136] & fast_layout[6]);
    assign fast_block[905]= (frame_right[137] & fast_select_13) | (xmss_address[137] & fast_layout[6]);
    assign fast_block[906]= (frame_right[138] & fast_select_13) | (xmss_address[138] & fast_layout[6]);
    assign fast_block[907]= (frame_right[139] & fast_select_13) | (xmss_address[139] & fast_layout[6]);
    assign fast_block[908]= (frame_right[140] & fast_select_13) | (xmss_address[140] & fast_layout[6]);
    assign fast_block[909]= (frame_right[141] & fast_select_13) | (xmss_address[141] & fast_layout[6]);
    assign fast_block[910]= (frame_right[142] & fast_select_13) | (xmss_address[142] & fast_layout[6]);
    assign fast_block[911]= (frame_right[143] & fast_select_13) | (xmss_address[143] & fast_layout[6]);
    assign fast_block[912]= (frame_right[144] & fast_select_13) | (xmss_address[144] & fast_layout[6]);
    assign fast_block[913]= (frame_right[145] & fast_select_13) | (xmss_address[145] & fast_layout[6]);
    assign fast_block[914]= (frame_right[146] & fast_select_13) | (xmss_address[146] & fast_layout[6]);
    assign fast_block[915]= (frame_right[147] & fast_select_13) | (xmss_address[147] & fast_layout[6]);
    assign fast_block[916]= (frame_right[148] & fast_select_13) | (xmss_address[148] & fast_layout[6]);
    assign fast_block[917]= (frame_right[149] & fast_select_13) | (xmss_address[149] & fast_layout[6]);
    assign fast_block[918]= (frame_right[150] & fast_select_13) | (xmss_address[150] & fast_layout[6]);
    assign fast_block[919]= (frame_right[151] & fast_select_13) | (xmss_address[151] & fast_layout[6]);
    assign fast_block[920]= (frame_right[152] & fast_select_13) | (xmss_address[152] & fast_layout[6]);
    assign fast_block[921]= (frame_right[153] & fast_select_13) | (xmss_address[153] & fast_layout[6]);
    assign fast_block[922]= (frame_right[154] & fast_select_13) | (xmss_address[154] & fast_layout[6]);
    assign fast_block[923]= (frame_right[155] & fast_select_13) | (xmss_address[155] & fast_layout[6]);
    assign fast_block[924]= (frame_right[156] & fast_select_13) | (xmss_address[156] & fast_layout[6]);
    assign fast_block[925]= (frame_right[157] & fast_select_13) | (xmss_address[157] & fast_layout[6]);
    assign fast_block[926]= (frame_right[158] & fast_select_13) | (xmss_address[158] & fast_layout[6]);
    assign fast_block[927]= (frame_right[159] & fast_select_13) | (xmss_address[159] & fast_layout[6]);
    assign fast_block[928]= (frame_right[160] & fast_select_13) | (xmss_address[160] & fast_layout[6]);
    assign fast_block[929]= (frame_right[161] & fast_select_13) | (xmss_address[161] & fast_layout[6]);
    assign fast_block[930]= (frame_right[162] & fast_select_13) | (xmss_address[162] & fast_layout[6]);
    assign fast_block[931]= (frame_right[163] & fast_select_13) | (xmss_address[163] & fast_layout[6]);
    assign fast_block[932]= (frame_right[164] & fast_select_13) | (xmss_address[164] & fast_layout[6]);
    assign fast_block[933]= (frame_right[165] & fast_select_13) | (xmss_address[165] & fast_layout[6]);
    assign fast_block[934]= (frame_right[166] & fast_select_13) | (xmss_address[166] & fast_layout[6]);
    assign fast_block[935]= (frame_right[167] & fast_select_13) | (xmss_address[167] & fast_layout[6]);
    assign fast_block[936]= (frame_right[168] & fast_select_13) | (xmss_address[168] & fast_layout[6]);
    assign fast_block[937]= (frame_right[169] & fast_select_13) | (xmss_address[169] & fast_layout[6]);
    assign fast_block[938]= (frame_right[170] & fast_select_13) | (xmss_address[170] & fast_layout[6]);
    assign fast_block[939]= (frame_right[171] & fast_select_13) | (xmss_address[171] & fast_layout[6]);
    assign fast_block[940]= (frame_right[172] & fast_select_13) | (xmss_address[172] & fast_layout[6]);
    assign fast_block[941]= (frame_right[173] & fast_select_13) | (xmss_address[173] & fast_layout[6]);
    assign fast_block[942]= (frame_right[174] & fast_select_13) | (xmss_address[174] & fast_layout[6]);
    assign fast_block[943]= (frame_right[175] & fast_select_13) | (xmss_address[175] & fast_layout[6]);
    assign fast_block[944]= (frame_right[176] & fast_select_13) | (xmss_address[176] & fast_layout[6]);
    assign fast_block[945]= (frame_right[177] & fast_select_13) | (xmss_address[177] & fast_layout[6]);
    assign fast_block[946]= (frame_right[178] & fast_select_13) | (xmss_address[178] & fast_layout[6]);
    assign fast_block[947]= (frame_right[179] & fast_select_13) | (xmss_address[179] & fast_layout[6]);
    assign fast_block[948]= (frame_right[180] & fast_select_13) | (xmss_address[180] & fast_layout[6]);
    assign fast_block[949]= (frame_right[181] & fast_select_13) | (xmss_address[181] & fast_layout[6]);
    assign fast_block[950]= (frame_right[182] & fast_select_13) | (xmss_address[182] & fast_layout[6]);
    assign fast_block[951]= (frame_right[183] & fast_select_13) | (xmss_address[183] & fast_layout[6]);
    assign fast_block[952]= (frame_right[184] & fast_select_13) | (xmss_address[184] & fast_layout[6]);
    assign fast_block[953]= (frame_right[185] & fast_select_13) | (xmss_address[185] & fast_layout[6]);
    assign fast_block[954]= (frame_right[186] & fast_select_13) | (xmss_address[186] & fast_layout[6]);
    assign fast_block[955]= (frame_right[187] & fast_select_13) | (xmss_address[187] & fast_layout[6]);
    assign fast_block[956]= (frame_right[188] & fast_select_13) | (xmss_address[188] & fast_layout[6]);
    assign fast_block[957]= (frame_right[189] & fast_select_13) | (xmss_address[189] & fast_layout[6]);
    assign fast_block[958]= (frame_right[190] & fast_select_13) | (xmss_address[190] & fast_layout[6]);
    assign fast_block[959]= (frame_right[191] & fast_select_13) | (xmss_address[191] & fast_layout[6]);
    assign fast_block[960]= (frame_right[192] & fast_select_13) | (xmss_address[192] & fast_layout[6]);
    assign fast_block[961]= (frame_right[193] & fast_select_13) | (xmss_address[193] & fast_layout[6]);
    assign fast_block[962]= (frame_right[194] & fast_select_13) | (xmss_address[194] & fast_layout[6]);
    assign fast_block[963]= (frame_right[195] & fast_select_13) | (xmss_address[195] & fast_layout[6]);
    assign fast_block[964]= (frame_right[196] & fast_select_13) | (xmss_address[196] & fast_layout[6]);
    assign fast_block[965]= (frame_right[197] & fast_select_13) | (xmss_address[197] & fast_layout[6]);
    assign fast_block[966]= (frame_right[198] & fast_select_13) | (xmss_address[198] & fast_layout[6]);
    assign fast_block[967]= (frame_right[199] & fast_select_13) | (xmss_address[199] & fast_layout[6]);
    assign fast_block[968]= (frame_right[200] & fast_select_13) | (xmss_address[200] & fast_layout[6]);
    assign fast_block[969]= (frame_right[201] & fast_select_13) | (xmss_address[201] & fast_layout[6]);
    assign fast_block[970]= (frame_right[202] & fast_select_13) | (xmss_address[202] & fast_layout[6]);
    assign fast_block[971]= (frame_right[203] & fast_select_13) | (xmss_address[203] & fast_layout[6]);
    assign fast_block[972]= (frame_right[204] & fast_select_13) | (xmss_address[204] & fast_layout[6]);
    assign fast_block[973]= (frame_right[205] & fast_select_13) | (xmss_address[205] & fast_layout[6]);
    assign fast_block[974]= (frame_right[206] & fast_select_13) | (xmss_address[206] & fast_layout[6]);
    assign fast_block[975]= (frame_right[207] & fast_select_13) | (xmss_address[207] & fast_layout[6]);
    assign fast_block[976]= (frame_right[208] & fast_select_13) | (xmss_address[208] & fast_layout[6]);
    assign fast_block[977]= (frame_right[209] & fast_select_13) | (xmss_address[209] & fast_layout[6]);
    assign fast_block[978]= (frame_right[210] & fast_select_13) | (xmss_address[210] & fast_layout[6]);
    assign fast_block[979]= (frame_right[211] & fast_select_13) | (xmss_address[211] & fast_layout[6]);
    assign fast_block[980]= (frame_right[212] & fast_select_13) | (xmss_address[212] & fast_layout[6]);
    assign fast_block[981]= (frame_right[213] & fast_select_13) | (xmss_address[213] & fast_layout[6]);
    assign fast_block[982]= (frame_right[214] & fast_select_13) | (xmss_address[214] & fast_layout[6]);
    assign fast_block[983]= (frame_right[215] & fast_select_13) | (xmss_address[215] & fast_layout[6]);
    assign fast_block[984]= (frame_right[216] & fast_select_13) | (xmss_address[216] & fast_layout[6]);
    assign fast_block[985]= (frame_right[217] & fast_select_13) | (xmss_address[217] & fast_layout[6]);
    assign fast_block[986]= (frame_right[218] & fast_select_13) | (xmss_address[218] & fast_layout[6]);
    assign fast_block[987]= (frame_right[219] & fast_select_13) | (xmss_address[219] & fast_layout[6]);
    assign fast_block[988]= (frame_right[220] & fast_select_13) | (xmss_address[220] & fast_layout[6]);
    assign fast_block[989]= (frame_right[221] & fast_select_13) | (xmss_address[221] & fast_layout[6]);
    assign fast_block[990]= (frame_right[222] & fast_select_13) | (xmss_address[222] & fast_layout[6]);
    assign fast_block[991]= (frame_right[223] & fast_select_13) | (xmss_address[223] & fast_layout[6]);
    assign fast_block[992]= (frame_right[224] & fast_select_13) | (xmss_address[224] & fast_layout[6]);
    assign fast_block[993]= (frame_right[225] & fast_select_13) | (xmss_address[225] & fast_layout[6]);
    assign fast_block[994]= (frame_right[226] & fast_select_13) | (xmss_address[226] & fast_layout[6]);
    assign fast_block[995]= (frame_right[227] & fast_select_13) | (xmss_address[227] & fast_layout[6]);
    assign fast_block[996]= (frame_right[228] & fast_select_13) | (xmss_address[228] & fast_layout[6]);
    assign fast_block[997]= (frame_right[229] & fast_select_13) | (xmss_address[229] & fast_layout[6]);
    assign fast_block[998]= (frame_right[230] & fast_select_13) | (xmss_address[230] & fast_layout[6]);
    assign fast_block[999]= (frame_right[231] & fast_select_13) | (xmss_address[231] & fast_layout[6]);
    assign fast_block[1000]= (frame_right[232] & fast_select_13) | (xmss_address[232] & fast_layout[6]);
    assign fast_block[1001]= (frame_right[233] & fast_select_13) | (xmss_address[233] & fast_layout[6]);
    assign fast_block[1002]= (frame_right[234] & fast_select_13) | (xmss_address[234] & fast_layout[6]);
    assign fast_block[1003]= (frame_right[235] & fast_select_13) | (xmss_address[235] & fast_layout[6]);
    assign fast_block[1004]= (frame_right[236] & fast_select_13) | (xmss_address[236] & fast_layout[6]);
    assign fast_block[1005]= (frame_right[237] & fast_select_13) | (xmss_address[237] & fast_layout[6]);
    assign fast_block[1006]= (frame_right[238] & fast_select_13) | (xmss_address[238] & fast_layout[6]);
    assign fast_block[1007]= (frame_right[239] & fast_select_13) | (xmss_address[239] & fast_layout[6]);
    assign fast_block[1008]= (frame_right[240] & fast_select_13) | (xmss_address[240] & fast_layout[6]);
    assign fast_block[1009]= (frame_right[241] & fast_select_13) | (xmss_address[241] & fast_layout[6]);
    assign fast_block[1010]= (frame_right[242] & fast_select_13) | (xmss_address[242] & fast_layout[6]);
    assign fast_block[1011]= (frame_right[243] & fast_select_13) | (xmss_address[243] & fast_layout[6]);
    assign fast_block[1012]= (frame_right[244] & fast_select_13) | (xmss_address[244] & fast_layout[6]);
    assign fast_block[1013]= (frame_right[245] & fast_select_13) | (xmss_address[245] & fast_layout[6]);
    assign fast_block[1014]= (frame_right[246] & fast_select_13) | (xmss_address[246] & fast_layout[6]);
    assign fast_block[1015]= (frame_right[247] & fast_select_13) | (xmss_address[247] & fast_layout[6]);
    assign fast_block[1016]= (frame_right[248] & fast_select_13) | (xmss_address[248] & fast_layout[6]);
    assign fast_block[1017]= (frame_right[249] & fast_select_13) | (xmss_address[249] & fast_layout[6]);
    assign fast_block[1018]= (frame_right[250] & fast_select_13) | (xmss_address[250] & fast_layout[6]);
    assign fast_block[1019]= (frame_right[251] & fast_select_13) | (xmss_address[251] & fast_layout[6]);
    assign fast_block[1020]= (frame_right[252] & fast_select_13) | (xmss_address[252] & fast_layout[6]);
    assign fast_block[1021]= (frame_right[253] & fast_select_13) | (xmss_address[253] & fast_layout[6]);
    assign fast_block[1022]= (frame_right[254] & fast_select_13) | (xmss_address[254] & fast_layout[6]);
    assign fast_block[1023]= (frame_right[255] & fast_select_13) | (xmss_address[255] & fast_layout[6]);
    assign fast_block[1024]= fast_select_14;
    assign fast_block[1025]= fast_select_14;
    assign fast_block[1026]= fast_select_14;
    assign fast_block[1027]= fast_select_14;
    assign fast_block[1028]= fast_select_14;
    assign fast_block[1029]= 1'b0;
    assign fast_block[1030]= 1'b0;
    assign fast_block[1031]= 1'b0;
    assign fast_block[1032]= 1'b0;
    assign fast_block[1033]= 1'b0;
    assign fast_block[1034]= 1'b0;
    assign fast_block[1035]= 1'b0;
    assign fast_block[1036]= 1'b0;
    assign fast_block[1037]= 1'b0;
    assign fast_block[1038]= 1'b0;
    assign fast_block[1039]= 1'b0;
    assign fast_block[1040]= 1'b0;
    assign fast_block[1041]= 1'b0;
    assign fast_block[1042]= 1'b0;
    assign fast_block[1043]= 1'b0;
    assign fast_block[1044]= 1'b0;
    assign fast_block[1045]= 1'b0;
    assign fast_block[1046]= 1'b0;
    assign fast_block[1047]= 1'b0;
    assign fast_block[1048]= 1'b0;
    assign fast_block[1049]= 1'b0;
    assign fast_block[1050]= 1'b0;
    assign fast_block[1051]= 1'b0;
    assign fast_block[1052]= 1'b0;
    assign fast_block[1053]= 1'b0;
    assign fast_block[1054]= 1'b0;
    assign fast_block[1055]= 1'b0;
    assign fast_block[1056]= 1'b0;
    assign fast_block[1057]= 1'b0;
    assign fast_block[1058]= 1'b0;
    assign fast_block[1059]= 1'b0;
    assign fast_block[1060]= 1'b0;
    assign fast_block[1061]= 1'b0;
    assign fast_block[1062]= 1'b0;
    assign fast_block[1063]= 1'b0;
    assign fast_block[1064]= 1'b0;
    assign fast_block[1065]= 1'b0;
    assign fast_block[1066]= 1'b0;
    assign fast_block[1067]= 1'b0;
    assign fast_block[1068]= 1'b0;
    assign fast_block[1069]= 1'b0;
    assign fast_block[1070]= 1'b0;
    assign fast_block[1071]= 1'b0;
    assign fast_block[1072]= 1'b0;
    assign fast_block[1073]= 1'b0;
    assign fast_block[1074]= 1'b0;
    assign fast_block[1075]= 1'b0;
    assign fast_block[1076]= 1'b0;
    assign fast_block[1077]= 1'b0;
    assign fast_block[1078]= 1'b0;
    assign fast_block[1079]= 1'b0;
    assign fast_block[1080]= 1'b0;
    assign fast_block[1081]= 1'b0;
    assign fast_block[1082]= 1'b0;
    assign fast_block[1083]= 1'b0;
    assign fast_block[1084]= 1'b0;
    assign fast_block[1085]= 1'b0;
    assign fast_block[1086]= 1'b0;
    assign fast_block[1087]=1'b1;
    logic [63:0] stream_data;
    integer i;
    wire at_end_word=position[12:3]==input_length[12:3];
    wire past_end_word=position[12:3]>input_length[12:3];
    always @* begin
        stream_data=source_word(position[12:3]);
        if((shape==MESSAGE_PRF || shape==MESSAGE_DIGEST || shape==XMSS_MESSAGE)
            && position[12:3]>=message_prefix_words && 32'(message_word_index)<MESSAGE_WORDS)
            stream_data=message_word_data;
        if(shape==ADDRESS_LIST && position>=13'(prefix_bytes))
            stream_data=node_word(256'(list_data0),{8'd0,list_remainder[4:3]});
        if(shape==LMS_MESSAGE || shape==LMS_PUBLIC) begin
            stream_data=0;
            case(position)
                0:stream_data=request_identifier[63:0];
                8:stream_data=request_identifier[127:64];
                16:begin
                    stream_data[31:0]=be32(lms_q);
                    stream_data[47:32]=shape==LMS_MESSAGE ? 16'h8181 : 16'h8080;
                    stream_data[63:48]=shape==LMS_MESSAGE ? randomizer[15:0] : list_data0[15:0];
                end
                default:begin
                    if(shape==LMS_MESSAGE) begin
                        case(position)
                            24:stream_data=64'(256'(randomizer)>>16);
                            32:stream_data=64'(256'(randomizer)>>80);
                            40:stream_data=64'(256'(randomizer)>>144);
                            48:stream_data={message_word_data[15:0],randomizer[255:208]};
                            default:stream_data={message_word_data[15:0],alignment_carry[63:16]};
                        endcase
                    end else begin
                        case(position[4:3])
                            0:stream_data=list_data0[143:80];
                            1:stream_data=list_data0[207:144];
                            2:stream_data={list_data0[15:0],alignment_carry[63:16]};
                            default:stream_data=list_data0[79:16];
                        endcase
                    end
                end
            endcase
        end
        for(i=0;i<8;i=i+1) begin
            if(past_end_word || (at_end_word && 3'(i)>=input_length[2:0]))
                stream_data[i*8 +:8]=0;
            if(at_end_word && 3'(i)==input_length[2:0]) stream_data[i*8 +:8]=8'h1f;
            if(stream_last && beat==16 && i==7) stream_data[i*8+7]=1;
        end
    end
    shake_context #(.UNROLL(UNROLL),.DIGEST_BYTES(DIGEST_BYTES)) sponge (
        .clk,.rst,.context_valid(request_valid && request_ready && !reject_request),.context_ready(hash_ready),
        .fast_block_valid(request_valid && request_ready && !reject_request && fixed_block),.fast_block_ready(fast_ready),
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
            alignment_carry<=0;
        end else begin
            // Accepting a new caller request has priority over draining the
            // old response. Its digest is observed before this edge updates
            // the sponge, so local feedback needs no extra result register.
            if(request_valid && request_ready) begin
                error<=reject_request;
                position<=0;
                beat<=0;
                list_cursor<=0;
                list_remainder<=0;
                alignment_carry<=0;
                node_words<=node_bytes[5:3];
                case(shape)
                    ADDRESS_LIST:input_length<=list_length;
                    MESSAGE_PRF,MESSAGE_DIGEST:input_length<=13'(message_prefix)+13'(message_length);
                    XMSS_MESSAGE:input_length<=13'd128+13'(message_length);
                    LMS_MESSAGE:input_length<=13'd54+13'(message_length);
                    LMS_PUBLIC:input_length<=13'd2166;
                    default:input_length<=0;
                endcase
                if(PROFILE_ENABLE && !reject_request) begin
                    hash_count<=hash_count+1'b1;
                    if(fixed_block) permutation_count<=permutation_count+1'b1;
                end
                state<=reject_request ? RESPONSE : fixed_block ? WAIT_HASH : STREAM;
            end else case(state)
                STREAM: if(STREAM_ENABLE && stream_accept) begin
                    if(shape==LMS_MESSAGE) alignment_carry<=message_word_data;
                    else if(shape==LMS_PUBLIC) alignment_carry<=list_data0[255:192];
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

    // Completion and the next explicit request may share the final-round edge.
    // The response observes the old advanced state; the accepting FF edge then
    // replaces it with the next request's fixed frame. No request is invented.
    wire final_round=state==RUN && 32'(round_index)+UNROLL>=24 && running_last;
    assign context_ready=state==IDLE || final_round;
    assign block_ready=state==WAIT_BLOCK;
    assign fast_block_ready=(context_ready && context_valid)
        || (state==WAIT_BLOCK && first_block && append_index==0);
    assign response_valid=!rst && final_round;
    assign response_digest=state==RUN ? advanced_state[DIGEST_BYTES*8-1:0]
        : sponge_state[DIGEST_BYTES*8-1:0];
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
        end else if(context_valid && context_ready) begin
            first_block<=1;
            append_index<=0;
            if(take_fast) begin
                running_last<=1;
                round_index<=0;
                state<=RUN;
            end else state<=WAIT_BLOCK;
        end else begin
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
