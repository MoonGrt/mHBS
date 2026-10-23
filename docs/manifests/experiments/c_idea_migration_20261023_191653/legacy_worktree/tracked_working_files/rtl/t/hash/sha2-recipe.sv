`ifdef MHBS_SHA2
`timescale 1ns / 1ps
`default_nettype none
// SHA2 recipe execution: one compression lane, P independent contexts.
// Byte-vector ports use byte zero in the least significant bits.
// verilog_format: off
module recipe #(
    parameter integer N = 32,
    parameter integer DIGEST_BYTES = N==16 ? 34 : 32, INDEX_BITS = 7,
    parameter integer UNROLL = 2, PIPELINE = 1,
    parameter integer MAX_MESSAGE_BYTES = 87,
    parameter [15:0] RECIPE_MASK = 16'hffff,
    parameter bit SHARED_STATE=0,
    localparam integer TAG_BITS=PIPELINE>1 ? $clog2(PIPELINE) : 1
) (
`ifndef SYNTHESIS
    output wire [63:0] batch_hashes,batch_permutations,
    output logic [63:0] hash_count,permutation_count,
`endif
    input wire clk, rst, output logic error,
    input wire batch_mode,batch_request_valid, output wire batch_request_ready,
    input wire [TAG_BITS-1:0] batch_request_tag,
    input wire [4:0] batch_steps, batch_capture_after, input wire batch_capture_enable,
    input wire [19:0] batch_leaf, input wire [7:0] batch_a, input wire [31:0] batch_b,
    input wire [1:0] batch_family, input wire batch_no_seed,
    input wire [3:0] batch_start, input wire [255:0] batch_initial_value,
    input wire [3:0] batch_fixed_shape, input wire batch_pair, input wire [255:0] batch_right,
    input wire [7:0] batch_seed_domain, batch_step_domain,
    output wire batch_response_valid, input wire batch_response_ready,
    output wire [TAG_BITS-1:0] batch_response_tag,
    output wire [255:0] batch_response_digest, batch_response_capture,
    input wire [TAG_BITS-1:0] batch_read_tag,
    output wire [255:0] batch_read_digest,batch_read_capture,
    input wire [5:0] node_bytes, input wire [127:0] identifier,
    input wire request_valid, output wire request_ready,
    input wire [63:0] request_recipe, request_step_recipe, input wire request_chain,
    input wire [4:0] request_steps, request_capture_after, input wire request_capture,
    input wire [N*8-1:0] secret_seed, secret_prf, public_seed, root, randomizer,
    input wire [MAX_MESSAGE_BYTES*8-1:0] message_buffer, input wire [6:0] message_length,
    input wire [4:0] request_layer, input wire [63:0] request_tree, input wire [19:0] request_leaf,
    input wire [INDEX_BITS-1:0] request_a, input wire [31:0] request_b,
    input wire [N*8-1:0] request_left, request_right,
    output wire [INDEX_BITS-1:0] list_index0, list_index1, list_next_index0,
    input wire [N*8-1:0] list_data0, list_data1,
    output wire response_valid, input wire response_ready,
    output wire [DIGEST_BYTES*8-1:0] response_value, output wire [N*8-1:0] response_capture
);
// verilog_format: on
    localparam [255:0] IV = 256'h6a09e667bb67ae853c6ef372a54ff53a510e527f9b05688c1f83d9ab5be0cd19;
    typedef enum logic [3:0] { DIRECT, SEED, KEY, MASK0, MASK1, FINAL,
        HMAC_IN, HMAC_OUT, HMSG_IN, MGF0, MGF1 } phase_t;
    typedef enum logic [2:0] { SELECT, DESCRIBE, PREPARE, BUILD, DRAIN } formatter_t;
    typedef enum logic [3:0] {
        FIXED_NONE, SLH_SECRET_TAIL, SLH_VALUE_TAIL, SLH_PAIR_TAIL,
        ADDRESS_TAIL, PUBLIC_ADDRESS_BLOCK, VALUE_TAIL, PAIR_BLOCK,
        PAD_128_TAIL, MGF_TAIL, LMS_SECRET_BLOCK, LMS_VALUE_BLOCK,
        LMS_LEAF_BLOCK, LMS_PARENT_FIRST, LMS_PARENT_LAST
    } fixed_t;

    // Only requests own contexts; completed results stay live until consumed.
    // P=1 reduces these banks and selectors to a single scalar execution slot.
    logic [PIPELINE-1:0] busy_slot, complete, need_block, scalar_slot, capture_enable, paired;
    logic [PIPELINE-1:0] final_compression;
    logic [PIPELINE-1:0] public_prefix_context;
    phase_t phase[0:PIPELINE-1];
    logic [3:0] shape[0:PIPELINE-1];
    logic [1:0] family[0:PIPELINE-1];
    logic [19:0] leaf[0:PIPELINE-1];
    logic [7:0] address_a[0:PIPELINE-1], seed_domain[0:PIPELINE-1], step_domain[0:PIPELINE-1];
    logic [31:0] address_b[0:PIPELINE-1];
    logic [4:0] iteration[0:PIPELINE-1], end_step[0:PIPELINE-1], capture_step[0:PIPELINE-1];
    wire [7:0] arity[0:PIPELINE-1];
    wire [5:0] output_bytes[0:PIPELINE-1];
    logic [7:0] scalar_arity;
    logic [5:0] scalar_output_bytes;
    logic [6:0] block_index[0:PIPELINE-1];
    logic [255:0] cv[0:PIPELINE-1], digest[0:PIPELINE-1], key_value[0:PIPELINE-1], captured[0:PIPELINE-1];
    logic [DIGEST_BYTES*8-1:0] scalar_result;
    // Scalar jobs drain all batch contexts before allocation. Their randomizer
    // remains live through HMAC/H_msg/MGF, independently of digest/key/capture.
    // Capture the executor's source selection once, outside the beat datapath.
    logic [N*8-1:0] scalar_randomizer;
    // Admission reserves a tag immediately, then allocates its banks from this
    // registered record. Executor-derived selection never reaches a result or
    // capture bank through the same clock path.
    typedef struct packed {
        logic scalar,no_seed,pair,capture,invalid;
        logic [TAG_BITS-1:0] tag;
        logic [3:0] shape;
        logic [1:0] family;
        logic [4:0] start,steps,capture_step;
        logic [255:0] value,right;
        logic [19:0] leaf;
        logic [7:0] address_a,seed_domain,step_domain,arity;
        logic [31:0] address_b;
        logic [5:0] output_bytes;
    } admission_t;
    admission_t admission;
    logic ingress_pending;
    logic [PIPELINE-1:0] allocation_pending;

    function automatic [255:0] reverse_bytes(input [255:0] data);
        for (integer k=0;k<32;k=k+1) reverse_bytes[k*8+:8]=data[255-k*8-:8];
    endfunction
    function automatic [31:0] be32(input [31:0] value);
        be32={value[7:0],value[15:8],value[23:16],value[31:24]};
    endfunction
    function automatic [63:0] be64(input [63:0] value);
        be64={be32(value[31:0]),be32(value[63:32])};
    endfunction
    function automatic [255:0] node_result(input [255:0] data,input [1:0] f);
        node_result = f==0 ? {128'd0,data[127:0]} : data;
    endfunction
    function automatic [12:0] input_length(input integer t);
        begin
            case (phase[t])
                KEY,MASK0,MASK1: input_length=96;
                FINAL: input_length=paired[t] ? 128 : 96;
                HMAC_IN: input_length=13'd80+13'(message_length);
                HMAC_OUT: input_length=96;
                HMSG_IN: input_length=13'd48+13'(message_length);
                MGF0,MGF1: input_length=68;
                default: begin
                    if (shape[t]==0 || phase[t]==SEED) begin
                        case(family[t])
                            0: input_length=102;
                            1: input_length=128;
                            default: input_length=55;
                        endcase
                    end else case(shape[t])
                        1: input_length=102;
                        2: input_length=paired[t] ? 118 : 102;
                        5: input_length=96;
                        6: input_length=13'd128+13'(message_length);
                        7: input_length=128;
                        9,10: input_length=55;
                        11: input_length=13'd54+13'(message_length);
                        12: input_length=13'd86+{1'b0,arity[t],4'd0};
                        13: input_length=13'd22+{arity[t],5'd0};
                        14: input_length=54;
                        15: input_length=86;
                        default: input_length=0;
                    endcase
                end
            endcase
        end
    endfunction
    function automatic [6:0] last_block(input integer t);
        last_block=7'((input_length(t)+13'd8)>>6);
    endfunction
    function automatic [31:0] effective_b(input integer t);
        effective_b = shape[t]==0 && phase[t]!=SEED && step_domain[t]!=3 ?
            {27'd0,iteration[t]} : address_b[t];
    endfunction
    function automatic [7:0] domain(input integer t);
        domain = phase[t]==SEED || shape[t]==1 || shape[t]==7 || shape[t]==9 ? seed_domain[t] : step_domain[t];
    endfunction
    // Decode small controls before the wide source mux. Every byte in a beat
    // shares these three 64-bit reads; no per-byte variable node shifters.
    typedef enum logic [4:0] {
        SLH_SEED, SLH_VALUE, SLH_LIST, XMSS_INDEX, XMSS_MESSAGE, XMSS_SEED,
        XMSS_PRF, XMSS_FINAL, LMS_SEED, LMS_CHAIN, LMS_MESSAGE, LMS_LIST,
        LMS_LEAF, LMS_PARENT, SLH_HMAC_IN, SLH_HMAC_OUT, SLH_HMSG, SLH_MGF0, SLH_MGF1
    } format_t;
    typedef enum logic [4:0] {
        SRC_ZERO, SRC_SECRET, SRC_PRF, SRC_PUBLIC, SRC_ROOT, SRC_RANDOM,
        SRC_VALUE, SRC_KEY, SRC_RIGHT, SRC_MESSAGE, SRC_ADDRESS, SRC_LIST0, SRC_LIST1,
        SRC_TWO, SRC_THREE, SRC_FOUR, SRC_PAIR, SRC_COUNTER,
        SRC_IPAD_KEY, SRC_OPAD_KEY, SRC_IPAD, SRC_OPAD
    } source_t;
    typedef enum logic [2:0] { ALIGNED, SHIFT_ONE, SHIFT_TWO, BRIDGE_SIX, BRIDGE_SEVEN } window_t;
    formatter_t formatter;
    format_t format_kind;
    fixed_t format_fixed;
    logic [TAG_BITS-1:0] format_tag;
    // The completed block may be accepted while the next descriptor is read.
    // Its tag is the only descriptor field that changes before that edge;
    // format_cv and the block words remain held until compression accepts.
    logic block_ready;
    logic [TAG_BITS-1:0] block_tag;
    logic [1:0] beat;
    wire [511:0] block_buffer;
    logic [255:0] format_address;
    // Address selection ends at small context fields. PREPARE performs only
    // byte wiring and format selection before BUILD reads the address words.
    typedef struct packed {
        logic [19:0] leaf;
        logic [7:0] address_a,domain_value;
        logic [31:0] address_b;
        logic [4:0] iteration;
        logic chain,seed_phase,tree_domain;
        logic [1:0] compound;
    } address_fields_t;
    address_fields_t address_fields;
    logic [255:0] format_cv;
    // One job uses either SLH's padded public seed or XMSS's domain-3 public
    // PRF prefix. Reuse one raw CV bank for both; a cold context computes it
    // on the existing lane while other eligible first blocks wait.
    logic public_prefix_valid,public_prefix_pending,public_prefix_described;
    logic public_prefix_xmss;
    logic [255:0] public_prefix_seed;
    logic [255:0] public_prefix_cv;
    logic [TAG_BITS-1:0] public_prefix_tag;
    wire [255:0] public_seed_key=256'(public_seed);
    wire public_prefix_match=public_prefix_valid &&
        public_prefix_xmss==(family[format_tag]==1) &&
        public_prefix_seed[127:0]==public_seed[127:0] &&
        (!public_prefix_xmss || public_prefix_seed[255:128]==public_seed_key[255:128]);
    wire describe_public_prefix=public_prefix_context[format_tag] &&
        block_index[format_tag]==0 && public_prefix_match;
    wire [6:0] describe_block=describe_public_prefix ? 7'd1 : block_index[format_tag];
    logic [12:0] format_length;
    logic [6:0] format_block;
    logic [INDEX_BITS-1:0] format_first_index;
    logic [8:0] word_control[0:2];
    logic [7:0] list_word_select[0:2],following_list_word_select[0:2];
    logic [INDEX_BITS-1:0] next_list_address,following_list_address;
    window_t window_control;
    logic [15:0] payload_mask, delimiter_mask;
    logic [63:0] list_words[0:2];
    logic list_words_valid;
    logic list_beat,following_list_beat;
    logic length_beat;
    wire [8:0] global_beat={format_block,beat};

    function automatic format_t selected_format(input integer t);
        begin
            case(phase[t])
                KEY,MASK0,MASK1: selected_format=XMSS_PRF;
                FINAL: selected_format=XMSS_FINAL;
                HMAC_IN: selected_format=SLH_HMAC_IN;
                HMAC_OUT: selected_format=SLH_HMAC_OUT;
                HMSG_IN: selected_format=SLH_HMSG;
                MGF0: selected_format=SLH_MGF0;
                MGF1: selected_format=SLH_MGF1;
                default: case(shape[t])
                    0: case(family[t])
                        0: selected_format=phase[t]==SEED ? SLH_SEED : SLH_VALUE;
                        1: selected_format=XMSS_SEED;
                        default: selected_format=phase[t]==SEED ? LMS_SEED : LMS_CHAIN;
                    endcase
                    1: selected_format=SLH_SEED;
                    2: selected_format=SLH_VALUE;
                    3: selected_format=SLH_HMAC_IN;
                    4: selected_format=SLH_HMSG;
                    5: selected_format=XMSS_INDEX;
                    6: selected_format=XMSS_MESSAGE;
                    7: selected_format=XMSS_SEED;
                    8: selected_format=XMSS_FINAL;
                    9: selected_format=LMS_SEED;
                    10: selected_format=LMS_CHAIN;
                    11: selected_format=LMS_MESSAGE;
                    12: selected_format=SLH_LIST;
                    13: selected_format=LMS_LIST;
                    14: selected_format=LMS_LEAF;
                    default: selected_format=LMS_PARENT;
                endcase
            endcase
        end
    endfunction
    // These frames have constant byte positions. Decode their layout beside
    // the descriptor, then write the existing block store in one clock. Only
    // registered context fields feed this assembly; streaming keeps its
    // separate address, source-selection and byte-alignment stages.
    function automatic fixed_t fixed_format(input format_t kind,input [6:0] block_number,
        input pair,input chain);
        begin
            fixed_format=FIXED_NONE;
            case(kind)
                SLH_SEED: if(block_number==1) fixed_format=SLH_SECRET_TAIL;
                SLH_VALUE: if(block_number==1)
                    fixed_format=pair && !chain ? SLH_PAIR_TAIL : SLH_VALUE_TAIL;
                XMSS_INDEX,XMSS_PRF: if(block_number==1) fixed_format=ADDRESS_TAIL;
                XMSS_SEED: begin
                    if(block_number==1) fixed_format=PUBLIC_ADDRESS_BLOCK;
                    else if(block_number==2) fixed_format=PAD_128_TAIL;
                end
                XMSS_FINAL: begin
                    if(block_number==1) fixed_format=pair ? PAIR_BLOCK : VALUE_TAIL;
                    else if(block_number==2) fixed_format=PAD_128_TAIL;
                end
                SLH_HMAC_OUT: if(block_number==1) fixed_format=VALUE_TAIL;
                SLH_MGF0,SLH_MGF1: if(block_number==1) fixed_format=MGF_TAIL;
                LMS_SEED: if(block_number==0) fixed_format=LMS_SECRET_BLOCK;
                LMS_CHAIN: if(block_number==0) fixed_format=LMS_VALUE_BLOCK;
                LMS_LEAF: if(block_number==0) fixed_format=LMS_LEAF_BLOCK;
                LMS_PARENT: begin
                    if(block_number==0) fixed_format=LMS_PARENT_FIRST;
                    else if(block_number==1) fixed_format=LMS_PARENT_LAST;
                end
                default: begin end
            endcase
        end
    endfunction
    function automatic [255:0] packed_address(input integer t,input format_t kind);
        reg [31:0] compound;
        reg [7:0] chain_step;
        reg [15:0] separator;
        begin
            compound=phase[t]==MASK0 ? 32'd1 : phase[t]==MASK1 ? 32'd2 : 32'd0;
            chain_step=kind==LMS_SEED ? 8'hff : shape[t]==0 ? {3'd0,iteration[t]} : address_b[t][7:0];
            separator=kind==LMS_MESSAGE ? 16'h8181 : kind==LMS_LIST ? 16'h8080 :
                kind==LMS_LEAF ? 16'h8282 : 16'h8383;
            case(kind)
                SLH_SEED,SLH_VALUE,SLH_LIST: packed_address={80'd0,
                    be32(effective_b(t)),be32({24'd0,address_a[t]}),be32({12'd0,leaf[t]}),
                    domain(t),be64(request_tree),3'd0,request_layer};
                XMSS_INDEX,XMSS_MESSAGE: packed_address={be32({12'd0,leaf[t]}),224'd0};
                XMSS_SEED,XMSS_PRF: packed_address={be32(compound),be32(effective_b(t)),
                    be32({24'd0,address_a[t]}),be32({12'd0,leaf[t]}),be32({24'd0,domain(t)}),96'd0};
                LMS_SEED,LMS_CHAIN: packed_address={72'd0,chain_step,address_a[t],8'd0,be32({12'd0,leaf[t]}),identifier};
                LMS_MESSAGE,LMS_LIST,LMS_LEAF,LMS_PARENT: packed_address={80'd0,separator,
                    be32(kind==LMS_LEAF || kind==LMS_PARENT ? address_b[t] : {12'd0,leaf[t]}),identifier};
                default: packed_address=0;
            endcase
        end
    endfunction
    function automatic [255:0] staged_address(input address_fields_t fields,input format_t kind);
        reg [31:0] chain_b;
        reg [7:0] chain_step;
        reg [15:0] separator;
        begin
            chain_b=fields.chain && !fields.seed_phase && !fields.tree_domain ?
                {27'd0,fields.iteration} : fields.address_b;
            chain_step=kind==LMS_SEED ? 8'hff : fields.chain ?
                {3'd0,fields.iteration} : fields.address_b[7:0];
            separator=kind==LMS_MESSAGE ? 16'h8181 : kind==LMS_LIST ? 16'h8080 :
                kind==LMS_LEAF ? 16'h8282 : 16'h8383;
            case(kind)
                SLH_SEED,SLH_VALUE,SLH_LIST: staged_address={80'd0,
                    be32(chain_b),be32({24'd0,fields.address_a}),be32({12'd0,fields.leaf}),
                    fields.domain_value,be64(request_tree),3'd0,request_layer};
                XMSS_INDEX,XMSS_MESSAGE: staged_address={be32({12'd0,fields.leaf}),224'd0};
                XMSS_SEED,XMSS_PRF: staged_address={be32({30'd0,fields.compound}),be32(chain_b),
                    be32({24'd0,fields.address_a}),be32({12'd0,fields.leaf}),
                    be32({24'd0,fields.domain_value}),96'd0};
                LMS_SEED,LMS_CHAIN: staged_address={72'd0,chain_step,fields.address_a,
                    8'd0,be32({12'd0,fields.leaf}),identifier};
                LMS_MESSAGE,LMS_LIST,LMS_LEAF,LMS_PARENT: staged_address={80'd0,separator,
                    be32(kind==LMS_LEAF || kind==LMS_PARENT ? fields.address_b :
                        {12'd0,fields.leaf}),identifier};
                default: staged_address=0;
            endcase
        end
    endfunction
    function automatic [8:0] control(input source_t source,input [3:0] word_index);
        control={source,word_index};
    endfunction
    function automatic [8:0] payload_control(input format_t kind,input [9:0] word_index);
        begin
            payload_control=control(SRC_ZERO,0);
            case(kind)
                SLH_SEED: if(word_index<2) payload_control=control(SRC_SECRET,word_index[3:0]);
                SLH_VALUE: begin
                    if(word_index<2) payload_control=control(SRC_VALUE,word_index[3:0]);
                    else if(word_index<4) payload_control=control(SRC_RIGHT,4'(word_index-10'd2));
                end
                LMS_SEED: if(word_index<4) payload_control=control(SRC_SECRET,word_index[3:0]);
                LMS_CHAIN,LMS_LEAF: if(word_index<4) payload_control=control(SRC_VALUE,word_index[3:0]);
                LMS_PARENT: begin
                    if(word_index<4) payload_control=control(SRC_VALUE,word_index[3:0]);
                    else if(word_index<8) payload_control=control(SRC_RIGHT,4'(word_index-10'd4));
                end
                LMS_MESSAGE: begin
                    if(word_index<4) payload_control=control(SRC_RANDOM,word_index[3:0]);
                    else if(word_index<15) payload_control=control(SRC_MESSAGE,4'(word_index-10'd4));
                end
                // List word_index is relative to the registered endpoint pair.
                SLH_LIST: begin
                    if(word_index<2) payload_control=control(SRC_LIST0,word_index[3:0]);
                    else payload_control=control(SRC_LIST1,4'(word_index-10'd2));
                end
                LMS_LIST: begin
                    if(word_index<4) payload_control=control(SRC_LIST0,word_index[3:0]);
                    else payload_control=control(SRC_LIST1,4'(word_index-10'd4));
                end
                default: payload_control=control(SRC_ZERO,0);
            endcase
        end
    endfunction
    function automatic [8:0] aligned_control(input format_t kind,input [9:0] w);
        begin
            aligned_control=control(SRC_ZERO,0);
            case(kind)
                SLH_SEED,SLH_VALUE,SLH_LIST: begin
                    if(w<2) aligned_control=control(SRC_PUBLIC,w[3:0]);
                    else if(w>=8 && w<10) aligned_control=control(SRC_ADDRESS,4'(w-10'd8));
                end
                LMS_SEED,LMS_CHAIN,LMS_MESSAGE,LMS_LIST,LMS_LEAF,LMS_PARENT:
                    if(w<2) aligned_control=control(SRC_ADDRESS,w[3:0]);
                XMSS_INDEX,XMSS_MESSAGE,XMSS_SEED,XMSS_PRF,XMSS_FINAL: begin
                    if(w==3) aligned_control=control(kind==XMSS_MESSAGE ? SRC_TWO :
                        kind==XMSS_SEED ? SRC_FOUR : kind==XMSS_FINAL ? SRC_PAIR : SRC_THREE,0);
                    else if(w>=4 && w<8) aligned_control=control(
                        kind==XMSS_INDEX ? SRC_PRF : kind==XMSS_MESSAGE ? SRC_RANDOM :
                        kind==XMSS_SEED ? SRC_SECRET : kind==XMSS_FINAL ? SRC_KEY : SRC_PUBLIC,4'(w-10'd4));
                    else if(w>=8 && w<12) aligned_control=control(
                        kind==XMSS_MESSAGE ? SRC_ROOT : kind==XMSS_SEED ? SRC_PUBLIC :
                        kind==XMSS_FINAL ? SRC_VALUE : SRC_ADDRESS,4'(w-10'd8));
                    else if(w>=12 && w<16 && (kind==XMSS_MESSAGE || kind==XMSS_SEED || kind==XMSS_FINAL))
                        aligned_control=control(kind==XMSS_FINAL ? SRC_RIGHT : SRC_ADDRESS,4'(w-10'd12));
                    else if(w>=16 && w<27 && kind==XMSS_MESSAGE)
                        aligned_control=control(SRC_MESSAGE,4'(w-10'd16));
                end
                SLH_HMAC_IN,SLH_HMAC_OUT: begin
                    if(w<2) aligned_control=control(kind==SLH_HMAC_IN ? SRC_IPAD_KEY : SRC_OPAD_KEY,w[3:0]);
                    else if(w<8) aligned_control=control(kind==SLH_HMAC_IN ? SRC_IPAD : SRC_OPAD,0);
                    else if(w<10 && kind==SLH_HMAC_IN) aligned_control=control(SRC_RANDOM,4'(w-10'd8));
                    else if(w<12 && kind==SLH_HMAC_OUT) aligned_control=control(SRC_VALUE,4'(w-10'd8));
                    else if(w>=10 && w<21 && kind==SLH_HMAC_IN) aligned_control=control(SRC_MESSAGE,4'(w-10'd10));
                end
                SLH_HMSG: begin
                    if(w<2) aligned_control=control(SRC_RANDOM,w[3:0]);
                    else if(w<4) aligned_control=control(SRC_PUBLIC,4'(w-10'd2));
                    else if(w<6) aligned_control=control(SRC_ROOT,4'(w-10'd4));
                    else if(w<17) aligned_control=control(SRC_MESSAGE,4'(w-10'd6));
                end
                SLH_MGF0,SLH_MGF1: begin
                    if(w<2) aligned_control=control(SRC_RANDOM,w[3:0]);
                    else if(w<4) aligned_control=control(SRC_PUBLIC,4'(w-10'd2));
                    else if(w<8) aligned_control=control(SRC_KEY,4'(w-10'd4));
                    else if(w==8 && kind==SLH_MGF1) aligned_control=control(SRC_COUNTER,0);
                end
                default: aligned_control=control(SRC_ZERO,0);
            endcase
        end
    endfunction
    function automatic [8:0] beat_word_control(input format_t kind,input [8:0] pos,input integer k);
        reg slh_prefix,lms_prefix,unaligned;
        reg [9:0] first_word;
        begin
            slh_prefix=kind==SLH_SEED || kind==SLH_VALUE || kind==SLH_LIST;
            lms_prefix=kind==LMS_SEED || kind==LMS_CHAIN || kind==LMS_MESSAGE ||
                kind==LMS_LIST || kind==LMS_LEAF || kind==LMS_PARENT;
            unaligned=(slh_prefix && pos>=5) || (lms_prefix && pos>=1);
            first_word={pos,1'b0};
            if(unaligned && ((slh_prefix && pos==5) || (lms_prefix && pos==1))) begin
                beat_word_control=k==0 ? control(SRC_ADDRESS,4'd2) : payload_control(kind,10'(k-1));
            end else if(unaligned) begin
                if(kind==SLH_LIST) first_word=10'd1;
                else if(kind==LMS_LIST) first_word=pos[0] ? 10'd3 : 10'd1;
                else first_word=first_word-(slh_prefix ? 10'd11 : 10'd3);
                beat_word_control=payload_control(kind,first_word+10'(k));
            end else beat_word_control=aligned_control(kind,first_word+10'(k));
        end
    endfunction
    function automatic [7:0] list_select(input [8:0] selected);
        case(source_t'(selected[8:4]))
            SRC_LIST0: list_select=8'b00000001<<selected[1:0];
            SRC_LIST1: list_select=8'b00010000<<selected[1:0];
            default: list_select=0;
        endcase
    endfunction
    function automatic logic contains_list(input format_t kind,input [8:0] pos);
        reg [8:0] selected;
        begin
            contains_list=0;
            for(integer k=0;k<3;k=k+1) begin
                selected=beat_word_control(kind,pos,k);
                contains_list=contains_list || selected[8:4]==SRC_LIST0 || selected[8:4]==SRC_LIST1;
            end
        end
    endfunction
    // Register current and following word selections together. Endpoint words
    // for the following beat can then be fetched while the current beat enters
    // source_window; neither RAM selection nor byte alignment loses a stage.
    task automatic prepare_beat(input format_t kind,input [8:0] pos,input [12:0] length);
        reg slh_prefix,lms_prefix,unaligned;
        begin
            slh_prefix=kind==SLH_SEED || kind==SLH_VALUE || kind==SLH_LIST;
            lms_prefix=kind==LMS_SEED || kind==LMS_CHAIN || kind==LMS_MESSAGE ||
                kind==LMS_LIST || kind==LMS_LEAF || kind==LMS_PARENT;
            unaligned=(slh_prefix && pos>=5) || (lms_prefix && pos>=1);
            window_control<=ALIGNED;
            if(unaligned && ((slh_prefix && pos==5) || (lms_prefix && pos==1)))
                window_control<=kind==LMS_SEED || kind==LMS_CHAIN ? BRIDGE_SEVEN : BRIDGE_SIX;
            else if(unaligned)
                window_control<=kind==LMS_SEED || kind==LMS_CHAIN ? SHIFT_ONE : SHIFT_TWO;
            for(integer k=0;k<3;k=k+1) begin
                word_control[k]<=beat_word_control(kind,pos,k);
                list_word_select[k]<=list_select(beat_word_control(kind,pos,k));
                following_list_word_select[k]<=list_select(beat_word_control(kind,pos+9'd1,k));
            end
            list_beat<=contains_list(kind,pos);
            following_list_beat<=contains_list(kind,pos+9'd1);
            next_list_address<=list_address(kind,pos+9'd1);
            following_list_address<=list_address(kind,pos+9'd2);
            for(integer k=0;k<16;k=k+1) begin
                payload_mask[k]<=pos<length[12:4] || (pos==length[12:4] && 4'(k)<length[3:0]);
                delimiter_mask[k]<=pos==length[12:4] && 4'(k)==length[3:0];
            end
            length_beat<=pos=={7'((length+13'd8)>>6),2'b11};
        end
    endtask
    function automatic [63:0] node_word(input [255:0] value,input [1:0] index);
        case(index)
            0: node_word=value[63:0];
            1: node_word=value[127:64];
            2: node_word=value[191:128];
            default: node_word=value[255:192];
        endcase
    endfunction
    wire [703:0] padded_message=704'(message_buffer);
    function automatic [63:0] source_word(input [8:0] selected,input [63:0] fetched_list_word);
        reg [255:0] value;
        reg [63:0] literal;
        begin
            // Fixed-only sources are assembled by prefix_data/fixed_data;
            // message/list beats need no secret, digest or capture-bank mux.
            value=0; literal=0;
            case(source_t'(selected[8:4]))
                SRC_PUBLIC: value=256'(public_seed);
                SRC_ROOT: value=256'(root);
                SRC_RANDOM: value=256'(scalar_randomizer);
                SRC_ADDRESS: value=format_address;
                SRC_LIST0,SRC_LIST1: literal=fetched_list_word;
                SRC_MESSAGE: literal=selected[3:0]<11 ? padded_message[selected[3:0]*64+:64] : 64'd0;
                default: value=0;
            endcase
            source_word=node_word(value,selected[1:0]) ^ literal;
        end
    endfunction
    wire [191:0] selected_window={source_word(word_control[2],list_words[2]),source_word(word_control[1],list_words[1]),source_word(word_control[0],list_words[0])};
    // Context/word selection and byte alignment occupy separate clock stages.
    // This is one beat of storage, not a duplicate bank of context nodes.
    // Non-list beats continue to enter the stage on consecutive clocks.
    logic [191:0] source_window;
    window_t staged_window;
    logic [15:0] staged_payload_mask,staged_delimiter_mask;
    logic staged_length_beat,beat_pending;
    logic [1:0] staged_beat;
    logic [127:0] payload,formatted_beat;
    wire [63:0] encoded_length=be64({48'd0,format_length,3'd0});
    always_comb begin
        case(staged_window)
            SHIFT_ONE: payload=source_window[135:8];
            SHIFT_TWO: payload=source_window[143:16];
            BRIDGE_SIX: payload={source_window[143:64],source_window[47:0]};
            BRIDGE_SEVEN: payload={source_window[135:64],source_window[55:0]};
            default: payload=source_window[127:0];
        endcase
        if(staged_length_beat) payload[127:64]=encoded_length;
        for(integer k=0;k<16;k=k+1)
            formatted_beat[127-k*8-:8]=(staged_length_beat && k>=8) ? payload[k*8+:8] :
                staged_payload_mask[k] ? payload[k*8+:8] : staged_delimiter_mask[k] ? 8'h80 : 8'd0;
    end
    function automatic [INDEX_BITS-1:0] list_address(input format_t kind,input [8:0] pos);
        case(kind)
            SLH_LIST: list_address=pos>=6 ? INDEX_BITS'(pos-9'd6) : INDEX_BITS'(0);
            LMS_LIST: list_address=pos>=2 ? INDEX_BITS'((pos-9'd2)>>1) : INDEX_BITS'(0);
            default: list_address=0;
        endcase
    endfunction
    // Combinational endpoint adapters follow the beat being fetched, which
    // can be one beat ahead of the retained words entering source_window.
    assign list_index0=list_address(format_kind,global_beat+
        ((formatter==BUILD && (!list_beat || list_words_valid)) ? 9'd1 : 9'd0));
    assign list_index1=list_index0+1'b1;
    function automatic [INDEX_BITS-1:0] first_list_address(input [3:0] recipe_shape,input [6:0] block_number);
        // List recipes remain in DIRECT for their entire multi-block hash.
        // Prefetch therefore needs the recipe shape, not the full phase/family
        // formatter decoder behind the round-robin selection.
        case(recipe_shape)
            12: first_list_address=block_number>=2 ? INDEX_BITS'({block_number,2'b00}-9'd6) : INDEX_BITS'(0);
            13: first_list_address=block_number!=0 ? INDEX_BITS'({block_number,1'b0}-8'd1) : INDEX_BITS'(0);
            default: first_list_address=0;
        endcase
    endfunction
    // The endpoint workspace registers this address in PREPARE, one clock
    // before BUILD can fetch its first list words. Context selection and the
    // first-index arithmetic terminate at this local descriptor register.
    wire source_beat_ready=!list_beat || list_words_valid;
    assign list_next_index0=formatter==PREPARE ? format_first_index :
        formatter==BUILD ? (source_beat_ready ? following_list_address : next_list_address) :
        list_address(format_kind,global_beat);
    // Decode before the asynchronous endpoint read. Each retained 64-bit word
    // has one shared one-hot selector, so endpoint data crosses only AND/OR
    // selection rather than two current/following node-word muxes.
    wire [511:0] endpoint_pair={256'(list_data1),256'(list_data0)};
    wire [63:0] fetched_list_word[0:2];
    for(genvar word_index=0;word_index<3;word_index=word_index+1) begin : list_fetch
        wire [7:0] selected=source_beat_ready ? following_list_word_select[word_index] : list_word_select[word_index];
        logic [63:0] data;
        always_comb begin
            data=0;
            for(integer k=0;k<8;k=k+1)
                data=data | (endpoint_pair[k*64+:64] & {64{selected[k]}});
        end
        assign fetched_list_word[word_index]=data;
    end
    function automatic logic prefix_block(input format_t kind);
        case(kind)
            SLH_SEED,SLH_VALUE,SLH_LIST,XMSS_INDEX,XMSS_MESSAGE,
            XMSS_SEED,XMSS_PRF,XMSS_FINAL,SLH_HMAC_IN,SLH_HMAC_OUT,
            SLH_MGF0,SLH_MGF1: prefix_block=1'b1;
            default: prefix_block=1'b0;
        endcase
    endfunction
    function automatic [511:0] prefix_data(input integer t,input format_t kind);
        reg [255:0] public_bytes,random_bytes,prf_bytes;
        begin
            public_bytes=reverse_bytes(256'(public_seed));
            random_bytes=reverse_bytes(256'(scalar_randomizer));
            prf_bytes=reverse_bytes(256'(secret_prf));
            case(kind)
                SLH_SEED,SLH_VALUE,SLH_LIST: prefix_data={public_bytes[255:128],384'd0};
                XMSS_INDEX: prefix_data={256'd3,prf_bytes};
                XMSS_MESSAGE: prefix_data={256'd2,random_bytes};
                XMSS_SEED: prefix_data={256'd4,reverse_bytes(256'(secret_seed))};
                XMSS_PRF: prefix_data={256'd3,public_bytes};
                XMSS_FINAL: prefix_data={255'd0,paired[t],reverse_bytes(key_value[t])};
                SLH_HMAC_IN: prefix_data={prf_bytes[255:128]^{16{8'h36}},{48{8'h36}}};
                SLH_HMAC_OUT: prefix_data={prf_bytes[255:128]^{16{8'h5c}},{48{8'h5c}}};
                SLH_MGF0,SLH_MGF1: prefix_data={random_bytes[255:128],public_bytes[255:128],reverse_bytes(key_value[t])};
                default: prefix_data=0;
            endcase
        end
    endfunction
    function automatic [511:0] fixed_data(input integer t,input fixed_t kind,input [255:0] address);
        reg [255:0] address_bytes,value_bytes,right_bytes,secret_bytes,public_bytes;
        begin
            address_bytes=reverse_bytes(address);
            value_bytes=reverse_bytes(digest[t]);
            right_bytes=reverse_bytes(captured[t]);
            secret_bytes=reverse_bytes(256'(secret_seed));
            public_bytes=reverse_bytes(256'(public_seed));
            case(kind)
                SLH_SECRET_TAIL: fixed_data={address_bytes[255:80],secret_bytes[255:128],
                    8'h80,136'd0,64'd816};
                SLH_VALUE_TAIL: fixed_data={address_bytes[255:80],value_bytes[255:128],
                    8'h80,136'd0,64'd816};
                SLH_PAIR_TAIL: fixed_data={address_bytes[255:80],value_bytes[255:128],
                    right_bytes[255:128],8'h80,8'd0,64'd944};
                ADDRESS_TAIL: fixed_data={address_bytes,8'h80,184'd0,64'd768};
                PUBLIC_ADDRESS_BLOCK: fixed_data={public_bytes,address_bytes};
                VALUE_TAIL: fixed_data={value_bytes,8'h80,184'd0,64'd768};
                PAIR_BLOCK: fixed_data={value_bytes,right_bytes};
                PAD_128_TAIL: fixed_data={8'h80,440'd0,64'd1024};
                MGF_TAIL: fixed_data={31'd0,format_kind==SLH_MGF1,8'h80,408'd0,64'd544};
                LMS_SECRET_BLOCK: fixed_data={address_bytes[255:72],secret_bytes,8'h80,64'd440};
                LMS_VALUE_BLOCK: fixed_data={address_bytes[255:72],value_bytes,8'h80,64'd440};
                LMS_LEAF_BLOCK: fixed_data={address_bytes[255:80],value_bytes,8'h80,8'd0,64'd432};
                LMS_PARENT_FIRST: fixed_data={address_bytes[255:80],value_bytes,right_bytes[255:176]};
                LMS_PARENT_LAST: fixed_data={right_bytes[175:0],8'h80,264'd0,64'd688};
                default: fixed_data=0;
            endcase
        end
    endfunction
    task automatic reserve_block(input integer t);
        begin
            // Round-robin arbitration ends at the tag register. Context reads,
            // descriptor decoding and first-block data do not share this path.
            format_tag<=TAG_BITS'(t); formatter<=DESCRIBE;
            schedule_cursor<=t==PIPELINE-1 ? TAG_BITS'(0) : TAG_BITS'(t+1);
        end
    endtask

    logic candidate_valid;
    logic [TAG_BITS-1:0] candidate;
    logic [TAG_BITS-1:0] schedule_cursor;
    logic upper_valid, lower_valid;
    logic [TAG_BITS-1:0] upper_candidate, lower_candidate;
    wire write_prefix=formatter==PREPARE && format_block==0 && prefix_block(format_kind);
    wire public_prefix_launch=formatter==PREPARE && public_prefix_described;
    // Include this cycle's launch: PREPARE can reserve the next descriptor
    // before the pending bit is registered. It must not launch a second cold
    // prefix while the first compression is in flight.
    wire public_prefix_wait=public_prefix_pending || public_prefix_described;
    wire [PIPELINE-1:0] schedulable;
    for(genvar slot=0;slot<PIPELINE;slot=slot+1) begin : prefix_schedule
        assign schedulable[slot]=need_block[slot] &&
            !(public_prefix_wait && public_prefix_context[slot] && block_index[slot]==0);
    end
    always_comb begin
        upper_valid=0; lower_valid=0; upper_candidate=0; lower_candidate=0;
        // Read each request bit at a constant index. Two priority encoders
        // replace cursor addition/modulo and a variable request-bit mux in
        // every scan entry, while retaining the same round-robin order.
        for(integer k=0;k<PIPELINE;k=k+1) begin
            if(!upper_valid && schedulable[k] && TAG_BITS'(k)>=schedule_cursor) begin
                upper_valid=1; upper_candidate=TAG_BITS'(k);
            end
            if(!lower_valid && schedulable[k]) begin
                lower_valid=1; lower_candidate=TAG_BITS'(k);
            end
        end
        candidate_valid=upper_valid || lower_valid;
        candidate=upper_valid ? upper_candidate : lower_candidate;
    end
    wire write_beat=beat_pending;
    wire write_fixed=formatter==PREPARE && format_fixed!=FIXED_NONE;
    wire [511:0] prepared_prefix=prefix_data(int'(format_tag),format_kind);
    wire [511:0] prepared_fixed=fixed_data(int'(format_tag),format_fixed,
        staged_address(address_fields,format_kind));
    // The last fixed chain block is also the next step's frame template.
    // Only its domain/step and digest change. Retain narrow lookahead control
    // while compression runs; any normal block write replaces this owner.
    logic replay_valid,replay_slh,replay_tree_domain;
    logic [TAG_BITS-1:0] replay_tag;
    logic [4:0] replay_step,replay_end;
    logic [7:0] replay_domain;
    wire [PIPELINE-1:0] replay_possible;
    wire [4:0] replay_following=replay_step+5'd1;
    wire replay_more=replay_following<replay_end;
    wire replay_take;
    wire [31:0] replay_b=replay_tree_domain ? block_buffer[367:336] : {27'd0,replay_step};
    wire [511:0] replay_block=replay_slh ?
        {block_buffer[511:440],replay_domain,block_buffer[431:368],replay_b,
         compression_cv[255:128],block_buffer[207:0]} :
        {block_buffer[511:336],3'd0,replay_step,compression_cv,block_buffer[71:0]};
    always_ff @(posedge clk) begin : replay_lookahead
        if(rst) begin
            replay_valid<=0; replay_tag<=0;
        end else begin
            if(write_prefix || write_fixed || write_beat) replay_valid<=0;
            if(write_fixed) begin
                replay_valid<=replay_possible[format_tag];
                replay_tag<=format_tag;
                replay_slh<=family[format_tag]==0;
                replay_step<=phase[format_tag]==SEED ? 5'd0 : iteration[format_tag]+5'd1;
                replay_end<=end_step[format_tag];
                replay_domain<=step_domain[format_tag];
                replay_tree_domain<=step_domain[format_tag]==3;
            end
            if(replay_take) begin
                replay_valid<=replay_more;
                replay_step<=replay_following;
            end
        end
    end
    // Constant word addresses let each 128-bit bank own its write enable.
    // Mixing a full prefix write with a dynamic part-select update would
    // create a much wider update/retention mux around this same 512-bit store.
    for(genvar word_index=0;word_index<4;word_index=word_index+1) begin : block_words
        logic [127:0] data;
        assign block_buffer[511-word_index*128-:128]=data;
        always_ff @(posedge clk)
            if(!rst && (write_prefix || write_fixed || (write_beat && staged_beat==2'(word_index))))
                data<=write_prefix ? prepared_prefix[511-word_index*128-:128] :
                    write_fixed ? prepared_fixed[511-word_index*128-:128] : formatted_beat;
    end
    wire compression_ready, compression_valid;
    wire [255:0] compression_cv;
    wire [TAG_BITS-1:0] compression_tag;
    // compression_cv is the registered feed-forward output. Replaying its
    // digest directly into the next block preserves that register boundary.
    // The retained template owns the same CV/tag; only digest/step bits mux.
    // Registered block ownership selects data independently of the late
    // replay handshake: without a queued block, only replay can be valid.
    // Keep recipe publication control outside the compression datapath during
    // synthesis; this boundary adds no state, latency or hardware interface.
    (* keep_hierarchy = "yes" *)
    sha256 #(.PIPELINE(PIPELINE),.UNROLL(UNROLL),.TAG_BITS(TAG_BITS)) compression (
        .clk,.rst,.input_valid(block_ready || replay_take),.input_ready(compression_ready),
        .input_cv(format_cv),.input_block(block_ready ? block_buffer : replay_block),.input_tag(block_tag),
        .output_valid(compression_valid),.output_ready(1'b1),.output_cv(compression_cv),.output_tag(compression_tag)
    );
    wire compression_complete_event=compression_valid && !rst;
    // Completion metadata travels with the outstanding block. Avoid decoding
    // phase, message length and arity again behind the compression return tag.
    wire [PIPELINE-1:0] return_hit,return_final,return_restart,return_schedulable;
    assign replay_take=!rst && compression_complete_event && replay_valid && compression_tag==replay_tag &&
        formatter==SELECT && !candidate_valid && !block_ready && !beat_pending && compression_ready;
    // A returned block already identifies its next owner. When no queued
    // request exists, reserve that owner's descriptor on the return edge;
    // its digest/phase updates become visible before DESCRIBE reads them.
    // Arbitration and the block register still separate return from SHA256.
    wire reserve_return=formatter==SELECT && !candidate_valid && !block_ready && |return_schedulable && !replay_take;
    logic scalar_clear_pending,scalar_upper_pending;
    wire scalar_clear_event=return_final[0] && scalar_slot[0] && scalar_clear_pending;
    wire scalar_upper_event=return_final[0] && scalar_slot[0] && scalar_upper_pending;
    wire [DIGEST_BYTES-1:0] scalar_write_mask;
    wire hash_complete_event=|return_final;
    wire [255:0] returned=reverse_bytes(compression_cv);

    always_ff @(posedge clk) begin : public_prefix_cache
        if(rst) begin
            public_prefix_valid<=0;
            public_prefix_pending<=0;
            public_prefix_tag<=0;
        end else begin
            if(public_prefix_launch) begin
                public_prefix_valid<=0;
                public_prefix_pending<=1;
                public_prefix_tag<=format_tag;
                public_prefix_seed<=public_seed_key;
                public_prefix_xmss<=family[format_tag]==1;
            end
            if(public_prefix_pending && compression_complete_event && compression_tag==public_prefix_tag) begin
                public_prefix_cv<=compression_cv;
                public_prefix_valid<=1;
                public_prefix_pending<=0;
            end
        end
    end

    logic response_held;
    logic [TAG_BITS-1:0] held_tag, completed_tag;
    logic completed_valid;
    always_comb begin
        completed_tag=0; completed_valid=0;
        for(integer k=0;k<PIPELINE;k=k+1)
            if(!completed_valid && complete[k] && !scalar_slot[k] &&
                (!response_held || held_tag!=TAG_BITS'(k))) begin
                completed_valid=1; completed_tag=TAG_BITS'(k);
            end
    end
    assign batch_response_valid=response_held;
    assign batch_response_tag=held_tag;
    assign batch_response_digest=digest[held_tag];
    assign batch_response_capture=captured[held_tag];
    assign batch_read_digest=digest[batch_read_tag];
    assign batch_read_capture=captured[batch_read_tag];
    assign response_valid=complete[0] && scalar_slot[0];
    assign response_value=scalar_result;
    assign response_capture=captured[0][N*8-1:0];
    assign request_ready=!rst && !ingress_pending && !batch_mode && busy_slot==0;
    assign batch_request_ready=!rst && !ingress_pending && batch_mode && int'(batch_request_tag)<PIPELINE &&
        (!busy_slot[batch_request_tag] || (batch_response_valid && batch_response_ready && held_tag==batch_request_tag));
    wire scalar_accept=request_valid && request_ready;
    wire batch_accept=batch_request_valid && batch_request_ready;
    wire accept=scalar_accept || batch_accept;
    // Admission data is sampled only on accept. Select it with the job mode,
    // independently of the busy/ready reduction in the handshake enable.
    wire scalar_input=!batch_mode;
    wire [TAG_BITS-1:0] incoming_tag=scalar_input ? TAG_BITS'(0) : batch_request_tag;
    wire [3:0] incoming_shape=scalar_input ? (request_chain ? 4'd0 : request_recipe[59:56]) : batch_fixed_shape;
    wire [3:0] scalar_shape=request_recipe[59:56];
    wire [1:0] incoming_family=scalar_input ?
        ((scalar_shape<=4 || scalar_shape==12) ? 2'd0 :
         (scalar_shape==5 || scalar_shape==6 || scalar_shape==7 || scalar_shape==8) ? 2'd1 : 2'd2) : batch_family;
    wire incoming_no_seed=scalar_input ?
        !(request_chain && (scalar_shape==1 || scalar_shape==7 || scalar_shape==9)) : batch_no_seed;
    wire [4:0] incoming_start=scalar_input ? 5'd0 : {1'b0,batch_start};
    wire [4:0] incoming_steps=scalar_input ? (request_chain ? request_steps : 5'd0) : batch_steps;
    wire [4:0] incoming_capture_step=scalar_input ? request_capture_after : batch_capture_after;
    wire incoming_capture=scalar_input ? request_capture : batch_capture_enable;
    wire [255:0] incoming_value=scalar_input ? 256'(request_left) : batch_initial_value;
    wire incoming_pair=scalar_input ? request_recipe[47:40]==2 : batch_pair;
    function automatic phase_t initial_phase(input [3:0] s,input [1:0] f,input no_seed);
        case(s)
            0: initial_phase=!no_seed ? SEED : f==1 ? KEY : DIRECT;
            3: initial_phase=HMAC_IN;
            4: initial_phase=HMSG_IN;
            8: initial_phase=KEY;
            default: initial_phase=DIRECT;
        endcase
    endfunction
    function automatic logic cached_public_phase(input [1:0] f,input [3:0] s,input phase_t p);
        cached_public_phase=f==0 ? (s==0 || s==1 || s==2 || s==12) :
            f==1 && (p==KEY || p==MASK0 || p==MASK1);
    endfunction

    // Return decode ends at a one-hot bank event. All phase/length/capture
    // decisions below read a constant slot, independently of the return tag.
    wire reserve_format=candidate_valid &&
        (formatter==SELECT || (formatter==PREPARE && write_prefix) || write_fixed || formatter==DRAIN);
    // Batch requests always carry one node and a family-sized result. Only
    // scalar tag zero owns variable list arity and digest length.
    always_ff @(posedge clk) begin
        if(rst) begin scalar_arity<=0; scalar_output_bytes<=0; end
        else if(allocation_pending[0] && admission.scalar) begin
            scalar_arity<=admission.arity;
            scalar_output_bytes<=admission.output_bytes;
        end
    end
    for(genvar slot=0;slot<PIPELINE;slot=slot+1) begin : contexts
        assign arity[slot]=slot==0 && scalar_slot[0] ? scalar_arity : 8'd1;
        assign output_bytes[slot]=slot==0 && scalar_slot[0] ? scalar_output_bytes :
            family[slot]==0 ? 6'd16 : 6'd32;
        wire allocate=allocation_pending[slot];
        wire reserve=accept && incoming_tag==TAG_BITS'(slot);
        wire consume=(batch_response_valid && batch_response_ready && held_tag==TAG_BITS'(slot)) ||
            (slot==0 && response_valid && response_ready);
        assign return_hit[slot]=compression_complete_event && compression_tag==TAG_BITS'(slot);
        assign return_final[slot]=return_hit[slot] && final_compression[slot];
        wire seed_phase=phase[slot]==SEED;
        wire [4:0] next_iteration=iteration[slot]+5'd1;
        wire [4:0] reached=seed_phase ? 5'd0 : next_iteration;
        // Compare seed/step cases in parallel: late phase selection chooses
        // boolean results rather than feeding an incrementer/comparator chain.
        wire continues_node=shape[slot]==0 &&
            (seed_phase ? end_step[slot]!=0 : next_iteration<end_step[slot]);
        assign replay_possible[slot]=continues_node && (family[slot]==0 || family[slot]==2);
        wire capture_node=capture_enable[slot] &&
            ((shape[slot]==7 || seed_phase) ? capture_step[slot]==0 :
                capture_step[slot]==next_iteration);
        logic finishing_node,restart_hash;
        phase_t following_phase;
        always_comb begin
            case(phase[slot])
                KEY,MASK0,MASK1,HMAC_IN,HMSG_IN,MGF0,MGF1: finishing_node=1'b0;
                default: finishing_node=1'b1;
            endcase
            case(phase[slot])
                KEY: following_phase=MASK0;
                MASK0: following_phase=paired[slot] ? MASK1 : FINAL;
                MASK1: following_phase=FINAL;
                HMAC_IN: following_phase=HMAC_OUT;
                HMSG_IN: following_phase=MGF0;
                MGF0: following_phase=MGF1;
                default: following_phase=family[slot]==1 ? KEY : DIRECT;
            endcase
            restart_hash=phase[slot]==KEY || phase[slot]==MASK0 || phase[slot]==MASK1 ||
                phase[slot]==HMAC_IN || phase[slot]==HMSG_IN ||
                (phase[slot]==MGF0 && output_bytes[slot]>32) ||
                (finishing_node && continues_node);
        end
        assign return_restart[slot]=return_hit[slot] && (!final_compression[slot] || restart_hash);
        // A seed return can enter a cached KEY phase for the first time.
        // Apply the cold-fill barrier to this direct reservation as well as
        // normal arbitration; intermediate blocks continue independently.
        assign return_schedulable[slot]=return_restart[slot] &&
            !(return_final[slot] && public_prefix_wait &&
              cached_public_phase(family[slot],shape[slot],following_phase));
        if(slot==0) begin : scalar_descriptor
            // Only tag zero can own a scalar response. Prepare its publication
            // controls alongside final_compression, before that block starts;
            // iteration/phase logic then ends at these two narrow registers.
            always_ff @(posedge clk) begin
                if(rst) begin scalar_clear_pending<=0; scalar_upper_pending<=0; end
                else if(replay_take && replay_tag==0 && scalar_slot[0]) begin
                    scalar_clear_pending<=!replay_more;
                    scalar_upper_pending<=0;
                end
                else if(formatter==PREPARE && format_tag==0 && scalar_slot[0]) begin
                    scalar_clear_pending<=phase[0]==MGF0 || (finishing_node && !continues_node);
                    scalar_upper_pending<=phase[0]==MGF1;
                end
            end
        end
        always_ff @(posedge clk) begin
            if(rst) begin
                allocation_pending[slot]<=0;
                busy_slot[slot]<=0; complete[slot]<=0; need_block[slot]<=0; scalar_slot[slot]<=0;
                final_compression[slot]<=0; capture_enable[slot]<=0; paired[slot]<=0;
                public_prefix_context[slot]<=0;
                phase[slot]<=DIRECT; shape[slot]<=0; family[slot]<=0; block_index[slot]<=0;
            end else begin
                // Reserve and admission data enter on the same edge. A local
                // one-hot register removes the binary-tag decode from wide
                // allocation enables without adding a context or clock.
                allocation_pending[slot]<=reserve;
                // Preserve the original edge priority: consume, formatter,
                // compression return, registered allocation, new reservation.
                if(consume) begin complete[slot]<=0; busy_slot[slot]<=0; end
                if(reserve_format && candidate==TAG_BITS'(slot)) need_block[slot]<=0;
                if(formatter==DESCRIBE && (!block_ready || compression_ready) &&
                    format_tag==TAG_BITS'(slot) && describe_public_prefix)
                    block_index[slot]<=7'd1;
                if(formatter==PREPARE && format_tag==TAG_BITS'(slot))
                    final_compression[slot]<=format_block==7'((format_length+13'd8)>>6);
                if(return_hit[slot]) begin
                    if(!final_compression[slot]) begin
                        cv[slot]<=compression_cv;
                        block_index[slot]<=block_index[slot]+7'd1; need_block[slot]<=!reserve_return;
                    end else begin
                        if(restart_hash) begin
                            phase[slot]<=following_phase;
                            public_prefix_context[slot]<=cached_public_phase(family[slot],shape[slot],following_phase);
                            block_index[slot]<=replay_take ? (replay_slh ? 7'd1 : 7'd0) : 7'd0;
                            need_block[slot]<=!reserve_return && !replay_take;
                        end
                        case(phase[slot])
                            KEY: key_value[slot]<=returned;
                            MASK0: digest[slot]<=digest[slot]^returned;
                            MASK1: captured[slot]<=captured[slot]^returned;
                            HMAC_IN: digest[slot]<=returned;
                            HMSG_IN: key_value[slot]<=returned;
                            MGF0: if(output_bytes[slot]<=32) begin
                                digest[slot]<=returned; complete[slot]<=1;
                            end
                            MGF1: complete[slot]<=1;
                            default: begin
                                digest[slot]<=node_result(returned,family[slot]);
                                if(capture_node) captured[slot]<=node_result(returned,family[slot]);
                                if(continues_node) iteration[slot]<=reached;
                                else complete[slot]<=1;
                            end
                        endcase
                    end
                end
                if(allocate) begin
                    need_block[slot]<=1; scalar_slot[slot]<=admission.scalar;
                    shape[slot]<=admission.shape; family[slot]<=admission.family;
                    public_prefix_context[slot]<=cached_public_phase(admission.family,admission.shape,
                        initial_phase(admission.shape,admission.family,admission.no_seed));
                    paired[slot]<=admission.pair;
                    phase[slot]<=initial_phase(admission.shape,admission.family,admission.no_seed);
                    block_index[slot]<=0;
                    digest[slot]<=node_result(admission.value,admission.family);
                    captured[slot]<=admission.pair ? admission.right : 256'd0;
                    leaf[slot]<=admission.leaf;
                    address_a[slot]<=admission.address_a; address_b[slot]<=admission.address_b;
                    seed_domain[slot]<=admission.seed_domain; step_domain[slot]<=admission.step_domain;
                    iteration[slot]<=admission.start; end_step[slot]<=admission.start+admission.steps;
                    capture_step[slot]<=admission.capture_step; capture_enable[slot]<=admission.capture;
                    if(admission.shape==0 && admission.no_seed) begin
                        if(admission.capture && admission.capture_step==admission.start)
                            captured[slot]<=node_result(admission.value,admission.family);
                        if(admission.steps==0) begin need_block[slot]<=0; complete[slot]<=1; end
                    end
                    if(admission.invalid) begin need_block[slot]<=0; complete[slot]<=1; end
                end
                if(reserve) begin
                    busy_slot[slot]<=1; complete[slot]<=0; need_block[slot]<=0;
                end
            end
        end
    end
    for(genvar byte_index=0;byte_index<DIGEST_BYTES;byte_index=byte_index+1) begin : scalar_bytes
        assign scalar_write_mask[byte_index]=byte_index<int'(output_bytes[0]) &&
            ((byte_index<32 && scalar_clear_event) || (byte_index>=32 && scalar_upper_event));
    end
    // Batch completions only publish through digest/captured. They cannot
    // update a scalar response, whose sole valid owner is context zero.
    always_ff @(posedge clk) begin : scalar_publication
        if(rst) scalar_result<=0;
        else begin
            if(scalar_clear_event) scalar_result<=0;
            for(integer byte_index=0;byte_index<DIGEST_BYTES;byte_index=byte_index+1)
                if(scalar_write_mask[byte_index]) begin
                    if(byte_index<32) scalar_result[byte_index*8+:8]<=returned[byte_index*8+:8];
                    else scalar_result[byte_index*8+:8]<=returned[(byte_index-32)*8+:8];
                end
            if(ingress_pending && admission.scalar && admission.shape==0 &&
                admission.no_seed && admission.steps==0)
                scalar_result<=(DIGEST_BYTES*8)'(node_result(admission.value,admission.family));
            if(ingress_pending && admission.invalid) scalar_result<=0;
        end
    end
    always_ff @(posedge clk) begin : execution
        if(rst) begin
            formatter<=SELECT; format_tag<=0; beat<=0;
            public_prefix_described<=0;
            response_held<=0; held_tag<=0; schedule_cursor<=0; error<=0; list_words_valid<=0;
            beat_pending<=0;
            block_ready<=0; block_tag<=0;
            ingress_pending<=0;
        end else begin
            beat_pending<=0;
            if(compression_ready) block_ready<=0;
            ingress_pending<=0;
            if(ingress_pending && admission.invalid) error<=1;
            // Match the common executor's idle-tag contract: after draining a
            // batch, tag zero selects the first retained signature capture.
            if(!response_held || batch_response_ready) begin
                response_held<=completed_valid; held_tag<=completed_tag;
            end
            case(formatter)
                SELECT: begin
                    if(candidate_valid) reserve_block(int'(candidate));
                    else if(reserve_return) reserve_block(int'(compression_tag));
                end
                DESCRIBE: if(!block_ready || compression_ready) begin
                    format_kind<=selected_format(int'(format_tag));
                    format_fixed<=fixed_format(selected_format(int'(format_tag)),describe_block,
                        paired[format_tag],shape[format_tag]==0);
                    format_length<=input_length(int'(format_tag));
                    address_fields.leaf<=leaf[format_tag];
                    address_fields.address_a<=address_a[format_tag];
                    address_fields.address_b<=address_b[format_tag];
                    address_fields.iteration<=iteration[format_tag];
                    address_fields.domain_value<=domain(int'(format_tag));
                    address_fields.chain<=shape[format_tag]==0;
                    address_fields.seed_phase<=phase[format_tag]==SEED;
                    address_fields.tree_domain<=step_domain[format_tag]==3;
                    address_fields.compound<=phase[format_tag]==MASK0 ? 2'd1 :
                        phase[format_tag]==MASK1 ? 2'd2 : 2'd0;
                    public_prefix_described<=public_prefix_context[format_tag] && describe_block==0;
                    format_block<=describe_block;
                    format_first_index<=first_list_address(shape[format_tag],describe_block);
                    // Context CV banks only store returned intermediate
                    // states. Select the initial IV once at this shared port.
                    format_cv<=describe_public_prefix ? public_prefix_cv :
                        block_index[format_tag]==0 ? IV : cv[format_tag];
                    beat<=0; list_words_valid<=0; formatter<=PREPARE;
                end
                PREPARE: begin
                    public_prefix_described<=0;
                    format_address<=staged_address(address_fields,format_kind);
                    // Decode byte controls only from registered descriptors.
                    // Fixed first blocks still use one full 512-bit write.
                    if(write_prefix || write_fixed) begin
                        block_ready<=1; block_tag<=format_tag;
                        if(candidate_valid) reserve_block(int'(candidate));
                        else formatter<=SELECT;
                    end
                    else begin
                        prepare_beat(format_kind,{format_block,2'd0},format_length);
                        formatter<=BUILD;
                    end
                end
                // Select only the three required RAM words before registering.
                // The following cycle performs common source selection, window
                // alignment and padding. Non-list beats retain their cadence.
                BUILD: begin
                    if((list_beat && !list_words_valid) || (beat!=3 && following_list_beat))
                        for(integer k=0;k<3;k=k+1) list_words[k]<=fetched_list_word[k];
                    if(list_beat && !list_words_valid) begin
                        list_words_valid<=1;
                    end else begin
                        source_window<=selected_window;
                        staged_window<=window_control;
                        staged_payload_mask<=payload_mask;
                        staged_delimiter_mask<=delimiter_mask;
                        staged_length_beat<=length_beat;
                        staged_beat<=beat; beat_pending<=1;
                        // Retain only words needed by the following beat.
                        list_words_valid<=beat!=3 && following_list_beat;
                        if(beat==3) formatter<=DRAIN;
                        else begin
                            beat<=beat+1'b1;
                            prepare_beat(format_kind,{format_block,beat+2'd1},format_length);
                        end
                    end
                end
                // Commit the last registered beat before compression samples
                // the complete block. Descriptor reads for the next context
                // can overlap that handshake without duplicating block data.
                DRAIN: begin
                    block_ready<=1; block_tag<=format_tag;
                    if(candidate_valid) reserve_block(int'(candidate));
                    else formatter<=SELECT;
                end
                default: formatter<=SELECT;
            endcase
            // Slot owners reserve on this same acceptance edge. Only the
            // shared admission record is written here.
            if(accept) begin
                ingress_pending<=1;
                admission.tag<=incoming_tag; admission.scalar<=scalar_input;
                admission.shape<=incoming_shape; admission.family<=incoming_family;
                admission.no_seed<=incoming_no_seed; admission.pair<=incoming_pair;
                admission.start<=incoming_start; admission.steps<=incoming_steps;
                admission.capture_step<=scalar_input && !request_chain ?
                    (scalar_shape==7 ? 5'd0 : 5'd1) : incoming_capture_step;
                admission.capture<=incoming_capture; admission.value<=incoming_value;
                admission.right<=scalar_input ? 256'(request_right) : batch_right;
                admission.leaf<=scalar_input ? request_leaf : batch_leaf;
                admission.address_a<=scalar_input ? 8'(request_a) : batch_a;
                admission.address_b<=scalar_input ? request_b : batch_b;
                admission.seed_domain<=scalar_input ? request_recipe[55:48] : batch_seed_domain;
                admission.step_domain<=scalar_input ?
                    (request_chain ? request_step_recipe[55:48] : request_recipe[55:48]) : batch_step_domain;
                admission.arity<=scalar_input ? request_recipe[47:40] : 8'd1;
                admission.output_bytes<=scalar_input ? request_recipe[37:32] : incoming_family==0 ? 6'd16 : 6'd32;
                admission.invalid<=scalar_input && (!RECIPE_MASK[scalar_shape] || scalar_shape==0);
                if(scalar_accept) scalar_randomizer<=randomizer;
            end
        end
    end

`ifndef SYNTHESIS
    always_ff @(posedge clk) begin : debug_replay_owner
        if(!rst && replay_take) begin
            if(!return_final[replay_tag] || !replay_possible[replay_tag] ||
                replay_step !== (phase[replay_tag]==SEED ? 5'd0 : iteration[replay_tag]+5'd1) ||
                replay_end !== end_step[replay_tag] ||
                format_tag !== replay_tag || block_tag !== replay_tag ||
                format_cv !== (replay_slh ? public_prefix_cv : IV) ||
                (replay_slh ? block_index[replay_tag]!=1 : block_index[replay_tag]!=0))
                $fatal(1,"SHA2 replay lost its live chain/template owner");
        end
    end
    always_ff @(posedge clk) begin : debug_public_prefix
        if(!rst) begin
            if(public_prefix_launch && (!write_prefix || public_prefix_pending))
                $fatal(1,"SHA2 public prefix already in flight");
            if(public_prefix_pending && compression_complete_event && compression_tag==public_prefix_tag &&
                (!busy_slot[public_prefix_tag] || !public_prefix_context[public_prefix_tag] ||
                 block_index[public_prefix_tag]!=0 || final_compression[public_prefix_tag]))
                $fatal(1,"SHA2 public prefix return lost its initial block owner");
        end
    end
    always_ff @(posedge clk) begin : debug_allocation_events
        if(!rst) begin
            if(!$onehot0(allocation_pending))
                $fatal(1,"multiple SHA2 allocation slots pending");
            for(integer slot=0;slot<PIPELINE;slot=slot+1)
                if(allocation_pending[slot] !== (ingress_pending && admission.tag==TAG_BITS'(slot)))
                    $fatal(1,"local SHA2 allocation differs from registered admission tag");
        end
    end
    always_ff @(posedge clk) begin : debug_scalar_events
        if(!rst) begin
            if(scalar_clear_event && scalar_upper_event)
                $fatal(1,"multiple SHA2 scalar publication events on one return");
            if(return_final[0] && scalar_slot[0] &&
                (scalar_clear_pending !== (phase[0]==MGF0 ||
                    (contexts[0].finishing_node && !contexts[0].continues_node)) ||
                 scalar_upper_pending !== (phase[0]==MGF1)))
                $fatal(1,"SHA2 prepared scalar publication differs from return phase");
            for(integer slot=1;slot<PIPELINE;slot=slot+1)
                if(busy_slot[slot] && scalar_slot[slot])
                    $fatal(1,"SHA2 scalar response allocated outside tag zero");
        end
    end
    always_ff @(posedge clk) begin : debug_list_prefetch
        if(!rst && formatter==BUILD && !write_fixed) begin
            if(list_beat!==contains_list(format_kind,global_beat) ||
                following_list_beat!==contains_list(format_kind,global_beat+9'd1))
                $fatal(1,"SHA2 prepared list flags differ from formatter controls");
            if(list_next_index0!==list_address(format_kind,global_beat+(source_beat_ready ? 9'd2 : 9'd1)))
                $fatal(1,"SHA2 prepared list prefetch address differs from beat reference");
            for(integer k=0;k<3;k=k+1)
                if(!$onehot0(source_beat_ready ? following_list_word_select[k] : list_word_select[k]))
                    $fatal(1,"SHA2 endpoint word selector is not one-hot");
        end
    end
    always_ff @(posedge clk) begin : debug_staged_address
        if(!rst && formatter==PREPARE &&
            staged_address(address_fields,format_kind) !== packed_address(int'(format_tag),format_kind))
            $fatal(1,"SHA2 staged address differs from live-context reference");
    end
    always_ff @(posedge clk) begin : debug_prefix_only_sources
        if(!rst && formatter==BUILD && !write_fixed)
            for(integer k=0;k<3;k=k+1)
                case(source_t'(word_control[k][8:4]))
                    SRC_SECRET,SRC_VALUE,SRC_RIGHT,SRC_COUNTER,
                    SRC_PRF,SRC_KEY,SRC_IPAD_KEY,SRC_OPAD_KEY,SRC_TWO,
                    SRC_THREE,SRC_FOUR,SRC_PAIR,SRC_IPAD,SRC_OPAD:
                        $fatal(1,"SHA2 prefix-only source reached serialized BUILD");
                    default: begin end
                endcase
    end
    always_ff @(posedge clk) begin : debug_prepared_completion
        if(!rst && compression_complete_event && int'(compression_tag)<PIPELINE &&
            final_compression[compression_tag] !==
                (block_index[compression_tag]==last_block(int'(compression_tag))))
            $fatal(1,"SHA2 prepared completion metadata differs from recipe length");
    end
    logic [63:0] counted_batch_hashes,counted_batch_permutations;
    assign batch_hashes=counted_batch_hashes;
    assign batch_permutations=counted_batch_permutations;
    always_ff @(posedge clk) begin
        if(rst) begin
            hash_count<=0; permutation_count<=0; counted_batch_hashes<=0; counted_batch_permutations<=0;
        end else if(compression_complete_event) begin
            if(scalar_slot[compression_tag]) begin
                permutation_count<=permutation_count+64'd1;
                if(hash_complete_event) hash_count<=hash_count+64'd1;
            end else begin
                counted_batch_permutations<=counted_batch_permutations+64'd1;
                if(hash_complete_event) counted_batch_hashes<=counted_batch_hashes+64'd1;
            end
        end
    end
`endif
endmodule
`default_nettype wire
`endif
