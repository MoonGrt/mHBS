`timescale 1ns/1ps
module tb_source_bank;
    localparam [15:0] RECIPE_MASK = 16'hffff;
    localparam [3:0] MESSAGE_PRF=3, MESSAGE_DIGEST=4, ROOT_MESSAGE=6,
        PREFIX_MESSAGE=11, ADDRESS_LIST=12, PREFIX_LIST=13;
    logic [15:0] shapes;
    logic [2:0] node_words;
    logic [255:0] secret_prf,randomizer,public_seed,root,address,list_data0;
    logic [127:0] identifier;
    logic [31:0] leaf;
    logic [695:0] message_buffer;
    wire [703:0] padded_message = {8'd0,message_buffer};
    function automatic [31:0] be32(input [31:0] value);
        be32={value[7:0],value[15:8],value[23:16],value[31:24]};
    endfunction
            function automatic [63:0] node_word(input [255:0] data, input [5:0] index);
                begin
                    case (index)
                        0: node_word = data[63:0];
                        1: node_word = data[127:64];
                        2: node_word = data[191:128];
                        3: node_word = data[255:192];
                        default: node_word = 0;
                    endcase
                end
            endfunction
            function automatic [63:0] message_word(input [5:0] index);
                begin
                    message_word = index < 11 ? padded_message[index*64+:64] : 64'd0;
                end
            endfunction
            function automatic [63:0] old_source_word(input [5:0] index, input bit lms_only);
                reg [2:0] source;
                reg [5:0] selected_index;
                reg [63:0] literal;
                begin
                    source = 0;
                    selected_index = index;
                    literal = 0;
                    (* parallel_case *) case (1'b1)
                        shapes[MESSAGE_PRF]:
                        if (!lms_only && RECIPE_MASK[MESSAGE_PRF]) begin
                            if (index < node_words) source = 1;
                            else if (index < 2 * node_words) begin
                                source = 2;
                                selected_index = index - node_words;
                            end else begin
                                source = 5;
                                selected_index = index - 2 * node_words;
                            end
                        end
                        shapes[MESSAGE_DIGEST]:
                        if (!lms_only && RECIPE_MASK[MESSAGE_DIGEST]) begin
                            if (index < node_words) source = 2;
                            else if (index < 2 * node_words) begin
                                source = 3;
                                selected_index = index - node_words;
                            end else if (index < 3 * node_words) begin
                                source = 4;
                                selected_index = index - 2 * node_words;
                            end else begin
                                source = 5;
                                selected_index = index - 3 * node_words;
                            end
                        end
                        shapes[ROOT_MESSAGE]:
                        if (!lms_only && RECIPE_MASK[ROOT_MESSAGE]) begin
                            if (index == 3) literal = 64'h0200000000000000;
                            else if (index < 4) literal = 0;
                            else if (index < 8) begin
                                source = 2;
                                selected_index = index - 4;
                            end else if (index < 12) begin
                                source = 4;
                                selected_index = index - 8;
                            end else if (index == 15) literal = {be32(leaf), 32'd0};
                            else if (index >= 16) begin
                                source = 5;
                                selected_index = index - 16;
                            end
                        end
                        shapes[PREFIX_MESSAGE]:
                        if (RECIPE_MASK[PREFIX_MESSAGE]) begin
                            // Unaligned 22-byte prefix: assemble three aligned words,
                            // then retain the fixed window starting two bytes later.
                            if (index >= 3 && index < 7) begin
                                source = 2;
                                selected_index = index - 3;
                            end else if (index >= 7) begin
                                source = 5;
                                selected_index = index - 7;
                            end
                        end
                        shapes[ADDRESS_LIST]:
                        if (!lms_only && RECIPE_MASK[ADDRESS_LIST]) begin
                            if (index < node_words) source = 3;
                            else if (index < node_words + 4) begin
                                source = 6;
                                selected_index = index - node_words;
                            end else begin
                                source = 7;
                                selected_index = index - node_words - 4;
                            end
                        end
                        shapes[PREFIX_LIST]:
                        if (!lms_only && RECIPE_MASK[PREFIX_LIST]) begin
                            case (index)
                                0: literal = identifier[63:0];
                                1: literal = identifier[127:64];
                                2: literal = {list_data0[15:0], 16'h8080, be32(leaf)};
                                3: literal = list_data0[79:16];
                                default: literal = 0;
                            endcase
                        end
                        default: begin
                        end
                    endcase
                    case (source)
                        1: old_source_word = node_word(secret_prf, selected_index);
                        2: old_source_word = node_word(randomizer, selected_index);
                        3: old_source_word = node_word(public_seed, selected_index);
                        4: old_source_word = node_word(root, selected_index);
                        5: old_source_word = message_word(selected_index);
                        6: old_source_word = node_word(address, selected_index);
                        7: old_source_word = node_word(list_data0, selected_index);
                        default: old_source_word = literal;
                    endcase
                end
            endfunction
            function automatic [63:0] new_source_word(input [5:0] index, input bit lms_only);
                reg [2:0] source;
                reg [5:0] selected_index;
                reg [63:0] literal;
                reg [255:0] selected_node;
                begin
                    source = 0;
                    selected_index = index;
                    literal = 0;
                    (* parallel_case *) case (1'b1)
                        shapes[MESSAGE_PRF]:
                        if (!lms_only && RECIPE_MASK[MESSAGE_PRF]) begin
                            if (index < node_words) source = 1;
                            else if (index < 2 * node_words) begin
                                source = 2;
                                selected_index = index - node_words;
                            end else begin
                                source = 5;
                                selected_index = index - 2 * node_words;
                            end
                        end
                        shapes[MESSAGE_DIGEST]:
                        if (!lms_only && RECIPE_MASK[MESSAGE_DIGEST]) begin
                            if (index < node_words) source = 2;
                            else if (index < 2 * node_words) begin
                                source = 3;
                                selected_index = index - node_words;
                            end else if (index < 3 * node_words) begin
                                source = 4;
                                selected_index = index - 2 * node_words;
                            end else begin
                                source = 5;
                                selected_index = index - 3 * node_words;
                            end
                        end
                        shapes[ROOT_MESSAGE]:
                        if (!lms_only && RECIPE_MASK[ROOT_MESSAGE]) begin
                            if (index == 3) literal = 64'h0200000000000000;
                            else if (index < 4) literal = 0;
                            else if (index < 8) begin
                                source = 2;
                                selected_index = index - 4;
                            end else if (index < 12) begin
                                source = 4;
                                selected_index = index - 8;
                            end else if (index == 15) literal = {be32(leaf), 32'd0};
                            else if (index >= 16) begin
                                source = 5;
                                selected_index = index - 16;
                            end
                        end
                        shapes[PREFIX_MESSAGE]:
                        if (RECIPE_MASK[PREFIX_MESSAGE]) begin
                            // Unaligned 22-byte prefix: assemble three aligned words,
                            // then retain the fixed window starting two bytes later.
                            if (index >= 3 && index < 7) begin
                                source = 2;
                                selected_index = index - 3;
                            end else if (index >= 7) begin
                                source = 5;
                                selected_index = index - 7;
                            end
                        end
                        shapes[ADDRESS_LIST]:
                        if (!lms_only && RECIPE_MASK[ADDRESS_LIST]) begin
                            if (index < node_words) source = 3;
                            else if (index < node_words + 4) begin
                                source = 6;
                                selected_index = index - node_words;
                            end else begin
                                source = 7;
                                selected_index = index - node_words - 4;
                            end
                        end
                        shapes[PREFIX_LIST]:
                        if (!lms_only && RECIPE_MASK[PREFIX_LIST]) begin
                            case (index)
                                0: literal = identifier[63:0];
                                1: literal = identifier[127:64];
                                2: literal = {list_data0[15:0], 16'h8080, be32(leaf)};
                                3: literal = list_data0[79:16];
                                default: literal = 0;
                            endcase
                        end
                        default: begin
                        end
                    endcase
                    // The six node sources share one word address. Select the
                    // node first, then extract one 64-bit word from that bank.
                    case (source)
                        1: selected_node = secret_prf;
                        2: selected_node = randomizer;
                        3: selected_node = public_seed;
                        4: selected_node = root;
                        6: selected_node = address;
                        7: selected_node = list_data0;
                        default: selected_node = 256'd0;
                    endcase
                    if (source == 5) new_source_word = message_word(selected_index);
                    else if (source == 0) new_source_word = literal;
                    else new_source_word = node_word(selected_node, selected_index);
                end
            endfunction
    integer seed_i, shape_i, words_i, index_i, lms_i, word_i, cases=0;
    task random_inputs;
        for (word_i=0;word_i<8;word_i=word_i+1) begin
            secret_prf[word_i*32+:32]=$random;
            randomizer[word_i*32+:32]=$random;
            public_seed[word_i*32+:32]=$random;
            root[word_i*32+:32]=$random;
            address[word_i*32+:32]=$random;
            list_data0[word_i*32+:32]=$random;
        end
        for (word_i=0;word_i<21;word_i=word_i+1)
            message_buffer[word_i*32+:32]=$random;
        message_buffer[695:672]=$random;
        identifier={$random,$random,$random,$random};
        leaf=$random;
    endtask
    initial begin
        for(seed_i=0;seed_i<32;seed_i=seed_i+1) begin
            random_inputs();
            for(shape_i=0;shape_i<16;shape_i=shape_i+1) begin
                shapes=16'b1<<shape_i;
                for(words_i=0;words_i<8;words_i=words_i+1) begin
                    node_words=3'(words_i);
                    for(index_i=0;index_i<64;index_i=index_i+1)
                        for(lms_i=0;lms_i<2;lms_i=lms_i+1) begin
                            if(old_source_word(6'(index_i),1'(lms_i)) !==
                               new_source_word(6'(index_i),1'(lms_i)))
                                $fatal(1,"source mismatch shape=%0d words=%0d index=%0d lms=%0d",shape_i,words_i,index_i,lms_i);
                            cases=cases+1;
                        end
                end
            end
        end
        $display("PASS actual scalar source functions: %0d cases",cases);
        $finish;
    end
endmodule
