`ifdef MHBS_SHA2
`timescale 1ns / 1ps
`default_nettype none
// SHA2 recipe execution: one compression lane, P independent contexts.
// Byte-vector ports use byte zero in the least significant bits.
// verilog_format: off
module recipe #(
    parameter integer N = 32,
    parameter integer DIGEST_BYTES = N==16 ? 34 : 32, INDEX_BITS = 7,
    parameter integer UNROLL = 1, PIPELINE = 1,
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
    typedef enum logic [1:0] { SELECT, BUILD, SEND } formatter_t;

    // Only requests own contexts; completed results stay live until consumed.
    // P=1 reduces these banks and selectors to a single scalar execution slot.
    logic [PIPELINE-1:0] busy_slot, complete, need_block, scalar_slot, capture_enable, paired;
    phase_t phase[0:PIPELINE-1];
    logic [3:0] shape[0:PIPELINE-1];
    logic [1:0] family[0:PIPELINE-1];
    logic [19:0] leaf[0:PIPELINE-1];
    logic [7:0] address_a[0:PIPELINE-1], seed_domain[0:PIPELINE-1], step_domain[0:PIPELINE-1];
    logic [31:0] address_b[0:PIPELINE-1];
    logic [4:0] iteration[0:PIPELINE-1], end_step[0:PIPELINE-1], capture_step[0:PIPELINE-1];
    logic [7:0] arity[0:PIPELINE-1];
    logic [5:0] output_bytes[0:PIPELINE-1];
    logic [6:0] block_index[0:PIPELINE-1];
    wire [255:0] cv[0:PIPELINE-1];
    logic [255:0] retained_cv[0:PIPELINE-1];
    logic [255:0] digest[0:PIPELINE-1], key_value[0:PIPELINE-1], captured[0:PIPELINE-1];
    // With one context the compressor's registered output already retains
    // the preceding block CV until another compression finishes. First blocks
    // use IV; subsequent blocks consume that held output directly. Multiple
    // contexts still need their own CV bank while other tags execute.
    if (PIPELINE == 1) begin : single_context_cv
        assign cv[0] = block_index[0] == 0 ? IV : compression_cv;
    end else begin : independent_context_cv
        for (genvar slot=0; slot<PIPELINE; slot++)
            assign cv[slot] = retained_cv[slot];
    end
    logic [DIGEST_BYTES*8-1:0] scalar_result;

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
    logic [TAG_BITS-1:0] format_tag;
    logic [1:0] beat;
    logic [511:0] block_buffer;
    logic [255:0] format_address;
    logic [12:0] format_length;
    logic [8:0] word_control[0:2];
    window_t window_control;
    logic [15:0] payload_mask, delimiter_mask;
    logic length_beat;
    wire [8:0] global_beat={block_index[format_tag],beat};

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
    // Compute next-beat controls while the current beat traverses the source
    // mux. Prefixes with 6/7 trailing bytes use fixed wiring, not barrel shifts.
    task automatic prepare_beat(input format_t kind,input [8:0] pos,input [12:0] length);
        reg slh_prefix,lms_prefix,unaligned;
        reg [9:0] first_word;
        begin
            slh_prefix=kind==SLH_SEED || kind==SLH_VALUE || kind==SLH_LIST;
            lms_prefix=kind==LMS_SEED || kind==LMS_CHAIN || kind==LMS_MESSAGE ||
                kind==LMS_LIST || kind==LMS_LEAF || kind==LMS_PARENT;
            unaligned=(slh_prefix && pos>=5) || (lms_prefix && pos>=1);
            first_word={pos,1'b0};
            window_control<=ALIGNED;
            if(unaligned && ((slh_prefix && pos==5) || (lms_prefix && pos==1))) begin
                window_control<=kind==LMS_SEED || kind==LMS_CHAIN ? BRIDGE_SEVEN : BRIDGE_SIX;
                word_control[0]<=control(SRC_ADDRESS,4'd2);
                word_control[1]<=payload_control(kind,10'd0);
                word_control[2]<=payload_control(kind,10'd1);
            end else if(unaligned) begin
                window_control<=kind==LMS_SEED || kind==LMS_CHAIN ? SHIFT_ONE : SHIFT_TWO;
                if(kind==SLH_LIST) first_word=10'd1;
                else if(kind==LMS_LIST) first_word=pos[0] ? 10'd3 : 10'd1;
                else first_word=first_word-(slh_prefix ? 10'd11 : 10'd3);
                for(integer k=0;k<3;k=k+1) word_control[k]<=payload_control(kind,first_word+10'(k));
            end else begin
                for(integer k=0;k<3;k=k+1) word_control[k]<=aligned_control(kind,first_word+10'(k));
            end
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
    function automatic [63:0] source_word(input [8:0] selected);
        reg [255:0] value;
        reg [63:0] literal;
        reg [63:0] key_pad;
        begin
            value=0; literal=0; key_pad=0;
            case(source_t'(selected[8:4]))
                SRC_SECRET: value=256'(secret_seed);
                SRC_PRF: value=256'(secret_prf);
                SRC_PUBLIC: value=256'(public_seed);
                SRC_ROOT: value=256'(root);
                SRC_RANDOM: value=256'(randomizer);
                SRC_VALUE: value=digest[format_tag];
                SRC_KEY: value=key_value[format_tag];
                SRC_RIGHT: value=captured[format_tag];
                SRC_ADDRESS: value=format_address;
                SRC_LIST0: value=256'(list_data0);
                SRC_LIST1: value=256'(list_data1);
                SRC_IPAD_KEY: begin value=256'(secret_prf); key_pad=64'h3636363636363636; end
                SRC_OPAD_KEY: begin value=256'(secret_prf); key_pad=64'h5c5c5c5c5c5c5c5c; end
                SRC_MESSAGE: literal=selected[3:0]<11 ? padded_message[selected[3:0]*64+:64] : 64'd0;
                SRC_TWO: literal=64'h0200000000000000;
                SRC_THREE: literal=64'h0300000000000000;
                SRC_FOUR: literal=64'h0400000000000000;
                SRC_PAIR: literal={7'd0,paired[format_tag],56'd0};
                SRC_COUNTER: literal=64'h0000000001000000;
                SRC_IPAD: literal=64'h3636363636363636;
                SRC_OPAD: literal=64'h5c5c5c5c5c5c5c5c;
                default: value=0;
            endcase
            source_word=node_word(value,selected[1:0]) ^ key_pad ^ literal;
        end
    endfunction
    wire [191:0] source_window={source_word(word_control[2]),source_word(word_control[1]),source_word(word_control[0])};
    logic [127:0] payload,formatted_beat;
    wire [63:0] encoded_length=be64({48'd0,format_length,3'd0});
    always_comb begin
        case(window_control)
            SHIFT_ONE: payload=source_window[135:8];
            SHIFT_TWO: payload=source_window[143:16];
            BRIDGE_SIX: payload={source_window[143:64],source_window[47:0]};
            BRIDGE_SEVEN: payload={source_window[135:64],source_window[55:0]};
            default: payload=source_window[127:0];
        endcase
        if(length_beat) payload[127:64]=encoded_length;
        for(integer k=0;k<16;k=k+1)
            formatted_beat[127-k*8-:8]=(length_beat && k>=8) ? payload[k*8+:8] :
                payload_mask[k] ? payload[k*8+:8] : delimiter_mask[k] ? 8'h80 : 8'd0;
    end
    function automatic [INDEX_BITS-1:0] list_address(input format_t kind,input [8:0] pos);
        case(kind)
            SLH_LIST: list_address=pos>=6 ? INDEX_BITS'(pos-9'd6) : INDEX_BITS'(0);
            LMS_LIST: list_address=pos>=2 ? INDEX_BITS'((pos-9'd2)>>1) : INDEX_BITS'(0);
            default: list_address=0;
        endcase
    endfunction
    assign list_index0=list_address(format_kind,global_beat);
    assign list_index1=list_index0+1'b1;
    // In SEND, the old block already resides in block_buffer. Its acceptance
    // can also prepare the next slot and prefetch its first endpoint address.
    wire start_format=candidate_valid && (formatter==SELECT || (formatter==SEND && compression_ready));
    assign list_next_index0=start_format ? list_address(selected_format(int'(candidate)),{block_index[candidate],2'd0}) :
        list_address(format_kind,{block_index[format_tag],formatter==BUILD && beat!=3 ? beat+2'd1 : beat});
    task automatic prepare_block(input integer t);
        begin
            format_tag<=TAG_BITS'(t); need_block[t]<=0; beat<=0; formatter<=BUILD;
            format_kind<=selected_format(t); format_length<=input_length(t);
            format_address<=packed_address(t,selected_format(t));
            prepare_beat(selected_format(t),{block_index[t],2'd0},input_length(t));
            schedule_cursor<=t==PIPELINE-1 ? TAG_BITS'(0) : TAG_BITS'(t+1);
        end
    endtask

    logic candidate_valid;
    logic [TAG_BITS-1:0] candidate;
    logic [TAG_BITS-1:0] schedule_cursor;
    integer scan;
    always_comb begin
        candidate_valid=0; candidate=0; scan=0;
        for(integer k=0;k<PIPELINE;k=k+1) begin
            scan=int'(schedule_cursor)+k;
            if(scan>=PIPELINE) scan=scan-PIPELINE;
            if(!candidate_valid && need_block[scan]) begin candidate_valid=1; candidate=TAG_BITS'(scan); end
        end
    end
    wire compression_ready, compression_valid;
    wire [255:0] compression_cv;
    wire [TAG_BITS-1:0] compression_tag;
    sha256 #(.PIPELINE(PIPELINE),.UNROLL(UNROLL),.TAG_BITS(TAG_BITS)) compression (
        .clk,.rst,.input_valid(formatter==SEND),.input_ready(compression_ready),
        .input_cv(cv[format_tag]),.input_block(block_buffer),.input_tag(format_tag),
        .output_valid(compression_valid),.output_ready(1'b1),.output_cv(compression_cv),.output_tag(compression_tag)
    );
    wire compression_complete_event=compression_valid && !rst;
    wire hash_complete_event=compression_complete_event && block_index[compression_tag]==last_block(int'(compression_tag));
    wire [255:0] returned=reverse_bytes(compression_cv);

    logic response_held;
    logic [TAG_BITS-1:0] held_tag, completed_tag;
    logic completed_valid;
    always_comb begin
        completed_tag=0; completed_valid=0;
        for(integer k=0;k<PIPELINE;k=k+1)
            if(!completed_valid && complete[k] && !scalar_slot[k] && (!response_held || held_tag!=TAG_BITS'(k))) begin
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
    assign request_ready=!rst && !batch_mode && busy_slot==0;
    assign batch_request_ready=!rst && batch_mode && int'(batch_request_tag)<PIPELINE &&
        (!busy_slot[batch_request_tag] || (batch_response_valid && batch_response_ready && held_tag==batch_request_tag));
    wire scalar_accept=request_valid && request_ready;
    wire batch_accept=batch_request_valid && batch_request_ready;
    wire accept=scalar_accept || batch_accept;
    wire [TAG_BITS-1:0] incoming_tag=scalar_accept ? TAG_BITS'(0) : batch_request_tag;
    wire [3:0] incoming_shape=scalar_accept ? (request_chain ? 4'd0 : request_recipe[59:56]) : batch_fixed_shape;
    wire [3:0] scalar_shape=request_recipe[59:56];
    wire [1:0] incoming_family=scalar_accept ?
        ((scalar_shape<=4 || scalar_shape==12) ? 2'd0 :
         (scalar_shape==5 || scalar_shape==6 || scalar_shape==7 || scalar_shape==8) ? 2'd1 : 2'd2) : batch_family;
    wire incoming_no_seed=scalar_accept ?
        !(request_chain && (scalar_shape==1 || scalar_shape==7 || scalar_shape==9)) : batch_no_seed;
    wire [4:0] incoming_start=scalar_accept ? 5'd0 : {1'b0,batch_start};
    wire [4:0] incoming_steps=scalar_accept ? (request_chain ? request_steps : 5'd0) : batch_steps;
    wire [4:0] incoming_capture_step=scalar_accept ? request_capture_after : batch_capture_after;
    wire incoming_capture=scalar_accept ? request_capture : batch_capture_enable;
    wire [255:0] incoming_value=scalar_accept ? 256'(request_left) : batch_initial_value;
    wire incoming_pair=scalar_accept ? request_recipe[47:40]==2 : batch_pair;
    function automatic phase_t initial_phase(input [3:0] s,input [1:0] f,input no_seed);
        case(s)
            0: initial_phase=!no_seed ? SEED : f==1 ? KEY : DIRECT;
            3: initial_phase=HMAC_IN;
            4: initial_phase=HMSG_IN;
            8: initial_phase=KEY;
            default: initial_phase=DIRECT;
        endcase
    endfunction

    // A full SHA256 call starts from IV. Intermediate compression returns only
    // update CV/offset; only a full call can change a recipe or chain phase.
    task automatic next_hash(input integer t,input phase_t next_phase);
        begin phase[t]<=next_phase; if(PIPELINE>1) retained_cv[t]<=IV; block_index[t]<=0; need_block[t]<=1; end
    endtask
    task automatic finish_node(input integer t,input [255:0] value);
        reg [255:0] node;
        reg [4:0] reached;
        begin
            node=node_result(value,family[t]);
            reached=phase[t]==SEED ? 5'd0 : iteration[t]+1'b1;
            digest[t]<=node;
            if(capture_enable[t] && capture_step[t]==(shape[t]==7 ? 5'd0 : reached)) captured[t]<=node;
            if(shape[t]==0 && reached<end_step[t]) begin
                iteration[t]<=reached;
                next_hash(t,family[t]==1 ? KEY : DIRECT);
            end else begin
                complete[t]<=1;
                if(scalar_slot[t]) begin
                    scalar_result<=0;
                    for(integer k=0;k<DIGEST_BYTES;k=k+1)
                        if(k<32 && k<int'(output_bytes[t])) scalar_result[k*8+:8]<=value[k*8+:8];
                end
            end
        end
    endtask
    always_ff @(posedge clk) begin : execution
        integer t;
        if(rst) begin
            busy_slot<=0; complete<=0; need_block<=0; scalar_slot<=0;
            capture_enable<=0; paired<=0; formatter<=SELECT; format_tag<=0; beat<=0;
            response_held<=0; held_tag<=0; schedule_cursor<=0; error<=0;
            scalar_result<=0;
            for(integer k=0;k<PIPELINE;k=k+1) begin
                phase[k]<=DIRECT; shape[k]<=0; family[k]<=0; block_index[k]<=0;
                arity[k]<=0; output_bytes[k]<=0;
            end
        end else begin
            // Match the common executor's idle-tag contract: after draining a
            // batch, tag zero selects the first retained signature capture.
            if(!response_held || batch_response_ready) begin
                response_held<=completed_valid; held_tag<=completed_tag;
            end
            if(batch_response_valid && batch_response_ready) begin
                complete[held_tag]<=0; busy_slot[held_tag]<=0;
            end
            if(response_valid && response_ready) begin complete[0]<=0; busy_slot[0]<=0; end
            case(formatter)
                SELECT: if(candidate_valid) prepare_block(int'(candidate));
                BUILD: begin
                    block_buffer[511-int'(beat)*128-:128]<=formatted_beat;
                    if(beat==3) formatter<=SEND;
                    else begin
                        beat<=beat+1'b1;
                        prepare_beat(format_kind,{block_index[format_tag],beat+2'd1},format_length);
                    end
                end
                SEND: if(compression_ready) begin
                    if(candidate_valid) prepare_block(int'(candidate));
                    else formatter<=SELECT;
                end
                default: formatter<=SELECT;
            endcase
            if(compression_complete_event) begin
                t=int'(compression_tag);
                if(!hash_complete_event) begin
                    if(PIPELINE>1) retained_cv[t]<=compression_cv;
                    block_index[t]<=block_index[t]+7'd1; need_block[t]<=1;
                end else case(phase[t])
                    KEY: begin key_value[t]<=returned; next_hash(t,MASK0); end
                    MASK0: begin digest[t]<=digest[t]^returned; next_hash(t,paired[t] ? MASK1 : FINAL); end
                    MASK1: begin captured[t]<=captured[t]^returned; next_hash(t,FINAL); end
                    HMAC_IN: begin digest[t]<=returned; next_hash(t,HMAC_OUT); end
                    HMSG_IN: begin key_value[t]<=returned; next_hash(t,MGF0); end
                    MGF0: begin
                        scalar_result<=0;
                        for(integer k=0;k<DIGEST_BYTES;k=k+1)
                            if(k<32 && k<int'(output_bytes[t])) scalar_result[k*8+:8]<=returned[k*8+:8];
                        if(output_bytes[t]>32) next_hash(t,MGF1);
                        else begin digest[t]<=returned; complete[t]<=1; end
                    end
                    MGF1: begin
                        for(integer k=32;k<DIGEST_BYTES;k=k+1)
                            if(k<int'(output_bytes[t])) scalar_result[k*8+:8]<=returned[(k-32)*8+:8];
                        complete[t]<=1;
                    end
                    default: finish_node(t,returned);
                endcase
            end
            // Allocation is last so a retiring tag can be refilled on this edge.
            if(accept) begin
                t=int'(incoming_tag);
                busy_slot[t]<=1; complete[t]<=0; need_block[t]<=1; scalar_slot[t]<=scalar_accept;
                shape[t]<=incoming_shape; family[t]<=incoming_family; paired[t]<=incoming_pair;
                phase[t]<=initial_phase(incoming_shape,incoming_family,incoming_no_seed);
                if(PIPELINE>1) retained_cv[t]<=IV;
                block_index[t]<=0; digest[t]<=node_result(incoming_value,incoming_family);
                captured[t]<=incoming_pair ? (scalar_accept ? 256'(request_right) : batch_right) : 256'd0;
                leaf[t]<=scalar_accept ? request_leaf : batch_leaf;
                address_a[t]<=scalar_accept ? 8'(request_a) : batch_a;
                address_b[t]<=scalar_accept ? request_b : batch_b;
                seed_domain[t]<=scalar_accept ? request_recipe[55:48] : batch_seed_domain;
                step_domain[t]<=scalar_accept ? (request_chain ? request_step_recipe[55:48] : request_recipe[55:48]) : batch_step_domain;
                iteration[t]<=incoming_start; end_step[t]<=incoming_start+incoming_steps;
                capture_step[t]<=scalar_accept && !request_chain ? (scalar_shape==7 ? 5'd0 : 5'd1) : incoming_capture_step;
                capture_enable[t]<=incoming_capture;
                arity[t]<=scalar_accept ? request_recipe[47:40] : 8'd1;
                output_bytes[t]<=scalar_accept ? request_recipe[37:32] : incoming_family==0 ? 6'd16 : 6'd32;
                if(incoming_shape==0 && incoming_no_seed) begin
                    if(incoming_capture && incoming_capture_step==incoming_start)
                        captured[t]<=node_result(incoming_value,incoming_family);
                    if(incoming_steps==0) begin
                        need_block[t]<=0; complete[t]<=1;
                        if(scalar_accept) scalar_result<=(DIGEST_BYTES*8)'(node_result(incoming_value,incoming_family));
                    end
                end
                if(scalar_accept && (!RECIPE_MASK[scalar_shape] || scalar_shape==0)) begin
                    error<=1; need_block[t]<=0; complete[t]<=1; scalar_result<=0;
                end
            end
        end
    end

`ifndef SYNTHESIS
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
