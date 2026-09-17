`timescale 1ns/1ps
`default_nettype none

// Static-descriptor 96-bit shift DATA_LOAD.  This keeps wide tree addresses in
// Scratchpad while the sequencer register file remains 32-bit.
// Descriptor: version, capability, source word, destination word,
// byte count, direction bit (1=right), shift amount.
module micro_hbs_wide_shift_load_adapter #(
    parameter integer DESCRIPTOR_COUNT = 16,
    parameter integer SCRATCH_WORDS = 1024,
    parameter integer ADDRESS_WIDTH = 16
) (
    input wire clk, input wire rst_n, input wire engine_busy,
    input wire cfg_valid, output wire cfg_ready,
    input wire [15:0] cfg_id, input wire [63:0] cfg_data,
    output logic cfg_error, output logic [15:0] cfg_error_code,
    input wire cmd_valid, output wire cmd_ready,
    input wire [7:0] cmd_opcode, input wire [31:0] cmd_imm,
    output wire cmd_match, output wire rsp_valid, input wire rsp_ready,
    output logic rsp_error, output logic [15:0] rsp_error_code,
    output wire scratch_request_valid,
    input wire scratch_request_ready,
    output logic scratch_request_write,
    output logic [ADDRESS_WIDTH-1:0] scratch_request_address,
    output logic [63:0] scratch_request_write_data,
    input wire scratch_response_valid,
    input wire [63:0] scratch_response_data,
    input wire scratch_response_error,
    output wire busy
);
    localparam logic [7:0] OP_DATA_LOAD = 8'h08;
    localparam logic [15:0] ERR_CFG = 16'h1101;
    localparam logic [15:0] ERR_COMMAND = 16'h1102;
    localparam logic [15:0] ERR_SCRATCH = 16'h1103;
    localparam integer INDEX_WIDTH = DESCRIPTOR_COUNT <= 2
        ? 1 : $clog2(DESCRIPTOR_COUNT);
    typedef enum logic [3:0] {
        S_IDLE, S_READ0_REQ, S_READ0_WAIT, S_READ1_REQ, S_READ1_WAIT,
        S_SHIFT, S_WRITE0, S_WRITE1, S_RESPONSE
    } state_t;
    state_t state;
    logic [63:0] descriptors [0:DESCRIPTOR_COUNT-1];
    logic [DESCRIPTOR_COUNT-1:0] configured;
    logic [63:0] active, word0, word1;
    logic [95:0] shifted;
    wire [15:0] d_source = active[47:32];
    wire [15:0] d_destination = active[31:16];
    wire [7:0] d_bytes = active[15:8];
    wire d_right = active[7];
    wire [6:0] d_shift = active[6:0];
    wire [95:0] stream = {
        word0[7:0], word0[15:8], word0[23:16], word0[31:24],
        word0[39:32], word0[47:40], word0[55:48], word0[63:56],
        word1[7:0], word1[15:8], word1[23:16], word1[31:24]
    };

    function automatic [63:0] reverse64(input [63:0] value);
        integer i;
        begin
            for (i = 0; i < 8; i = i + 1)
                reverse64[8*i +: 8] = value[63-8*i -: 8];
        end
    endfunction

    assign cfg_ready = !engine_busy && state == S_IDLE;
    assign cmd_ready = state == S_IDLE;
    assign cmd_match = cmd_opcode == OP_DATA_LOAD && cmd_imm < DESCRIPTOR_COUNT
        && configured[cmd_imm[INDEX_WIDTH-1:0]];
    assign rsp_valid = state == S_RESPONSE;
    assign busy = state != S_IDLE;
    assign scratch_request_valid = state == S_READ0_REQ
        || state == S_READ1_REQ || state == S_WRITE0 || state == S_WRITE1;

    always_comb begin
        scratch_request_write = 1'b0;
        scratch_request_address = '0;
        scratch_request_write_data = '0;
        case (state)
            S_READ0_REQ: scratch_request_address = d_source;
            S_READ1_REQ: scratch_request_address = d_source + 1'b1;
            S_WRITE0: begin
                scratch_request_write = 1'b1;
                scratch_request_address = d_destination;
                scratch_request_write_data = reverse64(shifted[95:32]);
            end
            S_WRITE1: begin
                scratch_request_write = 1'b1;
                scratch_request_address = d_destination + 1'b1;
                scratch_request_write_data = {
                    32'b0, shifted[7:0], shifted[15:8],
                    shifted[23:16], shifted[31:24]
                };
            end
            default: begin end
        endcase
    end

    always_ff @(posedge clk) begin
        if (cfg_valid && cfg_ready && cfg_id < DESCRIPTOR_COUNT
            && cfg_data[63:56] == 8'h01 && cfg_data[55:48] == 8'h01)
            descriptors[cfg_id[INDEX_WIDTH-1:0]] <= cfg_data;
    end

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= S_IDLE;
            configured <= '0;
            active <= '0;
            word0 <= '0;
            word1 <= '0;
            shifted <= '0;
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
                    || cfg_data[55:48] != 8'h01
                    || cfg_data[15:8] != 12 || !cfg_data[7]
                    || cfg_data[6:0] == 0 || cfg_data[6:0] >= 96
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
                        word0 <= scratch_response_data;
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
                        word1 <= scratch_response_data;
                        state <= S_SHIFT;
                    end
                end
                S_SHIFT: begin
                    if (d_bytes != 12 || !d_right
                        || d_source + 1 >= SCRATCH_WORDS
                        || d_destination + 1 >= SCRATCH_WORDS) begin
                        rsp_error <= 1'b1;
                        rsp_error_code <= ERR_SCRATCH;
                        state <= S_RESPONSE;
                    end else begin
                        shifted <= stream >> d_shift;
                        state <= S_WRITE0;
                    end
                end
                S_WRITE0: if (scratch_request_ready)
                    state <= S_WRITE1;
                S_WRITE1: if (scratch_request_ready)
                    state <= S_RESPONSE;
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
