`timescale 1ns/1ps
`default_nettype none

// Static 128-bit token sequencer for the product Sign image.  Coordinates are
// the low 24 bits of each 48-bit lane command.  RUN applies affine strides;
// LOOP replays a token range with a coordinate bias.  Two nested loops are
// sufficient for layer -> WOTS leaf traversal.
module micro_hbs_static_task_sequencer #(
    parameter integer PROGRAM_TOKENS = 384,
    parameter integer PROGRAM_TEMPLATES = 64,
    parameter TOKEN_INIT_FILE = "rtl/microcode/slh_dsa_128f_sign_tokens.mem",
    parameter TEMPLATE_INIT_FILE = "rtl/microcode/slh_dsa_128f_sign_templates.mem"
) (
    input  wire         clk,
    input  wire         rst_n,
    input  wire         job_valid,
    output wire         job_ready,
    input  wire [8:0]   job_entry,
    output logic        done,
    output wire         busy,
    output logic        error,
    output logic [7:0]  error_code,

    output wire         lane0_valid,
    input  wire         lane0_ready,
    output wire [47:0]  lane0_command,
    output wire [2:0]   lane0_event,
    output wire         lane1_valid,
    input  wire         lane1_ready,
    output wire [47:0]  lane1_command,
    output wire [2:0]   lane1_event,
    input  wire         lane0_done_valid,
    input  wire [2:0]   lane0_done_event,
    input  wire         lane1_done_valid,
    input  wire [2:0]   lane1_done_event,

    output wire [8:0]   program_counter,
    output wire [7:0]   pending_events,
    output logic [31:0] retired_words,
    output logic [31:0] retired_tokens
);
    localparam logic [1:0] TOKEN_SINGLE = 2'b00;
    localparam logic [1:0] TOKEN_RUN    = 2'b01;
    localparam logic [1:0] TOKEN_LOOP   = 2'b10;
    localparam logic [1:0] TOKEN_HALT   = 2'b11;
    localparam logic [3:0] OP_ISSUE = 4'h1;

    localparam logic [7:0] ERR_TOKEN     = 8'h31;
    localparam logic [7:0] ERR_TEMPLATE  = 8'h32;
    localparam logic [7:0] ERR_EVENT     = 8'h33;
    localparam logic [7:0] ERR_LOOP      = 8'h34;

    typedef enum logic [1:0] {S_IDLE, S_FETCH, S_LOAD, S_RUN} state_t;
    state_t state;
    logic [8:0] pc;
    logic [127:0] token_memory [0:PROGRAM_TOKENS-1];
    logic [127:0] template_memory [0:PROGRAM_TEMPLATES-1];

    initial begin
        $readmemh(TOKEN_INIT_FILE, token_memory);
        $readmemh(TEMPLATE_INIT_FILE, template_memory);
    end

    wire [127:0] token = token_memory[pc];
    wire [1:0] token_kind = token[127:126];
    wire [5:0] token_template = token[125:120];
    wire [23:0] token_coord0 = token[119:96];
    wire [23:0] token_coord1 = token[95:72];
    wire [5:0] token_repeat_minus_one = token[71:66];
    wire [23:0] token_stride0 = token[65:42];
    wire [23:0] token_stride1 = token[41:18];
    wire issue_reserved = |token[17:0];
    wire [11:0] loop_back_count = token[125:114] + 1'b1;
    wire [5:0] loop_repeats = token[113:108];
    wire [23:0] loop_delta0 = token[107:84];
    wire [23:0] loop_delta1 = token[83:60];
    wire loop_reserved = |token[59:0];
    wire halt_payload = |token[125:0];

    logic [1:0] loop_sp;
    logic [8:0] loop_pc [0:1];
    logic [5:0] loop_remaining [0:1];
    logic [23:0] loop_bias0 [0:1];
    logic [23:0] loop_bias1 [0:1];
    logic [23:0] loop_step0 [0:1];
    logic [23:0] loop_step1 [0:1];
    wire [24:0] total_bias0 = {1'b0, loop_bias0[0]}
        + {1'b0, loop_bias0[1]};
    wire [24:0] total_bias1 = {1'b0, loop_bias1[0]}
        + {1'b0, loop_bias1[1]};

    logic [23:0] coordinate0, coordinate1;
    logic [23:0] stride0, stride1;
    logic [5:0] repeats_remaining;
    wire [24:0] initial_coord0 = {1'b0, token_coord0} + total_bias0;
    wire [24:0] initial_coord1 = {1'b0, token_coord1} + total_bias1;
    wire template_in_range = token_template < PROGRAM_TEMPLATES;
    wire [127:0] template_data = template_in_range
        ? template_memory[token_template] : 128'b0;
    logic [127:0] instruction;
    always_comb begin
        instruction = template_data;
        instruction[75:52] = coordinate0;
        instruction[27:4] = coordinate1;
    end

    wire [7:0] wait_mask = instruction[123:116];
    wire [7:0] consume_mask = instruction[115:108];
    wire word_lane0_valid = instruction[107];
    wire word_lane1_valid = instruction[106];
    wire [2:0] word_lane0_event = instruction[105:103];
    wire [2:0] word_lane1_event = instruction[102:100];
    wire word_lane0_track = instruction[3];
    wire word_lane1_track = instruction[2];
    wire [7:0] allocate_mask =
        (word_lane0_valid && word_lane0_track
            ? (8'b1 << word_lane0_event) : 8'b0)
        | (word_lane1_valid && word_lane1_track
            ? (8'b1 << word_lane1_event) : 8'b0);
    wire [7:0] complete_mask =
        (lane0_done_valid ? (8'b1 << lane0_done_event) : 8'b0)
        | (lane1_done_valid ? (8'b1 << lane1_done_event) : 8'b0);
    wire scoreboard_ready, scoreboard_error;
    wire [2:0] scoreboard_error_code;
    wire requested_ready = (!word_lane0_valid || lane0_ready)
        && (!word_lane1_valid || lane1_ready);
    wire issue_fire = state == S_RUN && token_kind != TOKEN_HALT
        && scoreboard_ready && requested_ready;

    micro_hbs_event_scoreboard #(.EVENTS(8)) scoreboard (
        .clk, .rst_n, .clear(state == S_IDLE && job_valid && job_ready),
        .allocate_valid(issue_fire), .allocate_mask,
        .complete_valid(lane0_done_valid || lane1_done_valid),
        .complete_mask, .consume_valid(issue_fire), .consume_mask,
        .wait_mask, .wait_ready(scoreboard_ready), .pending(pending_events),
        .completed(), .error(scoreboard_error),
        .error_code(scoreboard_error_code)
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

    integer index;
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= S_IDLE;
            pc <= 0;
            done <= 0;
            error <= 0;
            error_code <= 0;
            coordinate0 <= 0;
            coordinate1 <= 0;
            stride0 <= 0;
            stride1 <= 0;
            repeats_remaining <= 0;
            loop_sp <= 0;
            retired_words <= 0;
            retired_tokens <= 0;
            for (index = 0; index < 2; index = index + 1) begin
                loop_pc[index] <= 0;
                loop_remaining[index] <= 0;
                loop_bias0[index] <= 0;
                loop_bias1[index] <= 0;
                loop_step0[index] <= 0;
                loop_step1[index] <= 0;
            end
        end else begin
            done <= 0;
            if (scoreboard_error && !error) begin
                error <= 1;
                error_code <= ERR_EVENT + {5'b0, scoreboard_error_code};
                state <= S_IDLE;
            end else case (state)
                S_IDLE: if (job_valid && job_ready) begin
                    pc <= job_entry;
                    loop_sp <= 0;
                    loop_bias0[0] <= 0;
                    loop_bias0[1] <= 0;
                    loop_bias1[0] <= 0;
                    loop_bias1[1] <= 0;
                    retired_words <= 0;
                    retired_tokens <= 0;
                    state <= S_FETCH;
                end
                S_FETCH: state <= S_LOAD;
                S_LOAD: begin
                    if (token_kind == TOKEN_LOOP) begin
                        if (loop_reserved || loop_repeats == 0
                                || loop_back_count > pc) begin
                            error <= 1;
                            error_code <= ERR_TOKEN;
                            state <= S_IDLE;
                        end else if (loop_sp != 0
                                && loop_pc[loop_sp-1] == pc) begin
                            if (loop_remaining[loop_sp-1] > 1) begin
                                loop_remaining[loop_sp-1]
                                    <= loop_remaining[loop_sp-1] - 1'b1;
                                loop_bias0[loop_sp-1] <= loop_bias0[loop_sp-1]
                                    + loop_step0[loop_sp-1];
                                loop_bias1[loop_sp-1] <= loop_bias1[loop_sp-1]
                                    + loop_step1[loop_sp-1];
                                pc <= pc - loop_back_count;
                            end else begin
                                loop_bias0[loop_sp-1] <= 0;
                                loop_bias1[loop_sp-1] <= 0;
                                loop_sp <= loop_sp - 1'b1;
                                pc <= pc + 1'b1;
                            end
                            retired_tokens <= retired_tokens + 1'b1;
                            state <= S_FETCH;
                        end else if (loop_sp == 2) begin
                            error <= 1;
                            error_code <= ERR_LOOP;
                            state <= S_IDLE;
                        end else begin
                            loop_pc[loop_sp] <= pc;
                            loop_remaining[loop_sp] <= loop_repeats;
                            loop_bias0[loop_sp] <= loop_delta0;
                            loop_bias1[loop_sp] <= loop_delta1;
                            loop_step0[loop_sp] <= loop_delta0;
                            loop_step1[loop_sp] <= loop_delta1;
                            loop_sp <= loop_sp + 1'b1;
                            pc <= pc - loop_back_count;
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
                                && token_repeat_minus_one == 0)
                            || (token_kind != TOKEN_HALT
                                && !template_in_range)
                            || (token_kind != TOKEN_HALT
                                && template_data[127:124] != OP_ISSUE)
                            || initial_coord0[24] || initial_coord1[24]) begin
                        error <= 1;
                        error_code <= token_kind == TOKEN_HALT
                            ? ERR_TOKEN : ERR_TEMPLATE;
                        state <= S_IDLE;
                    end else begin
                        coordinate0 <= initial_coord0[23:0];
                        coordinate1 <= initial_coord1[23:0];
                        stride0 <= token_stride0;
                        stride1 <= token_stride1;
                        repeats_remaining <= token_repeat_minus_one;
                        state <= S_RUN;
                    end
                end
                S_RUN: begin
                    if (token_kind == TOKEN_HALT) begin
                        if (pending_events == 0) begin
                            done <= 1;
                            retired_words <= retired_words + 1'b1;
                            retired_tokens <= retired_tokens + 1'b1;
                            state <= S_IDLE;
                        end
                    end else if (issue_fire) begin
                        retired_words <= retired_words + 1'b1;
                        if (repeats_remaining != 0) begin
                            coordinate0 <= coordinate0 + stride0;
                            coordinate1 <= coordinate1 + stride1;
                            repeats_remaining <= repeats_remaining - 1'b1;
                        end else begin
                            pc <= pc + 1'b1;
                            retired_tokens <= retired_tokens + 1'b1;
                            state <= S_FETCH;
                        end
                    end
                end
                default: begin
                    error <= 1;
                    error_code <= ERR_TOKEN;
                    state <= S_IDLE;
                end
            endcase
        end
    end
endmodule

`default_nettype wire
