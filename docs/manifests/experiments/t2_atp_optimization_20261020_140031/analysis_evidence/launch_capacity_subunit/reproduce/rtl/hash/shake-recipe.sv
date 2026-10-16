`ifndef MHBS_SHA2
`timescale 1ns / 1ps
`default_nettype none
// ABI 4 byte recipes: scalar execution for P1, scheduled contexts for P>1.
// Requests and their shared coordinates stay stable until results are consumed.
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
    // Shared pure formatting helpers. Execution state, registers and handshake
    // timing remain local to the scalar and scheduled implementations.
    wire [703:0] padded_message = {8'd0, message_buffer};
    localparam [3:0] ADDRESS_SEED = 1, ADDRESS_VALUE = 2, MESSAGE_PRF = 3,
        MESSAGE_DIGEST = 4, INDEX_PRF = 5, ROOT_MESSAGE = 6, MASKED_SEED = 7,
        MASKED_VALUE = 8, PREFIX_SEED = 9, PREFIX_VALUE = 10, PREFIX_MESSAGE = 11,
        ADDRESS_LIST = 12, PREFIX_LIST = 13, PREFIX_LEAF = 14, PREFIX_PARENT = 15;
    localparam bit STREAM_ENABLE = (RECIPE_MASK & 16'h3858) != 0;
    localparam logic [1:0] HASH_IDLE = 2'd0;
    localparam logic [1:0] HASH_WAIT_BLOCK = 2'd1;
    localparam logic [1:0] HASH_RUN = 2'd2;
    function automatic [31:0] be32(input [31:0] value);
        be32 = {value[7:0], value[15:8], value[23:16], value[31:24]};
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
    function automatic [63:0] node_word_indexed(input [255:0] data, input [1:0] index);
        begin
            case (index)
                0: node_word_indexed = data[63:0];
                1: node_word_indexed = data[127:64];
                2: node_word_indexed = data[191:128];
                default: node_word_indexed = data[255:192];
            endcase
        end
    endfunction
    function automatic [63:0] message_word(input [5:0] index);
        begin
            message_word = index < 11 ? padded_message[index*64+:64] : 64'd0;
        end
    endfunction
    function automatic [12:0] decode_length(input [63:0] desc);
        reg [12:0] nodes;
        begin
            nodes = node_bytes == 16 ? {1'b0, desc[47:40], 4'b0} :
                node_bytes == 24 ? ({1'b0, desc[47:40], 4'b0} + {2'b0, desc[47:40], 3'b0}) :
                {desc[47:40], 5'b0};
            if (!STREAM_ENABLE || !RECIPE_MASK[desc[59:56]]) decode_length = 0;
            else
                case (desc[59:56])
                    ADDRESS_SEED: decode_length = PIPELINE == 1 ? node_bytes + 32 + node_bytes : 13'd0;
                    ADDRESS_VALUE: decode_length = PIPELINE == 1 ? node_bytes + 32 + nodes : 13'd0;
                    ADDRESS_LIST: decode_length = node_bytes + 32 + nodes;
                    MESSAGE_PRF: decode_length = 2 * node_bytes + message_length;
                    MESSAGE_DIGEST: decode_length = 3 * node_bytes + message_length;
                    INDEX_PRF: decode_length = PIPELINE == 1 ? 96 : 13'd0;
                    ROOT_MESSAGE: decode_length = 128 + message_length;
                    MASKED_SEED: decode_length = PIPELINE == 1 ? 128 : 13'd0;
                    MASKED_VALUE: decode_length = PIPELINE == 1 ? 13'd64 + {desc[47:40], 5'd0} : 13'd0;
                    PREFIX_SEED, PREFIX_VALUE: decode_length = PIPELINE == 1 ? 55 : 13'd0;
                    PREFIX_MESSAGE: decode_length = 54 + message_length;
                    PREFIX_LIST: decode_length = 13'd22 + {desc[47:40], 5'd0};
                    PREFIX_LEAF: decode_length = PIPELINE == 1 ? 54 : 13'd0;
                    PREFIX_PARENT: decode_length = PIPELINE == 1 ? 86 : 13'd0;
                    default: decode_length = 0;
                endcase
        end
    endfunction
    function automatic [12:0] decode_source(input [5:0] index, input bit lms_only,
        input [15:0] shapes, input [2:0] node_words);
        reg [2:0] source;
        reg [5:0] selected_index;
        reg [3:0] literal;
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
                    if (index == 3) literal = 4'd1;
                    else if (index < 4) literal = 0;
                    else if (index < 8) begin
                        source = 2;
                        selected_index = index - 4;
                    end else if (index < 12) begin
                        source = 4;
                        selected_index = index - 8;
                    end else if (index == 15) literal = 4'd2;
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
                        0: literal = 4'd3;
                        1: literal = 4'd4;
                        2: literal = 4'd5;
                        3: literal = 4'd6;
                        default: literal = 0;
                    endcase
                end
                default: begin
                end
            endcase
            decode_source = {literal, source, selected_index};
        end
    endfunction
    function automatic [63:0] source_literal(input [3:0] code, input [31:0] leaf,
        input [127:0] id, input [N*8-1:0] first_node);
        begin
            case (code)
                1: source_literal = 64'h0200000000000000;
                2: source_literal = {be32(leaf), 32'd0};
                3: source_literal = id[63:0];
                4: source_literal = id[127:64];
                5: source_literal = {first_node[15:0], 16'h8080, be32(leaf)};
                6: source_literal = first_node[79:16];
                default: source_literal = 0;
            endcase
        end
    endfunction
    function automatic [511:0] list_nodes(input [5:0] bytes_per_node,
        input [N*8-1:0] first_node, second_node);
        begin
            case (bytes_per_node)
                16: list_nodes = {256'd0, second_node[127:0], first_node[127:0]};
                24: list_nodes = {128'd0, second_node[191:0], first_node[191:0]};
                default: list_nodes = {second_node, first_node};
            endcase
        end
    endfunction
    function automatic [143:0] list_words(input [511:0] nodes, input [1:0] index);
        begin
            case (index)
                0: list_words = nodes[143:0];
                1: list_words = nodes[207:64];
                2: list_words = nodes[271:128];
                default: list_words = nodes[335:192];
            endcase
        end
    endfunction
    function automatic [255:0] make_address(input [4:0] layer, input [63:0] tree,
        input [31:0] leaf, input [7:0] domain, input [31:0] a, b);
        make_address = {be32(b), be32(a), be32(leaf), be32({24'd0, domain}),
            be32(tree[31:0]), be32(tree[63:32]), 32'd0, be32({27'd0, layer})};
    endfunction

    generate
        if (PIPELINE == 1) begin : scalar_execution
            localparam bit MASKED_ENABLE = RECIPE_MASK[MASKED_VALUE];
            typedef enum logic [2:0] {
                IDLE,
                START,
                STREAM,
                WAIT_HASH,
                RESPONSE
            } state_t;
            state_t state;
            wire chain_feedback_valid;
            wire [3:0] chain_feedback_counter;
            logic seed_phase;
            logic [4:0] iteration;
            logic [1:0] compound;
            // XMSS retains its value across key/mask hashes. SLH
            // chains instead reuse the sponge's retained digest at the next START.
            logic [N*8-1:0] chain_value, temporary_key;
            wire [N*8-1:0] current_value = MASKED_ENABLE ? chain_value :
                seed_phase ? request_left : digest[N*8-1:0];
            logic [4:0] rate_block;
            logic [3:0] beat;
            logic stream_half;
            wire [63:0]
                recipe = request_chain && !seed_phase ? request_step_recipe : request_recipe;
            logic [15:0] seed_shapes, step_shapes;
            logic [12:0] seed_length, step_length;
            logic [2:0] stream_node_words;
            wire [15:0] shapes = request_chain && !seed_phase ? step_shapes : seed_shapes;
            // Decode lengths once in the existing request stage. In particular the
            // ADDRESS_LIST arity/24-byte-node addition must not feed every padding
            // byte comparator during STREAM. Request fields remain stable until the
            // response, but their registered decode cuts that wide data-path cone.
            always_ff @(posedge clk) begin
                if (!rst && state == IDLE && request_valid) begin
                    seed_shapes <= (16'b1 << request_recipe[59:56]) & RECIPE_MASK;
                    step_shapes <= (16'b1 << request_step_recipe[59:56]) & RECIPE_MASK;
                    seed_length <= decode_length(request_recipe);
                    step_length <= decode_length(request_step_recipe);
                    stream_node_words <= node_bytes[5:3];
                end
            end
            wire [7:0] domain = recipe[55:48];
            wire [7:0] arity = recipe[47:40];
            wire compact_chain = RECIPE_MASK[ADDRESS_SEED] && request_chain &&
                request_recipe[59:56] == ADDRESS_SEED;
            wire [31:0] a = request_a;
            wire [31:0] b = chain_feedback_valid ?
                (request_step_recipe[55:48] == 3 ? request_b : {28'd0, chain_feedback_counter}) :
                request_chain && !seed_phase ?
                (request_step_recipe[55:48] == 3 && request_step_recipe[59:56] == ADDRESS_VALUE ?
                 request_b : {27'd0, iteration}) : request_b;
            wire [N*8-1:0] left_value = request_chain ? current_value : request_left;
            wire [7:0] address_domain = chain_feedback_valid ? request_step_recipe[55:48] : domain;
            wire [31:0] leaf = {12'd0, request_leaf};
            wire [12:0] input_length = MASKED_ENABLE && shapes[MASKED_VALUE] && compound <
                arity + 1 ? 13'd96 : request_chain && !seed_phase ? step_length : seed_length;
            wire [5:0] stream_node_bytes = {stream_node_words, 3'b0};
            logic [1087:0] fast_block;
            logic [127:0] stream_data;
            logic [255:0] address, masked_address;
            wire fixed_block = ((RECIPE_MASK & 16'h3858) == 0 || shapes[ADDRESS_SEED] ||
                                shapes[ADDRESS_VALUE] || shapes[INDEX_PRF] || shapes[MASKED_SEED] ||
                                shapes[MASKED_VALUE] || shapes[PREFIX_SEED] || shapes[
                                PREFIX_VALUE] || shapes[PREFIX_LEAF] || shapes[PREFIX_PARENT]);
            wire [12:0] rate_offset = ({8'd0, rate_block} << 7) + ({8'd0, rate_block} << 3);
            wire stream_last = rate_offset + 13'd136 > input_length;
            wire hash_ready, block_ready, fast_ready, finish_valid;
            wire [DIGEST_BYTES*8-1:0] digest, finish_digest;
            wire [N*8-1:0] compact_capture;
            logic hash_error;
            wire completed = finish_valid;
            wire [DIGEST_BYTES*8-1:0] completed_value = finish_digest;
            assign response_value = fixed_block ?
                {{(DIGEST_BYTES * 8 - N * 8) {1'b0}}, digest[N*8-1:0]} : digest;
            assign response_capture = compact_capture;
            // Capture both chain modes in the sponge's existing register bank, on
            // the same final-round edge used by the former lane-local copy.
            wire capture_single = request_capture &&
                !(MASKED_ENABLE && shapes[MASKED_VALUE] && compound < arity + 1) &&
                (seed_phase ? request_capture_after == 0 : request_capture_after == iteration + 1);
            wire [7:0] prefix_bytes = shapes[ADDRESS_LIST] ? stream_node_bytes + 32 : 22;
            logic staged_valid, staged_last;
            logic [127:0] staged_data;
            wire stream_accept = !staged_valid || block_ready;
            // A scalar producer emits eight bytes per cycle into the existing
            // sixteen-byte absorb staging register.
            // Keeping a cursor avoids a rate_block*136 + beat*16 adder chain
            // ahead of the source selector and each padding-byte comparator.
            logic [12:0] position;
            logic [INDEX_BITS-1:0] list_cursor;
            logic [5:0] list_remainder;
            wire [4:0] stream_advance = 5'd8;
            wire [6:0] next_remainder = {1'b0, list_remainder} + stream_advance;
            assign list_index0 = list_cursor;
            assign list_next_index0 = state == IDLE && request_valid ? INDEX_BITS'(0) :
                state == STREAM && stream_accept && position >= prefix_bytes &&
                next_remainder >= stream_node_bytes ? list_cursor + 1'b1 : list_cursor;
            assign list_index1 = list_index0 + 1'b1;
            assign request_ready = state == IDLE;
            assign response_valid = state == RESPONSE;

            // All sponge beats start on an eight-byte boundary. Select two words
            // directly instead of shifting a maximum-size concatenated message frame.
            wire [2:0] node_words = stream_node_words;
            // Select a source and a small word address BEFORE the wide data mux.
            // All recipes share the same message/seed selectors instead of each
            // recipe instantiating its own variable 64-bit extraction network.
            // Prepare the next eight-byte beat's small selectors while emitting
            // the current beat. START provides the first selectors; backpressure
            // holds both selectors and position without another data stage.
            logic [12:0] source_control[0:1];
            wire [12:0] following_position = position + 13'(stream_advance);
            for (genvar word_slot = 0; word_slot < 2; word_slot++) begin : source_selectors
                always_ff @(posedge clk)
                    if (!rst) begin
                        if (state == START && hash_ready)
                            source_control[word_slot] <= decode_source(
                                6'(word_slot), word_slot != 0, shapes, node_words
                            );
                        else if (state == STREAM && stream_accept)
                            source_control[word_slot] <= decode_source(
                                following_position[8:3] + 6'(word_slot), word_slot != 0, shapes, node_words
                            );
                    end
            end
            function automatic [63:0] source_word(input [12:0] control);
                reg [5:0] selected_index;
                reg [63:0] literal;
                begin
                    selected_index = control[5:0];
                    literal = source_literal(control[12:9], leaf, identifier, list_data0);
                    // Source-range decoding bounds live node reads to four words;
                    // ADDRESS_LIST body beats use list_window instead.
                    case (control[8:6])
                        1: source_word = node_word_indexed(secret_prf, selected_index[1:0]);
                        2: source_word = node_word_indexed(randomizer, selected_index[1:0]);
                        3: source_word = node_word_indexed(public_seed, selected_index[1:0]);
                        4: source_word = node_word_indexed(root, selected_index[1:0]);
                        5: source_word = message_word(selected_index);
                        6: source_word = node_word_indexed(address, selected_index[1:0]);
                        7: source_word = node_word_indexed(list_data0, selected_index[1:0]);
                        default: source_word = literal;
                    endcase
                end
            endfunction
            logic [511:0] list_pair;
            always @* begin
                list_pair = list_nodes(stream_node_bytes, list_data0, list_data1);
            end
            // Legal list offsets are whole 64-bit words (SLH), or two bytes
            // beyond a word (LMS's 22-byte prefix). No general byte barrel shifter.
            logic [143:0] list_word_window;
            always @* begin
                list_word_window = list_words(list_pair, list_remainder[4:3]);
            end
            // SLH nodes and prefixes are eight-byte aligned. A beat never crosses
            // a node boundary; do not retain the legacy two-node byte window.
            wire [127:0] list_window = RECIPE_MASK[PREFIX_LIST] ?
                (list_remainder[1] ? {64'd0, list_word_window[79:16]} :
                 {64'd0, list_word_window[63:0]}) : {64'd0, node_word(
                list_data0, {4'd0, list_remainder[4:3]}
            )};
            logic [127:0] stream_payload;
            logic [127:0] source_window;
            always_comb begin
                source_window = {
                    source_word(source_control[1]),
                    source_word(source_control[0])
                };
                stream_payload = {64'd0, source_window[63:0]};
                if (shapes[PREFIX_MESSAGE]) begin
                    stream_payload = {64'd0, source_window[79:16]};
                    if (position == 0) stream_payload = {64'd0, identifier[63:0]};
                    else if (position == 8) stream_payload[63:0] = identifier[127:64];
                    else if (position == 16) stream_payload[47:0] = {16'h8181, be32(leaf)};
                end else
                    if ((shapes[ADDRESS_LIST] || shapes[PREFIX_LIST]) && position >= prefix_bytes)
                    stream_payload = list_window;
            end

            integer i;
            always @* begin
                address = make_address(request_layer, request_tree, leaf, address_domain, a, b);
                masked_address = {
                    be32(compound), be32(b), be32(a), be32(leaf), be32(domain), 96'd0
                };
            end
            // Select shared frame fields before alignment. This avoids replicating
            // every seed/value/key/mask selector for all three node lengths.
            logic [255:0] frame0, frame1, frame2, frame3;
            logic [183:0] frame_prefix;
            logic [7:0] frame_domain;
            logic frame_two;
            logic [2:0] frame_layout;
            always @* begin
                frame0 = 0;
                frame1 = 0;
                frame2 = 0;
                frame3 = 0;
                frame_prefix = 0;
                frame_domain = 0;
                frame_two = 0;
                frame_layout = 7;
                (* parallel_case *) case (1'b1)
                    shapes[ADDRESS_SEED], shapes[ADDRESS_VALUE]:
                    if (RECIPE_MASK[ADDRESS_SEED] || RECIPE_MASK[ADDRESS_VALUE]) begin
                        frame_layout = 0;
                        frame0 = public_seed;
                        frame1 = address;
                        frame2 = chain_feedback_valid ? finish_digest[N*8-1:0] :
                            shapes[ADDRESS_SEED] ? secret_seed : left_value;
                        frame_two = !chain_feedback_valid && shapes[ADDRESS_VALUE] && arity == 2;
                        frame3 = frame_two ? request_right : 256'd0;
                    end
                    shapes[INDEX_PRF]:
                    if (RECIPE_MASK[INDEX_PRF]) begin
                        frame_layout = 1;
                        frame_domain = 3;
                        frame1 = secret_prf;
                        frame2 = {be32(leaf), 224'd0};
                    end
                    shapes[MASKED_SEED]:
                    if (RECIPE_MASK[MASKED_SEED]) begin
                        frame_layout = 2;
                        frame_domain = 4;
                        frame1 = secret_seed;
                        frame2 = public_seed;
                        frame3 = masked_address;
                    end
                    shapes[MASKED_VALUE]:
                    if (MASKED_ENABLE) begin
                        if (compound < arity + 1) begin
                            frame_layout = 1;
                            frame_domain = 3;
                            frame1 = public_seed;
                            frame2 = masked_address;
                        end else begin
                            frame_layout = 3;
                            frame_domain = arity - 1'b1;
                            frame1 = temporary_key;
                            // MASK0 already masked the retained left value in place.
                            frame2 = chain_value;
                            frame_two = arity == 2;
                            // MASK1 is the retained sponge digest until this FINAL launch.
                            frame3 = frame_two ? request_right ^ digest[N*8-1:0] : 256'd0;
                        end
                    end
                    shapes[PREFIX_SEED], shapes[PREFIX_VALUE]:
                    if (RECIPE_MASK[PREFIX_SEED] || RECIPE_MASK[PREFIX_VALUE]) begin
                        frame_layout = 4;
                        frame_prefix = {
                            shapes[PREFIX_SEED] ? 8'hff : b[7:0],
                            8'(request_a),
                            8'd0,
                            be32(leaf),
                            identifier
                        };
                        frame1 = shapes[PREFIX_SEED] ? secret_seed : left_value;
                    end
                    shapes[PREFIX_LEAF], shapes[PREFIX_PARENT]:
                    if (RECIPE_MASK[PREFIX_LEAF] || RECIPE_MASK[PREFIX_PARENT]) begin
                        frame_layout = 5;
                        frame_prefix = {
                            8'd0,
                            shapes[PREFIX_LEAF] ? 16'h8282 : 16'h8383,
                            be32(request_b),
                            identifier
                        };
                        frame1 = left_value;
                        frame_two = shapes[PREFIX_PARENT];
                        frame2 = frame_two ? request_right : 256'd0;
                    end
                    default: begin
                    end
                endcase
            end
            always @* begin
                fast_block = 0;
                case (node_bytes)
                    16: begin
                        fast_block[0+:128] = public_seed[127:0];
                        fast_block[128+:256] = address;
                        fast_block[384+:128] = chain_feedback_valid ? finish_digest[127:0] :
                            shapes[ADDRESS_SEED] ? secret_seed[127:0] : left_value[127:0];
                        if (shapes[ADDRESS_VALUE] && arity == 2) begin
                            fast_block[512+:128] = request_right[127:0];
                            fast_block[640+:8]   = 8'h1f;
                        end else fast_block[512+:8] = 8'h1f;
                    end
                    24: begin
                        fast_block[0+:192] = public_seed[191:0];
                        fast_block[192+:256] = address;
                        fast_block[448+:192] = chain_feedback_valid ? finish_digest[191:0] :
                            shapes[ADDRESS_SEED] ? secret_seed[191:0] : left_value[191:0];
                        if (shapes[ADDRESS_VALUE] && arity == 2) begin
                            fast_block[640+:192] = request_right[191:0];
                            fast_block[832+:8]   = 8'h1f;
                        end else fast_block[640+:8] = 8'h1f;
                    end
                    32:
                    case (frame_layout)
                        0: begin
                            fast_block[0+:256]   = frame0[255:0];
                            fast_block[256+:256] = frame1;
                            fast_block[512+:256] = frame2[255:0];
                            fast_block[768+:256] = frame3[255:0];
                            if (frame_two) fast_block[1024+:8] = 8'h1f;
                            else fast_block[768+:8] = 8'h1f;
                        end
                        1: begin
                            fast_block[248+:8]   = frame_domain;
                            fast_block[256+:256] = frame1[255:0];
                            fast_block[512+:256] = frame2;
                            fast_block[768+:8]   = 8'h1f;
                        end
                        2: begin
                            fast_block[248+:8]   = frame_domain;
                            fast_block[256+:256] = frame1[255:0];
                            fast_block[512+:256] = frame2[255:0];
                            fast_block[768+:256] = frame3;
                            fast_block[1024+:8]  = 8'h1f;
                        end
                        3: begin
                            fast_block[248+:8]   = frame_domain;
                            fast_block[256+:256] = frame1[255:0];
                            fast_block[512+:256] = frame2[255:0];
                            fast_block[768+:256] = frame3[255:0];
                            if (frame_two) fast_block[1024+:8] = 8'h1f;
                            else fast_block[768+:8] = 8'h1f;
                        end
                        4: begin
                            fast_block[183:0] = frame_prefix;
                            fast_block[184+:256] = frame1[255:0];
                            fast_block[440+:8] = 8'h1f;
                        end
                        5: begin
                            fast_block[175:0] = frame_prefix[175:0];
                            fast_block[176+:256] = frame1[255:0];
                            fast_block[432+:256] = frame2[255:0];
                            if (frame_two) fast_block[688+:8] = 8'h1f;
                            else fast_block[432+:8] = 8'h1f;
                        end
                        default: begin
                        end
                    endcase
                    default: begin
                    end
                endcase
                fast_block[1087] = 1'b1;
            end
            // Share one remaining-length subtraction across the eight output
            // bytes instead of adding position to each byte's comparison index.
            wire [12:0] remaining_bytes = input_length - position;
            wire padding_reached = position > input_length;
            wire partial_beat = remaining_bytes < 8;
            always_comb begin
                stream_data = {64'd0, stream_payload[63:0]};
                for (i = 0; i < 8; i = i + 1) begin
                    if (padding_reached || (partial_beat && remaining_bytes[2:0] <= 3'(i)))
                        stream_data[i*8+:8] = 0;
                    if (!padding_reached && partial_beat && remaining_bytes[2:0] == 3'(i))
                        stream_data[i*8+:8] = 8'h1f;
                    if (beat == 8 && stream_last && i == 7)
                        stream_data[i*8+7] = 1'b1;
                end
            end

            assign batch_request_ready = 1'b0;
            assign batch_response_valid = 1'b0;
            assign batch_response_tag = '0;
            assign batch_response_digest = '0;
            assign batch_response_capture = '0;
            assign batch_read_digest = '0;
            assign batch_read_capture = '0;
`ifndef SYNTHESIS
            assign batch_hashes = 64'd0;
            assign batch_permutations = 64'd0;
`endif

            // One iterative Keccak state serves fixed blocks, chains and streams.
            logic [1:0] hash_state;
            logic saved_chain_enable, saved_chain_prefix;
            logic saved_chain_prefix_preserve_counter, saved_capture_enable;
            logic [4:0] saved_chain_count, saved_capture_after;
            logic first_block, running_last;
            logic [3:0] append_index;
            logic [1599:0] sponge_state;
            logic [4:0] chains_remaining, chain_iteration, round_index;
            logic [3:0] chain_counter;
            logic [N*8-1:0] captured_value;
            wire [3:0] counter_next = chain_counter + 1'b1;
            wire [3:0] transition_counter = saved_chain_prefix && chain_iteration == 1 ?
                chain_counter : counter_next;
            wire [1599:0] rounds[0:UNROLL];
            assign rounds[0] = sponge_state;
            for (genvar r = 0; r < UNROLL; r = r + 1) begin : unrolled
                // verilog_format: off
                (* keep_hierarchy="yes" *) keccak round_logic(.state_in(rounds[r]),
                    .round_index(round_index+5'(r)),.state_out(rounds[r+1]));
                // verilog_format: on
            end
            wire [1599:0] advanced_state = rounds[UNROLL];
            wire round_complete = round_index + UNROLL >= 24;
            wire round_update = hash_state == HASH_RUN;
            wire permutation_complete = round_update && round_complete;
            assign hash_ready = hash_state == HASH_IDLE;
            assign block_ready = hash_state == HASH_WAIT_BLOCK;
            assign fast_ready = (hash_state == HASH_IDLE && state == START) ||
                (hash_state == HASH_WAIT_BLOCK && first_block && append_index == 0);
            assign digest = sponge_state[DIGEST_BYTES*8-1:0];
            assign finish_valid = permutation_complete &&
                (!saved_chain_enable || chains_remaining <= 1) && running_last;
            assign finish_digest = advanced_state[DIGEST_BYTES*8-1:0];
            assign compact_capture = captured_value;

`ifndef SYNTHESIS
            initial begin
                if (UNROLL < 1 || UNROLL > 24 || 24 % UNROLL != 0)
                    $error("recipe scalar execution requires U dividing 24");
            end
`endif
            wire take_fast = state == START && fixed_block && fast_ready;
            wire take_stream = hash_state == HASH_WAIT_BLOCK && !take_fast && staged_valid;
            wire clear_stream = take_stream && first_block && append_index == 0;
            wire take_feedback = permutation_complete && saved_chain_enable && chains_remaining > 1;
            assign chain_feedback_valid   = take_feedback;
            assign chain_feedback_counter = transition_counter;
            logic [127:0] previous_rate;
            always_comb begin
                case (append_index)
                    0: previous_rate = sponge_state[0+:128];
                    1: previous_rate = sponge_state[128+:128];
                    2: previous_rate = sponge_state[256+:128];
                    3: previous_rate = sponge_state[384+:128];
                    4: previous_rate = sponge_state[512+:128];
                    5: previous_rate = sponge_state[640+:128];
                    6: previous_rate = sponge_state[768+:128];
                    7: previous_rate = sponge_state[896+:128];
                    default: previous_rate = {64'd0, sponge_state[1024+:64]};
                endcase
            end
            wire [127:0] absorbed_block = staged_data ^ (previous_rate & {128{!clear_stream}});
            for (genvar w = 0; w < 25; w = w + 1) begin : state_words
                wire select_stream = w < 17 && take_stream && append_index == w / 2;
                wire [63:0] fast_word;
                if (w < 17) assign fast_word = fast_block[w*64+:64];
                else assign fast_word = 64'd0;
                wire [63:0]
                    absorb_word = w % 2 == 0 ? absorbed_block[63:0] : absorbed_block[127:64];
                // These sources are disjoint in the hash FSM. Initialization
                // clears unselected words by enabling a write with no source.
                wire [63:0] next_word =
                    (fast_word & {64{take_fast || take_feedback}}) |
                    (absorb_word & {64{select_stream}}) |
                    (advanced_state[w*64+:64] & {64{round_update && !take_feedback}});
                always_ff @(posedge clk)
                    if (!rst && (round_update || take_fast || select_stream || clear_stream))
                        sponge_state[w*64+:64] <= next_word;
            end

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
                        HASH_IDLE:
                        if ((state == START)) begin
                            saved_chain_enable <= compact_chain;
                            saved_chain_prefix <= compact_chain;
                            saved_chain_prefix_preserve_counter <=
                                (request_step_recipe[55:48] == 3);
                            saved_chain_count <= (request_steps + 5'd1);
                            saved_capture_enable <=
                                (compact_chain ? request_capture : capture_single);
                            saved_capture_after <=
                                (compact_chain ? request_capture_after + 5'd1 : 5'd1);
                            first_block <= 1'b1;
                            append_index <= 0;
                            if ((state == START && fixed_block)) begin
                                running_last <= 1'b1;
                                chains_remaining <= compact_chain ? (request_steps + 5'd1) : 5'd1;
                                chain_counter <= 0;
                                chain_iteration <= 1;
                                round_index <= 0;
                                hash_state <= HASH_RUN;
                            end else hash_state <= HASH_WAIT_BLOCK;
                        end
                        HASH_WAIT_BLOCK:
                        if ((state == START && fixed_block) && fast_ready) begin
                            // Generic pre-padded one-rate-block path.  The recipe
                            // executor builds fixed-format blocks while this lane is
                            // idle, avoiding nine serial append cycles per context.
                            running_last <= 1'b1;
                            chains_remaining <= saved_chain_enable ? saved_chain_count : 5'd1;
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
                                    chains_remaining <= saved_chain_enable ? saved_chain_count :
                                        5'd1;
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
                                if (saved_capture_enable && saved_capture_after == chain_iteration)
                                    captured_value <= advanced_state[N*8-1:0];
                                if (saved_chain_enable && chains_remaining > 1) begin
                                    chains_remaining <= chains_remaining - 1'b1;
                                    if (!saved_chain_prefix_preserve_counter &&
                                        !(saved_chain_prefix && chain_iteration == 1))
                                        chain_counter <= chain_counter + 1'b1;
                                    chain_iteration <= chain_iteration + 1'b1;
                                    round_index <= 0;
                                end else begin
                                    if (running_last) begin
                                        hash_state <= HASH_IDLE;
                                    end else begin
                                        first_block <= 1'b0;
                                        hash_state  <= HASH_WAIT_BLOCK;
                                    end
                                end
                            end else begin
                                round_index <= round_index + UNROLL;
                            end
                        end
                        default: hash_state <= HASH_IDLE;
                    endcase
                end
            end
            always_ff @(posedge clk) begin
                if (rst) begin
                    staged_valid <= 0;
                    staged_last <= 0;
                    staged_data <= 0;
                    position <= 0;
                    list_cursor <= 0;
                    list_remainder <= 0;
                    state <= IDLE;
                    error <= 0;
                    seed_phase <= 1;
                    iteration <= 0;
                    compound <= 0;
                    rate_block <= 0;
                    beat <= 0;
                    stream_half <= 0;
                end else begin
                    if (STREAM_ENABLE && staged_valid && block_ready) staged_valid <= 0;
                    if (hash_error) begin
                        error <= 1;
                        state <= RESPONSE;
                    end else
                        case (state)
                            IDLE:
                            if (request_valid) begin
                                staged_valid <= 0;
                                position <= 0;
                                list_cursor <= 0;
                                list_remainder <= 0;
                                error <= 0;
                                seed_phase <= 1;
                                iteration <= 0;
                                compound <= 0;
                                chain_value <= request_left;
                                rate_block <= 0;
                                beat <= 0;
                                stream_half <= 0;
                                state <= START;
                            end
                            START:
                            if (hash_ready) begin
                                state <= fixed_block ? WAIT_HASH : STREAM;
                            end
                            STREAM:
                            if (STREAM_ENABLE && stream_accept) begin
                                position <= position + 13'(stream_advance);
                                if (stream_half) staged_data[127:64] <= stream_data[63:0];
                                else staged_data[63:0] <= stream_data[63:0];
                                staged_valid <= stream_half || beat == 8;
                                staged_last  <= stream_last;
                                if (beat == 8) staged_data[127:64] <= 0;
                                stream_half <= beat == 8 ? 1'b0 : !stream_half;
                                begin
                                    if (position < prefix_bytes) begin
                                        if (position + stream_advance >= prefix_bytes)
                                            list_remainder <= position + stream_advance -
                                                prefix_bytes;
                                    end else if (next_remainder >= stream_node_bytes) begin
                                        list_remainder <= next_remainder - stream_node_bytes;
                                        list_cursor <= list_cursor + 1'b1;
                                    end else list_remainder <= next_remainder;
                                end
                                if (beat == 8) begin
                                    beat <= 0;
                                    if (stream_last) state <= WAIT_HASH;
                                    else rate_block <= rate_block + 1'b1;
                                end else if (stream_half) beat <= beat + 1'b1;
                            end
                            WAIT_HASH:
                            if (completed) begin
                                if (compact_chain) begin
                                    state <= RESPONSE;
                                end else if (MASKED_ENABLE && shapes[MASKED_VALUE] &&
                                             compound < arity + 1) begin
                                    case (compound)
                                        0: temporary_key <= completed_value[N*8-1:0];
                                        // The unmasked value dies at MASK0 completion.
                                        1: chain_value <= left_value ^ completed_value[N*8-1:0];
                                        // MASK1 stays in sponge_state until FINAL reads it.
                                        default: begin end
                                    endcase
                                    compound <= compound + 1'b1;
                                    state <= START;
                                end else begin
                                    compound <= 0;
                                    chain_value <= completed_value[N*8-1:0];
                                    if (request_chain && (seed_phase ? request_steps != 0 :
                                                          iteration + 1 < request_steps)) begin
                                        seed_phase <= 0;
                                        if (!seed_phase) iteration <= iteration + 1'b1;
                                        state <= START;
                                    end else begin
                                        state <= RESPONSE;
                                    end
                                end
                            end
                            RESPONSE: if (response_ready) state <= IDLE;
                            default:  state <= IDLE;
                        endcase
                end
            end

`ifndef SYNTHESIS
            // Statistics are observers; no diagnostic state drives the execution FSM.
            always_ff @(posedge clk) begin : debug_statistics
                if (rst) begin
                    hash_count <= 64'd0;
                    permutation_count <= 64'd0;
                end else begin
                    if (state == START && hash_ready) begin
                        hash_count <= hash_count +
                            (compact_chain ? 64'(request_steps) + 64'd1 : 64'd1);
                        if (fixed_block)
                            permutation_count <= permutation_count +
                                (compact_chain ? 64'(request_steps) + 64'd1 : 64'd1);
                    end
                    if (state == STREAM && STREAM_ENABLE && stream_accept && beat == 8)
                        permutation_count <= permutation_count + 64'd1;
                end
            end
`endif
        end else begin : scheduled_execution
            typedef enum logic [2:0] {
                IDLE,
                START,
                STREAM,
                WAIT_HASH,
                RESPONSE,
                FIXED_WAIT
            } state_t;
            // Mode ownership and stream lookahead both feed caller handshakes.
            // Keep their phase bits directly registered rather than decoding a
            // compact state before the scheduler and next RAM address logic.
            (* fsm_encoding="one_hot" *) state_t state;
            logic [3:0] beat;
            wire [63:0] recipe = request_recipe;
            logic [15:0] seed_shapes;
            logic [12:0] seed_length;
            logic [2:0] stream_node_words;
            wire [15:0] shapes = seed_shapes;
            // Decode lengths once in the existing request stage. In particular the
            // ADDRESS_LIST arity/24-byte-node addition must not feed every padding
            // byte comparator during STREAM. Request fields remain stable until the
            // response, but their registered decode cuts that wide data-path cone.
            always_ff @(posedge clk) begin
                if (!rst && state == IDLE && request_valid) begin
                    seed_shapes <= (16'b1 << request_recipe[59:56]) & RECIPE_MASK;
                    seed_length <= decode_length(request_recipe);
                    stream_node_words <= node_bytes[5:3];
                end
            end
            wire [7:0] domain = recipe[55:48];
            wire [31:0] a = request_a, b = request_b;
            wire [31:0] leaf = {12'd0, request_leaf};
            wire [12:0] input_length = seed_length;
            wire [5:0] stream_node_bytes = {stream_node_words, 3'b0};
            logic [127:0] stream_data;
            wire [255:0] address = make_address(request_layer, request_tree, leaf, domain, a, b);
            wire hash_ready, block_ready, finish_valid;
            wire [DIGEST_BYTES*8-1:0] digest;
            wire completed = finish_valid;
            assign response_value = bridge_response ?
                {{(DIGEST_BYTES * 8 - N * 8) {1'b0}}, published_digest[N*8-1:0]} : digest;
            assign response_capture = bridge_response ? published_capture[N*8-1:0] :
                engine_capture[N*8-1:0];
            wire [7:0] prefix_bytes = shapes[ADDRESS_LIST] ? stream_node_bytes + 32 : 22;
            logic staged_valid, staged_last;
            logic [127:0] staged_data;
            logic fetched_valid;
            logic [127:0] fetched_source, fetched_list;
            logic fetched_use_list, fetched_prefix_head, fetched_prefix_tail;
            logic fetched_padding, fetched_partial, fetched_rate_tail, fetched_last;
            logic [3:0] fetched_remaining;
            wire output_accept = !staged_valid || block_ready;
            wire stream_accept = !fetched_valid || output_accept;
            // Emit sixteen bytes per cycle, then eight bytes at the end of the rate.
            // One cursor supplies source selection, padding and the final-block test.
            logic [12:0] position;
            logic [INDEX_BITS-1:0] list_cursor;
            logic [5:0] list_remainder;
            wire [4:0] stream_advance = beat != 8 ? 5'd16 : 5'd8;
            wire [6:0] next_remainder = {1'b0, list_remainder} + stream_advance;
            assign list_index0 = list_cursor;
            assign list_next_index0 = state == IDLE && request_valid ? INDEX_BITS'(0) :
                state == STREAM && stream_accept && position >= prefix_bytes &&
                next_remainder >= stream_node_bytes ? list_cursor + 1'b1 : list_cursor;
            assign list_index1 = list_index0 + 1'b1;
            assign
                request_ready = state == IDLE && (!scalar_fixed ||
                    (!batch_mode && request_valid && scalar_capacity));
            assign response_valid = state == RESPONSE || (state == FIXED_WAIT && engine_valid);

            // All sponge beats start on an eight-byte boundary. Select two words
            // directly instead of shifting a maximum-size concatenated message frame.
            wire [2:0] node_words = stream_node_words;
            // Source-range decoding already bounds live node reads to four words.
            // ADDRESS_LIST uses this selector only across its prefix; later beats
            // come from list_window. Do not repeat a six-bit bounds check per node.
            // Select a source and a small word address BEFORE the wide data mux.
            // All recipes share the same message/seed selectors instead of each
            // recipe instantiating its own variable 64-bit extraction network.
            // Compute the next beat's small selectors while producing the current
            // beat. START supplies the first selector; backpressure holds both the
            // selector and its position. No node data register or extra cycle is added.
            logic [12:0] source_control[0:2];
            wire [12:0] following_position = position + 13'(stream_advance);
            for (genvar word_slot = 0; word_slot < 3; word_slot++) begin : source_selectors
                always_ff @(posedge clk)
                    if (!rst) begin
                        if (state == START && hash_ready)
                            source_control[word_slot] <= decode_source(
                                6'(word_slot), word_slot == 2, shapes, node_words
                            );
                        else if (state == STREAM && stream_accept)
                            source_control[word_slot] <= decode_source(
                                following_position[8:3] + 6'(word_slot), word_slot == 2, shapes, node_words
                            );
                    end
            end
            function automatic [63:0] source_word(input [12:0] control);
                reg [63:0] literal;
                reg [5:0] selected_index;
                begin
                    selected_index = control[5:0];
                    literal = source_literal(control[12:9], leaf, identifier, list_data0);
                    case (control[8:6])
                        1: source_word = node_word_indexed(secret_prf, selected_index[1:0]);
                        2: source_word = node_word_indexed(randomizer, selected_index[1:0]);
                        3: source_word = node_word_indexed(public_seed, selected_index[1:0]);
                        4: source_word = node_word_indexed(root, selected_index[1:0]);
                        5: source_word = message_word(selected_index);
                        6: source_word = node_word_indexed(address, selected_index[1:0]);
                        // A scheduled ADDRESS_LIST can cross its prefix only for
                        // 24-byte nodes: the last prefix beat needs the first list
                        // word. Later list words use list_window, so no indexed
                        // endpoint-word mux is live on this source path.
                        7: source_word = list_data0[63:0];
                        default: source_word = literal;
                    endcase
                end
            endfunction
            logic [511:0] list_pair;
            always @* begin
                list_pair = list_nodes(stream_node_bytes, list_data0, list_data1);
            end
            // Legal list offsets are whole 64-bit words (SLH), or two bytes
            // beyond a word (LMS's 22-byte prefix). No general byte barrel shifter.
            logic [143:0] list_word_window;
            always @* begin
                list_word_window = list_words(list_pair, list_remainder[4:3]);
            end
            // A fixed two-node window supports both aligned SLH and the LMS prefix.
            wire [127:0] list_window = (RECIPE_MASK[PREFIX_LIST] && list_remainder[1]) ?
                list_word_window[143:16] : list_word_window[127:0];
            wire [191:0] source_window = {
                source_word(source_control[2]),
                source_word(source_control[1]),
                source_word(source_control[0])
            };
            // The RAM-to-window stage retains only the selected portions of
            // adjacent nodes. Cursor/source controls advance on its own handshake;
            // padding and the source/list merge run in the following stage.
            wire [12:0] remaining_bytes = input_length - position;
            wire padding_reached = position > input_length;
            wire partial_beat = remaining_bytes < 16;
            wire stream_last = padding_reached || remaining_bytes < 8;
`ifndef SYNTHESIS
            always @(posedge clk) begin : debug_prefix_list_word
                if (!rst && state == STREAM && stream_accept && shapes[ADDRESS_LIST] &&
                    position < prefix_bytes) begin
                    // Check only words contributing input bytes to the prefix
                    // beat. Full list beats use fetched_list, and the last rate
                    // beat has no second word.
                    for (integer i = 0; i < 2; i++) begin
                        if ((i == 0 || beat != 8) && position + 13'(8 * i) < input_length &&
                            source_control[i][8:6] == 3'd7 && source_control[i][5:0] != 0)
                            $fatal(1, "prefix beat requested a list word beyond the first");
                    end
                end
            end
`endif
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

            wire batch_perm_valid, batch_perm_ready, batch_perm_done;
            wire [1599:0] batch_perm_state, batch_perm_digest;
            wire [TAG_BITS-1:0] batch_perm_tag, batch_perm_result_tag;
            // The scalar fixed response occupies FIXED_WAIT until it is consumed.
            wire bridge_response = state == FIXED_WAIT;
            // A fixed request can enter the context engine on the outer handshake.
            // The response remains in its context until the caller consumes it.
            wire scalar_bridge = bridge_response ||
                (!batch_mode && state == IDLE && request_valid && scalar_fixed);
            // The intake register owns a newly accepted scalar request before
            // it is dispatched from FIXED_WAIT. Keep incoming recipe decoding
            // out of the datapath-mode and downstream-capacity feedback cone.
            wire engine_mode = batch_mode || bridge_response;
            wire engine_valid, scalar_capacity, batch_capacity;
            wire [255:0] engine_digest, engine_capture;
            wire [255:0] published_digest, published_capture;
            wire [3:0] scalar_shape = request_recipe[59:56];
            wire scalar_fixed = RECIPE_MASK[scalar_shape] &&
                (scalar_shape == 1 || scalar_shape == 2 || scalar_shape == 5 || scalar_shape == 7 ||
                 scalar_shape == 8 || scalar_shape == 9 || scalar_shape == 10 ||
                 scalar_shape == 14 || scalar_shape == 15);
            wire scalar_no_seed = !(request_chain && (scalar_shape == 1 || scalar_shape == 7 ||
                                                      scalar_shape == 9)) && scalar_shape != 7;
            wire [1:0] scalar_family = (scalar_shape == 1 || scalar_shape == 2) ?
                2'd0 : (scalar_shape == 9 || scalar_shape == 10 || scalar_shape == 14 ||
                        scalar_shape == 15) ? 2'd2 : 2'd1;
            assign batch_request_ready = batch_mode && !bridge_response && batch_capacity;
            // Only an accepted scalar request owns the response port. Decoding
            // an incoming request here would put recipe selection back into
            // the rolling scheduler's retire/free-slot/ready feedback path.
            assign batch_response_valid = engine_valid && !bridge_response;
            assign batch_read_digest = engine_digest;
            assign batch_read_capture = engine_capture;
            begin : fixed_context
                // Scalar tag 0 and batch tags share these contexts and the
                // existing Keccak datapath. Aliases preserve the former port widths.
                wire [TAG_BITS-1:0]
                    incoming_tag = scalar_bridge ? TAG_BITS'(0) : batch_request_tag;
                wire [4:0] incoming_steps = scalar_bridge ?
                    (request_chain ? request_steps : 5'd0) : batch_steps;
                wire [4:0] incoming_capture_after = scalar_bridge ?
                    (request_chain ? request_capture_after : scalar_no_seed ? 5'd1 : 5'd0) :
                    batch_capture_after;
                wire incoming_capture = scalar_bridge ? request_capture : batch_capture_enable;
                wire [1:0] incoming_family = scalar_bridge ? scalar_family : batch_family;
                wire incoming_no_seed = scalar_bridge ? scalar_no_seed : batch_no_seed;
                wire [3:0] incoming_start = scalar_bridge ? 4'd0 : batch_start;
                wire [255:0] incoming_initial_value = scalar_bridge ?
                    (scalar_shape == 5 ? 256'(secret_prf) : 256'(request_left)) :
                    batch_initial_value;
                wire [3:0] incoming_fixed_shape = scalar_bridge ?
                    (request_chain ? 4'd0 : scalar_shape) : batch_fixed_shape;
                wire incoming_pair = scalar_bridge ? request_recipe[47:40] == 2 : batch_pair;
                wire [255:0] incoming_right = scalar_bridge ? 256'(request_right) : batch_right;
                wire [255:0] ctx_secret_seed = 256'(secret_seed);
                wire [255:0] ctx_public_seed = 256'(public_seed);
                wire [19:0] incoming_leaf = scalar_bridge ? request_leaf : batch_leaf;
                wire [7:0] incoming_a = scalar_bridge ? 8'(request_a) : batch_a;
                wire [31:0] incoming_b = scalar_bridge ? request_b : batch_b;
                wire [7:0]
                    incoming_seed_domain = scalar_bridge ? request_recipe[55:48] : batch_seed_domain;
                wire [7:0] incoming_step_domain = scalar_bridge ?
                    (request_chain ? request_step_recipe[55:48] : request_recipe[55:48]) :
                    batch_step_domain;
                // One request register separates caller controls/endpoint RAM from
                // fixed formatting plus the first Keccak round. Feedback bypasses it.
                logic pending_valid;
                logic [TAG_BITS-1:0] ctx_request_tag;
                logic [4:0] ctx_request_steps, ctx_request_capture_after;
                logic ctx_request_capture, ctx_request_no_seed, ctx_request_pair;
                logic [1:0] ctx_request_family;
                logic [3:0] ctx_request_start, ctx_request_fixed_shape;
                logic [6:0] ctx_first_phase;
                logic [2:0] ctx_first_format;
                logic [255:0] ctx_request_initial_value, ctx_request_right;
                logic [19:0] ctx_request_leaf;
                logic [7:0] ctx_request_a, ctx_seed_domain, ctx_step_domain;
                logic [31:0] ctx_request_b;
                logic [4:0] ctx_request_layer;
                logic [63:0] ctx_request_tree;
                wire ctx_request_valid = pending_valid;
                wire ctx_request_ready;
                // Scalar result data are consumed only in FIXED_WAIT. An
                // incoming scalar recipe must not select the asynchronous RAM
                // read address used by a concurrently visible batch response.
                wire [TAG_BITS-1:0] ctx_read_tag = bridge_response ? TAG_BITS'(0) : batch_read_tag;
                wire [255:0] ctx_read_digest;
                wire [255:0] ctx_read_capture;
                wire ctx_response_valid;
                wire ctx_response_ready = bridge_response ? response_ready : batch_response_ready;
                logic [TAG_BITS-1:0] ctx_response_tag;
                wire ctx_perm_valid;
                wire ctx_perm_ready = batch_perm_ready;
                wire [1599:0] ctx_perm_state;
                wire [TAG_BITS-1:0] ctx_perm_tag;
                wire ctx_perm_done = batch_perm_done;
                wire [1599:0] ctx_perm_digest = batch_perm_digest;
                wire [TAG_BITS-1:0] ctx_perm_result_tag = batch_perm_result_tag;
`ifndef SYNTHESIS
                logic [63:0] ctx_hash_count, ctx_permutation_count;
                assign batch_hashes = ctx_hash_count;
                assign batch_permutations = ctx_permutation_count;
`endif
                assign engine_valid = ctx_response_valid;
                assign engine_digest = ctx_read_digest;
                assign engine_capture = ctx_read_capture;
                assign batch_response_tag = ctx_response_tag;
                assign batch_perm_valid = ctx_perm_valid;
                assign batch_perm_state = ctx_perm_state;
                assign batch_perm_tag = ctx_perm_tag;
                assign batch_response_digest = published_digest;
                assign batch_response_capture = published_capture;

                wire [255:0] seed_address = make_address(ctx_request_layer, ctx_request_tree,
                    {12'd0, ctx_request_leaf}, ctx_seed_domain, {24'd0, ctx_request_a}, ctx_request_b);
                wire [255:0] step_address = make_address(ctx_request_layer, ctx_request_tree,
                    {12'd0, ctx_request_leaf}, ctx_step_domain, {24'd0, ctx_request_a}, ctx_request_b);
                wire [255:0] address[0:PIPELINE-1];
                logic [4:0]
                    steps[0:PIPELINE-1], iteration[0:PIPELINE-1], capture_after[0:PIPELINE-1];
                logic [PIPELINE-1:0] busy, complete, capture_enable;
                // The address domain and fixed shape are shared until every slot drains,
                // so their address-counter policy is shared by the same batch.
                logic preserve_counter;
                (* ram_style="distributed" *) logic [255:0] digest[0:PIPELINE-1];
                (* ram_style="distributed" *) logic [255:0] captured[0:PIPELINE-1];
                // One-hot phase bits feed the returned tag's formatting controls directly.
                // They avoid decoding an encoded RAM output and then decoding next_phase.
                localparam [6:0] SEED = 7'b0000001, STEP = 7'b0000010, KEY = 7'b0000100,
                    MASK = 7'b0001000, FINAL = 7'b0010000, MASK1 = 7'b0100000, SINGLE = 7'b1000000;
                function automatic [6:0] starting_phase(input [3:0] shape,
                    input bit no_seed, input [1:0] kind);
                    starting_phase = shape == 8 ? KEY : shape == 7 ? SEED :
                        shape != 0 ? SINGLE : !no_seed ? SEED : kind == 1 ? KEY : STEP;
                endfunction
                function automatic [6:0] advance_phase(input [6:0] current_phase,
                    input bit pair_nodes, input [1:0] kind);
                    advance_phase = current_phase[2] ? MASK : current_phase[3] ?
                        (pair_nodes ? MASK1 : FINAL) : current_phase[5] ? FINAL :
                        kind == 1 ? KEY : STEP;
                endfunction
                function automatic [2:0] format_controls(input [6:0] selected_phase,
                    input [3:0] shape, input bit pair_nodes, input [1:0] kind);
                    reg seed, prf, two;
                    begin
                        seed = selected_phase[0] || shape == 7;
                        prf = selected_phase[2] || selected_phase[3] || selected_phase[5];
                        two = kind == 1 ? seed || (pair_nodes && !prf) :
                            kind == 2 && shape != 14 && shape != 15 ? 1'b0 : pair_nodes;
                        format_controls = {two, prf, seed};
                    end
                endfunction
                wire [6:0] incoming_phase = starting_phase(incoming_fixed_shape,
                    incoming_no_seed, incoming_family);
                wire [1:0] family[0:PIPELINE-1];
                wire [3:0] fixed_shape[0:PIPELINE-1];
                wire [PIPELINE-1:0] paired;
                logic [3:0] shared_shape;
                logic shared_pair;
                logic [6:0] phase[0:PIPELINE-1];
                (* ram_style="distributed" *) logic [255:0] key_value[0:PIPELINE-1];
                logic [PIPELINE-1:0] captured_valid, initial_pending, capture_initial;
                assign ctx_read_digest = initial_pending[ctx_read_tag] ? key_value[ctx_read_tag] :
                    digest[ctx_read_tag];
                assign ctx_read_capture = captured_valid[ctx_read_tag] ?
                    (capture_initial[ctx_read_tag] ? key_value[ctx_read_tag] :
                     captured[ctx_read_tag]) : 256'd0;
                wire [TAG_BITS-1:0] t = ctx_perm_result_tag;
                // Read context operands while the last Keccak round is running.
                // A slot has one permutation in flight; its operands stay live
                // from dispatch until this return. Only the new digest depends
                // on the final round, so context RAM need not follow its tag.
                // Position the context read address near its operand banks.
                // Its last-traversal enable differs from the generic round tag,
                // so synthesis keeps this register independent of that tag.
                logic [TAG_BITS-1:0] prefetch_tag;
                if (PIPELINE > 2) begin : local_read_address
                    always_ff @(posedge clk)
                        if (stage_valid[PIPELINE-3] && stage_fixed[PIPELINE-3] &&
                            stage_base[PIPELINE-3] + ROUNDS >= 24)
                            prefetch_tag <= stage_tag[PIPELINE-3];
                end else begin : input_read_address
                    wire source_valid = recycle || launch_valid;
                    wire source_fixed = recycle ? stage_fixed[PIPELINE-1] : launch_fixed;
                    wire [4:0] source_base = recycle ?
                        stage_base[PIPELINE-1] + 5'(ROUNDS) : 5'd0;
                    always_ff @(posedge clk)
                        if (source_valid && source_fixed && source_base + ROUNDS >= 24)
                            prefetch_tag <= recycle ? stage_tag[PIPELINE-1] : launch_tag;
                end
                wire prefetch_context = stage_valid[PIPELINE-2] &&
                    stage_fixed[PIPELINE-2] && stage_base[PIPELINE-2] + ROUNDS >= 24;
                logic [255:0] return_key, return_digest, return_captured, return_address;
                logic [PIPELINE-1:0] node_phase, more_steps, feedback_required;
                logic [6:0] return_phase, return_next_phase;
                logic [2:0] return_format;
                logic [4:0] return_next_step;
                logic return_node_phase, return_feedback_required, return_next_more_steps;
                logic return_capture, return_initial_pending, return_capture_initial;
                // Context control is stable from dispatch through the final round.
                // Read it beside the operands, before the returned tag can fan out
                // through phase decode, counter arithmetic and the block formatter.
                // One prepared format replaces the per-slot feedback format bank.
                always_ff @(posedge clk)
                    if (prefetch_context) begin
                        return_key <= key_value[prefetch_tag];
                        return_digest <= digest[prefetch_tag];
                        return_captured <= captured[prefetch_tag];
                        return_address <= address[prefetch_tag];
                        return_phase <= phase[prefetch_tag];
                        return_next_phase <= advance_phase(phase[prefetch_tag],
                            paired[prefetch_tag], family[prefetch_tag]);
                        return_format <= format_controls(advance_phase(phase[prefetch_tag],
                            paired[prefetch_tag], family[prefetch_tag]),
                            fixed_shape[prefetch_tag], paired[prefetch_tag], family[prefetch_tag]);
                        return_node_phase <= node_phase[prefetch_tag];
                        return_feedback_required <= feedback_required[prefetch_tag];
                        return_next_step <= node_phase[prefetch_tag] ? iteration[prefetch_tag] :
                            iteration[prefetch_tag] - 1'b1;
                        return_next_more_steps <= node_phase[prefetch_tag] ?
                            iteration[prefetch_tag] + 1'b1 < steps[prefetch_tag] :
                            more_steps[prefetch_tag];
                        return_capture <= capture_enable[prefetch_tag] &&
                            iteration[prefetch_tag] == capture_after[prefetch_tag];
                        return_initial_pending <= initial_pending[prefetch_tag];
                        return_capture_initial <= capture_initial[prefetch_tag];
                    end
`ifndef SYNTHESIS
                always @(posedge clk) begin : debug_operand_prefetch
                    if (!rst && prefetch_context && prefetch_tag !== stage_tag[PIPELINE-2])
                        $fatal(1, "local context read address lost its round tag");
                    if (!rst && ctx_perm_done) begin
                        if (return_address !== address[t])
                            $fatal(1, "prefetched address changed before return");
                        if (return_key !== key_value[t] || return_digest !== digest[t] ||
                            return_captured !== captured[t])
                            $fatal(1, "prefetched context operand changed before return");
                        if (return_phase !== phase[t] || return_node_phase !== node_phase[t] ||
                            return_feedback_required !== feedback_required[t] ||
                            return_next_phase !== advance_phase(phase[t], paired[t], family[t]) ||
                            return_next_step !== (node_phase[t] ? iteration[t] : iteration[t] - 1'b1) ||
                            return_next_more_steps !== (node_phase[t] ?
                                iteration[t] + 1'b1 < steps[t] : more_steps[t]) ||
                            return_capture !== (capture_enable[t] && iteration[t] == capture_after[t]) ||
                            return_initial_pending !== initial_pending[t] ||
                            return_capture_initial !== capture_initial[t])
                            $fatal(1, "prefetched context control changed before return");
                    end
                end
`endif
                wire node_done = return_node_phase;
                wire again = ctx_perm_done && return_feedback_required;
                wire capture_now = ctx_perm_done && node_done && return_capture;
                wire [6:0] next_phase = return_next_phase;
                wire next_node_phase = next_phase[0] || next_phase[1] || next_phase[4] ||
                    next_phase[6];
                wire next_more_steps = return_next_more_steps;
                wire [4:0] next_step = return_next_step;
                logic [255:0] next_address;
                always_comb begin
                    next_address = return_address;
                    if (!preserve_counter) next_address[224+:32] = be32({27'd0, next_step});
                end
                // Intake has already reserved an in-range idle tag. The pending
                // tag remains idle until this launch, so do not repeat its lookup
                // on the downstream-ready path that also permits queue refill.
                assign ctx_request_ready = !rst && !again && ctx_perm_ready;
`ifndef SYNTHESIS
                always @(posedge clk) begin : debug_pending_reservation
                    if (!rst && pending_valid) begin
                        if (ctx_request_tag >= PIPELINE)
                            $fatal(1, "pending request tag out of range");
                        else if (busy[ctx_request_tag] !== 1'b0)
                            $fatal(1, "pending request tag was not reserved idle");
                    end
                end
`endif
                wire accept = ctx_request_valid && ctx_request_ready;
                // Reserve the pending tag before its context becomes busy. A retired
                // context may be refilled on the same edge, but a queued tag may not.
                // Determine capacity independently of the request's recipe/mode.
                // Scalar intake occurs only in IDLE, where no scalar response can
                // retire. Batch intake uses its own response handshake for refill.
                // Mode selection is applied once, at the public ready outputs.
                wire queue_open = !rst && (!pending_valid || (!again && ctx_perm_ready));
                wire batch_retire = ctx_response_valid && batch_response_ready;
                wire scalar_slot_available =
                    !busy[0] &&
                    (!pending_valid || ctx_request_tag != TAG_BITS'(0));
                wire batch_slot_available = batch_request_tag < PIPELINE &&
                    (!busy[batch_request_tag] || (batch_retire && ctx_response_tag == batch_request_tag)) &&
                    (!pending_valid || ctx_request_tag != batch_request_tag);
                assign scalar_capacity = queue_open && scalar_slot_available;
                assign batch_capacity = queue_open && batch_slot_available;
                wire receive = (state == IDLE && request_valid && scalar_fixed &&
                    !batch_mode && scalar_capacity) || (batch_request_valid && batch_request_ready);
`ifndef SYNTHESIS
                // Preserve even ready-without-valid behavior while changing the
                // combinational factoring. These observers are absent in hardware.
                wire old_retire = ctx_response_valid && ctx_response_ready;
                wire old_scalar_slot = (!busy[0] || (old_retire && ctx_response_tag == 0)) &&
                    (!pending_valid || ctx_request_tag != 0);
                wire old_batch_slot = batch_request_tag < PIPELINE &&
                    (!busy[batch_request_tag] || (old_retire && ctx_response_tag == batch_request_tag)) &&
                    (!pending_valid || ctx_request_tag != batch_request_tag);
                wire old_ready = !rst && (batch_mode || scalar_bridge) && (!pending_valid || accept) &&
                    (scalar_bridge ? old_scalar_slot : old_batch_slot);
                wire old_valid = scalar_bridge ? state == IDLE && request_valid : batch_request_valid;
                always @(posedge clk) begin : debug_intake_equivalence
                    if (!rst) begin
                        if (state == IDLE && request_valid && request_ready &&
                            scalar_fixed && !batch_mode &&
                            (pending_valid || |busy || ctx_response_valid))
                            $fatal(1, "scalar intake before batch contexts drained");
                        if (batch_response_valid !== (engine_valid && !scalar_bridge))
                            $fatal(1, "accepted response ownership changed batch valid");
                        if ((ctx_response_valid && ctx_response_ready) !==
                            (ctx_response_valid && (scalar_bridge ?
                                state == FIXED_WAIT && response_ready : batch_response_ready)))
                            $fatal(1, "accepted response ownership changed retirement");
                        if (request_ready !== (state == IDLE &&
                            (!scalar_fixed || (!batch_mode && old_ready))))
                            $fatal(1, "scalar intake ready changed");
                        if (batch_request_ready !== (old_ready && !scalar_bridge))
                            $fatal(1, "batch intake ready changed");
                        if (receive !== (old_valid && old_ready))
                            $fatal(1, "context intake handshake changed");
                    end
                end
`endif
                always_ff @(posedge clk) begin
                    if (rst) pending_valid <= 0;
                    else begin
                        if (accept) pending_valid <= 0;
                        if (receive) begin
                            pending_valid <= 1;
                            ctx_request_tag <= incoming_tag;
                            ctx_request_steps <= incoming_steps;
                            ctx_request_capture_after <= incoming_capture_after;
                            ctx_request_capture <= incoming_capture;
                            ctx_request_family <= incoming_family;
                            ctx_request_no_seed <= incoming_no_seed;
                            ctx_request_start <= incoming_start;
                            ctx_request_initial_value <= incoming_initial_value;
                            ctx_request_fixed_shape <= incoming_fixed_shape;
                            ctx_request_pair <= incoming_pair;
                            ctx_first_phase <= incoming_phase;
                            ctx_first_format <= format_controls(incoming_phase,
                                incoming_fixed_shape, incoming_pair, incoming_family);
                            ctx_request_right <= incoming_right;
                            ctx_request_leaf <= incoming_leaf;
                            ctx_request_a <= incoming_a;
                            ctx_request_b <= incoming_b;
                            ctx_seed_domain <= incoming_seed_domain;
                            ctx_step_domain <= incoming_step_domain;
                            ctx_request_layer <= request_layer;
                            ctx_request_tree <= request_tree;
                        end
                    end
                end
                wire [3:0] requested_shape = ctx_request_fixed_shape;
                wire requested_pair = ctx_request_pair;
                wire zero_request = ctx_request_no_seed && ctx_request_steps == 0 &&
                    requested_shape == 0;
                assign ctx_perm_valid = again || (accept && !zero_request);
                // Select operands before the common width and padding formatter.
                wire [255:0] block_address = again ? next_address :
                    ctx_request_no_seed ? step_address : seed_address;
                wire [1:0] block_family = again ? family[t] : ctx_request_family;
                wire [6:0] first_phase = ctx_first_phase;
                wire first_node_phase = first_phase[0] || first_phase[1] || first_phase[6];
                wire first_more_steps = ctx_request_no_seed ? ctx_request_steps > 1 :
                    ctx_request_steps != 0;
                wire [6:0] block_phase = again ? next_phase : first_phase;
                wire [2:0] block_format = again ? return_format : ctx_first_format;
                wire [3:0] block_step = again ? next_step[3:0] : ctx_request_start;
                wire [3:0] block_shape = again ? fixed_shape[t] : requested_shape;
                wire block_pair = again ? paired[t] : requested_pair;
                wire [255:0] block_value = again ?
                    (return_phase[5] ? return_digest :
                     return_phase[3] ? return_digest ^ ctx_perm_digest[255:0] : ctx_perm_digest[255:0]) :
                    requested_shape == 1 || requested_shape == 9 ? ctx_secret_seed :
                    ctx_request_no_seed ? ctx_request_initial_value : ctx_secret_seed;
                wire [255:0]
                    block_right = again ? return_captured ^ ctx_perm_digest[255:0] : ctx_request_right;
                wire [1599:0] unified_state;
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
                assign ctx_perm_state = unified_state;
                assign ctx_perm_tag   = again ? t : ctx_request_tag;
                // Register response selection before it fans out through retire,
                // caller ready and executor transitions. Reuse the stall-hold
                // registers; digest/capture data stay in their existing banks.
                logic response_held;
                logic [TAG_BITS-1:0] held_tag, next_response_tag;
                logic [255:0] held_digest, held_capture;
                logic [PIPELINE-1:0] waiting_responses;
                // Completion and publication own separate lifetimes. The slot
                // remains complete/busy until retirement, while this queue bit
                // is removed as soon as its response payload is published.
                logic [PIPELINE-1:0] awaiting_response;
                wire publish_response = !response_held || ctx_response_ready;
                assign ctx_response_valid = response_held;
                assign ctx_response_tag = held_tag;
                assign published_digest = held_digest;
                assign published_capture = held_capture;
                always_comb begin
                    waiting_responses = awaiting_response;
                    next_response_tag = 0;
                    for (integer j = PIPELINE - 1; j >= 0; j = j - 1)
                        if (waiting_responses[j]) next_response_tag = TAG_BITS'(j);
                end
                always_ff @(posedge clk) begin
                    if (rst) awaiting_response <= 0;
                    else begin
                        if (publish_response && |waiting_responses)
                            awaiting_response[next_response_tag] <= 0;
                        if (accept && zero_request)
                            awaiting_response[ctx_request_tag] <= 1;
                        if (ctx_perm_done && !again)
                            awaiting_response[t] <= 1;
                    end
                end
                always_ff @(posedge clk) begin
                    if (rst) begin
                        response_held <= 0;
                        held_tag <= 0;
                    end else if (!response_held || ctx_response_ready) begin
                        response_held <= |waiting_responses;
                        held_tag <= next_response_tag;
                        // Completion is visible after its bank write commits.
                        // Publish payload and tag on the same edge, retaining
                        // both under backpressure. Workspace writes now start
                        // at these registers rather than an asynchronous RAM.
                        if (|waiting_responses) begin
                            held_digest <= initial_pending[next_response_tag] ?
                                key_value[next_response_tag] : digest[next_response_tag];
                            held_capture <= !captured_valid[next_response_tag] ? 256'd0 :
                                capture_initial[next_response_tag] ? key_value[next_response_tag] :
                                captured[next_response_tag];
                        end
                    end
                end
`ifndef SYNTHESIS
                always @(posedge clk) begin : debug_response_selection
                    if (!rst) begin
                        for (integer j = 0; j < PIPELINE; j++) begin
                            if (awaiting_response[j] !==
                                (complete[j] && !(response_held && held_tag == TAG_BITS'(j))))
                                $fatal(1, "response queue differs from completion ownership");
                        end
                    end
                    if (!rst && response_held) begin
                        if (held_tag >= PIPELINE)
                            $fatal(1, "published response tag out of range");
                        else if (!complete[held_tag] || !busy[held_tag])
                            $fatal(1, "published response does not own a completed slot");
                        else begin
                            if (held_digest !== (initial_pending[held_tag] ?
                                key_value[held_tag] : digest[held_tag]))
                                $fatal(1, "published digest differs from its completed slot");
                            if (held_capture !== (!captured_valid[held_tag] ? 256'd0 :
                                capture_initial[held_tag] ? key_value[held_tag] : captured[held_tag]))
                                $fatal(1, "published capture differs from its completed slot");
                        end
                    end
                end
`endif
`ifndef SYNTHESIS
                always @(posedge clk) begin : debug_format_controls
                    if (!rst) begin
                        if (pending_valid && (ctx_first_phase !== starting_phase(requested_shape,
                            ctx_request_no_seed, ctx_request_family) || ctx_first_format !==
                            format_controls(first_phase, requested_shape, requested_pair, ctx_request_family)))
                            $fatal(1, "registered request format differs from its recipe");
                        if (ctx_perm_done) begin
                            if (feedback_required[t] !== (!node_done || more_steps[t]))
                                $fatal(1, "registered feedback decision differs from its context");
                            if (return_format !== format_controls(next_phase,
                                fixed_shape[t], paired[t], family[t]))
                                $fatal(1, "registered feedback format differs from its phase");
                        end
                    end
                end
`endif
                // A KEY return always feeds MASK immediately, so feedback priority excludes
                // accepting an initial value on the same edge. Each bank has one write port.
                wire key_return = ctx_perm_done && return_phase[2];
                wire initial_transfer = key_return && return_initial_pending;
                wire key_write = key_return || (accept && ctx_request_no_seed);
                wire [TAG_BITS-1:0] key_write_tag = key_return ? t : ctx_request_tag;
                wire [255:0] key_write_data = key_return ? ctx_perm_digest[255:0] :
                    ctx_request_initial_value;
                wire mask_left = ctx_perm_done && paired[t] && return_phase[3];
                wire digest_write = ctx_perm_done && (node_done || initial_transfer || mask_left);
                wire [255:0] digest_write_data = initial_transfer ? return_key :
                    mask_left ? return_digest ^ ctx_perm_digest[255:0] : ctx_perm_digest[255:0];
                wire capture_transfer = initial_transfer && return_capture_initial;
                wire right_write = accept && requested_pair && requested_shape == 8;
                wire captured_write = capture_now || capture_transfer || right_write;
                wire [TAG_BITS-1:0] captured_write_tag = right_write ? ctx_request_tag : t;
                wire [255:0] captured_write_data = right_write ? ctx_request_right :
                    capture_transfer ? return_key : ctx_perm_digest[255:0];
                always_ff @(posedge clk) begin
                    if (!rst) begin
                        if (key_write) key_value[key_write_tag] <= key_write_data;
                        if (digest_write) digest[t] <= digest_write_data;
                        if (captured_write) captured[captured_write_tag] <= captured_write_data;
                    end
                end
                always_ff @(posedge clk) begin
                    if (rst) begin
                        node_phase <= 0;
                        more_steps <= 0;
                        feedback_required <= 0;
                        initial_pending <= 0;
                        capture_initial <= 0;
                        captured_valid <= 0;
                        busy <= 0;
                        complete <= 0;
                        capture_enable <= 0;
                        preserve_counter <= 0;
                    end else begin
                        if (ctx_response_valid && ctx_response_ready) begin
                            complete[ctx_response_tag] <= 0;
                            busy[ctx_response_tag] <= 0;
                        end
                        if (accept) begin
                            busy[ctx_request_tag] <= 1;
                            steps[ctx_request_tag] <= ctx_request_steps + {1'b0, ctx_request_start};
                            iteration[ctx_request_tag] <= ctx_request_no_seed ?
                                {1'b0, ctx_request_start} + 1'b1 : 5'd0;
                            phase[ctx_request_tag] <= first_phase;
                            node_phase[ctx_request_tag] <= first_node_phase;
                            more_steps[ctx_request_tag] <= first_more_steps;
                            feedback_required[ctx_request_tag] <= !first_node_phase || first_more_steps;
                            if (busy == 0) begin
                                shared_shape <= requested_shape;
                                shared_pair <= requested_pair;
                                preserve_counter <= ctx_step_domain == 3 || requested_shape != 0;
                            end
                            initial_pending[ctx_request_tag] <= ctx_request_no_seed;
                            if (zero_request) complete[ctx_request_tag] <= 1;
                            capture_after[ctx_request_tag]   <= ctx_request_capture_after;
                            capture_enable[ctx_request_tag]  <= ctx_request_capture;
                            captured_valid[ctx_request_tag]  <= 0;
                            capture_initial[ctx_request_tag] <= 0;
                            if (ctx_request_no_seed && ctx_request_capture &&
                                ctx_request_capture_after == {1'b0, ctx_request_start}) begin
                                capture_initial[ctx_request_tag] <= 1;
                                captured_valid[ctx_request_tag]  <= 1;
                            end
                        end
                        if (ctx_perm_done) begin
                            if (capture_now) begin
                                capture_initial[t] <= 0;
                                captured_valid[t]  <= 1;
                            end
                            if (capture_transfer) capture_initial[t] <= 0;
                            if (digest_write) initial_pending[t] <= 0;
                            if (again) begin
                                phase[t] <= next_phase;
                                node_phase[t] <= next_node_phase;
                                feedback_required[t] <= !next_node_phase || next_more_steps;
                                if (node_done) more_steps[t] <= next_more_steps;
                                if (node_done) iteration[t] <= iteration[t] + 1'b1;
                            end else complete[t] <= 1;
                        end
                    end
                end
                begin : shared_coordinates
                    logic [4:0] layer;
                    logic [63:0] tree;
                    logic [7:0] domain;
                    logic [1:0] kind;
                    logic [19:0] leaves[0:PIPELINE-1];
                    logic [7:0] chains[0:PIPELINE-1];
                    logic [31:0] indices[0:PIPELINE-1];
                    always_ff @(posedge clk)
                        if (!rst && accept) begin
                            if (busy == 0) begin
                                layer  <= ctx_request_layer;
                                tree   <= ctx_request_tree;
                                domain <= ctx_step_domain;
                                kind   <= ctx_request_family;
                            end
                            leaves[ctx_request_tag]  <= ctx_request_leaf;
                            chains[ctx_request_tag]  <= ctx_request_a;
                            indices[ctx_request_tag] <= ctx_request_b;
                        end
`ifndef SYNTHESIS
                    always @(posedge clk)
                        if (!rst && accept && |busy) begin
                            if (ctx_request_layer != layer || ctx_request_tree != tree ||
                                ctx_request_family != kind || ctx_step_domain != domain ||
                                requested_shape != shared_shape || requested_pair != shared_pair)
                                $fatal(1, "shared coordinates changed before contexts drained");
                        end
`endif
                    for (genvar j = 0; j < PIPELINE; j++) begin
                        assign address[j] = {
                            be32(indices[j]),
                            be32({24'd0, chains[j]}),
                            be32({12'd0, leaves[j]}),
                            be32({24'd0, domain}),
                            be32(tree[31:0]),
                            be32(tree[63:32]),
                            32'd0,
                            be32({27'd0, layer})
                        };
                        assign family[j] = kind;
                        assign fixed_shape[j] = shared_shape;
                        assign paired[j] = shared_pair;
                    end
                end
`ifndef SYNTHESIS
                // Diagnostics observe physical returns independently of functional control.
                always_ff @(posedge clk) begin : debug_statistics
                    if (rst) begin
                        ctx_hash_count <= 0;
                        ctx_permutation_count <= 0;
                    end else if (ctx_perm_done) begin
                        ctx_hash_count <= ctx_hash_count + 1'b1;
                        ctx_permutation_count <= ctx_permutation_count + 1'b1;
                    end
                end
`endif
            end
            // Shared P>1 Keccak datapath and streaming absorb control.

            logic [1:0] hash_state;
            logic first_block, running_last;
            logic [3:0] append_index;
            wire [24:0] state_write_enable;
            wire [1599:0] state_write_data;
            logic [1599:0] sponge_state;
            wire [1599:0] advanced_state;
            wire round_complete, round_update;
            // Fixed requests and streaming permutations share the P-stage datapath.
            // P1's iterative datapath lives only in scalar_execution.
            localparam integer ROUNDS = UNROLL * PIPELINE;
            logic [1599:0] state_reg[0:PIPELINE-1];
            logic [PIPELINE-1:0] stage_valid, stage_fixed;
            logic [4:0] stage_base[0:PIPELINE-1];
            logic [TAG_BITS-1:0] stage_tag[0:PIPELINE-1];
            logic sent;
            // The penultimate stage already knows whether this traversal is the
            // last. Register that decision alongside the final stage's metadata,
            // before it drives the 1600-bit loop mux and first Keccak round.
            logic recycle;
            always_ff @(posedge clk)
                if (rst) recycle <= 0;
                else recycle <= stage_valid[PIPELINE-2] &&
                    stage_base[PIPELINE-2] + ROUNDS < 24;
`ifndef SYNTHESIS
            always @(posedge clk) begin : debug_recycle_equivalence
                if (!rst && recycle !== (stage_valid[PIPELINE-1] &&
                    stage_base[PIPELINE-1] + ROUNDS < 24))
                    $fatal(1, "registered recycle decision changed");
            end
`endif
            wire ready = !rst && !recycle;
            wire finished = !rst && stage_valid[PIPELINE-1] && !recycle;
            wire normal_valid = hash_state == HASH_RUN && !sent;
            wire issue_valid = engine_mode ? batch_perm_valid : normal_valid;
            wire [1599:0] issue_state = normal_valid ? sponge_state : batch_perm_state;
            wire [TAG_BITS-1:0] issue_tag = engine_mode ? batch_perm_tag : '0;
            // Finish context lookup and block formatting before the first round.
            // This elastic register also holds a request while the round pipeline
            // recycles. Its valid bit owns the data across stalls and reset.
            logic launch_valid, launch_fixed;
            logic [1087:0] launch_state;
            wire [511:0] launch_capacity = launch_fixed ? 512'd0 : sponge_state[1599:1088];
            logic [TAG_BITS-1:0] launch_tag;
            wire launch_ready = !rst && (!launch_valid || ready);
            always_ff @(posedge clk) begin
                if (rst) launch_valid <= 0;
                else if (launch_ready) begin
                    launch_valid <= issue_valid;
                    if (issue_valid) begin
                        launch_fixed <= engine_mode;
                        launch_tag <= issue_tag;
                    end
                end
            end
            // Invalid data need not hold or reset. Retain only a blocked request.
            always_ff @(posedge clk)
                if (launch_ready) launch_state <= issue_state[1087:0];
`ifndef SYNTHESIS
            // Original elastic capacity snapshot is an independent simulation oracle.
            logic [511:0] debug_launch_capacity_snapshot;
            longint unsigned debug_launch_fixed_consumed = 0;
            longint unsigned debug_launch_stream_consumed = 0;
            longint unsigned debug_launch_stream_stalls = 0;
            longint unsigned debug_launch_stream_nonzero = 0;
            longint unsigned debug_launch_reset_pending = 0;
            always @(posedge clk) begin : debug_launch_capacity_reuse
                if (launch_ready) debug_launch_capacity_snapshot <= issue_state[1599:1088];
                if (rst && launch_valid) debug_launch_reset_pending++;
                if (!rst && launch_valid) begin
                    if (launch_capacity !== debug_launch_capacity_snapshot)
                        $fatal(1, "live sponge capacity differs from original elastic launch snapshot");
                    if (launch_fixed && !recycle) debug_launch_fixed_consumed++;
                    if (!launch_fixed) begin
                        if (recycle) debug_launch_stream_stalls++;
                        else debug_launch_stream_consumed++;
                        if (|launch_capacity) debug_launch_stream_nonzero++;
                    end
                end
            end
            final $display("LAUNCH_CAPACITY_ORACLE fixed=%0d stream=%0d stalled=%0d nonzero=%0d reset_pending=%0d",
                debug_launch_fixed_consumed, debug_launch_stream_consumed,
                debug_launch_stream_stalls, debug_launch_stream_nonzero, debug_launch_reset_pending);
`endif
            wire [1599:0] finished_state = state_reg[PIPELINE-1];
            for (genvar s = 0; s < PIPELINE; s = s + 1) begin : stages
                wire [1599:0] rounds[0:UNROLL];
                wire [4:0] start_round;
                wire [TAG_BITS-1:0] source_tag;
                wire source_valid, source_fixed;
                if (s == 0) begin : input_stage
                    assign rounds[0] = recycle ? state_reg[PIPELINE-1] : {launch_capacity, launch_state};
                    assign start_round = recycle ? stage_base[PIPELINE-1] + 5'(ROUNDS) : 5'd0;
                    assign source_tag = recycle ? stage_tag[PIPELINE-1] : launch_tag;
                    assign source_valid = recycle || launch_valid;
                    assign source_fixed = recycle ? stage_fixed[PIPELINE-1] : launch_fixed;
                end else begin : following_stage
                    assign rounds[0] = state_reg[s-1];
                    assign start_round = stage_base[s-1];
                    assign source_tag = stage_tag[s-1];
                    assign source_valid = stage_valid[s-1];
                    assign source_fixed = stage_fixed[s-1];
                end
                for (genvar r = 0; r < UNROLL; r = r + 1) begin : unrolled
                    // verilog_format: off
                    (* keep_hierarchy="yes" *) keccak round_logic(.state_in(rounds[r]),
                        .round_index(start_round+5'(s*UNROLL+r)),.state_out(rounds[r+1]));
                    // verilog_format: on
                end
                for (genvar w = 0; w < 25; w = w + 1) begin : words
                    if (s < PIPELINE - 1) begin : advancing
                        // Reset flushes metadata. Intermediate data can advance
                        // through reset and bubbles without a global enable net.
                        always_ff @(posedge clk)
                            state_reg[s][64*w+:64] <= rounds[UNROLL][64*w+:64];
                    end else begin : retained
                        always_ff @(posedge clk)
                            if (!rst) begin
                                if (SHARED_STATE && state_write_enable[w])
                                    state_reg[s][64*w+:64] <= state_write_data[64*w+:64];
                                else if (source_valid)
                                    state_reg[s][64*w+:64] <= rounds[UNROLL][64*w+:64];
                            end
                    end
                end
                always_ff @(posedge clk) begin
                    if (rst) stage_valid[s] <= 0;
                    else begin
                        stage_valid[s] <= source_valid;
                        if (source_valid) begin
                            stage_base[s] <= start_round;
                            stage_tag[s]  <= source_tag;
                            stage_fixed[s] <= source_fixed;
                        end
                    end
                end
            end
            assign batch_perm_ready = engine_mode && launch_ready;
            assign batch_perm_done = finished && stage_fixed[PIPELINE-1];
            assign batch_perm_digest = finished_state;
            assign batch_perm_result_tag = stage_tag[PIPELINE-1];
            if (SHARED_STATE) assign sponge_state = finished_state;
            assign advanced_state = finished_state;
            assign round_complete = finished && !stage_fixed[PIPELINE-1];
            assign round_update = hash_state == HASH_RUN && round_complete;
            always_ff @(posedge clk) begin
                if (rst) sent <= 0;
                else if (!engine_mode) begin
                    if (normal_valid && launch_ready) sent <= 1;
                    if (finished) sent <= 0;
                end
            end
`ifndef SYNTHESIS
            always @(posedge clk)
                if (!rst && SHARED_STATE && |state_write_enable)
                    if (|(stage_valid & ~(finished ?
                                          PIPELINE'(1 << (PIPELINE - 1)) : {PIPELINE{1'b0}})))
                        $fatal(1, "sponge write while pipeline occupied");
`endif
            wire permutation_complete = !engine_mode && hash_state == HASH_RUN && round_complete;

            assign hash_ready = hash_state == HASH_IDLE;
            assign block_ready = hash_state == HASH_WAIT_BLOCK;
            assign digest = sponge_state[DIGEST_BYTES*8-1:0];
            assign finish_valid = permutation_complete && running_last;

`ifndef SYNTHESIS
            initial begin
                if (UNROLL < 1 || PIPELINE < 1 || PIPELINE > 24 || ROUNDS > 24 ||
                    (24 % ROUNDS) != 0)
                    $error("recipe lane requires positive U/P and U*P dividing 24");
            end
`endif

            // Mutually exclusive word updates expose one data mux instead of a
            // priority network for whole-state loads mixed with partial absorption.
            wire take_stream = hash_state == HASH_WAIT_BLOCK && staged_valid;
            wire clear_stream = take_stream && first_block && append_index == 0;
            // One selected rate pair is absorbed per stream beat. Share that XOR
            // before distributing the result to the enabled state words.
            logic [127:0] previous_rate;
            always @* begin
                case (append_index)
                    0: previous_rate = sponge_state[0+:128];
                    1: previous_rate = sponge_state[128+:128];
                    2: previous_rate = sponge_state[256+:128];
                    3: previous_rate = sponge_state[384+:128];
                    4: previous_rate = sponge_state[512+:128];
                    5: previous_rate = sponge_state[640+:128];
                    6: previous_rate = sponge_state[768+:128];
                    7: previous_rate = sponge_state[896+:128];
                    default: previous_rate = {64'd0, sponge_state[1024+:64]};
                endcase
            end
            wire [127:0] absorbed_block = staged_data ^ (previous_rate & {128{!clear_stream}});
            genvar word_index;
            for (word_index = 0; word_index < 25; word_index = word_index + 1) begin : state_words
                wire select_stream = word_index < 17 && take_stream &&
                    append_index == word_index / 2;
                wire [63:0] round_or_clear = (clear_stream || SHARED_STATE) ?
                    64'd0 : advanced_state[word_index*64+:64];
                wire [63:0] absorb_word = word_index % 2 == 0 ? absorbed_block[63:0] :
                    absorbed_block[127:64];
                wire [63:0] next_word;
                assign next_word = select_stream ? absorb_word : round_or_clear;
                assign state_write_data[word_index*64+:64] = next_word;
                // A completed permutation already resides in the shared register.
                // Only absorption, initialization or a new chain block needs a write.
                assign state_write_enable[word_index] = !rst &&
                    ((!SHARED_STATE && round_update) || select_stream ||
                     clear_stream);
                if (!SHARED_STATE) begin : private_state
                    always_ff @(posedge clk)
                        if (state_write_enable[word_index])
                            sponge_state[word_index*64+:64] <= next_word;
                end
            end

            always_ff @(posedge clk) begin
                if (rst) begin
                    hash_state   <= HASH_IDLE;
                    first_block  <= 1;
                    running_last <= 0;
                    append_index <= 0;
                end else
                    case (hash_state)
                        HASH_IDLE:
                        if (state == START) begin
                            first_block  <= 1;
                            append_index <= 0;
                            hash_state   <= HASH_WAIT_BLOCK;
                        end
                        HASH_WAIT_BLOCK:
                        if (staged_valid) begin
                            if (append_index == 8) begin
                                running_last <= staged_last;
                                append_index <= 0;
                                hash_state   <= HASH_RUN;
                            end else append_index <= append_index + 1'b1;
                        end
                        HASH_RUN:
                        if (round_complete) begin
                            if (running_last) hash_state <= HASH_IDLE;
                            else begin
                                first_block <= 0;
                                hash_state  <= HASH_WAIT_BLOCK;
                            end
                        end
                        default: hash_state <= HASH_IDLE;
                    endcase
            end

            always_ff @(posedge clk) begin
                if (rst) begin
                    staged_valid <= 0;
                    staged_last <= 0;
                    staged_data <= 0;
                    position <= 0;
                    list_cursor <= 0;
                    list_remainder <= 0;
                    state <= IDLE;
                    error <= 0;
                    beat <= 0;
                end else begin
                    if (STREAM_ENABLE && output_accept) begin
                        staged_valid <= fetched_valid;
                        if (fetched_valid) begin
                            staged_data <= stream_data;
                            staged_last <= fetched_last;
                        end
                    end
                    case (state)
                        IDLE:
                        if (request_valid && request_ready) begin
                            staged_valid <= 0;
                            position <= 0;
                            list_cursor <= 0;
                            list_remainder <= 0;
                            error <= 0;
                            beat <= 0;
                            state <= scalar_fixed ? FIXED_WAIT : START;
                        end
                        FIXED_WAIT:
                        if (engine_valid && response_ready) begin
                            state <= IDLE;
                        end
                        START:
                        if (hash_ready) begin
                            state <= STREAM;
                        end
                        STREAM:
                        if (STREAM_ENABLE && stream_accept) begin
                            position <= position + 13'(stream_advance);
                            begin
                                if (position < prefix_bytes) begin
                                    if (position + stream_advance >= prefix_bytes)
                                        list_remainder <= position + stream_advance - prefix_bytes;
                                end else if (next_remainder >= stream_node_bytes) begin
                                    list_remainder <= next_remainder - stream_node_bytes;
                                    list_cursor <= list_cursor + 1'b1;
                                end else list_remainder <= next_remainder;
                            end
                            if (beat == 8) begin
                                beat <= 0;
                                if (stream_last) state <= WAIT_HASH;
                            end else beat <= beat + 1'b1;
                        end
                        WAIT_HASH: if (completed) state <= RESPONSE;
                        RESPONSE:
                        if (response_ready) begin
                            state <= IDLE;
                        end
                        default:   state <= IDLE;
                    endcase
                end
            end

`ifndef SYNTHESIS
            // Diagnostics observe the functional handshakes without driving the FSM.
            always_ff @(posedge clk) begin : debug_statistics
                if (rst) begin
                    hash_count <= 0;
                    permutation_count <= 0;
                end else begin
                    if (state == START && hash_ready) hash_count <= hash_count + 1'b1;
                    if (state == STREAM && STREAM_ENABLE && stream_accept && beat == 8)
                        permutation_count <= permutation_count + 1'b1;
                end
            end
`endif
        end
    endgenerate
    // Functional observation aliases preserve existing simulation probes.
    wire permutation_complete, running_last, batch_perm_done;
    wire [PIPELINE-1:0] stage_valid;
    generate
        if (PIPELINE == 1) begin : scalar_observation
            assign permutation_complete = scalar_execution.permutation_complete;
            assign running_last = scalar_execution.running_last;
            assign batch_perm_done = 1'b0;
            assign stage_valid = '0;
        end else begin : scheduled_observation
            assign permutation_complete = scheduled_execution.permutation_complete;
            assign running_last = scheduled_execution.running_last;
            assign batch_perm_done = scheduled_execution.batch_perm_done;
            assign stage_valid = scheduled_execution.stage_valid;
        end
    endgenerate
endmodule
`default_nettype wire

`endif // !MHBS_SHA2
