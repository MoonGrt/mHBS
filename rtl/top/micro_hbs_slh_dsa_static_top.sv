`timescale 1ns/1ps
`default_nettype none

// Product-facing SLH-DSA-SHAKE-128f Sign top.  All executable and descriptor
// images are immutable readmemh ROMs and are loaded into the proven stores by
// an internal reset-time sequencer.  No host configuration surface escapes.
module micro_hbs_slh_dsa_static_top #(
    parameter integer UNROLL = 2
) (
    input  wire         clk,
    input  wire         rst_n,
    output wire         init_done,
    output wire         init_error,

    input  wire         job_valid,
    output wire         job_ready,
    input  wire [31:0]  job_message_length,
    input  wire [127:0] job_sk_seed,
    input  wire [127:0] job_sk_prf,
    input  wire [127:0] job_pk_seed,
    input  wire [127:0] job_pk_root,
    input  wire [127:0] job_opt_rand,
    input  wire         message_valid,
    output wire         message_ready,
    input  wire [63:0]  message_data,
    input  wire [7:0]   message_keep,
    input  wire         message_last,
    output wire         out_valid,
    input  wire         out_ready,
    output wire [63:0]  out_data,
    output wire [7:0]   out_keep,
    output wire         out_last,

    output wire         busy,
    output wire         done,
    output wire         error,
    output wire [15:0]  error_code,
    output wire [255:0] last_digest,
    output wire [31:0]  accepted_job_commands,
    output wire [31:0]  admitted_message_words,
    output wire [31:0]  issued_hash_requests,
    output wire [31:0]  tree_parent_hashes,
    output wire [31:0]  retired_instructions,
    output wire [31:0]  scratch_reads,
    output wire [31:0]  scratch_writes,
    output wire [31:0]  absorbed_blocks,
    output wire [31:0]  retired_components
);
    localparam integer PROGRAM_WORDS = 160;
    localparam integer LAYOUT_WORDS = 17;
    localparam integer COMPONENT_WORDS_USED = 110;
    localparam integer BITFIELD_WORDS = 8;
    localparam integer EXPR_DESCRIPTOR_WORDS = 6;
    localparam integer EXPR_TOKEN_WORDS = 38;
    localparam integer DATA_DESCRIPTOR_WORDS = 5;
    localparam integer DATA_BINDING_WORDS = 3;
    localparam integer TREE_WORDS = 7;
    localparam logic [63:0] EXPECTED_IMAGE_XOR = 64'hb93bccd63245d8aa;

    localparam logic [3:0] ST_PROGRAM = 4'd0;
    localparam logic [3:0] ST_LAYOUT = 4'd1;
    localparam logic [3:0] ST_COMPONENT = 4'd2;
    localparam logic [3:0] ST_BITFIELD = 4'd3;
    localparam logic [3:0] ST_EXPR_DESCRIPTOR = 4'd4;
    localparam logic [3:0] ST_EXPR_TOKEN = 4'd5;
    localparam logic [3:0] ST_BASE_W = 4'd6;
    localparam logic [3:0] ST_WIDE_SHIFT = 4'd7;
    localparam logic [3:0] ST_DATA_DESCRIPTOR = 4'd8;
    localparam logic [3:0] ST_DATA_BINDING = 4'd9;
    localparam logic [3:0] ST_TREE = 4'd10;
    localparam logic [3:0] ST_CHECK = 4'd11;
    localparam logic [3:0] ST_READY = 4'd12;
    localparam logic [3:0] ST_ERROR = 4'd13;

    logic [63:0] program_image [0:PROGRAM_WORDS-1];
    logic [127:0] layout_image [0:LAYOUT_WORDS-1];
    logic [191:0] component_image [0:COMPONENT_WORDS_USED-1];
    logic [127:0] bitfield_image [0:BITFIELD_WORDS-1];
    logic [63:0] expr_descriptor_image [0:EXPR_DESCRIPTOR_WORDS-1];
    logic [63:0] expr_token_image [0:EXPR_TOKEN_WORDS-1];
    logic [63:0] base_w_image [0:0];
    logic [63:0] wide_shift_image [0:0];
    logic [127:0] data_descriptor_image [0:DATA_DESCRIPTOR_WORDS-1];
    logic [63:0] data_binding_image [0:DATA_BINDING_WORDS-1];
    logic [63:0] tree_image [0:TREE_WORDS-1];

    initial begin
        $readmemh("manifests/programs/rtl_images/slh_dsa_slh_dsa_shake_128f_sign.hex", program_image);
        $readmemh("manifests/programs/rtl_images/slh_dsa_shake_128f_sign_prehash_layouts.hex", layout_image);
        $readmemh("manifests/programs/rtl_images/slh_dsa_shake_128f_sign_prehash_components.hex", component_image);
        $readmemh("manifests/programs/rtl_images/slh_dsa_shake_128f_sign_digest_bitfields.hex", bitfield_image);
        $readmemh("manifests/programs/rtl_images/slh_dsa_shake_128f_sign_expr_descriptors.hex", expr_descriptor_image);
        $readmemh("manifests/programs/rtl_images/slh_dsa_shake_128f_sign_expr_tokens.hex", expr_token_image);
        $readmemh("manifests/programs/rtl_images/slh_dsa_shake_128f_sign_base_w_descriptor.hex", base_w_image);
        $readmemh("manifests/programs/rtl_images/slh_dsa_shake_128f_sign_wide_shift_descriptor.hex", wide_shift_image);
        $readmemh("manifests/programs/rtl_images/slh_dsa_shake_128f_sign_data_descriptors.hex", data_descriptor_image);
        $readmemh("manifests/programs/rtl_images/slh_dsa_shake_128f_sign_data_bindings.hex", data_binding_image);
        $readmemh("manifests/programs/rtl_images/slh_dsa_shake_128f_sign_tree_descriptors.hex", tree_image);
    end

    logic [3:0] init_state;
    logic [8:0] init_index;
    logic [63:0] image_xor;
    logic init_fault;

    logic program_we;
    logic [8:0] program_addr;
    logic [63:0] program_wdata;
    logic layout_cfg_valid, component_cfg_valid, bitfield_cfg_valid;
    logic expr_descriptor_cfg_valid, expr_token_cfg_valid;
    logic base_w_cfg_valid, wide_shift_cfg_valid;
    logic data_descriptor_cfg_valid, data_binding_cfg_valid, tree_cfg_valid;
    wire layout_cfg_ready, component_cfg_ready, bitfield_cfg_ready;
    wire expr_descriptor_cfg_ready, expr_token_cfg_ready;
    wire base_w_cfg_ready, wide_shift_cfg_ready;
    wire data_descriptor_cfg_ready, data_binding_cfg_ready, tree_cfg_ready;
    logic [15:0] layout_cfg_id, component_cfg_index, bitfield_cfg_id;
    logic [15:0] expr_descriptor_cfg_id, base_w_cfg_id, wide_shift_cfg_id;
    logic [15:0] data_descriptor_cfg_id, data_binding_cfg_id, tree_cfg_id;
    logic [5:0] expr_token_cfg_index;
    logic [127:0] layout_cfg_descriptor, bitfield_cfg_descriptor;
    logic [127:0] data_descriptor_cfg_data;
    logic [191:0] component_cfg_descriptor;
    logic [63:0] expr_descriptor_cfg_data, expr_token_cfg_data;
    logic [63:0] base_w_cfg_data, wide_shift_cfg_data;
    logic [63:0] data_binding_cfg_data, tree_cfg_data;
    wire layout_cfg_error, component_cfg_error, bitfield_cfg_error;
    wire expr_descriptor_cfg_error, base_w_cfg_error, wide_shift_cfg_error;
    wire data_descriptor_cfg_error, data_binding_cfg_error, tree_cfg_error;
    wire [15:0] unused_layout_error_code, unused_component_error_code;
    wire [15:0] unused_bitfield_error_code, unused_expr_error_code;
    wire [15:0] unused_base_w_error_code, unused_wide_shift_error_code;
    wire [15:0] unused_data_descriptor_error_code;
    wire [15:0] unused_data_binding_error_code, unused_tree_error_code;
    wire core_job_ready, core_message_ready;
    wire [31:0] unused_host_writes;

    wire any_cfg_error = layout_cfg_error || component_cfg_error
        || bitfield_cfg_error || expr_descriptor_cfg_error
        || base_w_cfg_error || wide_shift_cfg_error
        || data_descriptor_cfg_error || data_binding_cfg_error
        || tree_cfg_error;

    assign init_done = init_state == ST_READY;
    assign init_error = init_state == ST_ERROR;
    assign job_ready = init_done && core_job_ready;
    assign message_ready = init_done && core_message_ready;

    always_comb begin
        program_we = 1'b0;
        program_addr = init_index;
        program_wdata = '0;
        layout_cfg_valid = 1'b0;
        layout_cfg_id = '0;
        layout_cfg_descriptor = '0;
        component_cfg_valid = 1'b0;
        component_cfg_index = init_index;
        component_cfg_descriptor = '0;
        bitfield_cfg_valid = 1'b0;
        bitfield_cfg_id = '0;
        bitfield_cfg_descriptor = '0;
        expr_descriptor_cfg_valid = 1'b0;
        expr_descriptor_cfg_id = '0;
        expr_descriptor_cfg_data = '0;
        expr_token_cfg_valid = 1'b0;
        expr_token_cfg_index = init_index[5:0];
        expr_token_cfg_data = '0;
        base_w_cfg_valid = 1'b0;
        base_w_cfg_id = 16'd9;
        base_w_cfg_data = base_w_image[0];
        wide_shift_cfg_valid = 1'b0;
        wide_shift_cfg_id = 16'd13;
        wide_shift_cfg_data = wide_shift_image[0];
        data_descriptor_cfg_valid = 1'b0;
        data_descriptor_cfg_id = init_index;
        data_descriptor_cfg_data = '0;
        data_binding_cfg_valid = 1'b0;
        data_binding_cfg_id = init_index;
        data_binding_cfg_data = '0;
        tree_cfg_valid = 1'b0;
        tree_cfg_id = '0;
        tree_cfg_data = '0;
        case (init_state)
            ST_PROGRAM: begin
                program_we = 1'b1;
                program_wdata = program_image[init_index];
            end
            ST_LAYOUT: begin
                layout_cfg_valid = 1'b1;
                layout_cfg_descriptor = layout_image[init_index];
                case (init_index)
                    5: layout_cfg_id = 16'd10;
                    6: layout_cfg_id = 16'd11;
                    7: layout_cfg_id = 16'd12;
                    8: layout_cfg_id = 16'd13;
                    9: layout_cfg_id = 16'd14;
                    10: layout_cfg_id = 16'd15;
                    11: layout_cfg_id = 16'd18;
                    12: layout_cfg_id = 16'd19;
                    13: layout_cfg_id = 16'd20;
                    14: layout_cfg_id = 16'd21;
                    15: layout_cfg_id = 16'd22;
                    16: layout_cfg_id = 16'd23;
                    default: layout_cfg_id = init_index;
                endcase
            end
            ST_COMPONENT: begin
                component_cfg_valid = 1'b1;
                component_cfg_descriptor = component_image[init_index];
            end
            ST_BITFIELD: begin
                bitfield_cfg_valid = 1'b1;
                bitfield_cfg_descriptor = bitfield_image[init_index];
                case (init_index)
                    4: bitfield_cfg_id = 16'd10;
                    5: bitfield_cfg_id = 16'd12;
                    6: bitfield_cfg_id = 16'd14;
                    7: bitfield_cfg_id = 16'd15;
                    default: bitfield_cfg_id = init_index;
                endcase
            end
            ST_EXPR_DESCRIPTOR: begin
                expr_descriptor_cfg_valid = 1'b1;
                expr_descriptor_cfg_data = expr_descriptor_image[init_index];
                expr_descriptor_cfg_id = init_index == 5
                    ? 16'd11 : init_index + 16'd4;
            end
            ST_EXPR_TOKEN: begin
                expr_token_cfg_valid = 1'b1;
                expr_token_cfg_data = expr_token_image[init_index];
            end
            ST_BASE_W: base_w_cfg_valid = 1'b1;
            ST_WIDE_SHIFT: wide_shift_cfg_valid = 1'b1;
            ST_DATA_DESCRIPTOR: begin
                data_descriptor_cfg_valid = 1'b1;
                data_descriptor_cfg_data = data_descriptor_image[init_index];
            end
            ST_DATA_BINDING: begin
                data_binding_cfg_valid = 1'b1;
                data_binding_cfg_data = data_binding_image[init_index];
            end
            ST_TREE: begin
                tree_cfg_valid = 1'b1;
                tree_cfg_data = tree_image[init_index];
                tree_cfg_id = init_index < 5
                    ? init_index + 16'd5 : init_index + 16'd11;
            end
            default: begin end
        endcase
    end

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            init_state <= ST_PROGRAM;
            init_index <= '0;
            image_xor <= '0;
            init_fault <= 1'b0;
        end else begin
            if (any_cfg_error)
                init_fault <= 1'b1;
            case (init_state)
                ST_PROGRAM: begin
                    image_xor <= image_xor ^ program_wdata;
                    if (init_index == PROGRAM_WORDS-1) begin
                        init_state <= ST_LAYOUT;
                        init_index <= '0;
                    end else init_index <= init_index + 1'b1;
                end
                ST_LAYOUT: if (layout_cfg_ready) begin
                    image_xor <= image_xor ^ layout_cfg_descriptor[63:0]
                        ^ layout_cfg_descriptor[127:64];
                    if (init_index == LAYOUT_WORDS-1) begin
                        init_state <= ST_COMPONENT;
                        init_index <= '0;
                    end else init_index <= init_index + 1'b1;
                end
                ST_COMPONENT: if (component_cfg_ready) begin
                    image_xor <= image_xor ^ component_cfg_descriptor[63:0]
                        ^ component_cfg_descriptor[127:64]
                        ^ component_cfg_descriptor[191:128];
                    if (init_index == COMPONENT_WORDS_USED-1) begin
                        init_state <= ST_BITFIELD;
                        init_index <= '0;
                    end else init_index <= init_index + 1'b1;
                end
                ST_BITFIELD: if (bitfield_cfg_ready) begin
                    image_xor <= image_xor ^ bitfield_cfg_descriptor[63:0]
                        ^ bitfield_cfg_descriptor[127:64];
                    if (init_index == BITFIELD_WORDS-1) begin
                        init_state <= ST_EXPR_DESCRIPTOR;
                        init_index <= '0;
                    end else init_index <= init_index + 1'b1;
                end
                ST_EXPR_DESCRIPTOR: if (expr_descriptor_cfg_ready) begin
                    image_xor <= image_xor ^ expr_descriptor_cfg_data;
                    if (init_index == EXPR_DESCRIPTOR_WORDS-1) begin
                        init_state <= ST_EXPR_TOKEN;
                        init_index <= '0;
                    end else init_index <= init_index + 1'b1;
                end
                ST_EXPR_TOKEN: if (expr_token_cfg_ready) begin
                    image_xor <= image_xor ^ expr_token_cfg_data;
                    if (init_index == EXPR_TOKEN_WORDS-1) begin
                        init_state <= ST_BASE_W;
                        init_index <= '0;
                    end else init_index <= init_index + 1'b1;
                end
                ST_BASE_W: if (base_w_cfg_ready) begin
                    image_xor <= image_xor ^ base_w_cfg_data;
                    init_state <= ST_WIDE_SHIFT;
                end
                ST_WIDE_SHIFT: if (wide_shift_cfg_ready) begin
                    image_xor <= image_xor ^ wide_shift_cfg_data;
                    init_state <= ST_DATA_DESCRIPTOR;
                    init_index <= '0;
                end
                ST_DATA_DESCRIPTOR: if (data_descriptor_cfg_ready) begin
                    image_xor <= image_xor ^ data_descriptor_cfg_data[63:0]
                        ^ data_descriptor_cfg_data[127:64];
                    if (init_index == DATA_DESCRIPTOR_WORDS-1) begin
                        init_state <= ST_DATA_BINDING;
                        init_index <= '0;
                    end else init_index <= init_index + 1'b1;
                end
                ST_DATA_BINDING: if (data_binding_cfg_ready) begin
                    image_xor <= image_xor ^ data_binding_cfg_data;
                    if (init_index == DATA_BINDING_WORDS-1) begin
                        init_state <= ST_TREE;
                        init_index <= '0;
                    end else init_index <= init_index + 1'b1;
                end
                ST_TREE: if (tree_cfg_ready) begin
                    image_xor <= image_xor ^ tree_cfg_data;
                    if (init_index == TREE_WORDS-1) begin
                        init_state <= ST_CHECK;
                        init_index <= '0;
                    end else init_index <= init_index + 1'b1;
                end
                ST_CHECK: begin
                    if (init_fault || any_cfg_error
                        || image_xor !== EXPECTED_IMAGE_XOR)
                        init_state <= ST_ERROR;
                    else
                        init_state <= ST_READY;
                end
                default: begin end
            endcase
        end
    end

    micro_hbs_slh_dsa_top #(
        .PROGRAM_WORDS(256), .COMPONENT_WORDS(128), .UNROLL(UNROLL)
    ) core (
        .clk, .rst_n,
        .program_we, .program_addr, .program_wdata,
        .layout_cfg_valid, .layout_cfg_ready, .layout_cfg_id,
        .layout_cfg_descriptor, .layout_cfg_error,
        .layout_cfg_error_code(unused_layout_error_code),
        .component_cfg_valid, .component_cfg_ready, .component_cfg_index,
        .component_cfg_descriptor, .component_cfg_error,
        .component_cfg_error_code(unused_component_error_code),
        .bitfield_cfg_valid, .bitfield_cfg_ready, .bitfield_cfg_id,
        .bitfield_cfg_descriptor, .bitfield_cfg_error,
        .bitfield_cfg_error_code(unused_bitfield_error_code),
        .expr_descriptor_cfg_valid, .expr_descriptor_cfg_ready,
        .expr_descriptor_cfg_id, .expr_descriptor_cfg_data,
        .expr_descriptor_cfg_error,
        .expr_descriptor_cfg_error_code(unused_expr_error_code),
        .expr_token_cfg_valid, .expr_token_cfg_ready,
        .expr_token_cfg_index, .expr_token_cfg_data,
        .base_w_cfg_valid, .base_w_cfg_ready, .base_w_cfg_id,
        .base_w_cfg_data, .base_w_cfg_error,
        .base_w_cfg_error_code(unused_base_w_error_code),
        .wide_shift_cfg_valid, .wide_shift_cfg_ready, .wide_shift_cfg_id,
        .wide_shift_cfg_data, .wide_shift_cfg_error,
        .wide_shift_cfg_error_code(unused_wide_shift_error_code),
        .data_descriptor_cfg_valid, .data_descriptor_cfg_ready,
        .data_descriptor_cfg_id, .data_descriptor_cfg_data,
        .data_descriptor_cfg_error,
        .data_descriptor_cfg_error_code(unused_data_descriptor_error_code),
        .data_binding_cfg_valid, .data_binding_cfg_ready,
        .data_binding_cfg_id, .data_binding_cfg_data,
        .data_binding_cfg_error,
        .data_binding_cfg_error_code(unused_data_binding_error_code),
        .tree_cfg_valid, .tree_cfg_ready, .tree_cfg_id, .tree_cfg_data,
        .tree_cfg_error, .tree_cfg_error_code(unused_tree_error_code),
        .job_valid(job_valid && init_done), .job_ready(core_job_ready),
        .job_entry(9'd0), .job_message_length, .job_sk_seed, .job_sk_prf,
        .job_pk_seed, .job_pk_root, .job_opt_rand,
        .message_valid(message_valid && init_done),
        .message_ready(core_message_ready), .message_data, .message_keep,
        .message_last, .out_valid, .out_ready, .out_data, .out_keep,
        .out_last, .busy, .done, .error, .error_code, .last_digest,
        .accepted_job_commands, .admitted_message_words,
        .host_control_writes_during_busy(unused_host_writes),
        .issued_hash_requests, .tree_parent_hashes, .retired_instructions,
        .scratch_reads, .scratch_writes, .absorbed_blocks,
        .retired_components
    );
endmodule

`default_nettype wire
