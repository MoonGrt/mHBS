`timescale 1ns/1ps
`default_nettype none

// Atomic, no-DMA SLH-DSA Job admission path.
//
// One coarse Job latches all fixed 16-byte fields.  The message is then
// accepted as payload-only 64-bit beats and committed to private Scratchpad
// storage before core_start_valid is asserted.  No task, Hash, FORS-index,
// chain-length, address, or tree-decision input exists during execution.
module micro_hbs_slh_dsa_job_stream_loader #(
    parameter integer SCRATCH_WORDS = 1024,
    parameter integer MAX_MESSAGE_BYTES = 1024,
    parameter integer LOGICAL_SLOT_BYTES = 16,
    parameter integer SK_SEED_SLOT = 256,
    parameter integer SK_PRF_SLOT = 257,
    parameter integer PK_SEED_SLOT = 258,
    parameter integer PK_ROOT_SLOT = 259,
    parameter integer OPT_RAND_SLOT = 260,
    parameter integer MESSAGE_SLOT = 261
) (
    input  wire         clk,
    input  wire         rst_n,

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

    output wire         core_start_valid,
    input  wire         core_start_ready,
    output wire [8:0]   core_entry,
    output wire [31:0]  core_message_length,
    output wire [127:0] core_sk_seed,
    output wire [127:0] core_sk_prf,
    output wire [127:0] core_pk_seed,
    output wire [127:0] core_pk_root,
    output wire [127:0] core_opt_rand,
    input  wire         core_done,
    input  wire         core_error,
    input  wire [15:0]  core_error_code,

    output wire         scratch_request_valid,
    input  wire         scratch_request_ready,
    output wire         scratch_request_write,
    output wire [15:0]  scratch_request_address,
    output wire [63:0]  scratch_request_write_data,
    input  wire         scratch_bounds_error,

    output wire         busy,
    output logic        done,
    output logic        error,
    output logic [15:0] error_code,
    output logic [31:0] accepted_jobs,
    output logic [31:0] admitted_message_words
);
    localparam integer SLOT_WORDS = LOGICAL_SLOT_BYTES / 8;
    localparam integer MESSAGE_BASE_WORD = MESSAGE_SLOT * SLOT_WORDS;
    localparam integer MESSAGE_WORDS = (MAX_MESSAGE_BYTES + 7) / 8;
    localparam logic [15:0] ERR_MESSAGE_LENGTH = 16'h0c01;
    localparam logic [15:0] ERR_MESSAGE_KEEP = 16'h0c02;
    localparam logic [15:0] ERR_MESSAGE_LAST = 16'h0c03;
    localparam logic [15:0] ERR_SCRATCH_BOUNDS = 16'h0201;

    typedef enum logic [2:0] {
        S_IDLE, S_FIXED_REQ, S_FIXED_WAIT, S_MESSAGE,
        S_MESSAGE_WAIT, S_LAUNCH, S_RUN
    } state_t;
    state_t state;

    logic [3:0] fixed_word_index;
    logic [15:0] message_word_index;
    logic [31:0] message_remaining;
    logic [3:0] accepted_message_bytes;
    logic [8:0] entry_latched;
    logic [31:0] message_length_latched;
    logic [127:0] sk_seed_latched, sk_prf_latched;
    logic [127:0] pk_seed_latched, pk_root_latched, opt_rand_latched;

    logic [15:0] fixed_address;
    logic [63:0] fixed_data;
    logic [3:0] message_bytes_this_word;
    logic [8:0] keep_builder;
    logic [7:0] expected_keep;
    logic message_keep_valid, message_last_valid, message_format_valid;
    logic [63:0] masked_message_data;
    integer byte_index;

    assign job_ready = (state == S_IDLE);
    assign busy = (state != S_IDLE);
    assign core_start_valid = (state == S_LAUNCH);
    assign core_entry = entry_latched;
    assign core_message_length = message_length_latched;
    assign core_sk_seed = sk_seed_latched;
    assign core_sk_prf = sk_prf_latched;
    assign core_pk_seed = pk_seed_latched;
    assign core_pk_root = pk_root_latched;
    assign core_opt_rand = opt_rand_latched;

    assign message_ready = (state == S_MESSAGE) && scratch_request_ready;
    assign scratch_request_valid = (state == S_FIXED_REQ)
        || ((state == S_MESSAGE) && message_valid && message_format_valid);
    assign scratch_request_write = 1'b1;
    assign scratch_request_address = (state == S_FIXED_REQ)
        ? fixed_address : 16'(MESSAGE_BASE_WORD) + message_word_index;
    assign scratch_request_write_data = (state == S_FIXED_REQ)
        ? fixed_data : masked_message_data;

    always_comb begin
        fixed_address = '0;
        fixed_data = '0;
        case (fixed_word_index)
            4'd0, 4'd1: begin
                fixed_address = 16'(SK_SEED_SLOT * SLOT_WORDS)
                    + fixed_word_index[0];
                fixed_data = sk_seed_latched[64*fixed_word_index[0] +: 64];
            end
            4'd2, 4'd3: begin
                fixed_address = 16'(SK_PRF_SLOT * SLOT_WORDS)
                    + fixed_word_index[0];
                fixed_data = sk_prf_latched[64*fixed_word_index[0] +: 64];
            end
            4'd4, 4'd5: begin
                fixed_address = 16'(PK_SEED_SLOT * SLOT_WORDS)
                    + fixed_word_index[0];
                fixed_data = pk_seed_latched[64*fixed_word_index[0] +: 64];
            end
            4'd6, 4'd7: begin
                fixed_address = 16'(PK_ROOT_SLOT * SLOT_WORDS)
                    + fixed_word_index[0];
                fixed_data = pk_root_latched[64*fixed_word_index[0] +: 64];
            end
            4'd8, 4'd9: begin
                fixed_address = 16'(OPT_RAND_SLOT * SLOT_WORDS)
                    + fixed_word_index[0];
                fixed_data = opt_rand_latched[64*fixed_word_index[0] +: 64];
            end
            default: begin
                fixed_address = '0;
                fixed_data = '0;
            end
        endcase
    end

    always_comb begin
        if (message_remaining >= 8)
            message_bytes_this_word = 4'd8;
        else
            message_bytes_this_word = message_remaining[3:0];
        keep_builder = (9'b1 << message_bytes_this_word) - 1'b1;
        expected_keep = keep_builder[7:0];
        message_keep_valid = message_remaining != 0
            && message_keep == expected_keep;
        message_last_valid = message_last == (message_remaining <= 8);
        message_format_valid = message_keep_valid && message_last_valid;
        masked_message_data = message_data;
        for (byte_index = 0; byte_index < 8; byte_index = byte_index + 1)
            if (!expected_keep[byte_index])
                masked_message_data[8*byte_index +: 8] = 8'b0;
    end

    task automatic fail(input logic [15:0] code);
        begin
            error <= 1'b1;
            error_code <= code;
            state <= S_IDLE;
        end
    endtask

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= S_IDLE;
            fixed_word_index <= '0;
            message_word_index <= '0;
            message_remaining <= '0;
            accepted_message_bytes <= '0;
            entry_latched <= '0;
            message_length_latched <= '0;
            sk_seed_latched <= '0;
            sk_prf_latched <= '0;
            pk_seed_latched <= '0;
            pk_root_latched <= '0;
            opt_rand_latched <= '0;
            done <= 1'b0;
            error <= 1'b0;
            error_code <= '0;
            accepted_jobs <= '0;
            admitted_message_words <= '0;
        end else begin
            done <= 1'b0;
            error <= 1'b0;
            error_code <= '0;
            case (state)
                S_IDLE: if (job_valid && job_ready) begin
                    accepted_jobs <= accepted_jobs + 1'b1;
                    if (job_message_length > MAX_MESSAGE_BYTES)
                        fail(ERR_MESSAGE_LENGTH);
                    else begin
                        entry_latched <= job_entry;
                        message_length_latched <= job_message_length;
                        sk_seed_latched <= job_sk_seed;
                        sk_prf_latched <= job_sk_prf;
                        pk_seed_latched <= job_pk_seed;
                        pk_root_latched <= job_pk_root;
                        opt_rand_latched <= job_opt_rand;
                        fixed_word_index <= '0;
                        message_word_index <= '0;
                        message_remaining <= job_message_length;
                        state <= S_FIXED_REQ;
                    end
                end

                S_FIXED_REQ: if (scratch_request_ready)
                    state <= S_FIXED_WAIT;

                S_FIXED_WAIT: begin
                    if (scratch_bounds_error)
                        fail(ERR_SCRATCH_BOUNDS);
                    else if (fixed_word_index == 4'd9)
                        state <= (message_remaining == 0)
                            ? S_LAUNCH : S_MESSAGE;
                    else begin
                        fixed_word_index <= fixed_word_index + 1'b1;
                        state <= S_FIXED_REQ;
                    end
                end

                S_MESSAGE: if (message_valid && message_ready) begin
                    if (!message_keep_valid)
                        fail(ERR_MESSAGE_KEEP);
                    else if (!message_last_valid)
                        fail(ERR_MESSAGE_LAST);
                    else begin
                        accepted_message_bytes <= message_bytes_this_word;
                        state <= S_MESSAGE_WAIT;
                    end
                end

                S_MESSAGE_WAIT: begin
                    if (scratch_bounds_error)
                        fail(ERR_SCRATCH_BOUNDS);
                    else begin
                        admitted_message_words
                            <= admitted_message_words + 1'b1;
                        if (message_remaining == accepted_message_bytes)
                            state <= S_LAUNCH;
                        else begin
                            message_remaining <= message_remaining
                                - accepted_message_bytes;
                            message_word_index <= message_word_index + 1'b1;
                            state <= S_MESSAGE;
                        end
                    end
                end

                S_LAUNCH: if (core_start_ready)
                    state <= S_RUN;

                S_RUN: begin
                    if (core_error) begin
                        error <= 1'b1;
                        error_code <= core_error_code;
                        state <= S_IDLE;
                    end else if (core_done) begin
                        done <= 1'b1;
                        state <= S_IDLE;
                    end
                end

                default: fail(ERR_MESSAGE_LENGTH);
            endcase
        end
    end

    initial begin
        if (LOGICAL_SLOT_BYTES != 16)
            $error("SLH-DSA Job loader requires 16-byte logical slots");
        if (MAX_MESSAGE_BYTES < 1)
            $error("MAX_MESSAGE_BYTES must be positive");
        if (MESSAGE_BASE_WORD + MESSAGE_WORDS > SCRATCH_WORDS)
            $error("Job message region exceeds Scratchpad capacity");
        if ((SK_SEED_SLOT + 1) * SLOT_WORDS > SCRATCH_WORDS
            || (SK_PRF_SLOT + 1) * SLOT_WORDS > SCRATCH_WORDS
            || (PK_SEED_SLOT + 1) * SLOT_WORDS > SCRATCH_WORDS
            || (PK_ROOT_SLOT + 1) * SLOT_WORDS > SCRATCH_WORDS
            || (OPT_RAND_SLOT + 1) * SLOT_WORDS > SCRATCH_WORDS)
            $error("fixed Job fields exceed Scratchpad capacity");
    end
endmodule

`default_nettype wire
