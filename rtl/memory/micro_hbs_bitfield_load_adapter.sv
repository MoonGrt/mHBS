`timescale 1ns/1ps
`default_nettype none

// Static descriptor adapter for generic bit-field LOAD operations.
//
// Descriptor format (128 bits):
// [127:120] version=1, [119:112] capability=1
// [111:96] source word, [95:80] input bytes, [79:64] base bit offset
// [63:56] index stride in bits, [55:53] index register, [52] use index
// [51:45] field width, [44] destination is register, [43:41] dest register
// [40:25] destination word, [24:20] output bytes, [19:0] reserved.
module micro_hbs_bitfield_load_adapter #(
    parameter integer DESCRIPTOR_COUNT = 16,
    parameter integer SCRATCH_WORDS = 1024,
    parameter integer ADDRESS_WIDTH = 16
) (
    input  wire                         clk,
    input  wire                         rst_n,
    input  wire                         engine_busy,
    input  wire                         cfg_valid,
    output wire                         cfg_ready,
    input  wire [15:0]                  cfg_descriptor_id,
    input  wire [127:0]                 cfg_descriptor,
    output logic                        cfg_error,
    output logic [15:0]                 cfg_error_code,

    input  wire                         cmd_valid,
    output wire                         cmd_ready,
    input  wire [7:0]                   cmd_opcode,
    input  wire [31:0]                  cmd_imm,
    input  wire [255:0]                 cmd_registers,
    output wire                         cmd_match,
    output wire                         rsp_valid,
    input  wire                         rsp_ready,
    output wire                         rsp_error,
    output wire [15:0]                  rsp_error_code,
    output wire                         rsp_reg_write,
    output wire [7:0]                   rsp_reg_index,
    output wire [31:0]                  rsp_reg_value,

    output wire                         scratch_request_valid,
    input  wire                         scratch_request_ready,
    output wire                         scratch_request_write,
    output wire [ADDRESS_WIDTH-1:0]     scratch_request_address,
    output wire [63:0]                  scratch_request_write_data,
    input  wire                         scratch_response_valid,
    input  wire [63:0]                  scratch_response_data,
    input  wire                         scratch_response_error,
    output wire                         busy,
    output logic [31:0]                 accepted_commands
);
    localparam logic [7:0] OP_LOAD = 8'h08;
    localparam logic [15:0] ERR_CFG_BUSY = 16'h0e01;
    localparam logic [15:0] ERR_CFG_ID   = 16'h0e02;
    localparam logic [15:0] ERR_CFG_FMT  = 16'h0e03;
    localparam logic [15:0] ERR_CFG_DUP  = 16'h0e04;
    localparam logic [15:0] ERR_LOOKUP   = 16'h0e05;
    localparam logic [15:0] ERR_OPCODE   = 16'h0e06;
    localparam integer INDEX_WIDTH = DESCRIPTOR_COUNT <= 2
        ? 1 : $clog2(DESCRIPTOR_COUNT);

    typedef enum logic [1:0] {S_IDLE, S_LAUNCH, S_WAIT, S_ERROR} state_t;
    state_t state;
    logic [127:0] descriptors [0:DESCRIPTOR_COUNT-1];
    logic [DESCRIPTOR_COUNT-1:0] configured;
    logic [127:0] active;
    logic error_valid;
    logic [15:0] error_code_latched;

    wire [15:0] d_source = active[111:96];
    wire [15:0] d_input_bytes = active[95:80];
    wire [15:0] d_base_offset = active[79:64];
    wire [7:0] d_stride = active[63:56];
    wire [2:0] d_index_reg = active[55:53];
    wire d_use_index = active[52];
    wire [6:0] d_width = active[51:45];
    wire d_dest_is_reg = active[44];
    wire [2:0] d_dest_reg = active[43:41];
    wire [15:0] d_destination = active[40:25];
    wire [4:0] d_output_bytes = active[24:20];
    wire [31:0] index_value = cmd_registers[32*d_index_reg +: 32];
    (* use_dsp = "no" *) wire [47:0] offset_product
        = index_value * d_stride;
    wire [47:0] offset_calc = d_base_offset
        + (d_use_index ? offset_product : 48'b0);

    wire core_cmd_ready, core_rsp_valid, core_rsp_error, core_rsp_reg_write;
    wire [15:0] core_rsp_error_code;
    wire [7:0] core_rsp_reg_index;
    wire [31:0] core_rsp_reg_value;

    assign cfg_ready = !engine_busy && state == S_IDLE;
    assign cmd_ready = state == S_IDLE;
    assign cmd_match = cmd_opcode == OP_LOAD && cmd_imm < DESCRIPTOR_COUNT
        && configured[cmd_imm[INDEX_WIDTH-1:0]];
    assign busy = state != S_IDLE;
    assign rsp_valid = state == S_ERROR ? error_valid : core_rsp_valid;
    assign rsp_error = state == S_ERROR ? 1'b1 : core_rsp_error;
    assign rsp_error_code = state == S_ERROR
        ? error_code_latched : core_rsp_error_code;
    assign rsp_reg_write = state == S_ERROR ? 1'b0 : core_rsp_reg_write;
    assign rsp_reg_index = core_rsp_reg_index;
    assign rsp_reg_value = core_rsp_reg_value;

    micro_hbs_scratch_bitfield_load #(
        .SCRATCH_WORDS(SCRATCH_WORDS), .ADDRESS_WIDTH(ADDRESS_WIDTH)
    ) core (
        .clk, .rst_n, .cmd_valid(state == S_LAUNCH),
        .cmd_ready(core_cmd_ready), .busy(),
        .cmd_source_address(d_source[ADDRESS_WIDTH-1:0]),
        .cmd_input_bytes(d_input_bytes),
        .cmd_bit_offset(offset_calc[15:0]), .cmd_bit_width(d_width),
        .cmd_destination_is_reg(d_dest_is_reg),
        .cmd_destination_reg({5'b0, d_dest_reg}),
        .cmd_destination_address(d_destination[ADDRESS_WIDTH-1:0]),
        .cmd_output_bytes(d_output_bytes), .rsp_valid(core_rsp_valid),
        .rsp_ready(state == S_WAIT && rsp_ready),
        .rsp_error(core_rsp_error), .rsp_error_code(core_rsp_error_code),
        .rsp_reg_write(core_rsp_reg_write),
        .rsp_reg_index(core_rsp_reg_index),
        .rsp_reg_value(core_rsp_reg_value), .scratch_request_valid,
        .scratch_request_ready, .scratch_request_write,
        .scratch_request_address, .scratch_request_write_data,
        .scratch_response_valid, .scratch_response_data,
        .scratch_response_error, .accepted_commands(), .scratch_reads(),
        .scratch_writes()
    );

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= S_IDLE;
            configured <= '0;
            active <= '0;
            cfg_error <= 1'b0;
            cfg_error_code <= '0;
            error_valid <= 1'b0;
            error_code_latched <= '0;
            accepted_commands <= '0;
        end else begin
            cfg_error <= 1'b0;
            cfg_error_code <= '0;
            if (cfg_valid) begin
                if (!cfg_ready) begin
                    cfg_error <= 1'b1;
                    cfg_error_code <= ERR_CFG_BUSY;
                end else if (cfg_descriptor_id >= DESCRIPTOR_COUNT) begin
                    cfg_error <= 1'b1;
                    cfg_error_code <= ERR_CFG_ID;
                end else if (cfg_descriptor[127:120] != 8'h01
                             || cfg_descriptor[119:112] != 8'h01
                             || cfg_descriptor[19:0] != 0) begin
                    cfg_error <= 1'b1;
                    cfg_error_code <= ERR_CFG_FMT;
                end else if (configured[cfg_descriptor_id[INDEX_WIDTH-1:0]]) begin
                    cfg_error <= 1'b1;
                    cfg_error_code <= ERR_CFG_DUP;
                end else begin
                    descriptors[cfg_descriptor_id[INDEX_WIDTH-1:0]]
                        <= cfg_descriptor;
                    configured[cfg_descriptor_id[INDEX_WIDTH-1:0]] <= 1'b1;
                end
            end

            case (state)
                S_IDLE: if (cmd_valid) begin
                    accepted_commands <= accepted_commands + 1'b1;
                    if (cmd_opcode != OP_LOAD) begin
                        error_code_latched <= ERR_OPCODE;
                        error_valid <= 1'b1;
                        state <= S_ERROR;
                    end else if (cmd_imm >= DESCRIPTOR_COUNT
                                 || !configured[cmd_imm[INDEX_WIDTH-1:0]]) begin
                        error_code_latched <= ERR_LOOKUP;
                        error_valid <= 1'b1;
                        state <= S_ERROR;
                    end else begin
                        active <= descriptors[cmd_imm[INDEX_WIDTH-1:0]];
                        state <= S_LAUNCH;
                    end
                end
                S_LAUNCH: if (core_cmd_ready)
                    state <= S_WAIT;
                S_WAIT: if (core_rsp_valid && rsp_ready)
                    state <= S_IDLE;
                S_ERROR: if (rsp_ready) begin
                    error_valid <= 1'b0;
                    state <= S_IDLE;
                end
                default: state <= S_IDLE;
            endcase
        end
    end
endmodule

`default_nettype wire
