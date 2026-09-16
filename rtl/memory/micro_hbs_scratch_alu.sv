`timescale 1ns/1ps
`default_nettype none

// Word-serial STORE/MOVE and XOR executor for the single-port Scratchpad.
// Address generation and static descriptor lookup are intentionally separate.
// A complete-range precheck occurs before the first write, so a malformed
// command cannot leave a partially updated destination.
module micro_hbs_scratch_alu #(
    parameter integer WORDS = 512,
    parameter integer ADDRESS_WIDTH = 16,
    // Direct micro_hbs_scratchpad64 writes have a one-cycle error check but
    // no response_valid.  Set WRITE_ACK when an arbiter converts writes into
    // explicit response transactions.
    parameter bit WRITE_ACK = 1'b0
) (
    input  wire                     clk,
    input  wire                     rst_n,

    input  wire                     cmd_valid,
    output wire                     cmd_ready,
    input  wire [7:0]               cmd_opcode,
    input  wire [ADDRESS_WIDTH-1:0] cmd_source_a,
    input  wire [ADDRESS_WIDTH-1:0] cmd_source_b,
    input  wire [ADDRESS_WIDTH-1:0] cmd_destination,
    input  wire [15:0]              cmd_word_count,

    output wire                     rsp_valid,
    input  wire                     rsp_ready,
    output logic                    rsp_error,
    output logic [15:0]             rsp_error_code,

    output wire                     scratch_request_valid,
    input  wire                     scratch_request_ready,
    output wire                     scratch_request_write,
    output wire [ADDRESS_WIDTH-1:0] scratch_request_address,
    output wire [63:0]              scratch_request_write_data,
    input  wire                     scratch_response_valid,
    input  wire [63:0]              scratch_response_read_data,
    input  wire                     scratch_bounds_error,

    output logic [31:0]             accepted_commands,
    output logic [31:0]             completed_responses,
    output logic [31:0]             error_responses,
    output logic [31:0]             scratch_reads,
    output logic [31:0]             scratch_writes
);
    localparam logic [7:0] OP_STORE = 8'h09;
    localparam logic [7:0] OP_XOR   = 8'h0a;
    localparam logic [15:0] ERR_NONE       = 16'h0000;
    localparam logic [15:0] ERR_OPCODE     = 16'h0401;
    localparam logic [15:0] ERR_ZERO_WORDS = 16'h0402;
    localparam logic [15:0] ERR_BOUNDS     = 16'h0403;

    typedef enum logic [3:0] {
        S_IDLE, S_READ_A_REQ, S_READ_A_WAIT, S_READ_B_REQ, S_READ_B_WAIT,
        S_WRITE_REQ, S_WRITE_CHECK, S_RESPONSE
    } state_t;
    state_t state;

    logic [7:0] opcode_latched;
    logic [ADDRESS_WIDTH-1:0] source_a_latched;
    logic [ADDRESS_WIDTH-1:0] source_b_latched;
    logic [ADDRESS_WIDTH-1:0] destination_latched;
    logic [15:0] word_count_latched;
    logic [15:0] word_offset;
    logic [63:0] source_a_word;
    logic [63:0] write_word;

    logic [16:0] source_a_end;
    logic [16:0] source_b_end;
    logic [16:0] destination_end;
    localparam logic [16:0] WORDS_EXT = WORDS;

    assign cmd_ready = (state == S_IDLE);
    assign rsp_valid = (state == S_RESPONSE);
    assign scratch_request_valid = (state == S_READ_A_REQ)
        || (state == S_READ_B_REQ) || (state == S_WRITE_REQ);
    assign scratch_request_write = (state == S_WRITE_REQ);
    assign scratch_request_address = (state == S_READ_A_REQ)
        ? source_a_latched + word_offset[ADDRESS_WIDTH-1:0]
        : (state == S_READ_B_REQ)
            ? source_b_latched + word_offset[ADDRESS_WIDTH-1:0]
            : destination_latched + word_offset[ADDRESS_WIDTH-1:0];
    assign scratch_request_write_data = write_word;

    // End is exclusive.  One extra bit prevents address wrap from passing.
    always_comb begin
        source_a_end = {{(17-ADDRESS_WIDTH){1'b0}}, cmd_source_a}
            + {1'b0, cmd_word_count};
        source_b_end = {{(17-ADDRESS_WIDTH){1'b0}}, cmd_source_b}
            + {1'b0, cmd_word_count};
        destination_end = {{(17-ADDRESS_WIDTH){1'b0}}, cmd_destination}
            + {1'b0, cmd_word_count};
    end

    initial begin
        if (ADDRESS_WIDTH < 1 || ADDRESS_WIDTH > 16)
            $error("ADDRESS_WIDTH must be in 1..16");
        if (WORDS < 1 || WORDS > (1 << ADDRESS_WIDTH))
            $error("invalid WORDS/ADDRESS_WIDTH");
    end

    task automatic fail_response(input logic [15:0] code);
        begin
            rsp_error <= 1'b1;
            rsp_error_code <= code;
            error_responses <= error_responses + 1'b1;
            state <= S_RESPONSE;
        end
    endtask

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= S_IDLE;
            opcode_latched <= '0;
            source_a_latched <= '0;
            source_b_latched <= '0;
            destination_latched <= '0;
            word_count_latched <= '0;
            word_offset <= '0;
            source_a_word <= '0;
            write_word <= '0;
            rsp_error <= 1'b0;
            rsp_error_code <= ERR_NONE;
            accepted_commands <= '0;
            completed_responses <= '0;
            error_responses <= '0;
            scratch_reads <= '0;
            scratch_writes <= '0;
        end else begin
            case (state)
                S_IDLE: begin
                    if (cmd_valid) begin
                        accepted_commands <= accepted_commands + 1'b1;
                        rsp_error <= 1'b0;
                        rsp_error_code <= ERR_NONE;
                        word_offset <= 16'b0;
                        if (cmd_opcode != OP_STORE && cmd_opcode != OP_XOR) begin
                            fail_response(ERR_OPCODE);
                        end else if (cmd_word_count == 0) begin
                            fail_response(ERR_ZERO_WORDS);
                        end else if (source_a_end > WORDS_EXT
                                     || destination_end > WORDS_EXT
                                     || (cmd_opcode == OP_XOR
                                         && source_b_end > WORDS_EXT)) begin
                            fail_response(ERR_BOUNDS);
                        end else begin
                            opcode_latched <= cmd_opcode;
                            source_a_latched <= cmd_source_a;
                            source_b_latched <= cmd_source_b;
                            destination_latched <= cmd_destination;
                            word_count_latched <= cmd_word_count;
                            state <= S_READ_A_REQ;
                        end
                    end
                end

                S_READ_A_REQ: begin
                    if (scratch_request_ready) begin
                        scratch_reads <= scratch_reads + 1'b1;
                        state <= S_READ_A_WAIT;
                    end
                end

                S_READ_A_WAIT: begin
                    if (scratch_bounds_error) begin
                        fail_response(ERR_BOUNDS);
                    end else if (scratch_response_valid) begin
                        source_a_word <= scratch_response_read_data;
                        if (opcode_latched == OP_XOR)
                            state <= S_READ_B_REQ;
                        else begin
                            write_word <= scratch_response_read_data;
                            state <= S_WRITE_REQ;
                        end
                    end
                end

                S_READ_B_REQ: begin
                    if (scratch_request_ready) begin
                        scratch_reads <= scratch_reads + 1'b1;
                        state <= S_READ_B_WAIT;
                    end
                end

                S_READ_B_WAIT: begin
                    if (scratch_bounds_error) begin
                        fail_response(ERR_BOUNDS);
                    end else if (scratch_response_valid) begin
                        write_word <= source_a_word ^ scratch_response_read_data;
                        state <= S_WRITE_REQ;
                    end
                end

                S_WRITE_REQ: begin
                    if (scratch_request_ready) begin
                        scratch_writes <= scratch_writes + 1'b1;
                        state <= S_WRITE_CHECK;
                    end
                end

                S_WRITE_CHECK: begin
                    if (scratch_bounds_error) begin
                        fail_response(ERR_BOUNDS);
                    end else if (!WRITE_ACK || scratch_response_valid) begin
                        if (word_offset + 1'b1 == word_count_latched) begin
                            state <= S_RESPONSE;
                        end else begin
                            word_offset <= word_offset + 1'b1;
                            state <= S_READ_A_REQ;
                        end
                    end
                end

                S_RESPONSE: begin
                    if (rsp_ready) begin
                        completed_responses <= completed_responses + 1'b1;
                        state <= S_IDLE;
                    end
                end

                default: fail_response(ERR_OPCODE);
            endcase
        end
    end
endmodule

`default_nettype wire
