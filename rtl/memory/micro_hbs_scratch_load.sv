`timescale 1ns/1ps
`default_nettype none

// Single-word Scratchpad DATA_LOAD executor for the sequencer control registers.
// A static descriptor supplies the word address and the instruction supplies
// the destination register.  Only public/control data may be written to the
// eight 32-bit sequencer registers; cryptographic byte strings remain in the
// Scratchpad and use DATA_MOVE/HASH instead.
module micro_hbs_scratch_load #(
    parameter integer SCRATCH_WORDS = 512,
    parameter integer ADDRESS_WIDTH = 16
) (
    input  wire                         clk,
    input  wire                         rst_n,

    input  wire                         cmd_valid,
    output wire                         cmd_ready,
    input  wire [ADDRESS_WIDTH-1:0]     cmd_source_address,
    input  wire [7:0]                   cmd_destination_reg,
    input  wire                         cmd_high_word,

    output wire                         rsp_valid,
    input  wire                         rsp_ready,
    output logic                        rsp_error,
    output logic [15:0]                 rsp_error_code,
    output logic                        rsp_reg_write,
    output logic [7:0]                  rsp_reg_index,
    output logic [31:0]                 rsp_reg_value,

    output wire                         scratch_request_valid,
    input  wire                         scratch_request_ready,
    output wire [ADDRESS_WIDTH-1:0]     scratch_request_address,
    input  wire                         scratch_response_valid,
    input  wire [63:0]                  scratch_response_data,
    input  wire                         scratch_response_error,

    output logic [31:0]                 accepted_commands,
    output logic [31:0]                 completed_responses,
    output logic [31:0]                 error_responses
);
    localparam logic [15:0] ERR_ADDRESS  = 16'h0601;
    localparam logic [15:0] ERR_REGISTER = 16'h0602;
    localparam logic [15:0] ERR_SCRATCH  = 16'h0603;
    localparam logic [32:0] SCRATCH_LIMIT = 33'(SCRATCH_WORDS);

    typedef enum logic [1:0] {S_IDLE, S_READ_REQUEST, S_READ_RESPONSE,
                              S_RESPONSE} state_t;
    state_t state;

    logic [ADDRESS_WIDTH-1:0] source_latched;
    logic [7:0] destination_latched;
    logic high_word_latched;

    assign cmd_ready = (state == S_IDLE);
    assign rsp_valid = (state == S_RESPONSE);
    assign scratch_request_valid = (state == S_READ_REQUEST);
    assign scratch_request_address = source_latched;

    initial begin
        if (ADDRESS_WIDTH < 1 || ADDRESS_WIDTH > 32
            || SCRATCH_WORDS < 1 || SCRATCH_WORDS > (1 << ADDRESS_WIDTH))
            $error("invalid scratch-load dimensions");
    end

    task automatic fail_response(input logic [15:0] code);
        begin
            rsp_error <= 1'b1;
            rsp_error_code <= code;
            rsp_reg_write <= 1'b0;
            error_responses <= error_responses + 1'b1;
            state <= S_RESPONSE;
        end
    endtask

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= S_IDLE;
            source_latched <= '0;
            destination_latched <= '0;
            high_word_latched <= 1'b0;
            rsp_error <= 1'b0;
            rsp_error_code <= '0;
            rsp_reg_write <= 1'b0;
            rsp_reg_index <= '0;
            rsp_reg_value <= '0;
            accepted_commands <= '0;
            completed_responses <= '0;
            error_responses <= '0;
        end else begin
            case (state)
                S_IDLE: begin
                    if (cmd_valid) begin
                        accepted_commands <= accepted_commands + 1'b1;
                        rsp_error <= 1'b0;
                        rsp_error_code <= '0;
                        rsp_reg_write <= 1'b0;
                        rsp_reg_index <= '0;
                        rsp_reg_value <= '0;
                        if (cmd_destination_reg >= 8)
                            fail_response(ERR_REGISTER);
                        else if ({{(33-ADDRESS_WIDTH){1'b0}},
                                  cmd_source_address} >= SCRATCH_LIMIT)
                            fail_response(ERR_ADDRESS);
                        else begin
                            source_latched <= cmd_source_address;
                            destination_latched <= cmd_destination_reg;
                            high_word_latched <= cmd_high_word;
                            state <= S_READ_REQUEST;
                        end
                    end
                end

                S_READ_REQUEST: begin
                    if (scratch_request_ready)
                        state <= S_READ_RESPONSE;
                end

                S_READ_RESPONSE: begin
                    if (scratch_response_error)
                        fail_response(ERR_SCRATCH);
                    else if (scratch_response_valid) begin
                        rsp_reg_write <= 1'b1;
                        rsp_reg_index <= destination_latched;
                        rsp_reg_value <= high_word_latched
                            ? scratch_response_data[63:32]
                            : scratch_response_data[31:0];
                        state <= S_RESPONSE;
                    end
                end

                S_RESPONSE: begin
                    if (rsp_ready) begin
                        completed_responses <= completed_responses + 1'b1;
                        state <= S_IDLE;
                    end
                end

                default: fail_response(ERR_SCRATCH);
            endcase
        end
    end
endmodule

`default_nettype wire
