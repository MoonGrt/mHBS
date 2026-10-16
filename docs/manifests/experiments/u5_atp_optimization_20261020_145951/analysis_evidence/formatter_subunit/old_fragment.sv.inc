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
