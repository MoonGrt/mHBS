`timescale 1ns/1ps
`default_nettype none

// Native one-Job vertical slice for an XMSS WOTS+/L-tree leaf using only the
// generic JSON-lowered HASH_LAYOUT component program and descriptor-v2 STORE.
// Hash and data commands share one Scratchpad port; no WOTS/XMSS opcode or
// external task/hash ingress exists.
module micro_hbs_xmss_generic_leaf_slice #(
    parameter integer PROGRAM_WORDS = 128,
    parameter integer LAYOUT_COUNT = 16,
    parameter integer COMPONENT_WORDS = 128,
    parameter integer DATA_DESCRIPTOR_COUNT = 8,
    parameter integer BINDING_COUNT = 8,
    parameter integer SCRATCH_WORDS = 1024,
    parameter integer TREE_HEIGHT = 10,
    parameter integer ROOT_DESTINATION_SLOT = 230,
    parameter integer JOB_SK_SEED_SLOT = 248,
    parameter integer JOB_PUBLIC_SEED_SLOT = 249,
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

    input  wire         data_descriptor_cfg_valid,
    output wire         data_descriptor_cfg_ready,
    input  wire [15:0]  data_descriptor_cfg_id,
    input  wire [127:0] data_descriptor_cfg_data,
    output wire         data_descriptor_cfg_error,
    output wire [15:0]  data_descriptor_cfg_error_code,
    input  wire         binding_cfg_valid,
    output wire         binding_cfg_ready,
    input  wire [15:0]  binding_cfg_id,
    input  wire [7:0]   binding_cfg_format_version,
    input  wire [63:0]  binding_cfg_data,
    output wire         binding_cfg_error,
    output wire [15:0]  binding_cfg_error_code,

    input  wire         scratch_init_valid,
    output wire         scratch_init_ready,
    input  wire         scratch_init_write,
    input  wire [15:0]  scratch_init_address,
    input  wire [63:0]  scratch_init_write_data,
    output wire         scratch_init_rsp_valid,
    output wire [63:0]  scratch_init_rsp_data,
    output wire         scratch_init_error,

    input  wire         job_valid,
    output wire         job_ready,
    input  wire [8:0]   job_entry,
    input  wire [15:0]  job_target_leaf,
    input  wire [255:0] job_sk_seed,
    input  wire [255:0] job_public_seed,
    input  wire [255:0] job_address_template,
    output wire         busy,
    output wire         done,
    output wire         error,
    output wire [15:0]  error_code,
    output wire [255:0] last_digest,
    output wire [31:0]  accepted_job_commands,
    output wire [31:0]  host_control_writes_during_busy,
    output wire [31:0]  issued_hash_requests,
    output wire [31:0]  issued_data_requests,
    output wire [31:0]  issued_tree_requests,
    output wire [31:0]  retired_instructions,
    output wire [31:0]  retired_components,
    output wire [31:0]  composer_scratch_reads,
    output wire [31:0]  composer_scratch_writes,
    output wire [31:0]  absorbed_blocks,
    output wire [31:0]  scratch_transactions,
    output wire         root_valid,
    output wire [255:0] root,
    output wire         auth_valid,
    output wire [7:0]   auth_level,
    output wire [255:0] auth_node,
    output wire [15:0]  accepted_leaves,
    output wire [15:0]  parent_hashes,
    output wire         out_valid,
    input  wire         out_ready,
    output wire [63:0]  out_data,
    output wire [7:0]   out_keep,
    output wire         out_last
);
    localparam logic [15:0] ERR_UNSUPPORTED_PATH = 16'h0104;
    localparam logic [15:0] ERR_JOB_SEED_BOUNDS = 16'h0301;
    localparam integer ROOT_DESTINATION_WORD = ROOT_DESTINATION_SLOT * 4;
    localparam integer JOB_SK_SEED_WORD = JOB_SK_SEED_SLOT * 4;
    localparam integer JOB_PUBLIC_SEED_WORD = JOB_PUBLIC_SEED_SLOT * 4;

    typedef enum logic [2:0] {
        J_IDLE, J_WRITE_REQ, J_WRITE_WAIT, J_START, J_RUN
    } job_state_t;
    job_state_t job_state;
    logic [2:0] job_load_word;
    logic [8:0] job_entry_latched;
    logic [255:0] sk_seed_latched;
    wire seq_job_valid, seq_job_ready, seq_busy, seq_done, seq_error;
    wire [15:0] seq_error_code;
    wire [31:0] seq_host_control_writes_during_busy;
    logic [31:0] admission_host_control_writes;
    logic admission_error;

    wire hash_req_valid, hash_req_ready;
    wire [15:0] hash_layout_id;
    wire [1:0] hash_lane_mask;
    wire [7:0] hash_dest, hash_index_reg;
    wire [31:0] hash_index_value;
    wire hash_rsp_valid, hash_rsp_error;
    wire [15:0] hash_rsp_error_code;
    wire data_req_valid, data_req_ready;
    wire [7:0] data_req_opcode, data_req_flags, data_req_rd, data_req_rs;
    wire [31:0] data_req_imm, data_req_rs_value;
    wire data_rsp_valid, data_rsp_error, data_rsp_reg_write;
    wire [15:0] data_rsp_error_code;
    wire [7:0] data_rsp_reg_index;
    wire [31:0] data_rsp_reg_value;
    wire [255:0] register_snapshot;
    wire tree_req_valid, tree_req_ready;
    wire [7:0] tree_req_flags, tree_req_rd, tree_req_rs;
    wire [31:0] tree_req_imm, tree_req_rs_value;
    wire tree_rsp_valid, tree_rsp_error;
    wire [15:0] tree_rsp_error_code;
    logic [15:0] target_leaf_latched;
    logic [255:0] public_seed_latched, address_template_latched;

    wire desc_lookup_valid, desc_lookup_ready, desc_rsp_valid, desc_rsp_ready;
    wire [15:0] desc_lookup_id, desc_rsp_error_code;
    wire desc_rsp_error;
    wire [127:0] desc_value;
    wire [15:0] desc_flags, desc_source_a, desc_source_b, desc_destination;
    wire [15:0] desc_word_count;
    wire [3:0] desc_last_bytes, desc_address_mode;
    wire [7:0] desc_format_version;
    wire [31:0] desc_reserved;

    wire bind_lookup_valid, bind_lookup_ready, bind_rsp_valid, bind_rsp_ready;
    wire [15:0] bind_lookup_id, bind_rsp_error_code;
    wire bind_rsp_error;
    wire [63:0] bind_value;
    wire [1:0] bind_operand;
    wire bind_use_base_reg, bind_use_index_reg;
    wire [2:0] bind_base_reg, bind_index_reg;
    wire [15:0] bind_base_scale_words, bind_index_stride_words;

    wire composer_busy;
    wire composer_sp_req_valid, composer_sp_req_ready, composer_sp_req_write;
    wire [15:0] composer_sp_req_address;
    wire [63:0] composer_sp_req_write_data;
    wire composer_sp_rsp_valid, composer_sp_rsp_error;

    wire data_sp_req_valid, data_sp_req_ready, data_sp_req_write;
    wire [15:0] data_sp_req_address;
    wire [63:0] data_sp_req_write_data;
    wire data_sp_rsp_valid, data_sp_rsp_error;
    wire [63:0] data_sp_rsp_data;
    wire emit_sp_req_valid, emit_sp_req_ready, emit_sp_req_write;
    wire [15:0] emit_sp_req_address;
    wire [63:0] emit_sp_req_write_data;
    wire emit_sp_rsp_valid, emit_sp_rsp_ready, emit_sp_rsp_error;
    wire [63:0] emit_sp_rsp_data;

    wire tree_sp_req_valid, tree_sp_req_ready, tree_sp_req_write;
    wire [15:0] tree_sp_req_address;
    wire [63:0] tree_sp_req_write_data;
    wire tree_sp_rsp_valid, tree_sp_rsp_error;
    wire [63:0] tree_sp_rsp_data;
    wire adapter_tree_sp_req_valid, adapter_tree_sp_req_ready;
    wire adapter_tree_sp_req_write;
    wire [15:0] adapter_tree_sp_req_address;
    wire [63:0] adapter_tree_sp_req_write_data;
    wire adapter_tree_sp_rsp_valid, adapter_tree_sp_rsp_error;
    wire [63:0] adapter_tree_sp_rsp_data;
    wire tree_raw_rsp_valid, tree_raw_rsp_error;
    wire [15:0] tree_raw_rsp_error_code;
    wire [15:0] tree_node_base_word;
    wire parent_req_valid, parent_req_ready;
    wire [7:0] parent_req_height;
    wire [15:0] parent_req_start_leaf;
    wire [255:0] parent_req_left, parent_req_right;
    wire parent_rsp_valid, parent_rsp_error;
    wire [255:0] parent_rsp_value;
    logic root_write_active, root_write_wait, root_write_rsp_valid;
    logic root_write_rsp_error;
    logic [15:0] root_write_rsp_error_code;
    logic [1:0] root_write_index;
    logic [255:0] root_write_buffer;

    wire alu_req_valid, alu_req_ready, alu_req_write;
    wire [15:0] alu_req_address;
    wire [63:0] alu_req_write_data;
    wire alu_rsp_valid, alu_rsp_error;
    wire [63:0] alu_rsp_data;
    logic alu_response_owner_hash;

    wire arb_sp_req_valid, arb_sp_req_ready, arb_sp_req_write, arb_busy;
    wire [15:0] arb_sp_req_address;
    wire [63:0] arb_sp_req_write_data;
    wire sp_req_valid, sp_req_ready, sp_req_write;
    wire [15:0] sp_req_address;
    wire [63:0] sp_req_write_data, sp_rsp_data;
    wire sp_rsp_valid, sp_bounds_error;

    wire job_loader_active = (job_state == J_WRITE_REQ)
        || (job_state == J_WRITE_WAIT);
    wire job_loader_req_valid = (job_state == J_WRITE_REQ);
    wire [15:0] job_loader_address = (job_load_word < 4)
        ? (16'(JOB_SK_SEED_WORD) + {13'b0, job_load_word})
        : (16'(JOB_PUBLIC_SEED_WORD)
           + {14'b0, job_load_word[1:0]});
    wire [63:0] job_loader_data = (job_load_word < 4)
        ? sk_seed_latched[64*job_load_word[1:0] +: 64]
        : public_seed_latched[64*job_load_word[1:0] +: 64];

    assign seq_job_valid = (job_state == J_START);
    assign job_ready = (job_state == J_IDLE) && seq_job_ready;
    assign busy = (job_state != J_IDLE) || seq_busy;
    assign done = seq_done;
    assign error = seq_error || admission_error;
    assign error_code = admission_error
        ? ERR_JOB_SEED_BOUNDS : seq_error_code;
    assign host_control_writes_during_busy =
        seq_host_control_writes_during_busy + admission_host_control_writes;

    assign tree_node_base_word = {8'b0, tree_req_rd} * 16'd4;
    assign tree_rsp_valid = root_write_rsp_valid
        || (tree_raw_rsp_valid && !root_write_active);
    assign tree_rsp_error = root_write_rsp_valid
        ? root_write_rsp_error : tree_raw_rsp_error;
    assign tree_rsp_error_code = root_write_rsp_valid
        ? root_write_rsp_error_code : tree_raw_rsp_error_code;

    // The JSON Keygen layout names logical slot 230 as its root destination.
    // Hold the final TREE_PUSH response until all four root words have been
    // committed, then let the unchanged next EMIT instruction consume them.
    assign tree_sp_req_valid = root_write_active
        ? !root_write_wait : adapter_tree_sp_req_valid;
    assign tree_sp_req_write = root_write_active
        ? 1'b1 : adapter_tree_sp_req_write;
    assign tree_sp_req_address = root_write_active
        ? (16'(ROOT_DESTINATION_WORD) + {14'b0, root_write_index})
        : adapter_tree_sp_req_address;
    assign tree_sp_req_write_data = root_write_active
        ? root_write_buffer[64*root_write_index +: 64]
        : adapter_tree_sp_req_write_data;
    assign adapter_tree_sp_req_ready = !root_write_active
        && tree_sp_req_ready;
    assign adapter_tree_sp_rsp_valid = !root_write_active
        && tree_sp_rsp_valid;
    assign adapter_tree_sp_rsp_data = tree_sp_rsp_data;
    assign adapter_tree_sp_rsp_error = !root_write_active
        && tree_sp_rsp_error;

    assign alu_req_valid = composer_sp_req_valid || data_sp_req_valid;
    assign alu_req_write = composer_sp_req_valid
        ? composer_sp_req_write : data_sp_req_write;
    assign alu_req_address = composer_sp_req_valid
        ? composer_sp_req_address : data_sp_req_address;
    assign alu_req_write_data = composer_sp_req_valid
        ? composer_sp_req_write_data : data_sp_req_write_data;
    assign composer_sp_req_ready = alu_req_ready && composer_sp_req_valid;
    assign data_sp_req_ready = alu_req_ready && !composer_sp_req_valid;
    assign composer_sp_rsp_valid = alu_rsp_valid && alu_response_owner_hash;
    assign composer_sp_rsp_error = alu_rsp_error && alu_response_owner_hash;
    assign data_sp_rsp_valid = alu_rsp_valid && !alu_response_owner_hash;
    assign data_sp_rsp_error = alu_rsp_error && !alu_response_owner_hash;
    assign data_sp_rsp_data = alu_rsp_data;

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n)
            alu_response_owner_hash <= 1'b0;
        else if (alu_req_valid && alu_req_ready)
            alu_response_owner_hash <= composer_sp_req_valid;
    end

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            root_write_active <= 1'b0;
            root_write_wait <= 1'b0;
            root_write_rsp_valid <= 1'b0;
            root_write_rsp_error <= 1'b0;
            root_write_rsp_error_code <= '0;
            root_write_index <= '0;
            root_write_buffer <= '0;
        end else begin
            root_write_rsp_valid <= 1'b0;
            if (!root_write_active && root_valid) begin
                root_write_active <= 1'b1;
                root_write_wait <= 1'b0;
                root_write_index <= '0;
                root_write_buffer <= root;
                root_write_rsp_error <= 1'b0;
                root_write_rsp_error_code <= '0;
            end else if (root_write_active) begin
                if (!root_write_wait && tree_sp_req_ready)
                    root_write_wait <= 1'b1;
                else if (root_write_wait && tree_sp_rsp_valid) begin
                    if (tree_sp_rsp_error) begin
                        root_write_active <= 1'b0;
                        root_write_wait <= 1'b0;
                        root_write_rsp_valid <= 1'b1;
                        root_write_rsp_error <= 1'b1;
                        root_write_rsp_error_code <= 16'h0402;
                    end else if (root_write_index == 2'd3) begin
                        root_write_active <= 1'b0;
                        root_write_wait <= 1'b0;
                        root_write_rsp_valid <= 1'b1;
                    end else begin
                        root_write_index <= root_write_index + 1'b1;
                        root_write_wait <= 1'b0;
                    end
                end
            end
        end
    end

    initial begin
        if (JOB_SK_SEED_WORD + 4 > SCRATCH_WORDS
            || JOB_PUBLIC_SEED_WORD + 4 > SCRATCH_WORDS)
            $error("Job seed slots exceed Scratchpad capacity");
    end

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            job_state <= J_IDLE;
            job_load_word <= '0;
            job_entry_latched <= '0;
            target_leaf_latched <= '0;
            sk_seed_latched <= '0;
            public_seed_latched <= '0;
            address_template_latched <= '0;
            admission_host_control_writes <= '0;
            admission_error <= 1'b0;
        end else begin
            admission_error <= 1'b0;
            if (program_we && job_state != J_IDLE)
                admission_host_control_writes
                    <= admission_host_control_writes + 1'b1;
            case (job_state)
                J_IDLE: begin
                    if (job_valid && job_ready) begin
                        job_entry_latched <= job_entry;
                        target_leaf_latched <= job_target_leaf;
                        sk_seed_latched <= job_sk_seed;
                        public_seed_latched <= job_public_seed;
                        address_template_latched <= job_address_template;
                        job_load_word <= '0;
                        job_state <= J_WRITE_REQ;
                    end
                end
                J_WRITE_REQ: begin
                    if (sp_req_ready)
                        job_state <= J_WRITE_WAIT;
                end
                J_WRITE_WAIT: begin
                    // Scratchpad writes commit on the request handshake and do
                    // not produce response_valid.  This state supplies the one
                    // cycle needed for the registered bounds_error result.
                    if (sp_bounds_error) begin
                        admission_error <= 1'b1;
                        job_state <= J_IDLE;
                    end else begin
                        if (job_load_word == 3'd7)
                            job_state <= J_START;
                        else begin
                            job_load_word <= job_load_word + 1'b1;
                            job_state <= J_WRITE_REQ;
                        end
                    end
                end
                J_START: begin
                    if (seq_job_ready)
                        job_state <= J_RUN;
                end
                J_RUN: begin
                    if (seq_done || seq_error)
                        job_state <= J_IDLE;
                end
                default: job_state <= J_IDLE;
            endcase
        end
    end

    assign scratch_init_ready = !busy && !arb_busy && sp_req_ready;
    assign sp_req_valid = seq_busy ? arb_sp_req_valid
        : job_loader_active ? job_loader_req_valid : scratch_init_valid;
    assign sp_req_write = seq_busy ? arb_sp_req_write
        : job_loader_active ? 1'b1 : scratch_init_write;
    assign sp_req_address = seq_busy ? arb_sp_req_address
        : job_loader_active ? job_loader_address : scratch_init_address;
    assign sp_req_write_data = seq_busy ? arb_sp_req_write_data
        : job_loader_active ? job_loader_data : scratch_init_write_data;
    assign arb_sp_req_ready = seq_busy && sp_req_ready;
    assign scratch_init_rsp_valid = !busy && sp_rsp_valid;
    assign scratch_init_rsp_data = sp_rsp_data;
    assign scratch_init_error = !busy && sp_bounds_error;

    micro_hbs_sequencer #(.PROGRAM_WORDS(PROGRAM_WORDS)) sequencer (
        .clk, .rst_n, .program_we(program_we && job_state == J_IDLE),
        .program_addr, .program_wdata,
        .job_valid(seq_job_valid), .job_ready(seq_job_ready),
        .job_entry(job_entry_latched), .busy(seq_busy), .done(seq_done),
        .error(seq_error), .error_code(seq_error_code),
        .hash_req_valid, .hash_req_ready, .hash_layout_id, .hash_lane_mask,
        .hash_dest, .hash_index_reg, .hash_index_value, .hash_rsp_valid,
        .hash_rsp_error, .hash_rsp_error_code,
        .dynamic_bound_req(), .dynamic_bound_addr(),
        .dynamic_bound_valid(1'b0), .dynamic_bound_value(8'b0),
        .dynamic_bound_error(1'b0), .dynamic_bound_error_code(16'b0),
        .data_req_valid, .data_req_ready, .data_req_opcode, .data_req_flags,
        .data_req_rd, .data_req_rs, .data_req_imm, .data_req_rs_value,
        .data_rsp_valid, .data_rsp_error, .data_rsp_error_code,
        .data_rsp_reg_write, .data_rsp_reg_index, .data_rsp_reg_value,
        .tree_req_valid, .tree_req_ready, .tree_req_flags,
        .tree_req_rd, .tree_req_rs, .tree_req_imm,
        .tree_req_rs_value, .tree_rsp_valid,
        .tree_rsp_error, .tree_rsp_error_code,
        .accepted_job_commands,
        .host_control_writes_during_busy(seq_host_control_writes_during_busy),
        .issued_hash_requests, .issued_data_requests, .issued_tree_requests,
        .retired_instructions, .register_snapshot
    );

    micro_hbs_descriptor_shake_composer #(
        .LAYOUT_COUNT(LAYOUT_COUNT), .COMPONENT_WORDS(COMPONENT_WORDS),
        .SCRATCH_WORDS(SCRATCH_WORDS), .MAX_MESSAGE_BYTES(4096),
        .UNROLL(UNROLL)
    ) composer (
        .clk, .rst_n, .engine_busy(busy),
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
        .register_snapshot, .rsp_valid(hash_rsp_valid),
        .rsp_error(hash_rsp_error), .rsp_error_code(hash_rsp_error_code),
        .sp_req_valid(composer_sp_req_valid),
        .sp_req_ready(composer_sp_req_ready),
        .sp_req_write(composer_sp_req_write),
        .sp_req_address(composer_sp_req_address),
        .sp_req_write_data(composer_sp_req_write_data),
        .sp_rsp_valid(composer_sp_rsp_valid),
        .sp_rsp_read_data(alu_rsp_data), .sp_rsp_error(composer_sp_rsp_error),
        .busy(composer_busy), .last_digest,
        .scratch_reads(composer_scratch_reads),
        .scratch_writes(composer_scratch_writes), .absorbed_blocks,
        .retired_components
    );

    micro_hbs_data_descriptor_store #(
        .DESCRIPTOR_COUNT(DATA_DESCRIPTOR_COUNT), .FORMAT_VERSION(8'h02)
    ) data_descriptors (
        .clk, .rst_n, .engine_busy(busy),
        .cfg_valid(data_descriptor_cfg_valid),
        .cfg_ready(data_descriptor_cfg_ready),
        .cfg_descriptor_id(data_descriptor_cfg_id),
        .cfg_descriptor(data_descriptor_cfg_data),
        .cfg_error(data_descriptor_cfg_error),
        .cfg_error_code(data_descriptor_cfg_error_code),
        .lookup_valid(desc_lookup_valid), .lookup_ready(desc_lookup_ready),
        .lookup_descriptor_id(desc_lookup_id),
        .lookup_rsp_valid(desc_rsp_valid), .lookup_rsp_ready(desc_rsp_ready),
        .lookup_rsp_error(desc_rsp_error),
        .lookup_rsp_error_code(desc_rsp_error_code),
        .lookup_descriptor(desc_value), .descriptor_flags(desc_flags),
        .descriptor_source_a(desc_source_a),
        .descriptor_source_b(desc_source_b),
        .descriptor_destination(desc_destination),
        .descriptor_word_count(desc_word_count),
        .descriptor_last_bytes(desc_last_bytes),
        .descriptor_address_mode(desc_address_mode),
        .descriptor_format_version(desc_format_version),
        .descriptor_reserved(desc_reserved), .image_locked(),
        .descriptor_capacity(), .configured_count(), .accepted_loads(),
        .rejected_loads(), .host_writes_busy(), .lookup_requests(),
        .lookup_errors()
    );

    micro_hbs_address_binding_store #(.BINDING_COUNT(BINDING_COUNT))
        binding_store (
        .clk, .rst_n, .engine_busy(busy), .cfg_valid(binding_cfg_valid),
        .cfg_ready(binding_cfg_ready), .cfg_binding_id(binding_cfg_id),
        .cfg_format_version(binding_cfg_format_version),
        .cfg_binding(binding_cfg_data), .cfg_error(binding_cfg_error),
        .cfg_error_code(binding_cfg_error_code),
        .lookup_valid(bind_lookup_valid), .lookup_ready(bind_lookup_ready),
        .lookup_binding_id(bind_lookup_id),
        .lookup_rsp_valid(bind_rsp_valid), .lookup_rsp_ready(bind_rsp_ready),
        .lookup_rsp_error(bind_rsp_error),
        .lookup_rsp_error_code(bind_rsp_error_code),
        .lookup_binding(bind_value), .binding_operand(bind_operand),
        .binding_use_base_reg(bind_use_base_reg),
        .binding_base_reg(bind_base_reg),
        .binding_use_index_reg(bind_use_index_reg),
        .binding_index_reg(bind_index_reg),
        .binding_base_scale_words(bind_base_scale_words),
        .binding_index_stride_words(bind_index_stride_words),
        .image_locked(), .binding_capacity(), .configured_count(),
        .accepted_loads(), .rejected_loads(), .host_writes_busy(),
        .lookup_requests(), .lookup_errors()
    );

    micro_hbs_data_engine #(
        .SCRATCH_WORDS(SCRATCH_WORDS), .ADDRESS_WIDTH(16),
        .EMIT_DESCRIPTOR_BASE(16'd1)
    ) data_engine (
        .clk, .rst_n, .cmd_valid(data_req_valid), .cmd_ready(data_req_ready),
        .cmd_opcode(data_req_opcode), .cmd_flags(data_req_flags),
        .cmd_rd(data_req_rd), .cmd_rs(data_req_rs), .cmd_imm(data_req_imm),
        .cmd_rs_value(data_req_rs_value), .cmd_registers(register_snapshot),
        .rsp_valid(data_rsp_valid), .rsp_error(data_rsp_error),
        .rsp_error_code(data_rsp_error_code),
        .rsp_reg_write(data_rsp_reg_write),
        .rsp_reg_index(data_rsp_reg_index), .rsp_reg_value(data_rsp_reg_value),
        .descriptor_lookup_valid(desc_lookup_valid),
        .descriptor_lookup_ready(desc_lookup_ready),
        .descriptor_lookup_id(desc_lookup_id),
        .descriptor_rsp_valid(desc_rsp_valid),
        .descriptor_rsp_ready(desc_rsp_ready),
        .descriptor_rsp_error(desc_rsp_error),
        .descriptor_rsp_error_code(desc_rsp_error_code),
        .descriptor_flags(desc_flags), .descriptor_source_a(desc_source_a),
        .descriptor_source_b(desc_source_b),
        .descriptor_destination(desc_destination),
        .descriptor_word_count(desc_word_count),
        .descriptor_last_bytes(desc_last_bytes),
        .descriptor_address_mode(desc_address_mode),
        .descriptor_format_version(desc_format_version),
        .descriptor_reserved(desc_reserved),
        .binding_lookup_valid(bind_lookup_valid),
        .binding_lookup_ready(bind_lookup_ready),
        .binding_lookup_id(bind_lookup_id), .binding_rsp_valid(bind_rsp_valid),
        .binding_rsp_ready(bind_rsp_ready), .binding_rsp_error(bind_rsp_error),
        .binding_rsp_error_code(bind_rsp_error_code),
        .binding_operand(bind_operand),
        .binding_use_base_reg(bind_use_base_reg),
        .binding_base_reg(bind_base_reg),
        .binding_use_index_reg(bind_use_index_reg),
        .binding_index_reg(bind_index_reg),
        .binding_base_scale_words(bind_base_scale_words),
        .binding_index_stride_words(bind_index_stride_words),
        .data_scratch_request_valid(data_sp_req_valid),
        .data_scratch_request_ready(data_sp_req_ready),
        .data_scratch_request_write(data_sp_req_write),
        .data_scratch_request_address(data_sp_req_address),
        .data_scratch_request_write_data(data_sp_req_write_data),
        .data_scratch_response_valid(data_sp_rsp_valid),
        .data_scratch_response_data(data_sp_rsp_data),
        .data_scratch_response_error(data_sp_rsp_error),
        .emit_scratch_request_valid(emit_sp_req_valid),
        .emit_scratch_request_ready(emit_sp_req_ready),
        .emit_scratch_request_write(emit_sp_req_write),
        .emit_scratch_request_address(emit_sp_req_address),
        .emit_scratch_request_write_data(emit_sp_req_write_data),
        .emit_scratch_response_valid(emit_sp_rsp_valid),
        .emit_scratch_response_ready(emit_sp_rsp_ready),
        .emit_scratch_response_data(emit_sp_rsp_data),
        .emit_scratch_response_error(emit_sp_rsp_error),
        .out_valid, .out_ready, .out_data, .out_keep, .out_last,
        .accepted_commands(), .completed_commands(), .error_commands()
    );

    micro_hbs_tree_push_adapter #(
        .TREE_HEIGHT(TREE_HEIGHT), .NODE_BYTES(32),
        .SCRATCH_WORDS(SCRATCH_WORDS)
    ) tree_adapter (
        .clk, .rst_n, .cancel(1'b0),
        .cmd_valid(tree_req_valid), .cmd_ready(tree_req_ready),
        .cmd_descriptor_id(tree_req_imm[15:0]),
        .cmd_layout_id(tree_req_imm[15:0]), .cmd_node_source(8'h00),
        .cmd_node_base_word(tree_node_base_word), .cmd_node_index(16'b0),
        .cmd_leaf_index(tree_req_rs_value[15:0]),
        .cmd_tree_start(tree_req_rs_value == 0),
        .cmd_target_leaf(target_leaf_latched),
        .rsp_valid(tree_raw_rsp_valid), .rsp_error(tree_raw_rsp_error),
        .rsp_error_code(tree_raw_rsp_error_code), .rsp_descriptor_id(),
        .rsp_layout_id(), .sp_req_valid(adapter_tree_sp_req_valid),
        .sp_req_ready(adapter_tree_sp_req_ready),
        .sp_req_write(adapter_tree_sp_req_write),
        .sp_req_address(adapter_tree_sp_req_address),
        .sp_req_write_data(adapter_tree_sp_req_write_data),
        .sp_rsp_valid(adapter_tree_sp_rsp_valid),
        .sp_rsp_read_data(adapter_tree_sp_rsp_data),
        .sp_rsp_error(adapter_tree_sp_rsp_error),
        .sp_rsp_error_code(16'h0402),
        .parent_req_valid, .parent_req_ready, .parent_req_height,
        .parent_req_start_leaf, .parent_req_left, .parent_req_right,
        .parent_rsp_valid, .parent_rsp_value, .parent_rsp_error,
        .auth_valid, .auth_level, .auth_node, .root_valid, .root,
        .busy(), .poisoned(), .accepted_leaves, .parent_hashes,
        .peak_stack_nodes()
    );

    micro_hbs_xmss_tree_parent_context #(.UNROLL(UNROLL)) parent_context (
        .clk, .rst_n, .public_seed(public_seed_latched),
        .address_template(address_template_latched),
        .req_valid(parent_req_valid), .req_ready(parent_req_ready),
        .req_parent_height(parent_req_height),
        .req_start_leaf(parent_req_start_leaf),
        .req_left_node(parent_req_left), .req_right_node(parent_req_right),
        .rsp_valid(parent_rsp_valid), .rsp_parent(parent_rsp_value),
        .rsp_error(parent_rsp_error)
    );

    micro_hbs_scratch_arbiter #(.ADDRESS_WIDTH(16)) scratch_arbiter (
        .clk, .rst_n, .alu_request_valid(alu_req_valid),
        .alu_request_ready(alu_req_ready), .alu_request_write(alu_req_write),
        .alu_request_address(alu_req_address),
        .alu_request_write_data(alu_req_write_data),
        .alu_response_valid(alu_rsp_valid), .alu_response_ready(1'b1),
        .alu_response_read_data(alu_rsp_data),
        .alu_response_error(alu_rsp_error),
        .emit_request_valid(emit_sp_req_valid),
        .emit_request_ready(emit_sp_req_ready),
        .emit_request_write(emit_sp_req_write),
        .emit_request_address(emit_sp_req_address),
        .emit_request_write_data(emit_sp_req_write_data),
        .emit_response_valid(emit_sp_rsp_valid),
        .emit_response_ready(emit_sp_rsp_ready),
        .emit_response_read_data(emit_sp_rsp_data),
        .emit_response_error(emit_sp_rsp_error),
        .tree_request_valid(tree_sp_req_valid),
        .tree_request_ready(tree_sp_req_ready),
        .tree_request_write(tree_sp_req_write),
        .tree_request_address(tree_sp_req_address),
        .tree_request_write_data(tree_sp_req_write_data),
        .tree_response_valid(tree_sp_rsp_valid),
        .tree_response_ready(1'b1),
        .tree_response_read_data(tree_sp_rsp_data),
        .tree_response_error(tree_sp_rsp_error),
        .scratch_request_valid(arb_sp_req_valid),
        .scratch_request_ready(arb_sp_req_ready),
        .scratch_request_write(arb_sp_req_write),
        .scratch_request_address(arb_sp_req_address),
        .scratch_request_write_data(arb_sp_req_write_data),
        .scratch_response_valid(sp_rsp_valid),
        .scratch_response_read_data(sp_rsp_data),
        .scratch_bounds_error(sp_bounds_error), .busy(arb_busy),
        .outstanding(), .active_owner(), .alu_grants(), .emit_grants(),
        .tree_grants(), .accepted_transactions(scratch_transactions),
        .completed_transactions(), .error_transactions()
    );

    micro_hbs_scratchpad64 #(
        .WORDS(SCRATCH_WORDS), .ADDRESS_WIDTH(16)
    ) scratchpad (
        .clk, .rst_n, .request_valid(sp_req_valid),
        .request_ready(sp_req_ready), .request_write(sp_req_write),
        .request_address(sp_req_address), .request_write_data(sp_req_write_data),
        .response_valid(sp_rsp_valid), .response_read_data(sp_rsp_data),
        .bounds_error(sp_bounds_error), .scrub_start(1'b0),
        .scrub_busy(), .scrub_done()
    );
endmodule

`default_nettype wire
