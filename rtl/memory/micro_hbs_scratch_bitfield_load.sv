`timescale 1ns/1ps
`default_nettype none

// Generic MSB-first bit-field LOAD from a byte string held in Scratchpad.
//
// A command reads at most two adjacent 64-bit words, extracts 1..64 bits and
// either returns a 32-bit sequencer-register write or writes a 1..16-byte
// zero-extended big-endian integer to Scratchpad.  The descriptor adapter is
// expected to supply the static source/destination addresses and may form the
// bit offset from a sequencer register.  There is no algorithm-specific state.
module micro_hbs_scratch_bitfield_load #(
    parameter integer SCRATCH_WORDS = 1024,
    parameter integer ADDRESS_WIDTH = 16
) (
    input  wire                         clk,
    input  wire                         rst_n,
    input  wire                         cmd_valid,
    output wire                         cmd_ready,
    output wire                         busy,
    input  wire [ADDRESS_WIDTH-1:0]     cmd_source_address,
    input  wire [15:0]                  cmd_input_bytes,
    input  wire [15:0]                  cmd_bit_offset,
    input  wire [6:0]                   cmd_bit_width,
    input  wire                         cmd_destination_is_reg,
    input  wire [7:0]                   cmd_destination_reg,
    input  wire [ADDRESS_WIDTH-1:0]     cmd_destination_address,
    input  wire [4:0]                   cmd_output_bytes,

    output wire                         rsp_valid,
    input  wire                         rsp_ready,
    output logic                        rsp_error,
    output logic [15:0]                 rsp_error_code,
    output logic                        rsp_reg_write,
    output logic [7:0]                  rsp_reg_index,
    output logic [31:0]                 rsp_reg_value,

    output logic                        scratch_request_valid,
    input  wire                         scratch_request_ready,
    output logic                        scratch_request_write,
    output logic [ADDRESS_WIDTH-1:0]    scratch_request_address,
    output logic [63:0]                 scratch_request_write_data,
    input  wire                         scratch_response_valid,
    input  wire [63:0]                  scratch_response_data,
    input  wire                         scratch_response_error,

    output logic [31:0]                 accepted_commands,
    output logic [31:0]                 scratch_reads,
    output logic [31:0]                 scratch_writes
);
    localparam logic [15:0] ERR_COMMAND = 16'h0d01;
    localparam logic [15:0] ERR_SOURCE  = 16'h0d02;
    localparam logic [15:0] ERR_DEST    = 16'h0d03;
    localparam logic [15:0] ERR_SCRATCH = 16'h0d04;

    typedef enum logic [3:0] {
        S_IDLE, S_READ0_REQ, S_READ0_WAIT, S_READ1_REQ, S_READ1_WAIT,
        S_EXTRACT, S_WRITE_REQ, S_RESPONSE
    } state_t;
    state_t state;

    logic [ADDRESS_WIDTH-1:0] source_word;
    logic [ADDRESS_WIDTH-1:0] destination_word;
    logic [5:0] bit_in_word;
    logic [6:0] bit_width;
    logic destination_is_reg;
    logic [7:0] destination_reg;
    logic [4:0] output_bytes;
    logic needs_second_word;
    logic [63:0] word0, word1;
    logic [63:0] extracted_value;
    logic write_word_index;
    logic [127:0] stream_bits;
    logic [127:0] shifted_bits;
    logic [127:0] field_mask;
    logic [127:0] field_value;
    integer byte_index;
    integer value_byte_index;

    function automatic [63:0] reverse_bytes64(input [63:0] value);
        integer index;
        begin
            for (index = 0; index < 8; index = index + 1)
                reverse_bytes64[63-8*index -: 8] = value[8*index +: 8];
        end
    endfunction

    assign cmd_ready = (state == S_IDLE);
    assign busy = (state != S_IDLE);
    assign rsp_valid = (state == S_RESPONSE);

    always_comb begin
        stream_bits = {reverse_bytes64(word0), reverse_bytes64(word1)};
        shifted_bits = stream_bits >> (128 - bit_in_word - bit_width);
        field_mask = (128'b1 << bit_width) - 1'b1;
        field_value = shifted_bits & field_mask;
        scratch_request_valid = 1'b0;
        scratch_request_write = 1'b0;
        scratch_request_address = '0;
        scratch_request_write_data = '0;
        if (state == S_READ0_REQ) begin
            scratch_request_valid = 1'b1;
            scratch_request_address = source_word;
        end else if (state == S_READ1_REQ) begin
            scratch_request_valid = 1'b1;
            scratch_request_address = source_word + 1'b1;
        end else if (state == S_WRITE_REQ) begin
            scratch_request_valid = 1'b1;
            scratch_request_write = 1'b1;
            scratch_request_address = destination_word + write_word_index;
            for (byte_index = 0; byte_index < 8; byte_index = byte_index + 1) begin
                value_byte_index = output_bytes - 1
                    - (write_word_index * 8 + byte_index);
                if ((write_word_index * 8 + byte_index) < output_bytes
                    && value_byte_index >= 0 && value_byte_index < 8)
                    scratch_request_write_data[8*byte_index +: 8]
                        = extracted_value >> (8*value_byte_index);
            end
        end
    end

    task automatic fail(input logic [15:0] code);
        begin
            rsp_error <= 1'b1;
            rsp_error_code <= code;
            rsp_reg_write <= 1'b0;
            state <= S_RESPONSE;
        end
    endtask

    initial begin
        if (SCRATCH_WORDS < 1 || SCRATCH_WORDS > (1 << ADDRESS_WIDTH))
            $error("invalid Scratchpad dimensions");
    end

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= S_IDLE;
            source_word <= '0;
            destination_word <= '0;
            bit_in_word <= '0;
            bit_width <= '0;
            destination_is_reg <= 1'b0;
            destination_reg <= '0;
            output_bytes <= '0;
            needs_second_word <= 1'b0;
            word0 <= '0;
            word1 <= '0;
            extracted_value <= '0;
            write_word_index <= 1'b0;
            rsp_error <= 1'b0;
            rsp_error_code <= '0;
            rsp_reg_write <= 1'b0;
            rsp_reg_index <= '0;
            rsp_reg_value <= '0;
            accepted_commands <= '0;
            scratch_reads <= '0;
            scratch_writes <= '0;
        end else begin
            case (state)
                S_IDLE: if (cmd_valid) begin
                    accepted_commands <= accepted_commands + 1'b1;
                    rsp_error <= 1'b0;
                    rsp_error_code <= '0;
                    rsp_reg_write <= 1'b0;
                    rsp_reg_index <= '0;
                    rsp_reg_value <= '0;
                    if (cmd_bit_width == 0 || cmd_bit_width > 64
                        || cmd_input_bytes == 0
                        || ({1'b0, cmd_bit_offset} + cmd_bit_width)
                           > ({1'b0, cmd_input_bytes} << 3))
                        fail(ERR_COMMAND);
                    else if (cmd_source_address
                             + (cmd_bit_offset >> 6)
                             + ((cmd_bit_offset[5:0] + cmd_bit_width > 64)
                                ? 1 : 0) >= SCRATCH_WORDS)
                        fail(ERR_SOURCE);
                    else if (cmd_destination_is_reg
                             && (cmd_destination_reg >= 8
                                 || cmd_bit_width > 32))
                        fail(ERR_DEST);
                    else if (!cmd_destination_is_reg
                             && (cmd_output_bytes == 0
                                 || cmd_output_bytes > 16
                                 || cmd_output_bytes * 8 < cmd_bit_width
                                 || cmd_destination_address
                                    + (cmd_output_bytes > 8 ? 1 : 0)
                                    >= SCRATCH_WORDS))
                        fail(ERR_DEST);
                    else begin
                        source_word <= cmd_source_address
                            + (cmd_bit_offset >> 6);
                        destination_word <= cmd_destination_address;
                        bit_in_word <= cmd_bit_offset[5:0];
                        bit_width <= cmd_bit_width;
                        destination_is_reg <= cmd_destination_is_reg;
                        destination_reg <= cmd_destination_reg;
                        output_bytes <= cmd_output_bytes;
                        needs_second_word <= cmd_bit_offset[5:0]
                            + cmd_bit_width > 64;
                        word0 <= '0;
                        word1 <= '0;
                        state <= S_READ0_REQ;
                    end
                end

                S_READ0_REQ: if (scratch_request_ready)
                    state <= S_READ0_WAIT;

                S_READ0_WAIT: begin
                    if (scratch_response_error)
                        fail(ERR_SCRATCH);
                    else if (scratch_response_valid) begin
                        word0 <= scratch_response_data;
                        scratch_reads <= scratch_reads + 1'b1;
                        state <= needs_second_word ? S_READ1_REQ : S_EXTRACT;
                    end
                end

                S_READ1_REQ: if (scratch_request_ready)
                    state <= S_READ1_WAIT;

                S_READ1_WAIT: begin
                    if (scratch_response_error)
                        fail(ERR_SCRATCH);
                    else if (scratch_response_valid) begin
                        word1 <= scratch_response_data;
                        scratch_reads <= scratch_reads + 1'b1;
                        state <= S_EXTRACT;
                    end
                end

                S_EXTRACT: begin
                    extracted_value <= field_value[63:0];
                    if (destination_is_reg) begin
                        rsp_reg_write <= 1'b1;
                        rsp_reg_index <= destination_reg;
                        rsp_reg_value <= field_value[31:0];
                        state <= S_RESPONSE;
                    end else begin
                        write_word_index <= 1'b0;
                        state <= S_WRITE_REQ;
                    end
                end

                S_WRITE_REQ: if (scratch_request_ready) begin
                    scratch_writes <= scratch_writes + 1'b1;
                    if (output_bytes > 8 && !write_word_index)
                        write_word_index <= 1'b1;
                    else
                        state <= S_RESPONSE;
                end

                S_RESPONSE: if (rsp_ready) begin
                    rsp_error <= 1'b0;
                    rsp_error_code <= '0;
                    rsp_reg_write <= 1'b0;
                    state <= S_IDLE;
                end

                default: fail(ERR_SCRATCH);
            endcase
        end
    end
endmodule

`default_nettype wire
