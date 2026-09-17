`timescale 1ns/1ps
`default_nettype none

// Descriptor-driven WOTS base-w/checksum DATA_LOAD for SLH-DSA n=16,w=16
// profile.  The transform itself is generic base-w logic; the descriptor
// supplies physical source/destination word addresses and the sequencer only
// supplies the immutable DATA_LOAD id.
module micro_hbs_base_w_load_adapter #(
    parameter integer DESCRIPTOR_COUNT = 16,
    parameter integer SCRATCH_WORDS = 1024,
    parameter integer ADDRESS_WIDTH = 16
) (
    input  wire                         clk,
    input  wire                         rst_n,
    input  wire                         engine_busy,
    input  wire                         cfg_valid,
    output wire                         cfg_ready,
    input  wire [15:0]                  cfg_id,
    input  wire [63:0]                  cfg_data,
    output logic                        cfg_error,
    output logic [15:0]                 cfg_error_code,
    input  wire                         cmd_valid,
    output wire                         cmd_ready,
    input  wire [7:0]                   cmd_opcode,
    input  wire [31:0]                  cmd_imm,
    output wire                         cmd_match,
    output wire                         rsp_valid,
    input  wire                         rsp_ready,
    output logic                        rsp_error,
    output logic [15:0]                 rsp_error_code,
    output wire                         scratch_request_valid,
    input  wire                         scratch_request_ready,
    output logic                        scratch_request_write,
    output logic [ADDRESS_WIDTH-1:0]    scratch_request_address,
    output logic [63:0]                 scratch_request_write_data,
    input  wire                         scratch_response_valid,
    input  wire [63:0]                  scratch_response_data,
    input  wire                         scratch_response_error,
    output wire                         busy
);
    localparam logic [7:0] OP_DATA_LOAD = 8'h08;
    localparam logic [15:0] ERR_CFG = 16'h1001;
    localparam logic [15:0] ERR_COMMAND = 16'h1002;
    localparam logic [15:0] ERR_SCRATCH = 16'h1003;
    localparam integer INDEX_WIDTH = DESCRIPTOR_COUNT <= 2
        ? 1 : $clog2(DESCRIPTOR_COUNT);

    typedef enum logic [3:0] {
        S_IDLE, S_READ0_REQ, S_READ0_WAIT, S_READ1_REQ, S_READ1_WAIT,
        S_PREPARE, S_WRITE, S_RESPONSE
    } state_t;
    state_t state;
    logic [63:0] descriptors [0:DESCRIPTOR_COUNT-1];
    logic [DESCRIPTOR_COUNT-1:0] configured;
    logic [63:0] active;
    logic [63:0] source_word0, source_word1;
    logic [2:0] write_index;
    wire [15:0] d_source = active[47:32];
    wire [15:0] d_destination = active[31:16];
    wire [7:0] d_input_bytes = active[15:8];
    wire [127:0] digest = {
        source_word0[7:0], source_word0[15:8], source_word0[23:16],
        source_word0[31:24], source_word0[39:32], source_word0[47:40],
        source_word0[55:48], source_word0[63:56],
        source_word1[7:0], source_word1[15:8], source_word1[23:16],
        source_word1[31:24], source_word1[39:32], source_word1[47:40],
        source_word1[55:48], source_word1[63:56]
    };
    wire [279:0] chain_lengths;

    assign cfg_ready = !engine_busy && state == S_IDLE;
    assign cmd_ready = state == S_IDLE;
    assign cmd_match = cmd_opcode == OP_DATA_LOAD && cmd_imm < DESCRIPTOR_COUNT
        && configured[cmd_imm[INDEX_WIDTH-1:0]];
    assign busy = state != S_IDLE;
    assign rsp_valid = state == S_RESPONSE;
    assign scratch_request_valid = state == S_READ0_REQ
        || state == S_READ1_REQ || state == S_WRITE;

    micro_hbs_base_w_checksum #(
        .N_BYTES(16), .LOG_W(4), .LEN1(32), .LEN2(3)
    ) base_w (.digest, .chain_lengths);

    always_comb begin
        scratch_request_write = 1'b0;
        scratch_request_address = '0;
        scratch_request_write_data = '0;
        if (state == S_READ0_REQ)
            scratch_request_address = d_source[ADDRESS_WIDTH-1:0];
        else if (state == S_READ1_REQ)
            scratch_request_address = d_source[ADDRESS_WIDTH-1:0] + 1'b1;
        else if (state == S_WRITE) begin
            scratch_request_write = 1'b1;
            scratch_request_address = d_destination[ADDRESS_WIDTH-1:0]
                + write_index;
            if (write_index < 4)
                scratch_request_write_data
                    = chain_lengths[64*write_index +: 64];
            else
                scratch_request_write_data = {40'b0, chain_lengths[279:256]};
        end
    end

    always_ff @(posedge clk) begin
        if (cfg_valid && cfg_ready && cfg_id < DESCRIPTOR_COUNT
            && cfg_data[63:56] == 8'h01 && cfg_data[55:48] == 8'h01
            && cfg_data[7:0] == 0)
            descriptors[cfg_id[INDEX_WIDTH-1:0]] <= cfg_data;
    end

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= S_IDLE;
            configured <= '0;
            active <= '0;
            source_word0 <= '0;
            source_word1 <= '0;
            write_index <= '0;
            cfg_error <= 1'b0;
            cfg_error_code <= '0;
            rsp_error <= 1'b0;
            rsp_error_code <= '0;
        end else begin
            cfg_error <= 1'b0;
            cfg_error_code <= '0;
            if (cfg_valid) begin
                if (!cfg_ready || cfg_id >= DESCRIPTOR_COUNT
                    || cfg_data[63:56] != 8'h01
                    || cfg_data[55:48] != 8'h01 || cfg_data[15:8] != 16
                    || cfg_data[7:0] != 0
                    || configured[cfg_id[INDEX_WIDTH-1:0]]) begin
                    cfg_error <= 1'b1;
                    cfg_error_code <= ERR_CFG;
                end else
                    configured[cfg_id[INDEX_WIDTH-1:0]] <= 1'b1;
            end
            case (state)
                S_IDLE: if (cmd_valid) begin
                    rsp_error <= 1'b0;
                    rsp_error_code <= '0;
                    if (cmd_opcode != OP_DATA_LOAD || !cmd_match) begin
                        rsp_error <= 1'b1;
                        rsp_error_code <= ERR_COMMAND;
                        state <= S_RESPONSE;
                    end else begin
                        active <= descriptors[cmd_imm[INDEX_WIDTH-1:0]];
                        state <= S_READ0_REQ;
                    end
                end
                S_READ0_REQ: if (scratch_request_ready)
                    state <= S_READ0_WAIT;
                S_READ0_WAIT: begin
                    if (scratch_response_error) begin
                        rsp_error <= 1'b1;
                        rsp_error_code <= ERR_SCRATCH;
                        state <= S_RESPONSE;
                    end else if (scratch_response_valid) begin
                        source_word0 <= scratch_response_data;
                        state <= S_READ1_REQ;
                    end
                end
                S_READ1_REQ: if (scratch_request_ready)
                    state <= S_READ1_WAIT;
                S_READ1_WAIT: begin
                    if (scratch_response_error) begin
                        rsp_error <= 1'b1;
                        rsp_error_code <= ERR_SCRATCH;
                        state <= S_RESPONSE;
                    end else if (scratch_response_valid) begin
                        source_word1 <= scratch_response_data;
                        state <= S_PREPARE;
                    end
                end
                S_PREPARE: begin
                    if (d_input_bytes != 16 || d_source + 1 >= SCRATCH_WORDS
                        || d_destination + 4 >= SCRATCH_WORDS) begin
                        rsp_error <= 1'b1;
                        rsp_error_code <= ERR_SCRATCH;
                        state <= S_RESPONSE;
                    end else begin
                        write_index <= 0;
                        state <= S_WRITE;
                    end
                end
                S_WRITE: if (scratch_request_ready) begin
                    if (write_index == 4)
                        state <= S_RESPONSE;
                    else
                        write_index <= write_index + 1'b1;
                end
                S_RESPONSE: if (rsp_ready) begin
                    rsp_error <= 1'b0;
                    rsp_error_code <= '0;
                    state <= S_IDLE;
                end
                default: state <= S_IDLE;
            endcase
        end
    end
endmodule

`default_nettype wire
