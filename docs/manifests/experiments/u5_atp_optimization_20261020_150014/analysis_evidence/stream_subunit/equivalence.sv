module formatter_old(input [255:0] block_address,block_value,block_right,ctx_public_seed,ctx_secret_seed,return_key,
input [6:0] block_phase,input [2:0] block_format,input [1:0] block_family,
input [5:0] node_bytes,input [3:0] block_step,block_shape,input block_pair,input [127:0] identifier,
output wire [1599:0] unified_state);
function automatic [31:0] be32(input [31:0] value); be32={value[7:0],value[15:8],value[23:16],value[31:24]}; endfunction
                begin : formatter
                    // Keep each byte placement independent of the family mux.
                    // Only the final, mutually exclusive layout enables merge nodes.
                    wire seed = block_format[0];
                    wire prf = block_format[1];
                    wire xmss = block_family == 1;
                    wire lms = block_family == 2;
                    wire lms_node = lms && (block_shape == 14 || block_shape == 15);
                    wire lms_chain = lms && !lms_node;
                    wire node16 = node_bytes == 16;
                    wire node24 = node_bytes == 24;
                    wire node32 = !node16 && !node24;
                    wire two = block_format[2];
                    wire [255:0] masked_address = {
                        be32(block_phase[3] ? 32'd1 : block_phase[5] ? 32'd2 : 32'd0),
                        block_shape != 0 ? block_address[255:224] : be32({28'd0, block_step}),
                        block_address[223:192], block_address[191:160], block_address[159:128], 96'd0
                    };
                    wire [7:0] xmss_domain = block_shape == 5 || prf ? 8'd3 :
                        seed ? 8'd4 : block_pair ? 8'd1 : 8'd0;
                    wire [255:0] xmss_key = block_shape == 5 ? block_value :
                        seed ? ctx_secret_seed : prf ? ctx_public_seed : return_key;
                    wire [255:0] xmss_value = block_shape == 5 ? {block_address[191:160],224'd0} :
                        seed ? ctx_public_seed : prf ? masked_address : block_value;
                    wire [255:0] xmss_right = seed ? masked_address : block_right;
                    wire [183:0] chain_prefix = {
                        (seed || block_shape == 9) ? 8'hff : block_shape == 10 ?
                            block_address[255:248] : {4'd0,block_step},
                        block_address[223:216],8'd0,block_address[191:160],identifier
                    };
                    wire [175:0] node_prefix = {
                        block_shape == 14 ? 16'h8282 : 16'h8383,block_address[255:224],identifier
                    };
                    logic [1087:0] slh16, slh24, slh32, xmss32, chain32, parent32;
                    always_comb begin
                        slh16 = 0;
                        slh16[511:0] = {block_value[127:0],block_address,ctx_public_seed[127:0]};
                        if (two) begin
                            slh16[639:512] = block_right[127:0];
                            slh16[647:640] = 8'h1f;
                        end else slh16[519:512] = 8'h1f;
                        slh24 = 0;
                        slh24[639:0] = {block_value[191:0],block_address,ctx_public_seed[191:0]};
                        if (two) begin
                            slh24[831:640] = block_right[191:0];
                            slh24[839:832] = 8'h1f;
                        end else slh24[647:640] = 8'h1f;
                        slh32 = 0;
                        slh32[767:0] = {block_value,block_address,ctx_public_seed};
                        if (two) begin
                            slh32[1023:768] = block_right;
                            slh32[1031:1024] = 8'h1f;
                        end else slh32[775:768] = 8'h1f;
                        xmss32 = 0;
                        xmss32[255:248] = xmss_domain;
                        xmss32[511:256] = xmss_key;
                        xmss32[767:512] = xmss_value;
                        if (two) begin
                            xmss32[1023:768] = xmss_right;
                            xmss32[1031:1024] = 8'h1f;
                        end else xmss32[775:768] = 8'h1f;
                        chain32 = 0;
                        chain32[183:0] = chain_prefix;
                        chain32[439:184] = block_value;
                        chain32[447:440] = 8'h1f;
                        parent32 = 0;
                        parent32[175:0] = node_prefix;
                        parent32[431:176] = block_value;
                        if (two) begin
                            parent32[687:432] = block_right;
                            parent32[695:688] = 8'h1f;
                        end else parent32[439:432] = 8'h1f;
                    end
                    wire [1087:0] payload =
                        ({1088{node16}} & slh16) |
                        ({1088{node24}} & slh24) |
                        ({1088{node32 && !xmss && !lms}} & slh32) |
                        ({1088{node32 && xmss}} & xmss32) |
                        ({1088{node32 && lms_chain}} & chain32) |
                        ({1088{node32 && lms_node}} & parent32);
                    assign unified_state = {512'd0, 1'b1, payload[1086:0]};
                end
endmodule
module formatter_new(input [255:0] block_address,block_value,block_right,ctx_public_seed,ctx_secret_seed,return_key,
input [6:0] block_phase,input [2:0] block_format,input [1:0] block_family,
input [5:0] node_bytes,input [3:0] block_step,block_shape,input block_pair,input [127:0] identifier,
output wire [1599:0] unified_state);
function automatic [31:0] be32(input [31:0] value); be32={value[7:0],value[15:8],value[23:16],value[31:24]}; endfunction
                begin : formatter
                    // Keep each byte placement independent of the family mux.
                    // Only the final, mutually exclusive layout enables merge nodes.
                    wire seed = block_format[0];
                    wire prf = block_format[1];
                    wire xmss = block_family == 1;
                    wire lms = block_family == 2;
                    wire lms_node = lms && (block_shape == 14 || block_shape == 15);
                    wire lms_chain = lms && !lms_node;
                    wire node16 = node_bytes == 16;
                    wire node24 = node_bytes == 24;
                    wire node32 = !node16 && !node24;
                    wire two = block_format[2];
                    wire [255:0] masked_address = {
                        be32(block_phase[3] ? 32'd1 : block_phase[5] ? 32'd2 : 32'd0),
                        block_shape != 0 ? block_address[255:224] : be32({28'd0, block_step}),
                        block_address[223:192], block_address[191:160], block_address[159:128], 96'd0
                    };
                    wire [7:0] xmss_domain = block_shape == 5 || prf ? 8'd3 :
                        seed ? 8'd4 : block_pair ? 8'd1 : 8'd0;
                    wire [255:0] xmss_key = block_shape == 5 ? block_value :
                        seed ? ctx_secret_seed : prf ? ctx_public_seed : return_key;
                    wire [255:0] xmss_value = block_shape == 5 ? {block_address[191:160],224'd0} :
                        seed ? ctx_public_seed : prf ? masked_address : block_value;
                    wire [255:0] xmss_right = seed ? masked_address : block_right;
                    wire [183:0] chain_prefix = {
                        (seed || block_shape == 9) ? 8'hff : block_shape == 10 ?
                            block_address[255:248] : {4'd0,block_step},
                        block_address[223:216],8'd0,block_address[191:160],identifier
                    };
                    wire [175:0] node_prefix = {
                        block_shape == 14 ? 16'h8282 : 16'h8383,block_address[255:224],identifier
                    };
                    logic [1087:0] slh16, slh24, node32_layout, chain32, parent32;
                    always_comb begin
                        slh16 = 0;
                        slh16[511:0] = {block_value[127:0],block_address,ctx_public_seed[127:0]};
                        if (two) begin
                            slh16[639:512] = block_right[127:0];
                            slh16[647:640] = 8'h1f;
                        end else slh16[519:512] = 8'h1f;
                        slh24 = 0;
                        slh24[639:0] = {block_value[191:0],block_address,ctx_public_seed[191:0]};
                        if (two) begin
                            slh24[831:640] = block_right[191:0];
                            slh24[839:832] = 8'h1f;
                        end else slh24[647:640] = 8'h1f;
                        // SHAKE SLH n=32 and XMSS use the same 32-byte
                        // value/right placement and identical suffix positions.
                        // Select differing fields once, before shared placement.
                        node32_layout = 0;
                        node32_layout[255:0] = xmss ? {xmss_domain,248'd0} : ctx_public_seed;
                        node32_layout[511:256] = xmss ? xmss_key : block_address;
                        node32_layout[767:512] = xmss ? xmss_value : block_value;
                        if (two) begin
                            node32_layout[1023:768] = xmss ? xmss_right : block_right;
                            node32_layout[1031:1024] = 8'h1f;
                        end else node32_layout[775:768] = 8'h1f;
                        chain32 = 0;
                        chain32[183:0] = chain_prefix;
                        chain32[439:184] = block_value;
                        chain32[447:440] = 8'h1f;
                        parent32 = 0;
                        parent32[175:0] = node_prefix;
                        parent32[431:176] = block_value;
                        if (two) begin
                            parent32[687:432] = block_right;
                            parent32[695:688] = 8'h1f;
                        end else parent32[439:432] = 8'h1f;
                    end
                    wire [1087:0] payload =
                        ({1088{node16}} & slh16) |
                        ({1088{node24}} & slh24) |
                        ({1088{node32 && !lms}} & node32_layout) |
                        ({1088{node32 && lms_chain}} & chain32) |
                        ({1088{node32 && lms_node}} & parent32);
                    assign unified_state = {512'd0, 1'b1, payload[1086:0]};
                end
endmodule
module stream_old(input clk,rst,stream_accept,input state,input [15:0] shapes,
input [191:0] source_window,input [127:0] list_window,
input [12:0] position,remaining_bytes,input [7:0] prefix_bytes,
input padding_reached,partial_beat,stream_last,input [3:0] beat,
input [127:0] identifier,input [31:0] leaf,
output logic fetched_valid,output logic [127:0] stream_data);
localparam STREAM_ENABLE=1,STREAM=1,PREFIX_MESSAGE=11,ADDRESS_LIST=12,PREFIX_LIST=13;
function automatic [31:0] be32(input [31:0] value); be32={value[7:0],value[15:8],value[23:16],value[31:24]}; endfunction
logic fetched_prefix_head,fetched_prefix_tail,fetched_padding,fetched_partial,fetched_rate_tail,fetched_last;
logic [3:0] fetched_remaining;
logic [127:0] fetched_source,fetched_list; logic fetched_use_list;
            always_ff @(posedge clk) begin
                if (rst) fetched_valid <= 0;
                else if (stream_accept) begin
                    fetched_valid <= STREAM_ENABLE && state == STREAM;
                    if (STREAM_ENABLE && state == STREAM) begin
                        fetched_source <= shapes[PREFIX_MESSAGE] ?
                            source_window[143:16] : source_window[127:0];
                        fetched_list <= list_window;
                        fetched_use_list <= (shapes[ADDRESS_LIST] || shapes[PREFIX_LIST]) &&
                            position >= prefix_bytes;
                        fetched_prefix_head <= shapes[PREFIX_MESSAGE] && position == 0;
                        fetched_prefix_tail <= shapes[PREFIX_MESSAGE] && position == 16;
                        fetched_padding <= padding_reached;
                        fetched_partial <= partial_beat;
                        fetched_remaining <= remaining_bytes[3:0];
                        fetched_rate_tail <= beat == 8;
                        fetched_last <= stream_last;
                    end
                end
            end
            always_comb begin
                stream_data = fetched_use_list ? fetched_list : fetched_source;
                if (fetched_prefix_head) stream_data = identifier;
                else if (fetched_prefix_tail) stream_data[47:0] = {16'h8181, be32(leaf)};
                for (integer i = 0; i < 16; i++) begin
                    if (fetched_padding || (fetched_partial && fetched_remaining <= 4'(i)))
                        stream_data[i*8+:8] = 0;
                    if (!fetched_padding && fetched_partial && fetched_remaining == 4'(i))
                        stream_data[i*8+:8] = 8'h1f;
                    if (fetched_rate_tail) begin
                        if (i >= 8) stream_data[i*8+:8] = 0;
                        else if (i == 7 && fetched_last) stream_data[i*8+7] = 1'b1;
                    end
                end
            end

endmodule
module stream_new(input clk,rst,stream_accept,input state,input [15:0] shapes,
input [191:0] source_window,input [127:0] list_window,
input [12:0] position,remaining_bytes,input [7:0] prefix_bytes,
input padding_reached,partial_beat,stream_last,input [3:0] beat,
input [127:0] identifier,input [31:0] leaf,
output logic fetched_valid,output logic [127:0] stream_data);
localparam STREAM_ENABLE=1,STREAM=1,PREFIX_MESSAGE=11,ADDRESS_LIST=12,PREFIX_LIST=13;
function automatic [31:0] be32(input [31:0] value); be32={value[7:0],value[15:8],value[23:16],value[31:24]}; endfunction
logic fetched_prefix_head,fetched_prefix_tail,fetched_padding,fetched_partial,fetched_rate_tail,fetched_last;
logic [3:0] fetched_remaining;
logic [127:0] fetched_payload;
            always_ff @(posedge clk) begin
                if (rst) fetched_valid <= 0;
                else if (stream_accept) begin
                    fetched_valid <= STREAM_ENABLE && state == STREAM;
                    if (STREAM_ENABLE && state == STREAM) begin
                        // Only one source is live for this beat. Capture the
                        // selected 16-byte window once instead of retaining
                        // both candidate windows until the padding stage.
                        fetched_payload <= (shapes[ADDRESS_LIST] || shapes[PREFIX_LIST]) &&
                            position >= prefix_bytes ? list_window :
                            shapes[PREFIX_MESSAGE] ? source_window[143:16] : source_window[127:0];
                        fetched_prefix_head <= shapes[PREFIX_MESSAGE] && position == 0;
                        fetched_prefix_tail <= shapes[PREFIX_MESSAGE] && position == 16;
                        fetched_padding <= padding_reached;
                        fetched_partial <= partial_beat;
                        fetched_remaining <= remaining_bytes[3:0];
                        fetched_rate_tail <= beat == 8;
                        fetched_last <= stream_last;
                    end
                end
            end
`ifndef SYNTHESIS
            // Retain the former two-window stage as an independent simulation
            // oracle. It observes exactly the same fetch handshake and stall.
            logic [127:0] debug_fetched_source, debug_fetched_list;
            logic debug_fetched_use_list;
            always_ff @(posedge clk) begin : debug_stream_payload_snapshot
                if (!rst && stream_accept && STREAM_ENABLE && state == STREAM) begin
                    debug_fetched_source <= shapes[PREFIX_MESSAGE] ?
                        source_window[143:16] : source_window[127:0];
                    debug_fetched_list <= list_window;
                    debug_fetched_use_list <= (shapes[ADDRESS_LIST] || shapes[PREFIX_LIST]) &&
                        position >= prefix_bytes;
                end
                if (!rst && fetched_valid && fetched_payload !==
                    (debug_fetched_use_list ? debug_fetched_list : debug_fetched_source))
                    $fatal(1, "selected stream payload differs from original two-window stage");
            end
`endif
            always_comb begin
                stream_data = fetched_payload;
                if (fetched_prefix_head) stream_data = identifier;
                else if (fetched_prefix_tail) stream_data[47:0] = {16'h8181, be32(leaf)};
                for (integer i = 0; i < 16; i++) begin
                    if (fetched_padding || (fetched_partial && fetched_remaining <= 4'(i)))
                        stream_data[i*8+:8] = 0;
                    if (!fetched_padding && fetched_partial && fetched_remaining == 4'(i))
                        stream_data[i*8+:8] = 8'h1f;
                    if (fetched_rate_tail) begin
                        if (i >= 8) stream_data[i*8+:8] = 0;
                        else if (i == 7 && fetched_last) stream_data[i*8+7] = 1'b1;
                    end
                end
            end

endmodule
module tb;
logic clk=0; always #5 clk=~clk;
logic [255:0] block_address,block_value,block_right,ctx_public_seed,ctx_secret_seed,return_key;
logic [6:0] block_phase; logic [2:0] block_format; logic [1:0] block_family;
logic [5:0] node_bytes; logic [3:0] block_step,block_shape; logic block_pair; logic [127:0] identifier;
wire [1599:0] old_form,new_form;
formatter_old f0(.*, .unified_state(old_form)); formatter_new f1(.*, .unified_state(new_form));
logic rst,stream_accept,state; logic [15:0] shapes; logic [191:0] source_window; logic [127:0] list_window;
logic [12:0] position,remaining_bytes; logic [7:0] prefix_bytes;
logic padding_reached,partial_beat,stream_last; logic [3:0] beat; logic [31:0] leaf;
wire old_valid,new_valid; wire [127:0] old_data,new_data;
stream_old s0(.*,.fetched_valid(old_valid),.stream_data(old_data));
stream_new s1(.*,.fetched_valid(new_valid),.stream_data(new_data));
int directed_forms=0,random_forms=0,stream_checks=0;
task random_nodes;
    for(int j=0;j<8;j++) begin
        block_address[j*32+:32]=$urandom;block_value[j*32+:32]=$urandom;block_right[j*32+:32]=$urandom;
        ctx_public_seed[j*32+:32]=$urandom;ctx_secret_seed[j*32+:32]=$urandom;return_key[j*32+:32]=$urandom;
    end
    for(int j=0;j<4;j++) identifier[j*32+:32]=$urandom;
endtask
initial begin
    rst=1; stream_accept=1; state=0; shapes=0;source_window=0;list_window=0;position=0;remaining_bytes=0;
    prefix_bytes=0;padding_reached=0;partial_beat=0;stream_last=0;beat=0;leaf=0;
    random_nodes();block_phase=0;block_step=0;block_shape=0;block_pair=0;
    for(int family=0;family<4;family++) for(int width=0;width<64;width++) for(int fmt=0;fmt<8;fmt++) begin
        @(negedge clk);block_family=2'(family);node_bytes=6'(width);block_format=3'(fmt);
        #1;if(old_form!==new_form)$fatal(1,"directed formatter mismatch");directed_forms++;
    end
    for(int i=0;i<100000;i++) begin
        @(negedge clk);
        random_nodes(); block_phase=7'($urandom);block_format=3'($urandom);block_family=2'($urandom);
        node_bytes=6'($urandom);block_step=4'($urandom);block_shape=4'($urandom);block_pair=1'($urandom);
        rst=($urandom_range(0,100)==0);stream_accept=1'($urandom);state=1'($urandom);shapes=16'($urandom);
        for(int j=0;j<6;j++) source_window[j*32+:32]=$urandom;
        for(int j=0;j<4;j++) list_window[j*32+:32]=$urandom;
        position=13'($urandom);remaining_bytes=13'($urandom);prefix_bytes=8'($urandom);
        padding_reached=1'($urandom);partial_beat=1'($urandom);stream_last=1'($urandom);beat=4'($urandom);leaf=$urandom;
        #1;if(old_form!==new_form)$fatal(1,"random formatter mismatch");random_forms++;
        @(posedge clk);#1;if(old_valid!==new_valid)$fatal(1,"stream valid mismatch");
        if(old_valid) begin if(old_data!==new_data)$fatal(1,"stream payload mismatch");stream_checks++;end
    end
    $display("PASS formatter_directed=%0d formatter_random=%0d stream_valid_checks=%0d",directed_forms,random_forms,stream_checks);$finish;
end
endmodule
