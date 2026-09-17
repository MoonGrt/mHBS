`timescale 1ns/1ps
`default_nettype none

// 64-bit storage token:
//   [63:62] kind: 00 single, 01 affine run, 10 outer loop, 11 halt
//   [61:56] 128-bit template index
//   [55:43], [42:30] lane context bases
//   [29:25] repeat minus one
//   [24:20], [19:15] lane context strides
//   [14:0] reserved for ISSUE tokens.  LOOP uses [61:50] back-count-1,
//   [49:45] additional repetitions, [44:32] context delta.
// Expansion recreates the original 128-bit horizontal ISSUE word exactly.
module micro_hbs_horizontal_token_sequencer #(
    parameter integer PROGRAM_TOKENS = 256,
    parameter integer ADDRESS_WIDTH = $clog2(PROGRAM_TOKENS)
) (
    input  wire                     clk,
    input  wire                     rst_n,
    input  wire                     token_we,
    input  wire [ADDRESS_WIDTH-1:0] token_addr,
    input  wire [63:0]              token_wdata,
    input  wire                     template_we,
    input  wire [5:0]               template_addr,
    input  wire [127:0]             template_wdata,
    input  wire                     job_valid,
    output wire                     job_ready,
    input  wire [ADDRESS_WIDTH-1:0] job_entry,
    output logic                    done,
    output logic                    busy,
    output logic                    error,
    output logic [7:0]              error_code,

    output wire                     lane0_valid,
    input  wire                     lane0_ready,
    output wire [47:0]              lane0_command,
    output wire [2:0]               lane0_event,
    output wire                     lane1_valid,
    input  wire                     lane1_ready,
    output wire [47:0]              lane1_command,
    output wire [2:0]               lane1_event,

    input  wire                     lane0_done_valid,
    input  wire [2:0]               lane0_done_event,
    input  wire                     lane1_done_valid,
    input  wire [2:0]               lane1_done_event,

    output wire [ADDRESS_WIDTH-1:0] program_counter,
    output wire [7:0]               pending_events,
    output wire [7:0]               completed_events,
    output logic [31:0]             retired_words,
    output logic [31:0]             retired_tokens,
    output logic [31:0]             issued_lane0,
    output logic [31:0]             issued_lane1,
    output logic [31:0]             wait_cycles
);
    localparam logic [1:0] TOKEN_SINGLE = 2'b00;
    localparam logic [1:0] TOKEN_RUN    = 2'b01;
    localparam logic [1:0] TOKEN_LOOP   = 2'b10;
    localparam logic [1:0] TOKEN_HALT   = 2'b11;
    localparam logic [3:0] OP_ISSUE = 4'h1;

    localparam logic [7:0] ERR_TOKEN      = 8'h11;
    localparam logic [7:0] ERR_TEMPLATE   = 8'h12;
    localparam logic [7:0] ERR_EVENT      = 8'h13;
    localparam logic [7:0] ERR_DUP_EVENT  = 8'h14;
    localparam logic [7:0] ERR_BUSY_WRITE = 8'h15;

    typedef enum logic [1:0] {S_IDLE, S_FETCH, S_LOAD, S_RUN} state_t;
    state_t state;
    logic [ADDRESS_WIDTH-1:0] pc;
    wire [63:0] token;
    wire [1:0] token_kind = token[63:62];
    wire [5:0] token_template = token[61:56];
    wire [12:0] token_context0 = token[55:43];
    wire [12:0] token_context1 = token[42:30];
    wire [4:0] token_repeat_minus_one = token[29:25];
    wire [4:0] token_stride0 = token[24:20];
    wire [4:0] token_stride1 = token[19:15];
    wire issue_reserved = |token[14:0];
    wire halt_payload = |token[61:0];
    wire [12:0] loop_back_count = {1'b0, token[61:50]} + 1'b1;
    wire [4:0] loop_repeats = token[49:45];
    wire [12:0] loop_context_delta = token[44:32];
    wire loop_reserved = |token[31:0];

    wire [127:0] template_data;
    logic [12:0] context0, context1;
    logic [4:0] stride0, stride1;
    logic [4:0] repeats_remaining;
    logic loop_active;
    logic [4:0] loop_remaining;
    logic [12:0] loop_context_bias;
    logic [ADDRESS_WIDTH-1:0] loop_pc;
    wire [13:0] biased_context0 = {1'b0, token_context0}
        + (template_data[107] ? {1'b0, loop_context_bias} : 14'b0);
    wire [13:0] biased_context1 = {1'b0, token_context1}
        + (template_data[106] ? {1'b0, loop_context_bias} : 14'b0);
    logic [127:0] instruction;
    always_comb begin
        instruction = template_data;
        instruction[75:52] = {11'b0, context0};
        instruction[27:4] = {11'b0, context1};
    end

    wire [7:0] wait_mask = instruction[123:116];
    wire [7:0] consume_mask = instruction[115:108];
    wire word_lane0_valid = instruction[107];
    wire word_lane1_valid = instruction[106];
    wire [2:0] word_lane0_event = instruction[105:103];
    wire [2:0] word_lane1_event = instruction[102:100];
    wire word_lane0_track = instruction[3];
    wire word_lane1_track = instruction[2];
    wire duplicate_event = word_lane0_valid && word_lane1_valid
        && word_lane0_track && word_lane1_track
        && word_lane0_event == word_lane1_event;
    wire unsafe_run = token_kind == TOKEN_RUN
        && (|wait_mask || |consume_mask
            || word_lane0_track || word_lane1_track);

    wire scoreboard_wait_ready;
    wire scoreboard_error;
    wire [2:0] scoreboard_error_code;
    wire issue_opcode = state == S_RUN && token_kind != TOKEN_HALT;
    wire requested_lanes_ready = (!word_lane0_valid || lane0_ready)
        && (!word_lane1_valid || lane1_ready);
    wire issue_fire = issue_opcode && scoreboard_wait_ready
        && requested_lanes_ready && !duplicate_event;
    logic lane0_track_active, lane1_track_active;
    wire [7:0] allocate_mask =
        (word_lane0_valid && word_lane0_track
            ? (8'b1 << word_lane0_event) : 8'b0)
        | (word_lane1_valid && word_lane1_track
            ? (8'b1 << word_lane1_event) : 8'b0);
    wire [7:0] complete_mask =
        (lane0_done_valid && lane0_track_active
            ? (8'b1 << lane0_done_event) : 8'b0)
        | (lane1_done_valid && lane1_track_active
            ? (8'b1 << lane1_done_event) : 8'b0);
    wire scoreboard_clear = state == S_IDLE && job_valid && job_ready;
    wire any_write = token_we || template_we;

    micro_hbs_horizontal_token_store #(
        .PROGRAM_TOKENS(PROGRAM_TOKENS), .ADDRESS_WIDTH(ADDRESS_WIDTH)
    ) token_store (
        .clk, .write_enable(token_we && state == S_IDLE && !job_valid),
        .write_address(token_addr), .write_data(token_wdata),
        .read_address(pc), .read_data(token)
    );

    micro_hbs_horizontal_template_store template_store (
        .clk, .write_enable(template_we && state == S_IDLE && !job_valid),
        .write_address(template_addr), .write_data(template_wdata),
        .read_address(token_template), .read_data(template_data)
    );

    micro_hbs_event_scoreboard #(.EVENTS(8)) scoreboard (
        .clk, .rst_n, .clear(scoreboard_clear),
        .allocate_valid(issue_fire), .allocate_mask,
        .complete_valid((lane0_done_valid && lane0_track_active)
            || (lane1_done_valid && lane1_track_active)),
        .complete_mask, .consume_valid(issue_fire), .consume_mask,
        .wait_mask, .wait_ready(scoreboard_wait_ready),
        .pending(pending_events), .completed(completed_events),
        .error(scoreboard_error), .error_code(scoreboard_error_code)
    );

    assign job_ready = state == S_IDLE && !error;
    assign busy = state != S_IDLE;
    assign program_counter = pc;
    assign lane0_valid = issue_fire && word_lane0_valid;
    assign lane1_valid = issue_fire && word_lane1_valid;
    assign lane0_command = instruction[99:52];
    assign lane1_command = instruction[51:4];
    assign lane0_event = word_lane0_event;
    assign lane1_event = word_lane1_event;

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= S_IDLE;
            pc <= '0;
            context0 <= '0;
            context1 <= '0;
            stride0 <= '0;
            stride1 <= '0;
            repeats_remaining <= '0;
            loop_active <= 1'b0;
            loop_remaining <= '0;
            loop_context_bias <= '0;
            loop_pc <= '0;
            done <= 1'b0;
            error <= 1'b0;
            error_code <= '0;
            retired_words <= '0;
            retired_tokens <= '0;
            issued_lane0 <= '0;
            issued_lane1 <= '0;
            wait_cycles <= '0;
            lane0_track_active <= 1'b0;
            lane1_track_active <= 1'b0;
        end else begin
            done <= 1'b0;
            if (lane0_done_valid)
                lane0_track_active <= 1'b0;
            if (lane1_done_valid)
                lane1_track_active <= 1'b0;
            if (scoreboard_error && !error) begin
                error <= 1'b1;
                error_code <= ERR_EVENT + {5'b0, scoreboard_error_code};
                state <= S_IDLE;
            end else if (any_write && state != S_IDLE) begin
                error <= 1'b1;
                error_code <= ERR_BUSY_WRITE;
                state <= S_IDLE;
            end else case (state)
                S_IDLE: if (job_valid && job_ready && !any_write) begin
                    pc <= job_entry;
                    retired_words <= '0;
                    retired_tokens <= '0;
                    issued_lane0 <= '0;
                    issued_lane1 <= '0;
                    wait_cycles <= '0;
                    lane0_track_active <= 1'b0;
                    lane1_track_active <= 1'b0;
                    loop_active <= 1'b0;
                    loop_remaining <= '0;
                    loop_context_bias <= '0;
                    state <= S_FETCH;
                end
                S_FETCH: state <= S_LOAD;
                S_LOAD: begin
                    if (token_kind == TOKEN_LOOP) begin
                        if (loop_reserved || loop_repeats == 0
                                || loop_context_delta == 0
                                || loop_back_count > pc
                                || (loop_active && pc != loop_pc)) begin
                            error <= 1'b1;
                            error_code <= ERR_TOKEN;
                            state <= S_IDLE;
                        end else if (!loop_active) begin
                            loop_active <= 1'b1;
                            loop_remaining <= loop_repeats;
                            loop_context_bias <= loop_context_delta;
                            loop_pc <= pc;
                            pc <= pc - loop_back_count;
                            retired_tokens <= retired_tokens + 1'b1;
                            state <= S_FETCH;
                        end else if (loop_remaining > 1) begin
                            loop_remaining <= loop_remaining - 1'b1;
                            loop_context_bias <= loop_context_bias
                                + loop_context_delta;
                            pc <= pc - loop_back_count;
                            retired_tokens <= retired_tokens + 1'b1;
                            state <= S_FETCH;
                        end else begin
                            loop_active <= 1'b0;
                            loop_remaining <= '0;
                            loop_context_bias <= '0;
                            pc <= pc + 1'b1;
                            retired_tokens <= retired_tokens + 1'b1;
                            state <= S_FETCH;
                        end
                    end else if ((token_kind == TOKEN_HALT && halt_payload)
                            || (token_kind != TOKEN_HALT && issue_reserved)
                            || (token_kind == TOKEN_SINGLE
                                && (token_repeat_minus_one != 0
                                    || token_stride0 != 0
                                    || token_stride1 != 0))
                            || (token_kind == TOKEN_RUN
                                && token_repeat_minus_one == 0)) begin
                        error <= 1'b1;
                        error_code <= ERR_TOKEN;
                        state <= S_IDLE;
                    end else if (token_kind != TOKEN_HALT
                            && (template_data[127:124] != OP_ISSUE
                                || unsafe_run
                                || biased_context0[13]
                                || biased_context1[13])) begin
                        error <= 1'b1;
                        error_code <= ERR_TEMPLATE;
                        state <= S_IDLE;
                    end else begin
                        context0 <= biased_context0[12:0];
                        context1 <= biased_context1[12:0];
                        stride0 <= token_stride0;
                        stride1 <= token_stride1;
                        repeats_remaining <= token_repeat_minus_one;
                        state <= S_RUN;
                    end
                end
                S_RUN: begin
                    if (token_kind == TOKEN_HALT) begin
                        if (pending_events == 0) begin
                            retired_words <= retired_words + 1'b1;
                            retired_tokens <= retired_tokens + 1'b1;
                            done <= 1'b1;
                            state <= S_IDLE;
                        end else
                            wait_cycles <= wait_cycles + 1'b1;
                    end else if (duplicate_event) begin
                        error <= 1'b1;
                        error_code <= ERR_DUP_EVENT;
                        state <= S_IDLE;
                    end else if (issue_fire) begin
                        retired_words <= retired_words + 1'b1;
                        issued_lane0 <= issued_lane0 + word_lane0_valid;
                        issued_lane1 <= issued_lane1 + word_lane1_valid;
                        if (word_lane0_valid)
                            lane0_track_active <= word_lane0_track;
                        if (word_lane1_valid)
                            lane1_track_active <= word_lane1_track;
                        if (repeats_remaining != 0) begin
                            context0 <= context0 + stride0;
                            context1 <= context1 + stride1;
                            repeats_remaining <= repeats_remaining - 1'b1;
                        end else begin
                            pc <= pc + 1'b1;
                            retired_tokens <= retired_tokens + 1'b1;
                            state <= S_FETCH;
                        end
                    end else
                        wait_cycles <= wait_cycles + 1'b1;
                end
                default: begin
                    error <= 1'b1;
                    error_code <= ERR_TOKEN;
                    state <= S_IDLE;
                end
            endcase
        end
    end
endmodule

`default_nettype wire
