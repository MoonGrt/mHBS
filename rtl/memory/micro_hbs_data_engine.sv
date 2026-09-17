`timescale 1ns/1ps
`default_nettype none

// Descriptor-driven execution path for DATA_LOAD, DATA_MOVE and OUTPUT.
// Commands originate only from the Microsequencer.  Descriptor lookup and
// address generation are serialized deliberately: this is a deterministic
// single-Job engine, not a task runtime or descriptor scheduler.
//
// address_mode bits:
//   [0] add R[rs] as a word index to source_a
//   [1] add R[rs] as a word index to source_b
//   [2] add R[rs] as a word index to destination
//   [3] DATA_LOAD selects bits [63:32] instead of [31:0]
//
// For OUTPUT, EMIT_DESCRIPTOR_BASE + imm[31:16] selects the descriptor and the
// effective source base is
// descriptor.source_a + rd + imm[15:0] + (flags[0] ? R[rs] : 0).  Therefore
// existing direct rd+imm object selection remains expressible while the
// static descriptor supplies the physical base, length and final-byte mask.
module micro_hbs_data_engine #(
    parameter integer SCRATCH_WORDS = 512,
    parameter integer ADDRESS_WIDTH = 16,
    parameter logic [15:0] EMIT_DESCRIPTOR_BASE = 16'h0000,
    parameter integer EMIT_INSTRUCTION_STRIDE_WORDS = 1,
    parameter bit SCRATCH_WRITE_ACK = 1'b1
) (
    input  wire                         clk,
    input  wire                         rst_n,

    input  wire                         cmd_valid,
    output wire                         cmd_ready,
    input  wire [7:0]                   cmd_opcode,
    input  wire [7:0]                   cmd_flags,
    input  wire [7:0]                   cmd_rd,
    input  wire [7:0]                   cmd_rs,
    input  wire [31:0]                  cmd_imm,
    input  wire [31:0]                  cmd_rs_value,
    input  wire [255:0]                 cmd_registers,

    output logic                        rsp_valid,
    output logic                        rsp_error,
    output logic [15:0]                 rsp_error_code,
    output logic                        rsp_reg_write,
    output logic [7:0]                  rsp_reg_index,
    output logic [31:0]                 rsp_reg_value,

    output wire                         descriptor_lookup_valid,
    input  wire                         descriptor_lookup_ready,
    output wire [15:0]                  descriptor_lookup_id,
    input  wire                         descriptor_rsp_valid,
    output wire                         descriptor_rsp_ready,
    input  wire                         descriptor_rsp_error,
    input  wire [15:0]                  descriptor_rsp_error_code,
    input  wire [15:0]                  descriptor_flags,
    input  wire [15:0]                  descriptor_source_a,
    input  wire [15:0]                  descriptor_source_b,
    input  wire [15:0]                  descriptor_destination,
    input  wire [15:0]                  descriptor_word_count,
    input  wire [3:0]                   descriptor_last_bytes,
    input  wire [3:0]                   descriptor_address_mode,
    input  wire [7:0]                   descriptor_format_version,
    input  wire [31:0]                  descriptor_reserved,

    output wire                         binding_lookup_valid,
    input  wire                         binding_lookup_ready,
    output wire [15:0]                  binding_lookup_id,
    input  wire                         binding_rsp_valid,
    output wire                         binding_rsp_ready,
    input  wire                         binding_rsp_error,
    input  wire [15:0]                  binding_rsp_error_code,
    input  wire [1:0]                   binding_operand,
    input  wire                         binding_use_base_reg,
    input  wire [2:0]                   binding_base_reg,
    input  wire                         binding_use_index_reg,
    input  wire [2:0]                   binding_index_reg,
    input  wire [15:0]                  binding_base_scale_words,
    input  wire [15:0]                  binding_index_stride_words,

    output wire                         data_scratch_request_valid,
    input  wire                         data_scratch_request_ready,
    output wire                         data_scratch_request_write,
    output wire [ADDRESS_WIDTH-1:0]     data_scratch_request_address,
    output wire [63:0]                  data_scratch_request_write_data,
    input  wire                         data_scratch_response_valid,
    input  wire [63:0]                  data_scratch_response_data,
    input  wire                         data_scratch_response_error,

    output wire                         emit_scratch_request_valid,
    input  wire                         emit_scratch_request_ready,
    output wire                         emit_scratch_request_write,
    output wire [ADDRESS_WIDTH-1:0]     emit_scratch_request_address,
    output wire [63:0]                  emit_scratch_request_write_data,
    input  wire                         emit_scratch_response_valid,
    output wire                         emit_scratch_response_ready,
    input  wire [63:0]                  emit_scratch_response_data,
    input  wire                         emit_scratch_response_error,

    output wire                         out_valid,
    input  wire                         out_ready,
    output wire [63:0]                  out_data,
    output wire [7:0]                   out_keep,
    output wire                         out_last,

    output logic [31:0]                 accepted_commands,
    output logic [31:0]                 completed_commands,
    output logic [31:0]                 error_commands
);
    localparam logic [7:0] OP_DATA_LOAD  = 8'h08;
    localparam logic [7:0] OP_DATA_MOVE = 8'h09;
    localparam logic [7:0] OP_OUTPUT  = 8'h0c;

    localparam logic [15:0] ERR_OPCODE       = 16'h0701;
    localparam logic [15:0] ERR_DESCRIPTOR   = 16'h0702;
    localparam logic [15:0] ERR_DESCRIPTOR_OP= 16'h0703;
    localparam logic [15:0] ERR_DESCRIPTOR_FMT=16'h0704;
    localparam logic [15:0] ERR_BINDING       =16'h0705;

    typedef enum logic [3:0] {
        S_IDLE, S_LOOKUP_REQUEST, S_LOOKUP_RESPONSE, S_ADDRESS_PREP,
        S_BIND_LOOKUP_REQUEST, S_BIND_LOOKUP_RESPONSE,
        S_AGU_REQUEST, S_AGU_RESPONSE, S_EXECUTE_START,
        S_EXECUTE_WAIT, S_COMMAND_RESPONSE
    } state_t;
    state_t state;

    typedef enum logic [1:0] {
        A_SOURCE_A = 2'd0,
        A_DESTINATION = 2'd2
    } addr_t;
    addr_t address_phase;

    logic [7:0] opcode_latched;
    logic [7:0] flags_latched;
    logic [7:0] rd_latched;
    logic [31:0] imm_latched;
    logic [31:0] rs_value_latched;
    logic [255:0] registers_latched;
    logic [15:0] flags_desc;
    logic [15:0] source_a_desc, destination_desc;
    logic [15:0] word_count_desc;
    logic [3:0] last_bytes_desc, address_mode_desc;
    logic [7:0] format_version_desc;
    logic [15:0] binding_base_desc;
    logic [3:0] binding_count_desc;
    logic [3:0] binding_offset;
    logic binding_use_base_latched, binding_use_index_latched;
    logic [2:0] binding_base_reg_latched, binding_index_reg_latched;
    logic [15:0] binding_base_scale_latched;
    logic [15:0] binding_index_stride_latched;
    logic [ADDRESS_WIDTH-1:0] source_a_address;
    logic [ADDRESS_WIDTH-1:0] destination_address;

    wire agu_req_ready, agu_rsp_valid, agu_rsp_error;
    wire [15:0] agu_rsp_error_code;
    wire [ADDRESS_WIDTH-1:0] agu_rsp_address, agu_rsp_last_address;
    logic [31:0] agu_base;
    logic agu_use_term0, agu_use_term1;
    logic [31:0] agu_term0_value, agu_term1_value;
    logic [15:0] agu_term0_scale, agu_term1_scale;
    logic [15:0] agu_span;

    wire load_cmd_ready, load_rsp_valid, load_rsp_error, load_rsp_reg_write;
    wire [15:0] load_rsp_error_code;
    wire [7:0] load_rsp_reg_index;
    wire [31:0] load_rsp_reg_value;
    wire load_sp_req_valid;
    wire [ADDRESS_WIDTH-1:0] load_sp_req_address;

    wire alu_cmd_ready, alu_rsp_valid, alu_rsp_error;
    wire [15:0] alu_rsp_error_code;
    wire alu_sp_req_valid, alu_sp_req_write;
    wire [ADDRESS_WIDTH-1:0] alu_sp_req_address;
    wire [63:0] alu_sp_req_write_data;

    wire emit_cmd_ready, emit_busy, emit_done, emit_error;
    wire [15:0] emit_error_code;
    wire emit_sp_req_valid;
    wire [ADDRESS_WIDTH-1:0] emit_sp_req_address;

    wire exec_start = (state == S_EXECUTE_START);
    wire load_active = (opcode_latched == OP_DATA_LOAD);
    wire alu_active = (opcode_latched == OP_DATA_MOVE);
    wire emit_active = (opcode_latched == OP_OUTPUT);

    assign cmd_ready = (state == S_IDLE);
    assign descriptor_lookup_valid = (state == S_LOOKUP_REQUEST);
    assign descriptor_lookup_id = (opcode_latched == OP_OUTPUT)
        ? (EMIT_DESCRIPTOR_BASE + imm_latched[31:16])
        : imm_latched[15:0];
    assign descriptor_rsp_ready = (state == S_LOOKUP_RESPONSE);
    assign binding_lookup_valid = (state == S_BIND_LOOKUP_REQUEST);
    assign binding_lookup_id = binding_base_desc + binding_offset;
    assign binding_rsp_ready = (state == S_BIND_LOOKUP_RESPONSE);

    always_comb begin
        agu_base = 32'b0;
        agu_use_term0 = 1'b0;
        agu_term0_value = 32'b0;
        agu_term0_scale = 16'b0;
        agu_use_term1 = 1'b0;
        agu_term1_value = 32'b0;
        agu_term1_scale = 16'b0;
        agu_span = word_count_desc;
        case (address_phase)
            A_SOURCE_A: begin
                if (opcode_latched == OP_OUTPUT) begin
                    agu_base = {16'b0, source_a_desc}
                        + (({24'b0, rd_latched}
                            + {16'b0, imm_latched[15:0]}
                            + (flags_latched[0]
                               ? rs_value_latched : 32'b0))
                           * EMIT_INSTRUCTION_STRIDE_WORDS);
                end else begin
                    agu_base = {16'b0, source_a_desc};
                    if (opcode_latched == OP_DATA_LOAD)
                        agu_span = 16'd1;
                end
            end
            default: begin
                agu_base = {16'b0, destination_desc};
            end
        endcase

        if (format_version_desc == 8'h01) begin
            if (address_mode_desc[address_phase]) begin
                agu_use_term1 = 1'b1;
                agu_term1_value = rs_value_latched;
                agu_term1_scale = 16'd1;
            end
        end else begin
            agu_use_term0 = binding_use_base_latched;
            agu_term0_value = registers_latched[
                32*binding_base_reg_latched +: 32];
            agu_term0_scale = binding_base_scale_latched;
            agu_use_term1 = binding_use_index_latched;
            agu_term1_value = registers_latched[
                32*binding_index_reg_latched +: 32];
            agu_term1_scale = binding_index_stride_latched;
        end
    end

    micro_hbs_affine_agu #(
        .SCRATCH_WORDS(SCRATCH_WORDS), .ADDRESS_WIDTH(ADDRESS_WIDTH)
    ) agu (
        .clk, .rst_n, .req_valid(state == S_AGU_REQUEST),
        .req_ready(agu_req_ready), .req_base(agu_base),
        .req_use_term0(agu_use_term0), .req_term0_value(agu_term0_value),
        .req_term0_scale(agu_term0_scale),
        .req_use_term1(agu_use_term1), .req_term1_value(agu_term1_value),
        .req_term1_scale(agu_term1_scale), .req_span_words(agu_span),
        .rsp_valid(agu_rsp_valid), .rsp_ready(state == S_AGU_RESPONSE),
        .rsp_error(agu_rsp_error), .rsp_error_code(agu_rsp_error_code),
        .rsp_address(agu_rsp_address),
        .rsp_last_address(agu_rsp_last_address),
        .accepted_requests(), .completed_responses(), .error_responses()
    );

    micro_hbs_scratch_load #(
        .SCRATCH_WORDS(SCRATCH_WORDS), .ADDRESS_WIDTH(ADDRESS_WIDTH)
    ) load_engine (
        .clk, .rst_n, .cmd_valid(exec_start && load_active),
        .cmd_ready(load_cmd_ready), .cmd_source_address(source_a_address),
        .cmd_destination_reg(rd_latched),
        .cmd_high_word(address_mode_desc[3]), .rsp_valid(load_rsp_valid),
        .rsp_ready(state == S_EXECUTE_WAIT && load_active),
        .rsp_error(load_rsp_error), .rsp_error_code(load_rsp_error_code),
        .rsp_reg_write(load_rsp_reg_write),
        .rsp_reg_index(load_rsp_reg_index),
        .rsp_reg_value(load_rsp_reg_value),
        .scratch_request_valid(load_sp_req_valid),
        .scratch_request_ready(data_scratch_request_ready && load_active),
        .scratch_request_address(load_sp_req_address),
        .scratch_response_valid(data_scratch_response_valid && load_active),
        .scratch_response_data(data_scratch_response_data),
        .scratch_response_error(data_scratch_response_error && load_active),
        .accepted_commands(), .completed_responses(), .error_responses()
    );

    micro_hbs_scratch_alu #(
        .WORDS(SCRATCH_WORDS), .ADDRESS_WIDTH(ADDRESS_WIDTH),
        .WRITE_ACK(SCRATCH_WRITE_ACK)
    ) scratch_alu (
        .clk, .rst_n, .cmd_valid(exec_start && alu_active),
        .cmd_ready(alu_cmd_ready), .cmd_source_a(source_a_address),
        .cmd_destination(destination_address),
        .cmd_word_count(word_count_desc), .rsp_valid(alu_rsp_valid),
        .rsp_ready(state == S_EXECUTE_WAIT && alu_active),
        .rsp_error(alu_rsp_error), .rsp_error_code(alu_rsp_error_code),
        .scratch_request_valid(alu_sp_req_valid),
        .scratch_request_ready(data_scratch_request_ready && alu_active),
        .scratch_request_write(alu_sp_req_write),
        .scratch_request_address(alu_sp_req_address),
        .scratch_request_write_data(alu_sp_req_write_data),
        .scratch_response_valid(data_scratch_response_valid && alu_active),
        .scratch_response_read_data(data_scratch_response_data),
        .scratch_bounds_error(data_scratch_response_error && alu_active),
        .accepted_commands(), .completed_responses(), .error_responses(),
        .scratch_reads(), .scratch_writes()
    );

    micro_hbs_output_stream #(
        .SCRATCH_WORDS(SCRATCH_WORDS), .ADDRESS_WIDTH(ADDRESS_WIDTH)
    ) emit_engine (
        .clk, .rst_n, .emit_valid(exec_start && emit_active),
        .emit_ready(emit_cmd_ready), .emit_base_slot(source_a_address),
        .emit_use_index(1'b0), .emit_index_value(32'b0),
        .emit_length_words(word_count_desc),
        .emit_last_bytes(last_bytes_desc),
        .scratch_read_valid(emit_sp_req_valid),
        .scratch_read_ready(emit_scratch_request_ready),
        .scratch_read_address(emit_sp_req_address),
        .scratch_response_valid(emit_scratch_response_valid),
        .scratch_response_ready(emit_scratch_response_ready),
        .scratch_response_data(emit_scratch_response_data),
        .scratch_response_error(emit_scratch_response_error),
        .out_valid, .out_ready, .out_data, .out_keep, .out_last,
        .busy(emit_busy), .done(emit_done), .error(emit_error),
        .error_code(emit_error_code)
    );

    assign data_scratch_request_valid = load_active
        ? load_sp_req_valid : (alu_active ? alu_sp_req_valid : 1'b0);
    assign data_scratch_request_write = alu_active ? alu_sp_req_write : 1'b0;
    assign data_scratch_request_address = load_active
        ? load_sp_req_address : alu_sp_req_address;
    assign data_scratch_request_write_data = alu_active
        ? alu_sp_req_write_data : 64'b0;

    assign emit_scratch_request_valid = emit_sp_req_valid;
    assign emit_scratch_request_write = 1'b0;
    assign emit_scratch_request_address = emit_sp_req_address;
    assign emit_scratch_request_write_data = 64'b0;

    task automatic fail_command(input logic [15:0] code);
        begin
            rsp_valid <= 1'b1;
            rsp_error <= 1'b1;
            rsp_error_code <= code;
            rsp_reg_write <= 1'b0;
            error_commands <= error_commands + 1'b1;
            state <= S_COMMAND_RESPONSE;
        end
    endtask

    function automatic logic descriptor_matches(input logic [7:0] op,
                                                  input logic [15:0] f);
        begin
            case (op)
                OP_DATA_LOAD:  descriptor_matches = (f[3:0] == 4'b0001);
                OP_DATA_MOVE: descriptor_matches = (f[3:0] == 4'b0010);
                OP_OUTPUT:  descriptor_matches = (f[3:0] == 4'b1000);
                default:  descriptor_matches = 1'b0;
            endcase
        end
    endfunction

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= S_IDLE;
            address_phase <= A_SOURCE_A;
            opcode_latched <= '0;
            flags_latched <= '0;
            rd_latched <= '0;
            imm_latched <= '0;
            rs_value_latched <= '0;
            registers_latched <= '0;
            flags_desc <= '0;
            source_a_desc <= '0;
            destination_desc <= '0;
            word_count_desc <= '0;
            last_bytes_desc <= '0;
            address_mode_desc <= '0;
            format_version_desc <= '0;
            binding_base_desc <= '0;
            binding_count_desc <= '0;
            binding_offset <= '0;
            binding_use_base_latched <= 1'b0;
            binding_use_index_latched <= 1'b0;
            binding_base_reg_latched <= '0;
            binding_index_reg_latched <= '0;
            binding_base_scale_latched <= '0;
            binding_index_stride_latched <= '0;
            source_a_address <= '0;
            destination_address <= '0;
            rsp_valid <= 1'b0;
            rsp_error <= 1'b0;
            rsp_error_code <= '0;
            rsp_reg_write <= 1'b0;
            rsp_reg_index <= '0;
            rsp_reg_value <= '0;
            accepted_commands <= '0;
            completed_commands <= '0;
            error_commands <= '0;
        end else begin
            rsp_valid <= 1'b0;
            case (state)
                S_IDLE: begin
                    if (cmd_valid) begin
                        accepted_commands <= accepted_commands + 1'b1;
                        opcode_latched <= cmd_opcode;
                        flags_latched <= cmd_flags;
                        rd_latched <= cmd_rd;
                        imm_latched <= cmd_imm;
                        rs_value_latched <= cmd_rs_value;
                        registers_latched <= cmd_registers;
                        rsp_error <= 1'b0;
                        rsp_error_code <= '0;
                        rsp_reg_write <= 1'b0;
                        rsp_reg_index <= '0;
                        rsp_reg_value <= '0;
                        if (cmd_opcode != OP_DATA_LOAD && cmd_opcode != OP_DATA_MOVE
                            && cmd_opcode != OP_OUTPUT)
                            fail_command(ERR_OPCODE);
                        else if (cmd_opcode != OP_OUTPUT
                                 && cmd_imm[31:16] != 0)
                            fail_command(ERR_DESCRIPTOR);
                        else
                            state <= S_LOOKUP_REQUEST;
                    end
                end

                S_LOOKUP_REQUEST: begin
                    if (descriptor_lookup_ready)
                        state <= S_LOOKUP_RESPONSE;
                end

                S_LOOKUP_RESPONSE: begin
                    if (descriptor_rsp_valid) begin
                        if (descriptor_rsp_error)
                            fail_command(descriptor_rsp_error_code);
                        else if (descriptor_flags[15:4] != 0
                                 || !descriptor_matches(opcode_latched,
                                                        descriptor_flags))
                            fail_command(ERR_DESCRIPTOR_OP);
                        else if ((descriptor_format_version != 8'h01
                                  && descriptor_format_version != 8'h02)
                                 || (descriptor_format_version == 8'h01
                                     && descriptor_reserved != 0)
                                 || (descriptor_format_version == 8'h02
                                     && descriptor_reserved[11:0] != 0)
                                 || descriptor_word_count == 0
                                 || (opcode_latched == OP_DATA_LOAD
                                     && descriptor_word_count != 1)
                                 || (opcode_latched == OP_OUTPUT
                                     && (descriptor_last_bytes == 0
                                         || descriptor_last_bytes > 8))
                                 || (opcode_latched != OP_DATA_LOAD
                                     && descriptor_address_mode[3]))
                            fail_command(ERR_DESCRIPTOR_FMT);
                        else begin
                            flags_desc <= descriptor_flags;
                            source_a_desc <= descriptor_source_a;
                            destination_desc <= descriptor_destination;
                            word_count_desc <= descriptor_word_count;
                            last_bytes_desc <= descriptor_last_bytes;
                            address_mode_desc <= descriptor_address_mode;
                            format_version_desc <= descriptor_format_version;
                            binding_base_desc <= descriptor_reserved[31:16];
                            binding_count_desc <= descriptor_reserved[15:12];
                            binding_offset <= '0;
                            binding_use_base_latched <= 1'b0;
                            binding_use_index_latched <= 1'b0;
                            binding_base_reg_latched <= '0;
                            binding_index_reg_latched <= '0;
                            binding_base_scale_latched <= '0;
                            binding_index_stride_latched <= '0;
                            address_phase <= A_SOURCE_A;
                            state <= S_ADDRESS_PREP;
                        end
                    end
                end

                S_ADDRESS_PREP: begin
                    binding_offset <= '0;
                    binding_use_base_latched <= 1'b0;
                    binding_use_index_latched <= 1'b0;
                    binding_base_reg_latched <= '0;
                    binding_index_reg_latched <= '0;
                    binding_base_scale_latched <= '0;
                    binding_index_stride_latched <= '0;
                    if (format_version_desc == 8'h02
                        && address_mode_desc[address_phase]) begin
                        if (binding_count_desc == 0)
                            fail_command(ERR_BINDING);
                        else
                            state <= S_BIND_LOOKUP_REQUEST;
                    end else
                        state <= S_AGU_REQUEST;
                end

                S_BIND_LOOKUP_REQUEST: begin
                    if (binding_lookup_ready)
                        state <= S_BIND_LOOKUP_RESPONSE;
                end

                S_BIND_LOOKUP_RESPONSE: begin
                    if (binding_rsp_valid) begin
                        if (binding_rsp_error)
                            fail_command(binding_rsp_error_code);
                        else if (binding_operand == address_phase) begin
                            if ((!binding_use_base_reg
                                 && !binding_use_index_reg)
                                || (binding_use_base_reg
                                    && binding_base_scale_words == 0)
                                || (binding_use_index_reg
                                    && binding_index_stride_words == 0))
                                fail_command(ERR_BINDING);
                            else begin
                                binding_use_base_latched
                                    <= binding_use_base_reg;
                                binding_use_index_latched
                                    <= binding_use_index_reg;
                                binding_base_reg_latched <= binding_base_reg;
                                binding_index_reg_latched <= binding_index_reg;
                                binding_base_scale_latched
                                    <= binding_base_scale_words;
                                binding_index_stride_latched
                                    <= binding_index_stride_words;
                                state <= S_AGU_REQUEST;
                            end
                        end else if (binding_offset + 1
                                     < binding_count_desc) begin
                            binding_offset <= binding_offset + 1'b1;
                            state <= S_BIND_LOOKUP_REQUEST;
                        end else
                            fail_command(ERR_BINDING);
                    end
                end

                S_AGU_REQUEST: begin
                    if (agu_req_ready)
                        state <= S_AGU_RESPONSE;
                end

                S_AGU_RESPONSE: begin
                    if (agu_rsp_valid) begin
                        if (agu_rsp_error)
                            fail_command(agu_rsp_error_code);
                        else begin
                            case (address_phase)
                                A_SOURCE_A: begin
                                    source_a_address <= agu_rsp_address;
                                    if (opcode_latched == OP_DATA_MOVE) begin
                                        address_phase <= A_DESTINATION;
                                        state <= S_ADDRESS_PREP;
                                    end else
                                        state <= S_EXECUTE_START;
                                end
                                default: begin
                                    destination_address <= agu_rsp_address;
                                    state <= S_EXECUTE_START;
                                end
                            endcase
                        end
                    end
                end

                S_EXECUTE_START: begin
                    if ((load_active && load_cmd_ready)
                        || (alu_active && alu_cmd_ready)
                        || (emit_active && emit_cmd_ready))
                        state <= S_EXECUTE_WAIT;
                end

                S_EXECUTE_WAIT: begin
                    if (load_active && load_rsp_valid) begin
                        rsp_valid <= 1'b1;
                        rsp_error <= load_rsp_error;
                        rsp_error_code <= load_rsp_error_code;
                        rsp_reg_write <= load_rsp_reg_write;
                        rsp_reg_index <= load_rsp_reg_index;
                        rsp_reg_value <= load_rsp_reg_value;
                        if (load_rsp_error)
                            error_commands <= error_commands + 1'b1;
                        state <= S_COMMAND_RESPONSE;
                    end else if (alu_active && alu_rsp_valid) begin
                        rsp_valid <= 1'b1;
                        rsp_error <= alu_rsp_error;
                        rsp_error_code <= alu_rsp_error_code;
                        rsp_reg_write <= 1'b0;
                        if (alu_rsp_error)
                            error_commands <= error_commands + 1'b1;
                        state <= S_COMMAND_RESPONSE;
                    end else if (emit_active && emit_error) begin
                        fail_command(emit_error_code);
                    end else if (emit_active && emit_done) begin
                        rsp_valid <= 1'b1;
                        rsp_error <= 1'b0;
                        rsp_error_code <= '0;
                        rsp_reg_write <= 1'b0;
                        state <= S_COMMAND_RESPONSE;
                    end
                end

                S_COMMAND_RESPONSE: begin
                    // The sequencer has no response-ready signal and consumes
                    // the single-cycle pulse while it is in DATA_WAIT.
                    completed_commands <= completed_commands + 1'b1;
                    rsp_error <= 1'b0;
                    rsp_error_code <= '0;
                    rsp_reg_write <= 1'b0;
                    state <= S_IDLE;
                end

                default: fail_command(ERR_OPCODE);
            endcase
        end
    end
endmodule

`default_nettype wire
