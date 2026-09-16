`timescale 1ns/1ps
`default_nettype none

// Descriptor-driven, algorithm-independent SHAKE256 composer.
//
// Input mode 1 preserves the original contiguous-Scratchpad capability.
// Input mode 2 interprets a bounded static component program. Components can
// append a literal, zero bytes, one big-endian register word, a Scratchpad
// segment, or the XOR of two equal-length Scratchpad segments. Source and
// destination addresses are bounded affine expressions over the sequencer's
// read-only register snapshot. No component can loop, issue another hash, or
// accept a runtime task descriptor.
module micro_hbs_descriptor_shake_composer #(
    parameter integer LAYOUT_COUNT = 16,
    parameter integer COMPONENT_WORDS = 256,
    parameter integer SCRATCH_WORDS = 1024,
    parameter integer MAX_MESSAGE_BYTES = 4096,
    parameter integer LOGICAL_SLOT_BYTES = 32,
    parameter integer UNROLL = 2
) (
    input  wire         clk,
    input  wire         rst_n,
    input  wire         engine_busy,

    input  wire         cfg_valid,
    output wire         cfg_ready,
    input  wire [15:0]  cfg_layout_id,
    input  wire [127:0] cfg_descriptor,
    output wire         cfg_error,
    output wire [15:0]  cfg_error_code,

    input  wire         component_cfg_valid,
    output wire         component_cfg_ready,
    input  wire [15:0]  component_cfg_index,
    input  wire [191:0] component_cfg_descriptor,
    output wire         component_cfg_error,
    output wire [15:0]  component_cfg_error_code,

    input  wire         req_valid,
    output wire         req_ready,
    input  wire [15:0]  layout_id,
    input  wire [1:0]   lane_mask,
    input  wire [7:0]   destination,
    input  wire [31:0]  index_value,
    input  wire [255:0] register_snapshot,
    output logic        rsp_valid,
    output logic        rsp_error,
    output logic [15:0] rsp_error_code,

    output logic        sp_req_valid,
    input  wire         sp_req_ready,
    output logic        sp_req_write,
    output logic [15:0] sp_req_address,
    output logic [63:0] sp_req_write_data,
    input  wire         sp_rsp_valid,
    input  wire [63:0]  sp_rsp_read_data,
    input  wire         sp_rsp_error,

    output wire         busy,
    output logic [255:0] last_digest,
    output logic [31:0] scratch_reads,
    output logic [31:0] scratch_writes,
    output logic [31:0] absorbed_blocks,
    output logic [31:0] retired_components
);
    localparam logic [7:0] CAP_SHAKE256 = 8'h01;
    localparam logic [7:0] INPUT_CONTIGUOUS_SCRATCH = 8'h01;
    localparam logic [7:0] INPUT_COMPONENT_PROGRAM = 8'h02;
    localparam logic [7:0] OUTPUT_LOGICAL_SLOT = 8'h01;

    localparam logic [7:0] COMP_LITERAL_BE = 8'h01;
    localparam logic [7:0] COMP_ZERO = 8'h02;
    localparam logic [7:0] COMP_REGISTER_BE32 = 8'h03;
    localparam logic [7:0] COMP_SCRATCH = 8'h04;
    localparam logic [7:0] COMP_SCRATCH_XOR = 8'h05;
    localparam logic [7:0] COMP_AFFINE_BE32 = 8'h06;
    localparam logic [7:0] COMP_SHIFTED_AFFINE_BE32 = 8'h07;
    localparam logic [7:0] COMP_SELECT_SCRATCH = 8'h08;

    localparam logic [15:0] ERR_BAD_CAPABILITY = 16'h0b01;
    localparam logic [15:0] ERR_BAD_MODE       = 16'h0b02;
    localparam logic [15:0] ERR_BAD_DESCRIPTOR = 16'h0b03;
    localparam logic [15:0] ERR_BAD_LANE_MASK  = 16'h0103;
    localparam logic [15:0] ERR_SCRATCH_BOUNDS = 16'h0201;
    localparam logic [15:0] ERR_HASH           = 16'h0301;
    localparam logic [15:0] ERR_COMPONENT      = 16'h0b04;
    localparam logic [15:0] ERR_MESSAGE_LENGTH = 16'h0b05;
    localparam integer SLOT_WORDS = LOGICAL_SLOT_BYTES / 8;

    typedef enum logic [4:0] {
        S_IDLE, S_LAYOUT_WAIT, S_LAYOUT_PRODUCTS, S_LAYOUT_VALIDATE,
        S_HASH_START, S_CONTIG_BLOCK_PREP,
        S_CONTIG_READ_REQ, S_CONTIG_READ_WAIT, S_COMPONENT_REQ,
        S_COMPONENT_WAIT, S_COMPONENT_OPERANDS, S_COMPONENT_PRODUCTS,
        S_COMPONENT_VALIDATE, S_SOURCE_A_REQ,
        S_SOURCE_A_WAIT, S_SOURCE_B_REQ, S_SOURCE_B_WAIT, S_EMIT_BYTE,
        S_BLOCK_SEND, S_DIGEST_WAIT, S_WRITE_REQ
    } state_t;
    state_t state, resume_state;

    wire layout_lookup_ready, layout_lookup_rsp_valid;
    wire layout_lookup_rsp_error;
    wire [15:0] layout_lookup_rsp_error_code;
    wire [127:0] lookup_descriptor;
    wire layout_lookup_valid = (state == S_IDLE) && req_valid;

    logic [127:0] active_layout;

    wire [7:0] desc_capability = active_layout[119:112];
    wire [7:0] desc_input_mode = active_layout[111:104];
    wire [7:0] desc_output_mode = active_layout[103:96];
    wire [15:0] desc_flags = active_layout[95:80];
    wire [15:0] desc_message_bytes = active_layout[79:64];
    wire [15:0] desc_component_pc = active_layout[63:48];
    wire [7:0] desc_component_count = active_layout[47:40];
    wire [7:0] desc_source_count = active_layout[39:32];
    wire [15:0] desc_scratch_base_word = active_layout[31:16];
    wire [15:0] desc_scratch_span_words = active_layout[15:0];
    wire [16:0] desc_input_words = ({1'b0, desc_message_bytes} + 7) >> 3;
    wire [8:0] desc_output_words = ({1'b0, desc_flags[7:0]} + 7) >> 3;

    // Component-mode destination encoding in layout_descriptor[31:0].
    wire [7:0] desc_dest_base_slot = active_layout[31:24];
    wire [2:0] desc_dest_base_reg = active_layout[23:21];
    wire desc_dest_use_base_reg = active_layout[20];
    wire [2:0] desc_dest_index_reg = active_layout[19:17];
    wire desc_dest_use_index_reg = active_layout[16];
    wire [7:0] desc_dest_stride = active_layout[15:8];
    wire [7:0] desc_dest_reserved = active_layout[7:0];

    wire component_lookup_ready, component_lookup_rsp_valid;
    wire component_lookup_rsp_error;
    wire [15:0] component_lookup_rsp_error_code;
    wire [191:0] lookup_component;
    logic [191:0] active_component;
    wire component_lookup_valid = (state == S_COMPONENT_REQ);

    wire [7:0] comp_kind = active_component[183:176];
    wire [7:0] comp_byte_count = active_component[175:168];
    wire [7:0] comp_address_flags = active_component[167:160];
    wire [15:0] comp_a_base_slot = active_component[159:144];
    wire [2:0] comp_a_reg0 = active_component[142:140];
    wire [15:0] comp_a_scale0 = active_component[139:124];
    wire [2:0] comp_a_reg1 = active_component[122:120];
    wire [15:0] comp_a_scale1 = active_component[119:104];
    wire [15:0] comp_b_base_slot = active_component[103:88];
    wire [2:0] comp_b_reg0 = active_component[86:84];
    wire [15:0] comp_b_scale0 = active_component[83:68];
    wire [2:0] comp_b_reg1 = active_component[66:64];
    wire [15:0] comp_b_scale1 = active_component[63:48];
    wire [31:0] comp_immediate = active_component[47:16];
    wire [15:0] comp_reserved = active_component[15:0];

    logic [255:0] saved_registers;
    logic [7:0] saved_destination;
    logic [31:0] saved_index_value;
    logic [7:0] input_mode;
    logic [15:0] message_bytes;
    logic [15:0] total_emitted;
    logic [7:0] output_bytes;
    logic [4:0] output_words;
    logic [15:0] output_base_word;
    logic [15:0] source_word_address;
    logic [15:0] source_b_word_address;
    logic [15:0] remaining_bytes;
    logic [4:0] block_word_index;
    logic [4:0] block_words_target;
    logic [7:0] block_bytes_target;
    logic block_is_last;
    logic [1087:0] block_buffer;
    logic [7:0] block_fill;
    logic [4:0] write_word_index;
    logic [1087:0] digest_buffer;
    logic [15:0] component_pc;
    logic [7:0] components_remaining;
    logic [7:0] current_kind;
    logic [7:0] component_remaining;
    logic [7:0] component_byte_index;
    logic [31:0] component_immediate;
    logic [63:0] source_a_word, source_b_word;
    logic [2:0] source_byte_index;
    logic [31:0] comp_a_value0, comp_a_value1;
    logic [31:0] comp_b_value0, comp_b_value1;
    logic [47:0] comp_a_product0_reg, comp_a_product1_reg;
    logic [47:0] comp_b_product0_reg, comp_b_product1_reg;
    logic [31:0] dest_base_reg_value;
    logic [31:0] dest_index_reg_value;
    logic [39:0] dest_index_product_reg;

    wire [31:0] reg_a0 = saved_registers[32*comp_a_reg0 +: 32];
    wire [31:0] reg_a1 = saved_registers[32*comp_a_reg1 +: 32];
    wire [31:0] reg_b0 = saved_registers[32*comp_b_reg0 +: 32];
    wire [31:0] reg_b1 = saved_registers[32*comp_b_reg1 +: 32];
    (* use_dsp = "no" *) wire [47:0] comp_a_product0
        = comp_a_value0 * comp_a_scale0;
    (* use_dsp = "no" *) wire [47:0] comp_a_product1
        = comp_a_value1 * comp_a_scale1;
    (* use_dsp = "no" *) wire [47:0] comp_b_product0
        = comp_b_value0 * comp_b_scale0;
    (* use_dsp = "no" *) wire [47:0] comp_b_product1
        = comp_b_value1 * comp_b_scale1;
    wire [63:0] comp_a_slot_calc = {48'b0, comp_a_base_slot}
        + (comp_address_flags[0] ? comp_a_product0_reg : 64'b0)
        + (comp_address_flags[1] ? comp_a_product1_reg : 64'b0);
    wire [63:0] comp_b_slot_calc = {48'b0, comp_b_base_slot}
        + (comp_address_flags[2] ? comp_b_product0_reg : 64'b0)
        + (comp_address_flags[3] ? comp_b_product1_reg : 64'b0);
    wire [63:0] comp_a_word_calc = comp_a_slot_calc * SLOT_WORDS;
    wire [63:0] comp_b_word_calc = comp_b_slot_calc * SLOT_WORDS;
    wire [8:0] comp_span_words = ({1'b0, comp_byte_count} + 7) >> 3;
    wire [2:0] comp_shift_reg = comp_immediate[2:0];
    wire [4:0] comp_shift_add = comp_immediate[7:3];
    wire [31:0] comp_shift_reg_value =
        saved_registers[32*comp_shift_reg +: 32];
    wire [5:0] shifted_affine_amount =
        comp_shift_reg_value[5:0] + {1'b0, comp_shift_add};
    wire [31:0] shifted_affine_value = shifted_affine_amount >= 32
        ? 32'b0 : comp_a_slot_calc[31:0] >> shifted_affine_amount;
    wire [2:0] comp_select_value_reg = comp_immediate[2:0];
    wire [2:0] comp_select_shift_reg = comp_immediate[5:3];
    wire [4:0] comp_select_shift_add = comp_immediate[10:6];
    wire [31:0] comp_select_value =
        saved_registers[32*comp_select_value_reg +: 32];
    wire [31:0] comp_select_shift_value =
        saved_registers[32*comp_select_shift_reg +: 32];
    wire [5:0] select_shift_amount =
        comp_select_shift_value[5:0] + {1'b0, comp_select_shift_add};
    wire select_nonzero = select_shift_amount < 32
        && comp_select_value[select_shift_amount[4:0]];

    (* use_dsp = "no" *) wire [39:0] dest_index_product
        = dest_index_reg_value * desc_dest_stride;
    wire [63:0] dest_slot_calc = {56'b0, desc_dest_base_slot}
        + (desc_dest_use_base_reg ? dest_base_reg_value : 64'b0)
        + (desc_dest_use_index_reg
           ? dest_index_product_reg : 64'b0);
    wire [63:0] dest_word_calc = dest_slot_calc * SLOT_WORDS;

    wire shake_ready, shake_block_ready;
    wire [255:0] shake_digest;
    wire [1087:0] shake_rate_output;
    wire shake_digest_valid, shake_error;
    wire shake_start = (state == S_HASH_START) && shake_ready;
    wire shake_block_valid = (state == S_BLOCK_SEND);
    logic [7:0] emitted_byte;
    integer output_byte_index;
    logic [63:0] masked_output_word;

    assign req_ready = (state == S_IDLE) && layout_lookup_ready;
    assign busy = (state != S_IDLE);

    always_comb begin
        case (current_kind)
            COMP_LITERAL_BE, COMP_REGISTER_BE32, COMP_AFFINE_BE32,
            COMP_SHIFTED_AFFINE_BE32:
                emitted_byte = component_immediate[
                    8*(component_remaining-1) +: 8];
            COMP_ZERO: emitted_byte = 8'b0;
            COMP_SCRATCH, COMP_SELECT_SCRATCH:
                emitted_byte = source_a_word[8*source_byte_index +: 8];
            COMP_SCRATCH_XOR:
                emitted_byte = source_a_word[8*source_byte_index +: 8]
                    ^ source_b_word[8*source_byte_index +: 8];
            default: emitted_byte = 8'b0;
        endcase
    end

    always_comb begin
        sp_req_valid = 1'b0;
        sp_req_write = 1'b0;
        sp_req_address = '0;
        sp_req_write_data = '0;
        masked_output_word = digest_buffer[64*write_word_index +: 64];
        for (output_byte_index = 0; output_byte_index < 8;
             output_byte_index = output_byte_index + 1)
            if ((write_word_index * 8 + output_byte_index) >= output_bytes)
                masked_output_word[8*output_byte_index +: 8] = 8'b0;
        if (state == S_CONTIG_READ_REQ || state == S_SOURCE_A_REQ) begin
            sp_req_valid = 1'b1;
            sp_req_address = source_word_address;
        end else if (state == S_SOURCE_B_REQ) begin
            sp_req_valid = 1'b1;
            sp_req_address = source_b_word_address;
        end else if (state == S_WRITE_REQ) begin
            sp_req_valid = 1'b1;
            sp_req_write = 1'b1;
            sp_req_address = output_base_word + write_word_index;
            sp_req_write_data = masked_output_word;
        end
    end

    micro_hbs_layout_descriptor_store #(.LAYOUT_COUNT(LAYOUT_COUNT))
        descriptor_store (
        .clk, .rst_n, .engine_busy,
        .cfg_valid, .cfg_ready, .cfg_layout_id, .cfg_descriptor,
        .cfg_error, .cfg_error_code,
        .lookup_valid(layout_lookup_valid), .lookup_ready(layout_lookup_ready),
        .lookup_layout_id(layout_id),
        .lookup_rsp_valid(layout_lookup_rsp_valid),
        .lookup_rsp_error(layout_lookup_rsp_error),
        .lookup_rsp_error_code(layout_lookup_rsp_error_code),
        .lookup_descriptor, .image_locked(), .layout_capacity(),
        .configured_count(), .accepted_loads(), .rejected_loads(),
        .host_writes_busy(), .lookup_requests(), .lookup_errors()
    );

    micro_hbs_layout_component_store #(.COMPONENT_WORDS(COMPONENT_WORDS))
        component_store (
        .clk, .rst_n, .engine_busy,
        .cfg_valid(component_cfg_valid), .cfg_ready(component_cfg_ready),
        .cfg_index(component_cfg_index),
        .cfg_component(component_cfg_descriptor),
        .cfg_error(component_cfg_error),
        .cfg_error_code(component_cfg_error_code),
        .lookup_valid(component_lookup_valid),
        .lookup_ready(component_lookup_ready), .lookup_index(component_pc),
        .lookup_rsp_valid(component_lookup_rsp_valid),
        .lookup_rsp_error(component_lookup_rsp_error),
        .lookup_rsp_error_code(component_lookup_rsp_error_code),
        .lookup_component, .configured_count(), .accepted_loads(),
        .rejected_loads(), .host_writes_busy(), .lookup_requests(),
        .lookup_errors()
    );

    micro_hbs_shake256_stream #(.UNROLL(UNROLL)) shake_lane (
        .clk, .rst_n, .hash_start(shake_start), .hash_ready(shake_ready),
        .block_valid(shake_block_valid), .block_ready(shake_block_ready),
        .block_data(block_buffer), .block_bytes(block_bytes_target),
        .block_last(block_is_last), .digest(shake_digest),
        .rate_output(shake_rate_output),
        .digest_valid(shake_digest_valid), .error(shake_error)
    );

    task automatic fail(input logic [15:0] code);
        begin
            rsp_valid <= 1'b1;
            rsp_error <= 1'b1;
            rsp_error_code <= code;
            state <= S_IDLE;
        end
    endtask

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= S_IDLE;
            resume_state <= S_IDLE;
            saved_registers <= '0;
            saved_destination <= '0;
            saved_index_value <= '0;
            active_layout <= '0;
            input_mode <= '0;
            message_bytes <= '0;
            total_emitted <= '0;
            output_bytes <= '0;
            output_words <= '0;
            output_base_word <= '0;
            source_word_address <= '0;
            source_b_word_address <= '0;
            remaining_bytes <= '0;
            block_word_index <= '0;
            block_words_target <= '0;
            block_bytes_target <= '0;
            block_is_last <= 1'b0;
            block_buffer <= '0;
            block_fill <= '0;
            write_word_index <= '0;
            component_pc <= '0;
            active_component <= '0;
            components_remaining <= '0;
            current_kind <= '0;
            component_remaining <= '0;
            component_byte_index <= '0;
            component_immediate <= '0;
            source_a_word <= '0;
            source_b_word <= '0;
            source_byte_index <= '0;
            comp_a_value0 <= '0;
            comp_a_value1 <= '0;
            comp_b_value0 <= '0;
            comp_b_value1 <= '0;
            comp_a_product0_reg <= '0;
            comp_a_product1_reg <= '0;
            comp_b_product0_reg <= '0;
            comp_b_product1_reg <= '0;
            dest_base_reg_value <= '0;
            dest_index_reg_value <= '0;
            dest_index_product_reg <= '0;
            rsp_valid <= 1'b0;
            rsp_error <= 1'b0;
            rsp_error_code <= '0;
            last_digest <= '0;
            digest_buffer <= '0;
            scratch_reads <= '0;
            scratch_writes <= '0;
            absorbed_blocks <= '0;
            retired_components <= '0;
        end else begin
            rsp_valid <= 1'b0;
            rsp_error <= 1'b0;
            rsp_error_code <= '0;

            case (state)
                S_IDLE: if (req_valid && req_ready) begin
                    saved_destination <= destination;
                    saved_index_value <= index_value;
                    saved_registers <= register_snapshot;
                    if (lane_mask != 2'b01)
                        fail(ERR_BAD_LANE_MASK);
                    else
                        state <= S_LAYOUT_WAIT;
                end

                S_LAYOUT_WAIT: if (layout_lookup_rsp_valid) begin
                    if (layout_lookup_rsp_error)
                        fail(layout_lookup_rsp_error_code);
                    else begin
                        active_layout <= lookup_descriptor;
                        dest_base_reg_value <= saved_registers[
                            32*lookup_descriptor[23:21] +: 32];
                        dest_index_reg_value <= saved_registers[
                            32*lookup_descriptor[19:17] +: 32];
                        state <= S_LAYOUT_PRODUCTS;
                    end
                end

                // Isolate variable register selection and the small affine
                // multiplier from destination bounds/descriptor validation.
                // This costs two fixed cycles per HASH_LAYOUT request but
                // removes the descriptor-RAM -> block-buffer-enable path.
                S_LAYOUT_PRODUCTS: begin
                    dest_index_product_reg <= dest_index_product;
                    state <= S_LAYOUT_VALIDATE;
                end

                S_LAYOUT_VALIDATE: begin
                    if (desc_capability != CAP_SHAKE256)
                        fail(ERR_BAD_CAPABILITY);
                    else if (desc_output_mode != OUTPUT_LOGICAL_SLOT)
                        fail(ERR_BAD_MODE);
                    else if (desc_flags[15:8] != 0 || desc_flags[7:0] == 0
                             || desc_flags[7:0] > 136
                             || desc_message_bytes > MAX_MESSAGE_BYTES)
                        fail(ERR_BAD_DESCRIPTOR);
                    else if (desc_input_mode == INPUT_CONTIGUOUS_SCRATCH) begin
                        if (desc_component_pc != 0
                            || desc_component_count != 0
                            || desc_source_count != 1
                            || desc_scratch_span_words < desc_input_words
                            || ({2'b0, desc_scratch_base_word}
                                + desc_input_words) > SCRATCH_WORDS
                            || (({56'b0, saved_destination} * SLOT_WORDS)
                                + desc_output_words) > SCRATCH_WORDS)
                            fail(ERR_BAD_DESCRIPTOR);
                        else begin
                            input_mode <= INPUT_CONTIGUOUS_SCRATCH;
                            source_word_address <= desc_scratch_base_word;
                            remaining_bytes <= desc_message_bytes;
                            message_bytes <= desc_message_bytes;
                            output_bytes <= desc_flags[7:0];
                            output_words <= desc_output_words[4:0];
                            output_base_word <= saved_destination * SLOT_WORDS;
                            state <= S_HASH_START;
                        end
                    end else if (desc_input_mode == INPUT_COMPONENT_PROGRAM) begin
                        if (desc_message_bytes == 0
                            || desc_component_count == 0
                            || desc_source_count != desc_component_count
                            || desc_dest_reserved != 0
                            || (desc_dest_use_index_reg
                                && desc_dest_stride == 0)
                            || dest_word_calc > 16'hffff
                            || dest_word_calc + desc_output_words > SCRATCH_WORDS)
                            fail(ERR_BAD_DESCRIPTOR);
                        else begin
                            input_mode <= INPUT_COMPONENT_PROGRAM;
                            message_bytes <= desc_message_bytes;
                            total_emitted <= '0;
                            output_bytes <= desc_flags[7:0];
                            output_words <= desc_output_words[4:0];
                            output_base_word <= dest_word_calc[15:0];
                            component_pc <= desc_component_pc;
                            components_remaining <= desc_component_count;
                            block_buffer <= '0;
                            block_fill <= '0;
                            state <= S_HASH_START;
                        end
                    end else
                        fail(ERR_BAD_MODE);
                end

                S_HASH_START: if (shake_ready) begin
                    if (input_mode == INPUT_CONTIGUOUS_SCRATCH)
                        state <= S_CONTIG_BLOCK_PREP;
                    else
                        state <= S_COMPONENT_REQ;
                end

                S_CONTIG_BLOCK_PREP: begin
                    block_buffer <= '0;
                    block_word_index <= '0;
                    if (remaining_bytes > 135) begin
                        block_bytes_target <= 8'd136;
                        block_words_target <= 5'd17;
                        block_is_last <= 1'b0;
                        state <= S_CONTIG_READ_REQ;
                    end else begin
                        block_bytes_target <= remaining_bytes[7:0];
                        block_words_target <= (remaining_bytes + 7) >> 3;
                        block_is_last <= 1'b1;
                        if (remaining_bytes == 0)
                            state <= S_BLOCK_SEND;
                        else
                            state <= S_CONTIG_READ_REQ;
                    end
                end

                S_CONTIG_READ_REQ: begin
                    if (sp_rsp_error)
                        fail(ERR_SCRATCH_BOUNDS);
                    else if (sp_req_ready)
                        state <= S_CONTIG_READ_WAIT;
                end

                S_CONTIG_READ_WAIT: begin
                    if (sp_rsp_error)
                        fail(ERR_SCRATCH_BOUNDS);
                    else if (sp_rsp_valid) begin
                        block_buffer[64*block_word_index +: 64]
                            <= sp_rsp_read_data;
                        scratch_reads <= scratch_reads + 1'b1;
                        source_word_address <= source_word_address + 1'b1;
                        if (block_word_index + 1'b1 == block_words_target)
                            state <= S_BLOCK_SEND;
                        else begin
                            block_word_index <= block_word_index + 1'b1;
                            state <= S_CONTIG_READ_REQ;
                        end
                    end
                end

                S_COMPONENT_REQ: begin
                    if (component_lookup_ready)
                        state <= S_COMPONENT_WAIT;
                end

                S_COMPONENT_WAIT: if (component_lookup_rsp_valid) begin
                    if (component_lookup_rsp_error)
                        fail(component_lookup_rsp_error_code);
                    else begin
                        active_component <= lookup_component;
                        state <= S_COMPONENT_OPERANDS;
                    end
                end

                // Register the variable register-file selects separately from
                // the multiplier and address/bounds logic.  This keeps the
                // generic affine component format while removing the former
                // register-mux -> multiply -> add -> compare one-cycle path.
                S_COMPONENT_OPERANDS: begin
                    comp_a_value0 <= reg_a0;
                    comp_a_value1 <= reg_a1;
                    comp_b_value0 <= reg_b0;
                    comp_b_value1 <= reg_b1;
                    state <= S_COMPONENT_PRODUCTS;
                end

                S_COMPONENT_PRODUCTS: begin
                    comp_a_product0_reg <= comp_a_product0;
                    comp_a_product1_reg <= comp_a_product1;
                    comp_b_product0_reg <= comp_b_product0;
                    comp_b_product1_reg <= comp_b_product1;
                    state <= S_COMPONENT_VALIDATE;
                end

                S_COMPONENT_VALIDATE: begin
                    if (active_component[191:184] != 8'h01
                        || comp_reserved != 0 || comp_address_flags[7:4] != 0
                        || comp_byte_count == 0
                        || total_emitted + comp_byte_count > message_bytes)
                        fail(ERR_COMPONENT);
                    else if (comp_kind == COMP_LITERAL_BE
                             && (comp_byte_count > 4
                                 || comp_address_flags != 0))
                        fail(ERR_COMPONENT);
                    else if (comp_kind == COMP_ZERO
                             && comp_address_flags != 0)
                        fail(ERR_COMPONENT);
                    else if (comp_kind == COMP_REGISTER_BE32
                             && (comp_byte_count != 4
                                 || comp_address_flags != 0
                                 || comp_immediate[31:3] != 0))
                        fail(ERR_COMPONENT);
                    else if (comp_kind == COMP_AFFINE_BE32
                             && (comp_byte_count != 4
                                 || comp_address_flags[7:2] != 0
                                 || comp_a_slot_calc > 32'hffffffff))
                        fail(ERR_COMPONENT);
                    else if (comp_kind == COMP_SHIFTED_AFFINE_BE32
                             && (comp_byte_count != 4
                                 || comp_address_flags[7:2] != 0
                                 || comp_immediate[31:8] != 0
                                 || comp_a_slot_calc > 32'hffffffff))
                        fail(ERR_COMPONENT);
                    else if (comp_kind == COMP_SCRATCH
                             && (comp_address_flags[3:2] != 0
                                 || comp_a_word_calc > 16'hffff
                                 || comp_a_word_calc + comp_span_words
                                    > SCRATCH_WORDS))
                        fail(ERR_SCRATCH_BOUNDS);
                    else if (comp_kind == COMP_SCRATCH_XOR
                             && (comp_a_word_calc > 16'hffff
                                 || comp_b_word_calc > 16'hffff
                                 || comp_a_word_calc + comp_span_words
                                    > SCRATCH_WORDS
                                 || comp_b_word_calc + comp_span_words
                                    > SCRATCH_WORDS))
                        fail(ERR_SCRATCH_BOUNDS);
                    else if (comp_kind == COMP_SELECT_SCRATCH
                             && (comp_immediate[31:11] != 0
                                 || comp_a_word_calc > 16'hffff
                                 || comp_b_word_calc > 16'hffff
                                 || comp_a_word_calc + comp_span_words
                                    > SCRATCH_WORDS
                                 || comp_b_word_calc + comp_span_words
                                    > SCRATCH_WORDS))
                        fail(ERR_SCRATCH_BOUNDS);
                    else if (comp_kind != COMP_LITERAL_BE
                             && comp_kind != COMP_ZERO
                             && comp_kind != COMP_REGISTER_BE32
                             && comp_kind != COMP_AFFINE_BE32
                             && comp_kind != COMP_SHIFTED_AFFINE_BE32
                             && comp_kind != COMP_SCRATCH
                             && comp_kind != COMP_SCRATCH_XOR
                             && comp_kind != COMP_SELECT_SCRATCH)
                        fail(ERR_COMPONENT);
                    else begin
                        current_kind <= comp_kind;
                        component_remaining <= comp_byte_count;
                        component_byte_index <= '0;
                        source_byte_index <= '0;
                        if (comp_kind == COMP_REGISTER_BE32)
                            component_immediate <= saved_registers[
                                32*comp_immediate[2:0] +: 32];
                        else if (comp_kind == COMP_AFFINE_BE32)
                            component_immediate <= comp_a_slot_calc[31:0];
                        else if (comp_kind == COMP_SHIFTED_AFFINE_BE32)
                            component_immediate <= shifted_affine_value;
                        else
                            component_immediate <= comp_immediate;
                        source_word_address <=
                            (comp_kind == COMP_SELECT_SCRATCH && select_nonzero)
                            ? comp_b_word_calc[15:0]
                            : comp_a_word_calc[15:0];
                        source_b_word_address <= comp_b_word_calc[15:0];
                        if (comp_kind == COMP_SCRATCH
                            || comp_kind == COMP_SELECT_SCRATCH
                            || comp_kind == COMP_SCRATCH_XOR)
                            state <= S_SOURCE_A_REQ;
                        else
                            state <= S_EMIT_BYTE;
                    end
                end

                S_SOURCE_A_REQ: begin
                    if (sp_rsp_error)
                        fail(ERR_SCRATCH_BOUNDS);
                    else if (sp_req_ready)
                        state <= S_SOURCE_A_WAIT;
                end

                S_SOURCE_A_WAIT: begin
                    if (sp_rsp_error)
                        fail(ERR_SCRATCH_BOUNDS);
                    else if (sp_rsp_valid) begin
                        source_a_word <= sp_rsp_read_data;
                        scratch_reads <= scratch_reads + 1'b1;
                        if (current_kind == COMP_SCRATCH_XOR)
                            state <= S_SOURCE_B_REQ;
                        else
                            state <= S_EMIT_BYTE;
                    end
                end

                S_SOURCE_B_REQ: begin
                    if (sp_rsp_error)
                        fail(ERR_SCRATCH_BOUNDS);
                    else if (sp_req_ready)
                        state <= S_SOURCE_B_WAIT;
                end

                S_SOURCE_B_WAIT: begin
                    if (sp_rsp_error)
                        fail(ERR_SCRATCH_BOUNDS);
                    else if (sp_rsp_valid) begin
                        source_b_word <= sp_rsp_read_data;
                        scratch_reads <= scratch_reads + 1'b1;
                        state <= S_EMIT_BYTE;
                    end
                end

                S_EMIT_BYTE: begin
                    block_buffer[8*block_fill +: 8] <= emitted_byte;
                    component_remaining <= component_remaining - 1'b1;
                    component_byte_index <= component_byte_index + 1'b1;
                    total_emitted <= total_emitted + 1'b1;
                    block_fill <= block_fill + 1'b1;

                    if (component_remaining == 1) begin
                        retired_components <= retired_components + 1'b1;
                        component_pc <= component_pc + 1'b1;
                        components_remaining <= components_remaining - 1'b1;
                    end
                    if ((current_kind == COMP_SCRATCH
                         || current_kind == COMP_SELECT_SCRATCH
                         || current_kind == COMP_SCRATCH_XOR)
                        && source_byte_index == 7
                        && component_remaining != 1) begin
                        source_byte_index <= '0;
                        source_word_address <= source_word_address + 1'b1;
                        source_b_word_address <= source_b_word_address + 1'b1;
                    end else if (current_kind == COMP_SCRATCH
                                 || current_kind == COMP_SELECT_SCRATCH
                                 || current_kind == COMP_SCRATCH_XOR)
                        source_byte_index <= source_byte_index + 1'b1;

                    if (block_fill == 8'd135) begin
                        block_bytes_target <= 8'd136;
                        block_is_last <= (total_emitted + 1'b1 == message_bytes);
                        if (component_remaining == 1)
                            resume_state <= S_COMPONENT_REQ;
                        else if ((current_kind == COMP_SCRATCH
                                  || current_kind == COMP_SELECT_SCRATCH
                                  || current_kind == COMP_SCRATCH_XOR)
                                 && source_byte_index == 7)
                            resume_state <= S_SOURCE_A_REQ;
                        else
                            resume_state <= S_EMIT_BYTE;
                        state <= S_BLOCK_SEND;
                    end else if (component_remaining == 1) begin
                        if (components_remaining == 1) begin
                            if (total_emitted + 1'b1 != message_bytes)
                                fail(ERR_MESSAGE_LENGTH);
                            else begin
                                block_bytes_target <= block_fill + 1'b1;
                                block_is_last <= 1'b1;
                                state <= S_BLOCK_SEND;
                            end
                        end else
                            state <= S_COMPONENT_REQ;
                    end else if ((current_kind == COMP_SCRATCH
                                  || current_kind == COMP_SELECT_SCRATCH
                                  || current_kind == COMP_SCRATCH_XOR)
                                 && source_byte_index == 7)
                        state <= S_SOURCE_A_REQ;
                end

                S_BLOCK_SEND: begin
                    if (shake_error)
                        fail(ERR_HASH);
                    else if (shake_block_ready) begin
                        absorbed_blocks <= absorbed_blocks + 1'b1;
                        if (block_is_last)
                            state <= S_DIGEST_WAIT;
                        else if (input_mode == INPUT_CONTIGUOUS_SCRATCH) begin
                            remaining_bytes <= remaining_bytes - 16'd136;
                            state <= S_CONTIG_BLOCK_PREP;
                        end else begin
                            block_buffer <= '0;
                            block_fill <= '0;
                            state <= resume_state;
                        end
                    end
                end

                S_DIGEST_WAIT: begin
                    if (shake_error)
                        fail(ERR_HASH);
                    else if (shake_digest_valid) begin
                        last_digest <= shake_digest;
                        digest_buffer <= shake_rate_output;
                        write_word_index <= '0;
                        state <= S_WRITE_REQ;
                    end
                end

                S_WRITE_REQ: begin
                    if (sp_rsp_error)
                        fail(ERR_SCRATCH_BOUNDS);
                    else if (sp_req_ready) begin
                        scratch_writes <= scratch_writes + 1'b1;
                        if (write_word_index + 1'b1 == output_words) begin
                            rsp_valid <= 1'b1;
                            state <= S_IDLE;
                        end else
                            write_word_index <= write_word_index + 1'b1;
                    end
                end

                default: fail(ERR_BAD_DESCRIPTOR);
            endcase
        end
    end

    initial begin
        if (LOGICAL_SLOT_BYTES < 8
            || (LOGICAL_SLOT_BYTES % 8) != 0
            || (LOGICAL_SLOT_BYTES & (LOGICAL_SLOT_BYTES - 1)) != 0)
            $error("LOGICAL_SLOT_BYTES must be a power-of-two multiple of 8");
    end
endmodule

`default_nettype wire
