`timescale 1ns/1ps
`default_nettype none

// Native no-DMA SLH-DSA-SHAKE-128f Sign engine.  The message interface carries
// payload bytes only; after one admitted job, the JSON-lowered microprogram
// autonomously executes the complete PRF_msg, H_msg, FORS and hypertree path.
module micro_hbs_slh_dsa_prehash_slice #(
    parameter integer PROGRAM_WORDS = 256,
    parameter integer LAYOUT_COUNT = 32,
    parameter integer COMPONENT_WORDS = 128,
    parameter integer SCRATCH_WORDS = 1024,
    parameter integer MAX_MESSAGE_BYTES = 1024,
    parameter integer UNROLL = 2
) (
    input  wire         clk,
    input  wire         rst_n,
    input  wire         program_we,
    input  wire [8:0]   program_addr,
    input  wire [63:0]  program_wdata,
    input  wire         layout_cfg_valid,
    output wire         layout_cfg_ready,
    input  wire [15:0]  layout_cfg_id,
    input  wire [127:0] layout_cfg_descriptor,
    output wire         layout_cfg_error,
    output wire [15:0]  layout_cfg_error_code,
    input  wire         component_cfg_valid,
    output wire         component_cfg_ready,
    input  wire [15:0]  component_cfg_index,
    input  wire [191:0] component_cfg_descriptor,
    output wire         component_cfg_error,
    output wire [15:0]  component_cfg_error_code,
    input  wire         bitfield_cfg_valid,
    output wire         bitfield_cfg_ready,
    input  wire [15:0]  bitfield_cfg_id,
    input  wire [127:0] bitfield_cfg_descriptor,
    output wire         bitfield_cfg_error,
    output wire [15:0]  bitfield_cfg_error_code,
    input  wire         expr_descriptor_cfg_valid,
    output wire         expr_descriptor_cfg_ready,
    input  wire [15:0]  expr_descriptor_cfg_id,
    input  wire [63:0]  expr_descriptor_cfg_data,
    output wire         expr_descriptor_cfg_error,
    output wire [15:0]  expr_descriptor_cfg_error_code,
    input  wire         expr_token_cfg_valid,
    output wire         expr_token_cfg_ready,
    input  wire [5:0]   expr_token_cfg_index,
    input  wire [63:0]  expr_token_cfg_data,
    input  wire         base_w_cfg_valid,
    output wire         base_w_cfg_ready,
    input  wire [15:0]  base_w_cfg_id,
    input  wire [63:0]  base_w_cfg_data,
    output wire         base_w_cfg_error,
    output wire [15:0]  base_w_cfg_error_code,
    input  wire         wide_shift_cfg_valid,
    output wire         wide_shift_cfg_ready,
    input  wire [15:0]  wide_shift_cfg_id,
    input  wire [63:0]  wide_shift_cfg_data,
    output wire         wide_shift_cfg_error,
    output wire [15:0]  wide_shift_cfg_error_code,
    input  wire         data_descriptor_cfg_valid,
    output wire         data_descriptor_cfg_ready,
    input  wire [15:0]  data_descriptor_cfg_id,
    input  wire [127:0] data_descriptor_cfg_data,
    output wire         data_descriptor_cfg_error,
    output wire [15:0]  data_descriptor_cfg_error_code,
    input  wire         data_binding_cfg_valid,
    output wire         data_binding_cfg_ready,
    input  wire [15:0]  data_binding_cfg_id,
    input  wire [63:0]  data_binding_cfg_data,
    output wire         data_binding_cfg_error,
    output wire [15:0]  data_binding_cfg_error_code,
    input  wire         tree_cfg_valid,
    output wire         tree_cfg_ready,
    input  wire [15:0]  tree_cfg_id,
    input  wire [63:0]  tree_cfg_data,
    output wire         tree_cfg_error,
    output wire [15:0]  tree_cfg_error_code,

    input  wire         job_valid,
    output wire         job_ready,
    input  wire [8:0]   job_entry,
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
    output wire [31:0]  host_control_writes_during_busy,
    output wire [31:0]  issued_hash_requests,
    output wire [31:0]  tree_parent_hashes,
    output wire [31:0]  retired_instructions,
    output wire [31:0]  scratch_reads,
    output wire [31:0]  scratch_writes,
    output wire [31:0]  absorbed_blocks,
    output wire [31:0]  retired_components
);
    localparam logic [15:0] ERR_UNSUPPORTED_PATH = 16'h0104;

    wire loader_busy, loader_done, loader_error;
    wire [15:0] loader_error_code;
    wire core_start_valid, core_start_ready;
    wire [8:0] core_entry;
    wire [31:0] core_message_length;
    wire [127:0] core_sk_seed, core_sk_prf, core_pk_seed;
    wire [127:0] core_pk_root, core_opt_rand;
    wire loader_sp_valid, loader_sp_ready, loader_sp_write;
    wire [15:0] loader_sp_address;
    wire [63:0] loader_sp_write_data;

    wire seq_busy, seq_done, seq_error;
    wire [15:0] seq_error_code;
    wire [31:0] seq_accepted_jobs, seq_host_writes;
    wire hash_req_valid, hash_req_ready;
    wire [15:0] hash_layout_id;
    wire [1:0] hash_lane_mask;
    wire [7:0] hash_dest, hash_index_reg;
    wire [31:0] hash_index_value;
    wire hash_rsp_valid, hash_rsp_error;
    wire [15:0] hash_rsp_error_code;
    wire [31:0] issued_data_requests, issued_tree_requests;
    wire [255:0] register_snapshot;
    wire dynamic_bound_req;
    wire [15:0] dynamic_bound_addr;
    wire dynamic_bound_valid;
    wire [7:0] dynamic_bound_value;
    wire dynamic_bound_error;
    // Logical slots 35..69 are the 35 one-byte WOTS digits.  They are packed
    // offline/at LOAD9 into five physical words at 500..504; translate the
    // sequencer's logical dynamic-bound address through that static mapping.
    wire dynamic_bound_is_wots_digit = dynamic_bound_addr >= 16'd35
        && dynamic_bound_addr < 16'd70;
    wire [15:0] dynamic_bound_digit_offset = dynamic_bound_addr - 16'd35;
    wire [31:0] dynamic_bound_word_addr = dynamic_bound_is_wots_digit
        ? (32'd500 + (dynamic_bound_digit_offset >> 3))
        : (dynamic_bound_addr * 2);
    logic [2:0] dynamic_bound_byte_index;
    logic dynamic_bound_pending;
    wire data_req_valid, data_req_ready;
    wire [7:0] data_req_opcode, data_req_flags, data_req_rd, data_req_rs;
    wire [31:0] data_req_imm, data_req_rs_value;
    wire data_rsp_valid, data_rsp_error, data_rsp_reg_write;
    wire [15:0] data_rsp_error_code;
    wire [7:0] data_rsp_reg_index;
    wire [31:0] data_rsp_reg_value;
    wire tree_req_valid, tree_req_ready;
    wire [7:0] tree_req_flags, tree_req_rd, tree_req_rs;
    wire [31:0] tree_req_imm, tree_req_rs_value;
    wire tree_rsp_valid, tree_rsp_error;
    wire [15:0] tree_rsp_error_code;
    wire bitfield_cmd_ready, bitfield_cmd_match;
    wire bitfield_rsp_valid, bitfield_rsp_error;
    wire [15:0] bitfield_rsp_error_code;
    wire bitfield_rsp_reg_write;
    wire [7:0] bitfield_rsp_reg_index;
    wire [31:0] bitfield_rsp_reg_value;
    wire expr_cmd_ready, expr_cmd_match;
    wire expr_rsp_valid, expr_rsp_error;
    wire [15:0] expr_rsp_error_code;
    wire expr_rsp_reg_write;
    wire [7:0] expr_rsp_reg_index;
    wire [31:0] expr_rsp_reg_value;
    wire base_w_cmd_ready, base_w_cmd_match;
    wire base_w_rsp_valid, base_w_rsp_error;
    wire [15:0] base_w_rsp_error_code;
    wire wide_shift_cmd_ready, wide_shift_cmd_match;
    wire wide_shift_rsp_valid, wide_shift_rsp_error;
    wire [15:0] wide_shift_rsp_error_code;
    wire generic_cmd_ready, generic_rsp_valid, generic_rsp_error;
    wire [15:0] generic_rsp_error_code;
    wire generic_rsp_reg_write;
    wire [7:0] generic_rsp_reg_index;
    wire [31:0] generic_rsp_reg_value;
    wire generic_busy;

    wire composer_sp_valid, composer_sp_ready, composer_sp_write;
    wire [15:0] composer_sp_address;
    wire [63:0] composer_sp_write_data;
    wire bitfield_sp_valid, bitfield_sp_ready, bitfield_sp_write;
    wire [15:0] bitfield_sp_address;
    wire [63:0] bitfield_sp_write_data;
    wire bitfield_busy;
    wire expr_sp_valid, expr_sp_ready, expr_sp_write;
    wire [15:0] expr_sp_address;
    wire [63:0] expr_sp_write_data;
    wire expr_busy;
    wire base_w_sp_valid, base_w_sp_ready, base_w_sp_write;
    wire [15:0] base_w_sp_address;
    wire [63:0] base_w_sp_write_data;
    wire base_w_busy;
    wire wide_shift_sp_valid, wide_shift_sp_ready, wide_shift_sp_write;
    wire [15:0] wide_shift_sp_address;
    wire [63:0] wide_shift_sp_write_data;
    wire wide_shift_busy;
    wire generic_data_sp_valid, generic_data_sp_ready;
    wire generic_data_sp_write;
    wire [15:0] generic_data_sp_address;
    wire [63:0] generic_data_sp_write_data;
    wire generic_data_sp_rsp_valid, generic_data_sp_rsp_error;
    wire generic_emit_sp_valid, generic_emit_sp_ready;
    wire generic_emit_sp_write;
    wire [15:0] generic_emit_sp_address;
    wire [63:0] generic_emit_sp_write_data;
    wire generic_emit_sp_rsp_valid, generic_emit_sp_rsp_ready;
    wire generic_emit_sp_rsp_error;
    wire generic_sp_valid, generic_sp_ready, generic_sp_write;
    wire [15:0] generic_sp_address;
    wire [63:0] generic_sp_write_data;
    logic generic_response_owner_emit;
    wire tree_sp_valid, tree_sp_ready, tree_sp_write;
    wire [15:0] tree_sp_address;
    wire [63:0] tree_sp_write_data;
    wire tree_busy;

    wire data_desc_lookup_valid, data_desc_lookup_ready;
    wire [15:0] data_desc_lookup_id;
    wire data_desc_rsp_valid, data_desc_rsp_ready, data_desc_rsp_error;
    wire [15:0] data_desc_rsp_error_code, data_desc_flags;
    wire [15:0] data_desc_source_a, data_desc_source_b;
    wire [15:0] data_desc_destination, data_desc_word_count;
    wire [3:0] data_desc_last_bytes, data_desc_address_mode;
    wire [7:0] data_desc_format_version;
    wire [31:0] data_desc_reserved;
    wire binding_lookup_valid, binding_lookup_ready;
    wire [15:0] binding_lookup_id;
    wire binding_rsp_valid, binding_rsp_ready, binding_rsp_error;
    wire [15:0] binding_rsp_error_code;
    wire [1:0] binding_operand;
    wire binding_use_base_reg, binding_use_index_reg;
    wire [2:0] binding_base_reg, binding_index_reg;
    wire [15:0] binding_base_scale_words, binding_index_stride_words;
    wire composer_sp_rsp_valid, composer_sp_rsp_error;
    wire sp_valid, sp_ready, sp_write, sp_rsp_valid, sp_bounds_error;
    wire [15:0] sp_address;
    wire [63:0] sp_write_data, sp_read_data;
    logic [31:0] admission_program_writes;

    assign busy = loader_busy;
    assign done = loader_done;
    assign error = loader_error;
    assign error_code = loader_error_code;
    assign host_control_writes_during_busy = seq_host_writes
        + admission_program_writes;

    assign data_req_ready = bitfield_cmd_match ? bitfield_cmd_ready
        : (expr_cmd_match ? expr_cmd_ready
           : (base_w_cmd_match ? base_w_cmd_ready
              : (wide_shift_cmd_match ? wide_shift_cmd_ready
                                      : generic_cmd_ready)));
    assign data_rsp_valid = bitfield_rsp_valid || expr_rsp_valid
        || base_w_rsp_valid || wide_shift_rsp_valid || generic_rsp_valid;
    assign data_rsp_error = bitfield_rsp_valid ? bitfield_rsp_error
           : (expr_rsp_valid ? expr_rsp_error
              : (base_w_rsp_valid ? base_w_rsp_error
                 : (wide_shift_rsp_valid ? wide_shift_rsp_error
                                         : generic_rsp_error)));
    assign data_rsp_error_code = bitfield_rsp_valid ? bitfield_rsp_error_code
           : (expr_rsp_valid ? expr_rsp_error_code
              : (base_w_rsp_valid ? base_w_rsp_error_code
                 : (wide_shift_rsp_valid ? wide_shift_rsp_error_code
                                         : generic_rsp_error_code)));
    assign data_rsp_reg_write = bitfield_rsp_valid ? bitfield_rsp_reg_write
        : (expr_rsp_valid ? expr_rsp_reg_write : generic_rsp_reg_write);
    assign data_rsp_reg_index = bitfield_rsp_valid
        ? bitfield_rsp_reg_index
        : (expr_rsp_valid ? expr_rsp_reg_index : generic_rsp_reg_index);
    assign data_rsp_reg_value = bitfield_rsp_valid
        ? bitfield_rsp_reg_value
        : (expr_rsp_valid ? expr_rsp_reg_value : generic_rsp_reg_value);

    assign dynamic_bound_error = dynamic_bound_req
        && dynamic_bound_word_addr >= SCRATCH_WORDS;
    assign dynamic_bound_valid = dynamic_bound_pending && sp_rsp_valid;
    assign dynamic_bound_value =
        sp_read_data[8*dynamic_bound_byte_index +: 8];

    assign sp_valid = seq_busy
        ? (dynamic_bound_req
           ? (!dynamic_bound_pending && !dynamic_bound_error)
           : (generic_busy ? generic_sp_valid
           : (wide_shift_busy ? wide_shift_sp_valid
           : (base_w_busy ? base_w_sp_valid
           : (expr_busy ? expr_sp_valid
           : (bitfield_busy ? bitfield_sp_valid
              : (tree_sp_valid ? tree_sp_valid : composer_sp_valid)))
          ))))
        : loader_sp_valid;
    assign sp_write = seq_busy
        ? (dynamic_bound_req ? 1'b0
           : (generic_busy ? generic_sp_write
           : (wide_shift_busy ? wide_shift_sp_write
           : (base_w_busy ? base_w_sp_write
           : (expr_busy ? expr_sp_write
           : (bitfield_busy ? bitfield_sp_write
              : (tree_sp_valid ? tree_sp_write : composer_sp_write)))
          ))))
        : loader_sp_write;
    assign sp_address = seq_busy
        ? (dynamic_bound_req ? dynamic_bound_word_addr[15:0]
           : (generic_busy ? generic_sp_address
           : (wide_shift_busy ? wide_shift_sp_address
           : (base_w_busy ? base_w_sp_address
           : (expr_busy ? expr_sp_address
           : (bitfield_busy ? bitfield_sp_address
              : (tree_sp_valid ? tree_sp_address : composer_sp_address)))
          ))))
        : loader_sp_address;
    assign sp_write_data = seq_busy
        ? (dynamic_bound_req ? 64'b0
           : (generic_busy ? generic_sp_write_data
           : (wide_shift_busy ? wide_shift_sp_write_data
           : (base_w_busy ? base_w_sp_write_data
           : (expr_busy ? expr_sp_write_data
           : (bitfield_busy ? bitfield_sp_write_data
              : (tree_sp_valid ? tree_sp_write_data
                               : composer_sp_write_data)))
          ))))
        : loader_sp_write_data;
    assign composer_sp_ready = seq_busy && !dynamic_bound_req
        && !generic_busy && !wide_shift_busy
        && !base_w_busy && !expr_busy
        && !bitfield_busy && sp_ready;
    assign composer_sp_rsp_valid = seq_busy && !generic_busy && !wide_shift_busy
        && !base_w_busy && !expr_busy
        && !bitfield_busy && sp_rsp_valid;
    assign composer_sp_rsp_error = seq_busy && !generic_busy && !wide_shift_busy
        && !base_w_busy && !expr_busy
        && !bitfield_busy && sp_bounds_error;
    assign bitfield_sp_ready = seq_busy && !dynamic_bound_req
        && !generic_busy && !wide_shift_busy
        && !base_w_busy && !expr_busy
        && bitfield_busy
        && sp_ready;
    assign expr_sp_ready = seq_busy && !dynamic_bound_req
        && !generic_busy && !wide_shift_busy
        && !base_w_busy && expr_busy && sp_ready;
    assign base_w_sp_ready = seq_busy && !dynamic_bound_req
        && !generic_busy && !wide_shift_busy
        && base_w_busy && sp_ready;
    assign wide_shift_sp_ready = seq_busy && !dynamic_bound_req && !generic_busy
        && wide_shift_busy && sp_ready;
    assign tree_sp_ready = seq_busy && !dynamic_bound_req
        && !generic_busy && !wide_shift_busy
        && !base_w_busy && !expr_busy && !bitfield_busy
        && tree_sp_valid && sp_ready;
    assign generic_sp_valid = generic_emit_sp_valid || generic_data_sp_valid;
    assign generic_sp_write = generic_emit_sp_valid
        ? generic_emit_sp_write : generic_data_sp_write;
    assign generic_sp_address = generic_emit_sp_valid
        ? generic_emit_sp_address : generic_data_sp_address;
    assign generic_sp_write_data = generic_emit_sp_valid
        ? generic_emit_sp_write_data : generic_data_sp_write_data;
    assign generic_sp_ready = seq_busy && !dynamic_bound_req
        && generic_busy && sp_ready;
    assign generic_emit_sp_ready = generic_sp_ready && generic_emit_sp_valid;
    assign generic_data_sp_ready = generic_sp_ready && !generic_emit_sp_valid;
    assign generic_emit_sp_rsp_valid = seq_busy && generic_busy
        && sp_rsp_valid && generic_response_owner_emit;
    assign generic_emit_sp_rsp_error = seq_busy && generic_busy
        && sp_bounds_error && generic_response_owner_emit;
    assign generic_data_sp_rsp_valid = seq_busy && generic_busy
        && sp_rsp_valid && !generic_response_owner_emit;
    assign generic_data_sp_rsp_error = seq_busy && generic_busy
        && sp_bounds_error && !generic_response_owner_emit;
    assign loader_sp_ready = !seq_busy && sp_ready;

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n)
            generic_response_owner_emit <= 1'b0;
        else if (generic_sp_valid && generic_sp_ready)
            generic_response_owner_emit <= generic_emit_sp_valid;
    end

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            dynamic_bound_pending <= 1'b0;
            dynamic_bound_byte_index <= '0;
        end else begin
            if (dynamic_bound_valid || dynamic_bound_error)
                dynamic_bound_pending <= 1'b0;
            else if (dynamic_bound_req && !dynamic_bound_pending
                     && !dynamic_bound_error && sp_ready) begin
                dynamic_bound_pending <= 1'b1;
                dynamic_bound_byte_index <= dynamic_bound_is_wots_digit
                    ? dynamic_bound_digit_offset[2:0] : 3'b0;
            end
        end
    end

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n)
            admission_program_writes <= '0;
        else if (program_we && loader_busy && !seq_busy)
            admission_program_writes <= admission_program_writes + 1'b1;
    end

    micro_hbs_slh_dsa_job_stream_loader #(
        .SCRATCH_WORDS(SCRATCH_WORDS),
        .MAX_MESSAGE_BYTES(MAX_MESSAGE_BYTES)
    ) loader (
        .clk, .rst_n, .job_valid, .job_ready, .job_entry,
        .job_message_length, .job_sk_seed, .job_sk_prf, .job_pk_seed,
        .job_pk_root, .job_opt_rand, .message_valid, .message_ready,
        .message_data, .message_keep, .message_last,
        .core_start_valid, .core_start_ready, .core_entry,
        .core_message_length, .core_sk_seed, .core_sk_prf, .core_pk_seed,
        .core_pk_root, .core_opt_rand, .core_done(seq_done),
        .core_error(seq_error), .core_error_code(seq_error_code),
        .scratch_request_valid(loader_sp_valid),
        .scratch_request_ready(loader_sp_ready),
        .scratch_request_write(loader_sp_write),
        .scratch_request_address(loader_sp_address),
        .scratch_request_write_data(loader_sp_write_data),
        .scratch_bounds_error(sp_bounds_error), .busy(loader_busy),
        .done(loader_done), .error(loader_error),
        .error_code(loader_error_code),
        .accepted_jobs(accepted_job_commands), .admitted_message_words
    );

    micro_hbs_sequencer #(.PROGRAM_WORDS(PROGRAM_WORDS)) sequencer (
        .clk, .rst_n, .program_we(program_we && !loader_busy),
        .program_addr, .program_wdata,
        .job_valid(core_start_valid), .job_ready(core_start_ready),
        .job_entry(core_entry), .busy(seq_busy), .done(seq_done),
        .error(seq_error), .error_code(seq_error_code),
        .hash_req_valid, .hash_req_ready, .hash_layout_id, .hash_lane_mask,
        .hash_dest, .hash_index_reg, .hash_index_value, .hash_rsp_valid,
        .hash_rsp_error, .hash_rsp_error_code,
        .dynamic_bound_req, .dynamic_bound_addr,
        .dynamic_bound_valid, .dynamic_bound_value,
        .dynamic_bound_error, .dynamic_bound_error_code(16'h0201),
        .data_req_valid, .data_req_ready, .data_req_opcode,
        .data_req_flags, .data_req_rd, .data_req_rs, .data_req_imm,
        .data_req_rs_value, .data_rsp_valid, .data_rsp_error,
        .data_rsp_error_code, .data_rsp_reg_write, .data_rsp_reg_index,
        .data_rsp_reg_value,
        .tree_req_valid, .tree_req_ready, .tree_req_flags,
        .tree_req_rd, .tree_req_rs, .tree_req_imm, .tree_req_rs_value,
        .tree_rsp_valid, .tree_rsp_error, .tree_rsp_error_code,
        .accepted_job_commands(seq_accepted_jobs),
        .host_control_writes_during_busy(seq_host_writes),
        .issued_hash_requests, .issued_data_requests, .issued_tree_requests,
        .retired_instructions, .register_snapshot
    );

    micro_hbs_bitfield_load_adapter #(
        .DESCRIPTOR_COUNT(16), .SCRATCH_WORDS(SCRATCH_WORDS),
        .ADDRESS_WIDTH(16)
    ) bitfield_adapter (
        .clk, .rst_n, .engine_busy(loader_busy),
        .cfg_valid(bitfield_cfg_valid), .cfg_ready(bitfield_cfg_ready),
        .cfg_descriptor_id(bitfield_cfg_id),
        .cfg_descriptor(bitfield_cfg_descriptor),
        .cfg_error(bitfield_cfg_error),
        .cfg_error_code(bitfield_cfg_error_code),
        .cmd_valid(data_req_valid && bitfield_cmd_match),
        .cmd_ready(bitfield_cmd_ready),
        .cmd_opcode(data_req_opcode), .cmd_imm(data_req_imm),
        .cmd_registers(register_snapshot), .cmd_match(bitfield_cmd_match),
        .rsp_valid(bitfield_rsp_valid), .rsp_ready(1'b1),
        .rsp_error(bitfield_rsp_error),
        .rsp_error_code(bitfield_rsp_error_code),
        .rsp_reg_write(bitfield_rsp_reg_write),
        .rsp_reg_index(bitfield_rsp_reg_index),
        .rsp_reg_value(bitfield_rsp_reg_value),
        .scratch_request_valid(bitfield_sp_valid),
        .scratch_request_ready(bitfield_sp_ready),
        .scratch_request_write(bitfield_sp_write),
        .scratch_request_address(bitfield_sp_address),
        .scratch_request_write_data(bitfield_sp_write_data),
        .scratch_response_valid(seq_busy && bitfield_busy && sp_rsp_valid),
        .scratch_response_data(sp_read_data),
        .scratch_response_error(seq_busy && bitfield_busy && sp_bounds_error),
        .busy(bitfield_busy), .accepted_commands()
    );

    micro_hbs_expr_load_adapter #(
        .DESCRIPTOR_COUNT(16), .TOKEN_WORDS(64),
        .SCRATCH_WORDS(SCRATCH_WORDS), .ADDRESS_WIDTH(16)
    ) expr_adapter (
        .clk, .rst_n, .engine_busy(loader_busy),
        .descriptor_cfg_valid(expr_descriptor_cfg_valid),
        .descriptor_cfg_ready(expr_descriptor_cfg_ready),
        .descriptor_cfg_id(expr_descriptor_cfg_id),
        .descriptor_cfg_data(expr_descriptor_cfg_data),
        .descriptor_cfg_error(expr_descriptor_cfg_error),
        .descriptor_cfg_error_code(expr_descriptor_cfg_error_code),
        .token_cfg_valid(expr_token_cfg_valid),
        .token_cfg_ready(expr_token_cfg_ready),
        .token_cfg_index(expr_token_cfg_index),
        .token_cfg_data(expr_token_cfg_data),
        .cmd_valid(data_req_valid && expr_cmd_match),
        .cmd_ready(expr_cmd_ready), .cmd_opcode(data_req_opcode),
        .cmd_imm(data_req_imm), .cmd_registers(register_snapshot),
        .cmd_match(expr_cmd_match), .rsp_valid(expr_rsp_valid),
        .rsp_ready(1'b1), .rsp_error(expr_rsp_error),
        .rsp_error_code(expr_rsp_error_code),
        .rsp_reg_write(expr_rsp_reg_write),
        .rsp_reg_index(expr_rsp_reg_index),
        .rsp_reg_value(expr_rsp_reg_value),
        .scratch_request_valid(expr_sp_valid),
        .scratch_request_ready(expr_sp_ready),
        .scratch_request_write(expr_sp_write),
        .scratch_request_address(expr_sp_address),
        .scratch_request_write_data(expr_sp_write_data),
        .busy(expr_busy), .accepted_commands()
    );

    micro_hbs_base_w_load_adapter #(
        .DESCRIPTOR_COUNT(16), .SCRATCH_WORDS(SCRATCH_WORDS),
        .ADDRESS_WIDTH(16)
    ) base_w_adapter (
        .clk, .rst_n, .engine_busy(loader_busy),
        .cfg_valid(base_w_cfg_valid), .cfg_ready(base_w_cfg_ready),
        .cfg_id(base_w_cfg_id), .cfg_data(base_w_cfg_data),
        .cfg_error(base_w_cfg_error),
        .cfg_error_code(base_w_cfg_error_code),
        .cmd_valid(data_req_valid && base_w_cmd_match),
        .cmd_ready(base_w_cmd_ready), .cmd_opcode(data_req_opcode),
        .cmd_imm(data_req_imm), .cmd_match(base_w_cmd_match),
        .rsp_valid(base_w_rsp_valid), .rsp_ready(1'b1),
        .rsp_error(base_w_rsp_error),
        .rsp_error_code(base_w_rsp_error_code),
        .scratch_request_valid(base_w_sp_valid),
        .scratch_request_ready(base_w_sp_ready),
        .scratch_request_write(base_w_sp_write),
        .scratch_request_address(base_w_sp_address),
        .scratch_request_write_data(base_w_sp_write_data),
        .scratch_response_valid(seq_busy && base_w_busy && sp_rsp_valid),
        .scratch_response_data(sp_read_data),
        .scratch_response_error(seq_busy && base_w_busy && sp_bounds_error),
        .busy(base_w_busy)
    );

    micro_hbs_wide_shift_load_adapter #(
        .DESCRIPTOR_COUNT(16), .SCRATCH_WORDS(SCRATCH_WORDS),
        .ADDRESS_WIDTH(16)
    ) wide_shift_adapter (
        .clk, .rst_n, .engine_busy(loader_busy),
        .cfg_valid(wide_shift_cfg_valid),
        .cfg_ready(wide_shift_cfg_ready), .cfg_id(wide_shift_cfg_id),
        .cfg_data(wide_shift_cfg_data), .cfg_error(wide_shift_cfg_error),
        .cfg_error_code(wide_shift_cfg_error_code),
        .cmd_valid(data_req_valid && wide_shift_cmd_match),
        .cmd_ready(wide_shift_cmd_ready), .cmd_opcode(data_req_opcode),
        .cmd_imm(data_req_imm), .cmd_match(wide_shift_cmd_match),
        .rsp_valid(wide_shift_rsp_valid), .rsp_ready(1'b1),
        .rsp_error(wide_shift_rsp_error),
        .rsp_error_code(wide_shift_rsp_error_code),
        .scratch_request_valid(wide_shift_sp_valid),
        .scratch_request_ready(wide_shift_sp_ready),
        .scratch_request_write(wide_shift_sp_write),
        .scratch_request_address(wide_shift_sp_address),
        .scratch_request_write_data(wide_shift_sp_write_data),
        .scratch_response_valid(seq_busy && wide_shift_busy && sp_rsp_valid),
        .scratch_response_data(sp_read_data),
        .scratch_response_error(seq_busy && wide_shift_busy
                                && sp_bounds_error),
        .busy(wide_shift_busy)
    );

    micro_hbs_data_descriptor_store #(
        .DESCRIPTOR_COUNT(16), .FORMAT_VERSION(8'h02)
    ) data_descriptor_store (
        .clk, .rst_n, .engine_busy(loader_busy),
        .cfg_valid(data_descriptor_cfg_valid),
        .cfg_ready(data_descriptor_cfg_ready),
        .cfg_descriptor_id(data_descriptor_cfg_id),
        .cfg_descriptor(data_descriptor_cfg_data),
        .cfg_error(data_descriptor_cfg_error),
        .cfg_error_code(data_descriptor_cfg_error_code),
        .lookup_valid(data_desc_lookup_valid),
        .lookup_ready(data_desc_lookup_ready),
        .lookup_descriptor_id(data_desc_lookup_id),
        .lookup_rsp_valid(data_desc_rsp_valid),
        .lookup_rsp_ready(data_desc_rsp_ready),
        .lookup_rsp_error(data_desc_rsp_error),
        .lookup_rsp_error_code(data_desc_rsp_error_code),
        .lookup_descriptor(), .descriptor_flags(data_desc_flags),
        .descriptor_source_a(data_desc_source_a),
        .descriptor_source_b(data_desc_source_b),
        .descriptor_destination(data_desc_destination),
        .descriptor_word_count(data_desc_word_count),
        .descriptor_last_bytes(data_desc_last_bytes),
        .descriptor_address_mode(data_desc_address_mode),
        .descriptor_format_version(data_desc_format_version),
        .descriptor_reserved(data_desc_reserved), .image_locked(),
        .descriptor_capacity(), .configured_count(), .accepted_loads(),
        .rejected_loads(), .host_writes_busy(), .lookup_requests(),
        .lookup_errors()
    );

    micro_hbs_address_binding_store #(
        .BINDING_COUNT(16), .FORMAT_VERSION(8'h01)
    ) data_binding_store (
        .clk, .rst_n, .engine_busy(loader_busy),
        .cfg_valid(data_binding_cfg_valid),
        .cfg_ready(data_binding_cfg_ready),
        .cfg_binding_id(data_binding_cfg_id),
        .cfg_format_version(8'h01), .cfg_binding(data_binding_cfg_data),
        .cfg_error(data_binding_cfg_error),
        .cfg_error_code(data_binding_cfg_error_code),
        .lookup_valid(binding_lookup_valid),
        .lookup_ready(binding_lookup_ready),
        .lookup_binding_id(binding_lookup_id),
        .lookup_rsp_valid(binding_rsp_valid),
        .lookup_rsp_ready(binding_rsp_ready),
        .lookup_rsp_error(binding_rsp_error),
        .lookup_rsp_error_code(binding_rsp_error_code), .lookup_binding(),
        .binding_operand, .binding_use_base_reg, .binding_base_reg,
        .binding_use_index_reg, .binding_index_reg,
        .binding_base_scale_words, .binding_index_stride_words,
        .image_locked(), .binding_capacity(), .configured_count(),
        .accepted_loads(), .rejected_loads(), .host_writes_busy(),
        .lookup_requests(), .lookup_errors()
    );

    micro_hbs_data_engine #(
        .SCRATCH_WORDS(SCRATCH_WORDS), .ADDRESS_WIDTH(16),
        .EMIT_DESCRIPTOR_BASE(16'd4),
        .EMIT_INSTRUCTION_STRIDE_WORDS(2),
        .SCRATCH_WRITE_ACK(1'b0)
    ) generic_data_engine (
        .clk, .rst_n,
        .cmd_valid(data_req_valid && !bitfield_cmd_match && !expr_cmd_match
                   && !base_w_cmd_match && !wide_shift_cmd_match),
        .cmd_ready(generic_cmd_ready), .cmd_opcode(data_req_opcode),
        .cmd_flags(data_req_flags), .cmd_rd(data_req_rd),
        .cmd_rs(data_req_rs), .cmd_imm(data_req_imm),
        .cmd_rs_value(data_req_rs_value), .cmd_registers(register_snapshot),
        .rsp_valid(generic_rsp_valid), .rsp_error(generic_rsp_error),
        .rsp_error_code(generic_rsp_error_code),
        .rsp_reg_write(generic_rsp_reg_write),
        .rsp_reg_index(generic_rsp_reg_index),
        .rsp_reg_value(generic_rsp_reg_value),
        .descriptor_lookup_valid(data_desc_lookup_valid),
        .descriptor_lookup_ready(data_desc_lookup_ready),
        .descriptor_lookup_id(data_desc_lookup_id),
        .descriptor_rsp_valid(data_desc_rsp_valid),
        .descriptor_rsp_ready(data_desc_rsp_ready),
        .descriptor_rsp_error(data_desc_rsp_error),
        .descriptor_rsp_error_code(data_desc_rsp_error_code),
        .descriptor_flags(data_desc_flags),
        .descriptor_source_a(data_desc_source_a),
        .descriptor_source_b(data_desc_source_b),
        .descriptor_destination(data_desc_destination),
        .descriptor_word_count(data_desc_word_count),
        .descriptor_last_bytes(data_desc_last_bytes),
        .descriptor_address_mode(data_desc_address_mode),
        .descriptor_format_version(data_desc_format_version),
        .descriptor_reserved(data_desc_reserved),
        .binding_lookup_valid(binding_lookup_valid),
        .binding_lookup_ready(binding_lookup_ready),
        .binding_lookup_id(binding_lookup_id),
        .binding_rsp_valid(binding_rsp_valid),
        .binding_rsp_ready(binding_rsp_ready),
        .binding_rsp_error(binding_rsp_error),
        .binding_rsp_error_code(binding_rsp_error_code), .binding_operand,
        .binding_use_base_reg, .binding_base_reg,
        .binding_use_index_reg, .binding_index_reg,
        .binding_base_scale_words, .binding_index_stride_words,
        .data_scratch_request_valid(generic_data_sp_valid),
        .data_scratch_request_ready(generic_data_sp_ready),
        .data_scratch_request_write(generic_data_sp_write),
        .data_scratch_request_address(generic_data_sp_address),
        .data_scratch_request_write_data(generic_data_sp_write_data),
        .data_scratch_response_valid(generic_data_sp_rsp_valid),
        .data_scratch_response_data(sp_read_data),
        .data_scratch_response_error(generic_data_sp_rsp_error),
        .emit_scratch_request_valid(generic_emit_sp_valid),
        .emit_scratch_request_ready(generic_emit_sp_ready),
        .emit_scratch_request_write(generic_emit_sp_write),
        .emit_scratch_request_address(generic_emit_sp_address),
        .emit_scratch_request_write_data(generic_emit_sp_write_data),
        .emit_scratch_response_valid(generic_emit_sp_rsp_valid),
        .emit_scratch_response_ready(generic_emit_sp_rsp_ready),
        .emit_scratch_response_data(sp_read_data),
        .emit_scratch_response_error(generic_emit_sp_rsp_error),
        .out_valid, .out_ready, .out_data, .out_keep, .out_last,
        .accepted_commands(), .completed_commands(), .error_commands()
    );
    assign generic_busy = !generic_cmd_ready;

    micro_hbs_slh_dsa_tree_adapter #(
        .DESCRIPTOR_COUNT(32), .SCRATCH_WORDS(SCRATCH_WORDS),
        .MAX_TREE_HEIGHT(6), .UNROLL(UNROLL)
    ) tree_adapter (
        .clk, .rst_n, .engine_busy(loader_busy),
        .cfg_valid(tree_cfg_valid), .cfg_ready(tree_cfg_ready),
        .cfg_id(tree_cfg_id), .cfg_data(tree_cfg_data),
        .cfg_error(tree_cfg_error), .cfg_error_code(tree_cfg_error_code),
        .cmd_valid(tree_req_valid), .cmd_ready(tree_req_ready),
        .cmd_flags(tree_req_flags), .cmd_rd(tree_req_rd), .cmd_imm(tree_req_imm),
        .cmd_leaf_index(tree_req_rs_value),
        .cmd_registers(register_snapshot), .public_seed(core_pk_seed),
        .rsp_valid(tree_rsp_valid), .rsp_error(tree_rsp_error),
        .rsp_error_code(tree_rsp_error_code),
        .scratch_request_valid(tree_sp_valid),
        .scratch_request_ready(tree_sp_ready),
        .scratch_request_write(tree_sp_write),
        .scratch_request_address(tree_sp_address),
        .scratch_request_write_data(tree_sp_write_data),
        .scratch_response_valid(seq_busy && tree_busy && sp_rsp_valid),
        .scratch_response_data(sp_read_data),
        .scratch_response_error(seq_busy && tree_busy && sp_bounds_error),
        .busy(tree_busy), .accepted_leaves(), .parent_hashes(),
        .total_parent_hashes(tree_parent_hashes)
    );

    micro_hbs_descriptor_shake_composer #(
        .LAYOUT_COUNT(LAYOUT_COUNT), .COMPONENT_WORDS(COMPONENT_WORDS),
        .SCRATCH_WORDS(SCRATCH_WORDS),
        .MAX_MESSAGE_BYTES(MAX_MESSAGE_BYTES + 64),
        .LOGICAL_SLOT_BYTES(16), .UNROLL(UNROLL)
    ) composer (
        .clk, .rst_n, .engine_busy(loader_busy),
        .cfg_valid(layout_cfg_valid), .cfg_ready(layout_cfg_ready),
        .cfg_layout_id(layout_cfg_id),
        .cfg_descriptor(layout_cfg_descriptor),
        .cfg_error(layout_cfg_error),
        .cfg_error_code(layout_cfg_error_code),
        .component_cfg_valid, .component_cfg_ready, .component_cfg_index,
        .component_cfg_descriptor, .component_cfg_error,
        .component_cfg_error_code,
        .req_valid(hash_req_valid), .req_ready(hash_req_ready),
        .layout_id(hash_layout_id), .lane_mask(hash_lane_mask),
        .destination(hash_dest), .index_value(hash_index_value),
        .register_snapshot,
        .rsp_valid(hash_rsp_valid), .rsp_error(hash_rsp_error),
        .rsp_error_code(hash_rsp_error_code),
        .sp_req_valid(composer_sp_valid), .sp_req_ready(composer_sp_ready),
        .sp_req_write(composer_sp_write),
        .sp_req_address(composer_sp_address),
        .sp_req_write_data(composer_sp_write_data),
        .sp_rsp_valid(composer_sp_rsp_valid), .sp_rsp_read_data(sp_read_data),
        .sp_rsp_error(composer_sp_rsp_error), .busy(), .last_digest,
        .scratch_reads, .scratch_writes, .absorbed_blocks,
        .retired_components
    );

    micro_hbs_scratchpad64 #(
        .WORDS(SCRATCH_WORDS), .ADDRESS_WIDTH(16)
    ) scratchpad (
        .clk, .rst_n, .request_valid(sp_valid), .request_ready(sp_ready),
        .request_write(sp_write), .request_address(sp_address),
        .request_write_data(sp_write_data), .response_valid(sp_rsp_valid),
        .response_read_data(sp_read_data), .bounds_error(sp_bounds_error),
        .scrub_start(1'b0), .scrub_busy(), .scrub_done()
    );
endmodule

`default_nettype wire
