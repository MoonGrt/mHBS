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
    input  wire         defer_write,
    input  wire         repeat_hash,
    input  wire [7:0]   repeat_count,
    input  wire [7:0]   repeat_counter_offset,
    input  wire [31:0]  repeat_start,
    input  wire         capture_hash,
    input  wire [7:0]   capture_after0,
    input  wire [7:0]   capture_after1,
    input  wire [7:0]   destination,
    input  wire [7:0]   index_reg,
    input  wire [31:0]  index_value,
    input  wire [255:0] register_snapshot,
    output logic        rsp_valid,
    output logic        rsp_error,
    output logic [15:0] rsp_error_code,

    output logic        sp_req_valid,
    input  wire         sp_req_ready,
    output logic        sp_req_write,
    output logic        sp_req_pair,
    output logic [15:0] sp_req_address,
    output logic [63:0] sp_req_write_data,
    input  wire         sp_rsp_valid,
    input  wire [63:0]  sp_rsp_read_data,
    input  wire [127:0] sp_rsp_read_pair,
    input  wire         sp_rsp_error,
    input  wire         sp_external_write_valid,

    // Fixed-priority single-block client for TreeHash parent requests.  It
    // shares physical lane 1; sequencer ordering guarantees that no composer
    // command and TreeHash parent request are issued concurrently.
    input  wire          ext_hash_req_valid,
    output wire          ext_hash_req_ready,
    input  wire [1087:0] ext_hash_message,
    input  wire [7:0]    ext_hash_message_bytes,
    output logic         ext_hash_rsp_valid,
    output logic [255:0] ext_hash_rsp_digest,
    output logic         ext_hash_rsp_error,

    output wire         busy,
    output logic [255:0] last_digest,
    output logic [31:0] scratch_reads,
    output logic [31:0] scratch_writes,
    output logic [31:0] absorbed_blocks,
    output logic [31:0] retired_components,
    output logic [31:0] dual_hash_pairs,
    output logic [31:0] dual_service_cycles,
    output logic [31:0] lane0_active_cycles,
    output logic [31:0] lane1_active_cycles
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
        S_COMPONENT_WAIT, S_COMPONENT_PRODUCTS,
        S_COMPONENT_VALIDATE, S_SOURCE_A_REQ,
        S_SOURCE_A_WAIT, S_SOURCE_B_REQ, S_SOURCE_B_WAIT, S_EMIT_BYTE,
        S_BLOCK_SEND, S_DIGEST_WAIT, S_WRITE_REQ, S_PREFETCH_WAIT
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
    wire desc_repeat_prefix = desc_flags[8];
    wire desc_prefix_preserve_counter = desc_flags[9];
    wire [2:0] desc_prefix_domain = desc_flags[12:10];
    wire desc_pair_patch_counter = desc_flags[13];
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
    logic [15:0] component_pc;
    logic [7:0] components_remaining;
    logic [191:0] active_component;
    logic [191:0] prefetched_component;
    logic prefetch_pending;
    logic prefetch_products_pending;
    logic prefetch_ready;
    logic prefetch_error;
    logic [15:0] prefetch_error_code;
    logic [31:0] prefetch_a_value0, prefetch_a_value1;
    logic [31:0] prefetch_b_value0, prefetch_b_value1;
    wire prefetch_launch;
    wire [15:0] prefetch_launch_index;
    wire component_lookup_valid;
    wire [15:0] component_lookup_index;

    wire [7:0] comp_kind = active_component[183:176];
    wire [7:0] comp_byte_count = active_component[175:168];
    wire [7:0] comp_address_flags = active_component[167:160];
    wire [15:0] comp_a_base_slot = active_component[159:144];
    wire [15:0] comp_a_scale0 = active_component[139:124];
    wire [15:0] comp_a_scale1 = active_component[119:104];
    wire [15:0] comp_b_base_slot = active_component[103:88];
    wire [15:0] comp_b_scale0 = active_component[83:68];
    wire [15:0] comp_b_scale1 = active_component[63:48];
    wire [31:0] comp_immediate = active_component[47:16];
    wire [15:0] comp_reserved = active_component[15:0];

    logic [255:0] saved_registers;
    logic [7:0] saved_destination;
    logic [31:0] saved_index_value;
    logic [15:0] saved_layout_id;
    logic pair_mode;
    logic write_pair_lane;
    logic write_deferred;
    logic repeat_mode;
    logic repeat_replay;
    logic capture_mode;
    logic [7:0] saved_capture_after0, saved_capture_after1;
    logic [15:0] capture_output_base0, capture_output_base1;
    logic [127:0] capture_initial0, capture_initial1;
    logic [2:0] capture_write_phase;
    logic [7:0] repeats_remaining;
    logic [7:0] saved_repeat_counter_offset;
    logic [31:0] repeat_counter_value;
    logic lane0_running, lane1_running;
    logic lane0_result_valid, lane1_result_valid;
    logic [15:0] lane0_output_base, lane1_output_base;
    logic [255:0] lane0_digest_hold, lane1_digest_hold;
    logic [1087:0] lane0_rate_hold, lane1_rate_hold;
    logic ext_hash_active;
    logic [31:0] ext_hash_accepts, ext_hash_responses, ext_hash_errors;
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
    logic [63:0] rate_word_buffer;
    logic [2:0] rate_word_fill;
    logic [4:0] rate_word_index;
    logic [4:0] write_word_index;
    logic [1087:0] digest_buffer;
    logic [7:0] current_kind;
    logic current_is_scratch;
    logic [7:0] component_remaining;
    logic [7:0] component_byte_index;
    logic [31:0] component_immediate;
    logic [127:0] source_a_data, source_b_data;
    logic [4:0] source_window_bytes;
    logic source_pair_pending;
    logic feedback_component_hit;
    logic [3:0] source_byte_index;
    logic [31:0] comp_a_value0, comp_a_value1;
    logic [31:0] comp_b_value0, comp_b_value1;
    logic [47:0] comp_a_product0_reg, comp_a_product1_reg;
    logic [47:0] comp_b_product0_reg, comp_b_product1_reg;
    logic [31:0] dest_base_reg_value;
    logic [31:0] dest_index_reg_value;
    logic [39:0] dest_index_product_reg;

    // The active and look-ahead address stages share the same four small
    // multipliers.  A prefetched component only uses them after the active
    // component has left validation, so no arithmetic unit is duplicated.
    wire [191:0] product_component = prefetch_products_pending
        ? prefetched_component : active_component;
    wire [31:0] product_a_value0 = prefetch_products_pending
        ? prefetch_a_value0 : comp_a_value0;
    wire [31:0] product_a_value1 = prefetch_products_pending
        ? prefetch_a_value1 : comp_a_value1;
    wire [31:0] product_b_value0 = prefetch_products_pending
        ? prefetch_b_value0 : comp_b_value0;
    wire [31:0] product_b_value1 = prefetch_products_pending
        ? prefetch_b_value1 : comp_b_value1;
    (* use_dsp = "no" *) wire [47:0] comp_a_product0
        = product_a_value0 * product_component[139:124];
    (* use_dsp = "no" *) wire [47:0] comp_a_product1
        = product_a_value1 * product_component[119:104];
    (* use_dsp = "no" *) wire [47:0] comp_b_product0
        = product_b_value0 * product_component[83:68];
    (* use_dsp = "no" *) wire [47:0] comp_b_product1
        = product_b_value1 * product_component[63:48];
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
    wire [63:0] capture_slot_calc = {56'b0, desc_dest_reserved}
        + dest_slot_calc - {56'b0, desc_dest_base_slot};
    wire [63:0] capture_word_calc = capture_slot_calc * SLOT_WORDS;

    wire lane0_ready, lane0_block_ready;
    wire lane1_ready;
    wire [255:0] lane0_digest, lane1_digest;
    wire [255:0] lane0_capture_digest, lane1_capture_digest;
    wire lane0_capture_valid, lane1_capture_valid;
    wire [1087:0] lane0_rate_output;
    wire [1087:0] lane1_rate_output = {832'b0, lane1_digest};
    wire lane0_digest_valid, lane1_digest_valid, lane1_done;
    wire lane0_error, lane1_error;
    wire [7:0] lane0_capture_after
        = saved_capture_after0 + (desc_repeat_prefix ? 1'b1 : 1'b0);
    wire [7:0] lane1_capture_after
        = saved_capture_after1 + (desc_repeat_prefix ? 1'b1 : 1'b0);
    wire both_lanes_ready = lane0_ready && (!pair_mode || lane1_ready);
    wire lane0_start = (state == S_HASH_START) && both_lanes_ready
        && (input_mode != INPUT_COMPONENT_PROGRAM || component_lookup_ready);
    wire ext_hash_accept = ext_hash_req_valid && ext_hash_req_ready;
    wire lane0_block_valid = state == S_BLOCK_SEND;
    wire lane1_pair_start = state == S_BLOCK_SEND && pair_mode
        && block_is_last && lane0_block_ready && lane1_ready;
    wire lane1_start = lane1_pair_start || ext_hash_accept;
    logic [1087:0] lane1_pair_message;
    wire [1087:0] lane1_block_data = ext_hash_accept
        ? ext_hash_message : lane1_pair_message;
    wire [7:0] lane1_block_bytes = ext_hash_accept
        ? ext_hash_message_bytes : block_bytes_target;
    assign lane1_digest_valid = lane1_done;
    wire shake_block_ready = lane0_block_ready && (!pair_mode || lane1_ready);
    wire shake_error = lane0_error || (pair_mode && lane1_error);
    wire lane0_result_now = lane0_result_valid || lane0_digest_valid;
    wire lane1_result_now = lane1_result_valid || lane1_digest_valid;
    wire [1087:0] lane0_result_rate = lane0_digest_valid
        ? lane0_rate_output : lane0_rate_hold;
    wire [127:0] append_data;
    wire [4:0] append_bytes;
    // Decode the source class once in COMPONENT_VALIDATE.  In particular,
    // do not put current_kind -> append barrel/mask -> prefetch RAM enable on
    // one cycle.  append_bytes is min(remaining, 16, source room, rate room),
    // so this comparison is exactly equivalent to
    //   component_remaining == append_bytes
    // for every legal component while keeping the look-ahead request path
    // independent of the 128-bit data selector.
    wire emit_component_done
        = component_remaining <= 8'd16
        && ({1'b0, block_fill} + component_remaining <= 9'd136)
        && (!current_is_scratch
            || {1'b0, source_byte_index} + component_remaining
               <= {1'b0, source_window_bytes});
    wire emit_source_window_done = current_is_scratch
        && ({1'b0, source_byte_index} + append_bytes
            == {1'b0, source_window_bytes});
    wire emit_rate_done
        = ({1'b0, block_fill} + append_bytes == 9'd136);
    // The Scratchpad request enable must not depend on the 128-bit append
    // barrel/mask result.  For Scratchpad components the append consumes the
    // whole remaining 8/16-byte source window exactly when both the component
    // and current SHAKE rate have room for it.  This early equivalent form
    // cuts the append -> arbiter -> BRAM-enable critical path.
    wire [4:0] source_window_remaining = source_window_bytes
        - {1'b0, source_byte_index};
    wire stream_next_source_early = state == S_EMIT_BYTE
        && current_is_scratch
        && component_remaining > source_window_remaining
        && ({1'b0, block_fill} + source_window_remaining < 9'd136);
    wire [1:0] source_window_words = source_window_bytes[4:3];
    wire [15:0] next_source_word_address
        = source_word_address + source_window_words;
    wire next_source_pair = current_kind != COMP_SCRATCH_XOR
        && component_remaining - source_window_remaining > 8
        && !next_source_word_address[0];
    wire source_pair_request = current_kind != COMP_SCRATCH_XOR
        && component_remaining > 8 && !source_word_address[0];
    wire [15:0] selected_source_word_calc
        = (comp_kind == COMP_SELECT_SCRATCH && select_nonzero)
        ? comp_b_word_calc[15:0] : comp_a_word_calc[15:0];
    wire feedback_lookup_hit;
    wire [127:0] feedback_lookup_data;
    logic pair_feedback_valid;
    logic [15:0] pair_feedback_base0, pair_feedback_base1;
    logic [127:0] pair_feedback_data0, pair_feedback_data1;
    wire [1:0] feedback_lookup_words = comp_span_words > 2
        ? 2'd3 : comp_span_words[1:0];
    wire feedback_component_eligible
        = !pair_mode
        && (comp_kind == COMP_SCRATCH || comp_kind == COMP_SELECT_SCRATCH)
        && comp_span_words <= 2;
    wire pair_feedback_component_eligible = pair_mode
        && (comp_kind == COMP_SCRATCH || comp_kind == COMP_SELECT_SCRATCH)
        && comp_span_words <= 2;
    wire pair_feedback_hit = pair_feedback_valid
        && pair_feedback_component_eligible
        && selected_source_word_calc == pair_feedback_base0;
    wire [127:0] selected_feedback_data = pair_feedback_hit
        ? pair_feedback_data0
        : feedback_lookup_data;
    wire [1:0] feedback_word_used = state == S_COMPONENT_VALIDATE
        && ((feedback_component_eligible && feedback_lookup_hit)
            || pair_feedback_hit)
        ? feedback_lookup_words : 2'd0;
    wire feedback_fill_valid = !pair_mode && state == S_DIGEST_WAIT
        && lane0_digest_valid;
    wire [1:0] feedback_fill_words = output_words > 2
        ? 2'd2 : output_words[1:0];
    wire prefetch_first_launch = state == S_COMPONENT_WAIT
        && component_lookup_rsp_valid && !component_lookup_rsp_error
        && components_remaining > 1 && !prefetch_pending
        && !prefetch_products_pending && !prefetch_ready;
    wire prefetch_chain_launch = state == S_EMIT_BYTE
        && emit_component_done && components_remaining > 2
        && (prefetch_ready || prefetch_products_pending)
        && !prefetch_pending;
    wire prefetch_fallback_launch = state == S_COMPONENT_VALIDATE
        && components_remaining > 1 && !prefetch_pending
        && !prefetch_products_pending && !prefetch_ready;
    assign prefetch_launch = prefetch_first_launch
        || prefetch_chain_launch || prefetch_fallback_launch;
    assign prefetch_launch_index = prefetch_chain_launch
        ? component_pc + 2'd2 : component_pc + 1'b1;
    assign component_lookup_valid = (state == S_COMPONENT_REQ)
        || (state == S_HASH_START
            && input_mode == INPUT_COMPONENT_PROGRAM && both_lanes_ready)
        || prefetch_launch;
    assign component_lookup_index = prefetch_launch
        ? prefetch_launch_index : component_pc;
    wire [4:0] rate_word_sum
        = {2'b0, rate_word_fill} + append_bytes;
    wire [1:0] append_complete_words = rate_word_sum[4:3];
    wire [5:0] rate_word_shift = {rate_word_fill, 3'b000};
    wire [191:0] append_combined
        = {128'b0, rate_word_buffer}
        | ({64'b0, append_data} << rate_word_shift);
    logic [63:0] append_remainder;
    integer output_byte_index;
    integer feedback_byte_index;
    integer repeat_byte_index;
    logic [63:0] masked_output_word;
    logic [127:0] feedback_fill_data;

    function automatic [255:0] pair_register_image(
        input [255:0] image,
        input [2:0] pair_index_reg,
        input [31:0] pair_index,
        input lane_one
    );
        reg [255:0] result;
        begin
            result = image;
            result[32*pair_index_reg +: 32]
                = {pair_index[30:0], 1'b0} + lane_one;
            pair_register_image = result;
        end
    endfunction
    function automatic [31:0] pack_be32(input [31:0] value);
        pack_be32 = {value[7:0], value[15:8], value[23:16], value[31:24]};
    endfunction
    // Static P2 applies only to the two WOTS 64-byte layouts.  Their paired
    // message differs from lane 0 in the big-endian chain-address word and,
    // for F, the final 16-byte feedback value.  Patch those bounded fields
    // combinationally so both Keccak lanes start on the same cycle.
    always_comb begin
        lane1_pair_message = block_buffer;
        if (desc_pair_patch_counter)
            lane1_pair_message[8*44 +: 32]
                = pack_be32(saved_registers[32*7 +: 32] + 1'b1);
        else
            lane1_pair_message[8*40 +: 32]
                = pack_be32({saved_index_value[30:0], 1'b0} + 1'b1);
        if (saved_layout_id == 16'd14 || saved_layout_id == 16'd21)
            lane1_pair_message[8*(message_bytes-output_bytes) +: 128]
                = pair_feedback_data1;
    end

    assign req_ready = (state == S_IDLE) && layout_lookup_ready
        && !ext_hash_active && !ext_hash_req_valid;
    assign busy = (state != S_IDLE);
    assign ext_hash_req_ready = state == S_IDLE && !ext_hash_active
        && !req_valid && lane1_ready && ext_hash_message_bytes <= 135;

    micro_hbs_rate_append128 rate_append (
        .component_kind(current_kind),
        .component_remaining,
        .component_immediate,
        .source_a_data,
        .source_b_data,
        .source_window_bytes,
        .source_byte_index,
        .rate_fill(block_fill),
        .append_data,
        .append_bytes
    );

    // A 16-byte append can complete at most two 64-bit words.  Commit those
    // two fixed-width slices and retain only the final partial word locally.
    always_comb begin
        case (append_complete_words)
            2'd0: append_remainder = append_combined[63:0];
            2'd1: append_remainder = append_combined[127:64];
            default: append_remainder = append_combined[191:128];
        endcase
    end

    always_comb begin
        feedback_fill_data = lane0_rate_output[127:0];
        for (feedback_byte_index = 0; feedback_byte_index < 16;
             feedback_byte_index = feedback_byte_index + 1)
            if (feedback_byte_index >= output_bytes)
                feedback_fill_data[8*feedback_byte_index +: 8] = 8'b0;
    end

    always_comb begin
        sp_req_valid = 1'b0;
        sp_req_write = 1'b0;
        sp_req_pair = 1'b0;
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
            sp_req_pair = state == S_SOURCE_A_REQ && source_pair_request;
        end else if (stream_next_source_early
                     && !feedback_component_hit) begin
            // Consume the current 64-bit source word and issue the next read
            // in the same cycle.  Bounds were checked for the full component
            // before its first read, so this preserves fail-closed behavior.
            sp_req_valid = 1'b1;
            sp_req_address = next_source_word_address;
            sp_req_pair = next_source_pair;
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

    micro_hbs_hash_feedback_cache feedback_cache (
        .clk, .rst_n, .clear(!engine_busy),
        .fill_valid(feedback_fill_valid),
        .fill_base_address(output_base_word),
        .fill_words(feedback_fill_words),
        .fill_data(feedback_fill_data),
        .invalidate_valid(sp_external_write_valid),
        .lookup_base_address(selected_source_word_calc),
        .lookup_words(feedback_lookup_words),
        .lookup_hit(feedback_lookup_hit),
        .lookup_data(feedback_lookup_data)
    );

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
        .lookup_ready(component_lookup_ready),
        .lookup_index(component_lookup_index),
        .lookup_rsp_valid(component_lookup_rsp_valid),
        .lookup_rsp_error(component_lookup_rsp_error),
        .lookup_rsp_error_code(component_lookup_rsp_error_code),
        .lookup_component, .configured_count(), .accepted_loads(),
        .rejected_loads(), .host_writes_busy(), .lookup_requests(),
        .lookup_errors()
    );

    micro_hbs_shake256_stream #(.UNROLL(UNROLL)) shake_lane (
        .clk, .rst_n, .hash_start(lane0_start),
        .hash_ready(lane0_ready),
        .block_valid(lane0_block_valid),
        .block_ready(lane0_block_ready),
        .block_data(block_buffer), .block_bytes(block_bytes_target),
        .block_last(block_is_last),
        .repeat_enable(repeat_mode), .repeat_prefix(desc_repeat_prefix),
        .repeat_prefix_preserve_counter(desc_prefix_preserve_counter),
        .repeat_prefix_domain(desc_prefix_domain),
        .repeat_count(repeats_remaining),
        .repeat_counter_offset(saved_repeat_counter_offset),
        .repeat_feedback_offset(message_bytes - output_bytes),
        .repeat_feedback_bytes(output_bytes[5:0]),
        .repeat_counter_start(repeat_counter_value),
        .capture_enable(capture_mode),
        .capture_after(lane0_capture_after),
        .capture_digest(lane0_capture_digest),
        .capture_valid(lane0_capture_valid),
        .digest(lane0_digest), .rate_output(lane0_rate_output),
        .digest_valid(lane0_digest_valid), .error(lane0_error)
    );

    micro_hbs_shake256_single_block #(.UNROLL(UNROLL)) shake_lane1 (
        .clk, .rst_n, .start(lane1_start), .ready(lane1_ready),
        .message(lane1_block_data), .message_length(lane1_block_bytes),
        .repeat_enable(repeat_mode && !ext_hash_accept),
        .repeat_prefix(desc_repeat_prefix && !ext_hash_accept),
        .repeat_prefix_preserve_counter(desc_prefix_preserve_counter),
        .repeat_prefix_domain(desc_prefix_domain),
        .repeat_count(repeats_remaining),
        .repeat_counter_offset(saved_repeat_counter_offset),
        .repeat_feedback_offset(message_bytes - output_bytes),
        .repeat_feedback_bytes(output_bytes[5:0]),
        .repeat_counter_start(repeat_counter_value),
        .capture_enable(capture_mode && !ext_hash_accept),
        .capture_after(lane1_capture_after),
        .capture_digest(lane1_capture_digest),
        .capture_valid(lane1_capture_valid),
        .digest(lane1_digest), .done(lane1_done), .error(lane1_error)
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
            saved_layout_id <= '0;
            pair_mode <= 1'b0;
            write_pair_lane <= 1'b0;
            write_deferred <= 1'b0;
            repeat_mode <= 1'b0;
            repeat_replay <= 1'b0;
            capture_mode <= 1'b0;
            saved_capture_after0 <= '0;
            saved_capture_after1 <= '0;
            capture_output_base0 <= '0;
            capture_output_base1 <= '0;
            capture_initial0 <= '0;
            capture_initial1 <= '0;
            capture_write_phase <= '0;
            repeats_remaining <= '0;
            saved_repeat_counter_offset <= '0;
            repeat_counter_value <= '0;
            lane0_running <= 1'b0;
            lane1_running <= 1'b0;
            lane0_result_valid <= 1'b0;
            lane1_result_valid <= 1'b0;
            lane0_output_base <= '0;
            lane1_output_base <= '0;
            lane0_digest_hold <= '0;
            lane1_digest_hold <= '0;
            lane0_rate_hold <= '0;
            lane1_rate_hold <= '0;
            pair_feedback_valid <= 1'b0;
            pair_feedback_base0 <= '0;
            pair_feedback_base1 <= '0;
            pair_feedback_data0 <= '0;
            pair_feedback_data1 <= '0;
            ext_hash_active <= 1'b0;
            ext_hash_rsp_valid <= 1'b0;
            ext_hash_rsp_digest <= '0;
            ext_hash_rsp_error <= 1'b0;
            ext_hash_accepts <= '0;
            ext_hash_responses <= '0;
            ext_hash_errors <= '0;
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
            rate_word_buffer <= '0;
            rate_word_fill <= '0;
            rate_word_index <= '0;
            write_word_index <= '0;
            component_pc <= '0;
            active_component <= '0;
            prefetched_component <= '0;
            prefetch_pending <= 1'b0;
            prefetch_products_pending <= 1'b0;
            prefetch_ready <= 1'b0;
            prefetch_error <= 1'b0;
            prefetch_error_code <= '0;
            prefetch_a_value0 <= '0;
            prefetch_a_value1 <= '0;
            prefetch_b_value0 <= '0;
            prefetch_b_value1 <= '0;
            components_remaining <= '0;
            current_kind <= '0;
            current_is_scratch <= 1'b0;
            component_remaining <= '0;
            component_byte_index <= '0;
            component_immediate <= '0;
            source_a_data <= '0;
            source_b_data <= '0;
            source_window_bytes <= '0;
            source_pair_pending <= 1'b0;
            feedback_component_hit <= 1'b0;
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
            dual_hash_pairs <= '0;
            dual_service_cycles <= '0;
            lane0_active_cycles <= '0;
            lane1_active_cycles <= '0;
        end else begin
            rsp_valid <= 1'b0;
            rsp_error <= 1'b0;
            rsp_error_code <= '0;
            ext_hash_rsp_valid <= 1'b0;
            ext_hash_rsp_error <= 1'b0;

            if (ext_hash_accept) begin
                ext_hash_accepts <= ext_hash_accepts + 1'b1;
                ext_hash_active <= 1'b1;
                pair_mode <= 1'b0;
            end
            if (ext_hash_active && lane1_error) begin
                ext_hash_errors <= ext_hash_errors + 1'b1;
                ext_hash_active <= 1'b0;
                ext_hash_rsp_valid <= 1'b1;
                ext_hash_rsp_digest <= '0;
                ext_hash_rsp_error <= 1'b1;
            end else if (ext_hash_active && lane1_digest_valid) begin
                ext_hash_responses <= ext_hash_responses + 1'b1;
                ext_hash_active <= 1'b0;
                ext_hash_rsp_valid <= 1'b1;
                ext_hash_rsp_digest <= lane1_digest;
                ext_hash_rsp_error <= 1'b0;
            end

            if (pair_mode && (lane0_running || lane1_running))
                dual_service_cycles <= dual_service_cycles + 1'b1;
            if (lane0_running)
                lane0_active_cycles <= lane0_active_cycles + 1'b1;
            if (lane1_running)
                lane1_active_cycles <= lane1_active_cycles + 1'b1;
            if (lane0_digest_valid) begin
                lane0_digest_hold <= lane0_digest;
                lane0_rate_hold <= lane0_rate_output;
                lane0_result_valid <= 1'b1;
                lane0_running <= 1'b0;
            end
            if (pair_mode && lane1_digest_valid) begin
                lane1_digest_hold <= lane1_digest;
                lane1_rate_hold <= lane1_rate_output;
                lane1_result_valid <= 1'b1;
                lane1_running <= 1'b0;
            end
            if (lane1_pair_start) begin
                lane0_running <= 1'b1;
                lane1_running <= 1'b1;
            end
            if (sp_external_write_valid)
                pair_feedback_valid <= 1'b0;

            // Capture and address-evaluate one component ahead while the
            // current component performs Scratchpad access or rate emission.
            if (prefetch_launch && component_lookup_ready) begin
                prefetch_pending <= 1'b1;
                prefetch_error <= 1'b0;
                prefetch_error_code <= '0;
            end
            if (prefetch_pending && component_lookup_rsp_valid) begin
                prefetched_component <= lookup_component;
                prefetch_a_value0 <= saved_registers[
                    32*lookup_component[142:140] +: 32];
                prefetch_a_value1 <= saved_registers[
                    32*lookup_component[122:120] +: 32];
                prefetch_b_value0 <= saved_registers[
                    32*lookup_component[86:84] +: 32];
                prefetch_b_value1 <= saved_registers[
                    32*lookup_component[66:64] +: 32];
                prefetch_error <= component_lookup_rsp_error;
                prefetch_error_code <= component_lookup_rsp_error_code;
                prefetch_pending <= 1'b0;
                prefetch_products_pending <= 1'b1;
            end
            if (prefetch_products_pending) begin
                comp_a_product0_reg <= comp_a_product0;
                comp_a_product1_reg <= comp_a_product1;
                comp_b_product0_reg <= comp_b_product0;
                comp_b_product1_reg <= comp_b_product1;
                prefetch_products_pending <= 1'b0;
                prefetch_ready <= 1'b1;
            end

            case (state)
                S_IDLE: if (req_valid && req_ready) begin
                    saved_destination <= destination;
                    saved_index_value <= index_value;
                    saved_layout_id <= layout_id;
                    pair_mode <= lane_mask == 2'b11;
                    write_pair_lane <= 1'b0;
                    write_deferred <= defer_write;
                    repeat_mode <= repeat_hash;
                    repeat_replay <= 1'b0;
                    capture_mode <= capture_hash;
                    saved_capture_after0 <= capture_after0;
                    saved_capture_after1 <= capture_after1;
                    capture_write_phase <= '0;
                    repeats_remaining <= repeat_count;
                    saved_repeat_counter_offset <= repeat_counter_offset;
                    repeat_counter_value <= repeat_start;
                    lane0_result_valid <= 1'b0;
                    lane1_result_valid <= 1'b0;
                    lane0_running <= 1'b0;
                    lane1_running <= 1'b0;
                    saved_registers <= lane_mask == 2'b11
                        ? pair_register_image(register_snapshot,
                            index_reg[2:0], index_value, 1'b0)
                        : register_snapshot;
                    if ((lane_mask != 2'b01 && lane_mask != 2'b11)
                        || (lane_mask == 2'b11 && index_reg >= 8))
                        fail(ERR_BAD_LANE_MASK);
                    else if (defer_write && lane_mask != 2'b11)
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
                        dest_index_product_reg <= saved_registers[
                            32*lookup_descriptor[19:17] +: 32]
                            * lookup_descriptor[15:8];
                        state <= S_LAYOUT_VALIDATE;
                    end
                end

                // Isolate variable register selection and the small affine
                // multiplier from destination bounds/descriptor validation.
                // This costs two fixed cycles per HASH request but
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
                    else if (desc_flags[15:14] != 0
                             || (!desc_repeat_prefix
                                 && desc_flags[12:9] != 0)
                             || desc_flags[7:0] == 0
                             || desc_flags[7:0] > 136
                             || desc_message_bytes > MAX_MESSAGE_BYTES)
                        fail(ERR_BAD_DESCRIPTOR);
                    else if (desc_input_mode == INPUT_CONTIGUOUS_SCRATCH) begin
                        if (pair_mode || desc_repeat_prefix
                            || desc_component_pc != 0
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
                            || (pair_mode && desc_message_bytes > 135)
                            || (pair_mode
                                && (saved_layout_id != 16'd13
                                    && saved_layout_id != 16'd14
                                    && saved_layout_id != 16'd21
                                    && saved_layout_id != 16'd22
                                    && saved_layout_id != 16'd23
                                    || desc_message_bytes != 16'd64
                                    || desc_flags[7:0] != 8'd16))
                            || desc_component_count == 0
                            || desc_source_count != desc_component_count
                            || (!capture_mode && desc_dest_reserved != 0
                                && !desc_repeat_prefix)
                            || (desc_dest_use_index_reg
                                && desc_dest_stride == 0)
                            || dest_word_calc > 16'hffff
                            || dest_word_calc + desc_output_words > SCRATCH_WORDS
                            || (repeat_mode
                                && (repeats_remaining == 0
                                    || desc_message_bytes != 16'd64
                                    || desc_flags[7:0] != 8'd16
                                    || saved_repeat_counter_offset != 8'd44
                                    || (pair_mode
                                        && saved_layout_id != 16'd14
                                        && saved_layout_id != 16'd21
                                        && saved_layout_id != 16'd22
                                        && saved_layout_id != 16'd23)
                                    || (desc_repeat_prefix
                                        && saved_layout_id != 16'd22
                                        && saved_layout_id != 16'd23)))
                            || (desc_repeat_prefix && !repeat_mode)
                            || (capture_mode
                                && (!repeat_mode
                                    || write_deferred
                                    || desc_message_bytes != 16'd64
                                    || desc_flags[7:0] != 8'd16
                                    || desc_dest_reserved == 0
                                    || saved_capture_after0
                                       > repeats_remaining
                                    || (pair_mode && saved_capture_after1
                                        > repeats_remaining)
                                    || capture_word_calc + desc_output_words
                                       > SCRATCH_WORDS
                                    || (pair_mode
                                        && capture_word_calc
                                           + desc_dest_stride * SLOT_WORDS
                                           + desc_output_words
                                           > SCRATCH_WORDS))))
                            fail(ERR_BAD_DESCRIPTOR);
                        else begin
                            input_mode <= INPUT_COMPONENT_PROGRAM;
                            message_bytes <= desc_message_bytes;
                            total_emitted <= '0;
                            output_bytes <= desc_flags[7:0];
                            output_words <= desc_output_words[4:0];
                            output_base_word <= dest_word_calc[15:0];
                            lane0_output_base <= dest_word_calc[15:0];
                            capture_output_base0
                                <= capture_word_calc[15:0];
                            capture_output_base1
                                <= capture_word_calc[15:0]
                                    + desc_dest_stride * SLOT_WORDS;
                            if (pair_mode) begin
                                lane0_output_base <= dest_word_calc[15:0];
                                lane1_output_base <= dest_word_calc[15:0]
                                    + (desc_dest_stride * SLOT_WORDS);
                            end
                            component_pc <= desc_component_pc;
                            components_remaining <= desc_component_count;
                            block_buffer <= '0;
                            block_fill <= '0;
                            rate_word_buffer <= '0;
                            rate_word_fill <= '0;
                            rate_word_index <= '0;
                            prefetch_pending <= 1'b0;
                            prefetch_products_pending <= 1'b0;
                            prefetch_ready <= 1'b0;
                            state <= S_HASH_START;
                        end
                    end else
                        fail(ERR_BAD_MODE);
                end

                S_HASH_START: if (both_lanes_ready) begin
                    if (input_mode == INPUT_CONTIGUOUS_SCRATCH) begin
                        if (!pair_mode)
                            lane0_running <= 1'b1;
                        lane1_running <= 1'b0;
                        state <= S_CONTIG_BLOCK_PREP;
                    end else if (component_lookup_ready) begin
                        if (!pair_mode)
                            lane0_running <= 1'b1;
                        lane1_running <= 1'b0;
                        state <= S_COMPONENT_WAIT;
                    end
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
                        // The component RAM response is already registered.
                        // Capture its variable register operands here instead
                        // of spending a separate state on the same register
                        // mux. Multiplication and validation remain isolated
                        // in the following two pipeline stages.
                        comp_a_value0 <= saved_registers[
                            32*lookup_component[142:140] +: 32];
                        comp_a_value1 <= saved_registers[
                            32*lookup_component[122:120] +: 32];
                        comp_b_value0 <= saved_registers[
                            32*lookup_component[86:84] +: 32];
                        comp_b_value1 <= saved_registers[
                            32*lookup_component[66:64] +: 32];
                        state <= S_COMPONENT_PRODUCTS;
                    end
                end

                S_COMPONENT_PRODUCTS: begin
                    comp_a_product0_reg <= comp_a_product0;
                    comp_a_product1_reg <= comp_a_product1;
                    comp_b_product0_reg <= comp_b_product0;
                    comp_b_product1_reg <= comp_b_product1;
                    state <= S_COMPONENT_VALIDATE;
                end

                S_PREFETCH_WAIT: begin
                    if (prefetch_ready || prefetch_products_pending) begin
                        if (prefetch_error)
                            fail(prefetch_error_code);
                        else begin
                            prefetch_ready <= 1'b0;
                            prefetch_products_pending <= 1'b0;
                            active_component <= prefetched_component;
                            state <= S_COMPONENT_VALIDATE;
                        end
                    end
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
                        current_is_scratch <= comp_kind == COMP_SCRATCH
                            || comp_kind == COMP_SELECT_SCRATCH
                            || comp_kind == COMP_SCRATCH_XOR;
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
                        feedback_component_hit
                            <= (feedback_component_eligible
                                && feedback_lookup_hit) || pair_feedback_hit;
                        if ((feedback_component_eligible
                             && feedback_lookup_hit) || pair_feedback_hit) begin
                            source_a_data <= selected_feedback_data;
                            source_window_bytes
                                <= {feedback_lookup_words, 3'b000};
                            source_pair_pending <= 1'b0;
                            state <= S_EMIT_BYTE;
                        end else if (comp_kind == COMP_SCRATCH
                            || comp_kind == COMP_SELECT_SCRATCH
                            || comp_kind == COMP_SCRATCH_XOR)
                            state <= S_SOURCE_A_REQ;
                        else begin
                            feedback_component_hit <= 1'b0;
                            state <= S_EMIT_BYTE;
                        end
                    end
                end

                S_SOURCE_A_REQ: begin
                    if (sp_rsp_error)
                        fail(ERR_SCRATCH_BOUNDS);
                    else if (sp_req_ready) begin
                        source_pair_pending <= source_pair_request;
                        state <= S_SOURCE_A_WAIT;
                    end
                end

                S_SOURCE_A_WAIT: begin
                    if (sp_rsp_error)
                        fail(ERR_SCRATCH_BOUNDS);
                    else if (sp_rsp_valid) begin
                        source_a_data <= source_pair_pending
                            ? sp_rsp_read_pair : {64'b0, sp_rsp_read_data};
                        source_window_bytes <= source_pair_pending
                            ? 5'd16 : 5'd8;
                        scratch_reads <= scratch_reads
                            + (source_pair_pending ? 2'd2 : 1'b1);
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
                        source_b_data <= {64'b0, sp_rsp_read_data};
                        source_window_bytes <= 5'd8;
                        scratch_reads <= scratch_reads + 1'b1;
                        state <= S_EMIT_BYTE;
                    end
                end

                S_EMIT_BYTE: begin
                    if (append_complete_words != 0) begin
                        block_buffer[64*rate_word_index +: 64]
                            <= append_combined[63:0];
                        if (append_complete_words == 2)
                            block_buffer[64*(rate_word_index + 1'b1) +: 64]
                                <= append_combined[127:64];
                        rate_word_buffer <= append_remainder;
                        rate_word_fill <= rate_word_sum[2:0];
                        rate_word_index
                            <= rate_word_index + append_complete_words;
                    end else begin
                        rate_word_buffer <= append_remainder;
                        rate_word_fill <= rate_word_sum[2:0];
                        // The final partial word is zero-padded because the
                        // rate buffer and unused high bytes start at zero.
                        if (emit_component_done
                            && components_remaining == 1)
                            block_buffer[64*rate_word_index +: 64]
                                <= append_remainder;
                    end
                    component_remaining
                        <= component_remaining - append_bytes;
                    component_byte_index
                        <= component_byte_index + append_bytes;
                    total_emitted <= total_emitted + append_bytes;
                    block_fill <= block_fill + append_bytes;

                    if (emit_component_done) begin
                        retired_components <= retired_components
                            + (pair_mode ? 2'd2 : 1'b1);
                        component_pc <= component_pc + 1'b1;
                        components_remaining <= components_remaining - 1'b1;
                    end

                    if (emit_source_window_done) begin
                        source_byte_index <= '0;
                        if (!emit_component_done) begin
                            source_word_address <= next_source_word_address;
                            source_b_word_address
                                <= source_b_word_address + source_window_words;
                        end
                    end else if (current_is_scratch)
                        source_byte_index
                            <= source_byte_index + append_bytes;

                    if (emit_rate_done) begin
                        block_bytes_target <= 8'd136;
                        block_is_last
                            <= (total_emitted + append_bytes == message_bytes);
                        if (emit_component_done
                            && components_remaining == 1
                            && total_emitted + append_bytes != message_bytes)
                            fail(ERR_MESSAGE_LENGTH);
                        else if (emit_component_done
                                 && (prefetch_ready
                                     || prefetch_products_pending)
                                 && prefetch_error)
                            fail(prefetch_error_code);
                        else begin
                            if (emit_component_done) begin
                                if (prefetch_ready
                                    || prefetch_products_pending) begin
                                    active_component
                                        <= prefetched_component;
                                    prefetch_ready <= 1'b0;
                                    prefetch_products_pending <= 1'b0;
                                    resume_state <= S_COMPONENT_VALIDATE;
                                end else
                                    resume_state <= S_PREFETCH_WAIT;
                            end else if (emit_source_window_done)
                                resume_state <= S_SOURCE_A_REQ;
                            else
                                resume_state <= S_EMIT_BYTE;
                            state <= S_BLOCK_SEND;
                        end
                    end else if (emit_component_done) begin
                        if (components_remaining == 1) begin
                            if (total_emitted + append_bytes != message_bytes)
                                fail(ERR_MESSAGE_LENGTH);
                            else begin
                                block_bytes_target
                                    <= block_fill + append_bytes;
                                block_is_last <= 1'b1;
                                state <= S_BLOCK_SEND;
                            end
                        end else if (prefetch_ready
                                     || prefetch_products_pending) begin
                            if (prefetch_error)
                                fail(prefetch_error_code);
                            else begin
                                prefetch_ready <= 1'b0;
                                prefetch_products_pending <= 1'b0;
                                active_component <= prefetched_component;
                                state <= S_COMPONENT_VALIDATE;
                            end
                        end else
                            state <= S_PREFETCH_WAIT;
                    end else if (emit_source_window_done) begin
                        if (stream_next_source_early && sp_req_ready) begin
                            source_pair_pending <= next_source_pair;
                            state <= S_SOURCE_A_WAIT;
                        end else
                            state <= S_SOURCE_A_REQ;
                    end
                end

                S_BLOCK_SEND: begin
                    if (shake_error)
                        fail(ERR_HASH);
                    else if (shake_block_ready) begin
                        if (capture_mode && block_is_last) begin
                            capture_initial0 <= block_buffer[511:384];
                            capture_initial1 <= lane1_pair_message[511:384];
                        end
                        absorbed_blocks <= absorbed_blocks
                            + (repeat_mode
                               ? (pair_mode
                                  ? {23'b0, repeats_remaining, 1'b0}
                                  : {24'b0, repeats_remaining})
                               : (pair_mode ? 32'd2 : 32'd1));
                        if (block_is_last)
                            state <= S_DIGEST_WAIT;
                        else if (input_mode == INPUT_CONTIGUOUS_SCRATCH) begin
                            remaining_bytes <= remaining_bytes - 16'd136;
                            state <= S_CONTIG_BLOCK_PREP;
                        end else begin
                            block_buffer <= '0;
                            block_fill <= '0;
                            rate_word_buffer <= '0;
                            rate_word_fill <= '0;
                            rate_word_index <= '0;
                            state <= resume_state;
                        end
                    end
                end

                S_DIGEST_WAIT: begin
                    if (shake_error)
                        fail(ERR_HASH);
                    else if (!pair_mode && lane0_digest_valid) begin
                        last_digest <= lane0_digest;
                        digest_buffer <= capture_mode
                            ? {832'b0, (saved_capture_after0 == 0
                                && !desc_repeat_prefix
                                ? {128'b0, capture_initial0}
                                : lane0_capture_digest)}
                            : lane0_rate_output;
                        if (capture_mode) begin
                            output_base_word <= capture_output_base0;
                            capture_write_phase <= 3'd1;
                        end
                        write_word_index <= '0;
                        state <= S_WRITE_REQ;
                    end else if (pair_mode && lane0_result_now
                                 && lane1_result_now) begin
                        pair_feedback_valid <= 1'b1;
                        pair_feedback_base0 <= lane0_output_base;
                        pair_feedback_base1 <= lane1_output_base;
                        pair_feedback_data0 <= lane0_digest_valid
                            ? lane0_rate_output[127:0]
                            : lane0_rate_hold[127:0];
                        pair_feedback_data1 <= lane1_digest_valid
                            ? lane1_rate_output[127:0]
                            : lane1_rate_hold[127:0];
                        last_digest <= lane1_digest_valid
                            ? lane1_digest : lane1_digest_hold;
                        if (capture_mode) begin
                            digest_buffer <= {832'b0,
                                (saved_capture_after0 == 0
                                 && !desc_repeat_prefix
                                 ? {128'b0, capture_initial0}
                                 : lane0_capture_digest)};
                            output_base_word <= capture_output_base0;
                            capture_write_phase <= 3'd1;
                            write_word_index <= '0;
                            state <= S_WRITE_REQ;
                        end else if (write_deferred) begin
                            dual_hash_pairs <= dual_hash_pairs
                                + (repeat_mode
                                   ? {24'b0, repeats_remaining} : 32'd1);
                            rsp_valid <= 1'b1;
                            state <= S_IDLE;
                        end else begin
                            digest_buffer <= lane0_digest_valid
                                ? lane0_rate_output : lane0_rate_hold;
                            output_base_word <= lane0_output_base;
                            write_pair_lane <= 1'b0;
                            write_word_index <= '0;
                            state <= S_WRITE_REQ;
                        end
                    end
                end

                S_WRITE_REQ: begin
                    if (sp_rsp_error)
                        fail(ERR_SCRATCH_BOUNDS);
                    else if (sp_req_ready) begin
                        scratch_writes <= scratch_writes + 1'b1;
                        if (write_word_index + 1'b1 == output_words) begin
                            if (capture_write_phase == 3'd1) begin
                                if (pair_mode) begin
                                    digest_buffer <= {
                                        832'b0,
                                        (saved_capture_after1 == 0
                                         && !desc_repeat_prefix
                                         ? {128'b0, capture_initial1}
                                         : lane1_capture_digest)};
                                    output_base_word <= capture_output_base1;
                                    capture_write_phase <= 3'd2;
                                end else begin
                                    digest_buffer <= lane0_rate_hold;
                                    output_base_word <= lane0_output_base;
                                    capture_write_phase <= 3'd3;
                                end
                                write_word_index <= '0;
                            end else if (capture_write_phase == 3'd2) begin
                                digest_buffer <= lane0_rate_hold;
                                output_base_word <= lane0_output_base;
                                capture_write_phase <= 3'd3;
                                write_word_index <= '0;
                            end else if (capture_write_phase == 3'd3
                                         && pair_mode) begin
                                digest_buffer <= lane1_rate_hold;
                                output_base_word <= lane1_output_base;
                                capture_write_phase <= 3'd4;
                                write_word_index <= '0;
                            end else if (pair_mode && !write_pair_lane
                                        && capture_write_phase == 0) begin
                                digest_buffer <= lane1_rate_hold;
                                output_base_word <= lane1_output_base;
                                write_pair_lane <= 1'b1;
                                write_word_index <= '0;
                            end else begin
                                capture_write_phase <= '0;
                                if (pair_mode)
                                    dual_hash_pairs <= dual_hash_pairs
                                        + (repeat_mode
                                           ? {24'b0, repeats_remaining}
                                           : 32'd1);
                                rsp_valid <= 1'b1;
                                state <= S_IDLE;
                            end
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
