`timescale 1ns/1ps
`default_nettype none

// Generic internal EMIT executor for a 64-bit Scratchpad and output stream.
//
// Command interpretation:
//   first_slot = base_slot + (use_index ? index_value : 0)
//   length_words is the total number of consecutive 64-bit reads
//   last_bytes is the number of valid low-order bytes in the final word (1..8)
//
// The index is a word offset, not a byte offset.  Exactly one command, one
// Scratchpad read and one output word may be outstanding.  This is an internal
// microcode capability interface; it is not an external Job/task ingress.
module micro_hbs_output_stream #(
    parameter integer SCRATCH_WORDS = 512,
    parameter integer ADDRESS_WIDTH = 16
) (
    input  wire                         clk,
    input  wire                         rst_n,

    input  wire                         emit_valid,
    output logic                        emit_ready,
    input  wire [ADDRESS_WIDTH-1:0]     emit_base_slot,
    input  wire                         emit_use_index,
    input  wire [31:0]                  emit_index_value,
    input  wire [15:0]                  emit_length_words,
    input  wire [3:0]                   emit_last_bytes,

    output logic                        scratch_read_valid,
    input  wire                         scratch_read_ready,
    output logic [ADDRESS_WIDTH-1:0]    scratch_read_address,
    input  wire                         scratch_response_valid,
    output logic                        scratch_response_ready,
    input  wire [63:0]                  scratch_response_data,
    input  wire                         scratch_response_error,

    output logic                        out_valid,
    input  wire                         out_ready,
    output logic [63:0]                 out_data,
    output logic [7:0]                  out_keep,
    output logic                        out_last,

    output logic                        busy,
    output logic                        done,
    output logic                        error,
    output logic [15:0]                 error_code
);
    localparam logic [15:0] ERR_ZERO_LENGTH  = 16'h0501;
    localparam logic [15:0] ERR_LAST_BYTES   = 16'h0502;
    localparam logic [15:0] ERR_ADDRESS      = 16'h0503;
    localparam logic [15:0] ERR_SCRATCH_READ = 16'h0504;
    localparam logic [32:0] SCRATCH_LIMIT = 33'(SCRATCH_WORDS);

    typedef enum logic [1:0] {S_IDLE, S_READ_REQUEST, S_READ_RESPONSE,
                              S_OUTPUT} state_t;
    state_t state;

    logic [ADDRESS_WIDTH-1:0] current_address;
    logic [15:0] current_word;
    logic [15:0] saved_length_words;
    logic [3:0] saved_last_bytes;

    logic [32:0] command_start;
    logic [32:0] command_end;
    logic [32:0] extended_index;
    logic command_address_valid;

    always @(*) begin
        extended_index = emit_use_index
            ? {1'b0, emit_index_value} : 33'b0;
        command_start = {{(33-ADDRESS_WIDTH){1'b0}}, emit_base_slot}
            + extended_index;
        command_end = command_start;
        if (emit_length_words != 0)
            command_end = command_start
                + {{17{1'b0}}, emit_length_words} - 1'b1;
        command_address_valid = command_start < SCRATCH_LIMIT
            && command_end < SCRATCH_LIMIT;
    end

    assign emit_ready = (state == S_IDLE);
    assign busy = (state != S_IDLE);
    assign scratch_read_valid = (state == S_READ_REQUEST);
    assign scratch_read_address = current_address;
    assign scratch_response_ready = (state == S_READ_RESPONSE);
    assign out_valid = (state == S_OUTPUT);

    function automatic [7:0] byte_keep(input logic [3:0] byte_count);
        begin
            case (byte_count)
                4'd1: byte_keep = 8'h01;
                4'd2: byte_keep = 8'h03;
                4'd3: byte_keep = 8'h07;
                4'd4: byte_keep = 8'h0f;
                4'd5: byte_keep = 8'h1f;
                4'd6: byte_keep = 8'h3f;
                4'd7: byte_keep = 8'h7f;
                4'd8: byte_keep = 8'hff;
                default: byte_keep = 8'h00;
            endcase
        end
    endfunction

    initial begin
        if (ADDRESS_WIDTH < 1 || ADDRESS_WIDTH > 32
            || SCRATCH_WORDS < 1 || SCRATCH_WORDS > (1 << ADDRESS_WIDTH))
            $error("invalid output-stream Scratchpad dimensions");
    end

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= S_IDLE;
            current_address <= '0;
            current_word <= '0;
            saved_length_words <= '0;
            saved_last_bytes <= '0;
            out_data <= '0;
            out_keep <= '0;
            out_last <= 1'b0;
            done <= 1'b0;
            error <= 1'b0;
            error_code <= '0;
        end else begin
            done <= 1'b0;
            error <= 1'b0;
            error_code <= '0;

            case (state)
                S_IDLE: begin
                    out_keep <= '0;
                    out_last <= 1'b0;
                    if (emit_valid) begin
                        if (emit_length_words == 0) begin
                            error <= 1'b1;
                            error_code <= ERR_ZERO_LENGTH;
                        end else if (emit_last_bytes == 0
                            || emit_last_bytes > 8) begin
                            error <= 1'b1;
                            error_code <= ERR_LAST_BYTES;
                        end else if (!command_address_valid) begin
                            error <= 1'b1;
                            error_code <= ERR_ADDRESS;
                        end else begin
                            current_address
                                <= command_start[ADDRESS_WIDTH-1:0];
                            current_word <= 0;
                            saved_length_words <= emit_length_words;
                            saved_last_bytes <= emit_last_bytes;
                            state <= S_READ_REQUEST;
                        end
                    end
                end

                S_READ_REQUEST: begin
                    if (scratch_read_ready)
                        state <= S_READ_RESPONSE;
                end

                S_READ_RESPONSE: begin
                    if (scratch_response_valid) begin
                        if (scratch_response_error) begin
                            out_keep <= '0;
                            out_last <= 1'b0;
                            error <= 1'b1;
                            error_code <= ERR_SCRATCH_READ;
                            state <= S_IDLE;
                        end else begin
                            out_data <= scratch_response_data;
                            out_last <= (current_word + 1'b1
                                == saved_length_words);
                            if (current_word + 1'b1 == saved_length_words)
                                out_keep <= byte_keep(saved_last_bytes);
                            else
                                out_keep <= 8'hff;
                            state <= S_OUTPUT;
                        end
                    end
                end

                S_OUTPUT: begin
                    if (out_ready) begin
                        if (out_last) begin
                            done <= 1'b1;
                            state <= S_IDLE;
                        end else begin
                            current_address <= current_address + 1'b1;
                            current_word <= current_word + 1'b1;
                            state <= S_READ_REQUEST;
                        end
                    end
                end

                default: begin
                    out_keep <= '0;
                    out_last <= 1'b0;
                    error <= 1'b1;
                    error_code <= ERR_SCRATCH_READ;
                    state <= S_IDLE;
                end
            endcase
        end
    end
endmodule

`default_nettype wire
