`timescale 1ns/1ps
`default_nettype none

// Runtime ABI 4 program sequencer with one outstanding macro and event zero.
// Hash-lane parallelism is scheduled inside the macro executor. Coordinates are
// the low 24 bits of its 48-bit command. RUN applies affine strides;
// LOOP replays a token range with a coordinate bias.  Two nested loops are
// sufficient for layer -> WOTS leaf traversal.
module uhbs_program_sequencer (
    output wire [5:0] program_address, template_address,
    input wire [127:0] program_data, template_data,
    input wire [5:0] program_count,
    input wire [6:0] template_count,
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
    logic [5:0] pc;
    assign program_address=pc[5:0];
    assign template_address=token_template;
    logic [127:0] token, saved_template;
    wire [1:0] token_kind = token[127:126];
    wire [5:0] token_template = token[125:120];
    wire [23:0] token_coord0 = token[119:96];
    wire [5:0] token_repeat_minus_one = token[71:66];
    wire [23:0] token_stride0 = token[65:42];
    wire issue_reserved = |token[17:0] || |token[95:72] || |token[41:18];
    wire [12:0] loop_back_count = {1'b0,token[125:114]} + 1'b1;
    wire [5:0] loop_repeats = token[113:108];
    wire [23:0] loop_delta0 = token[107:84];
    wire loop_reserved = |token[83:0];
    wire halt_payload = |token[125:0];

    logic [1:0] loop_sp;
    logic [5:0] loop_pc [0:1];
    logic [5:0] loop_remaining [0:1];
    logic [23:0] loop_bias0 [0:1];
    logic [23:0] loop_step0 [0:1];
    wire [24:0] total_bias0 = {1'b0, loop_bias0[0]}
        + {1'b0, loop_bias0[1]};

    logic [23:0] coordinate0;
    logic [23:0] stride0;
    logic [5:0] repeats_remaining;
    wire [24:0] initial_coord0 = {1'b0, token_coord0} + total_bias0;
    wire template_in_range = token_template < template_count;
    logic [127:0] instruction;
    always_comb begin
        instruction = saved_template;
        instruction[75:52] = coordinate0;
    end

    wire wait_mask = instruction[116];
    wire consume_mask = instruction[108];
    wire word_lane0_valid = instruction[107];
    wire word_lane0_track = instruction[3];
    wire allocate_mask = word_lane0_valid && word_lane0_track;
    wire complete_mask = lane0_done_valid;
    wire event_pending;
    wire scoreboard_ready, scoreboard_error;
    wire [2:0] scoreboard_error_code;
    wire requested_ready = !word_lane0_valid || lane0_ready;
    wire issue_fire = state == S_RUN && token_kind != TOKEN_HALT
        && scoreboard_ready && requested_ready;

    uhbs_event_scoreboard #(.EVENTS(1)) scoreboard (
        .clk, .rst_n, .clear(state == S_IDLE && job_valid && job_ready),
        .allocate_valid(issue_fire), .allocate_mask,
        .complete_valid(lane0_done_valid),
        .complete_mask, .consume_valid(issue_fire), .consume_mask,
        .wait_mask, .wait_ready(scoreboard_ready), .pending(event_pending),
        .completed(), .error(scoreboard_error),
        .error_code(scoreboard_error_code)
    );

    assign job_ready = state == S_IDLE && !error;
    assign busy = state != S_IDLE;
    assign program_counter = {3'd0,pc};
    assign pending_events = {7'd0,event_pending};
    assign lane0_valid = issue_fire && word_lane0_valid;
    assign lane1_valid = 1'b0;
    assign lane0_command = instruction[99:52];
    assign lane1_command = 48'd0;
    assign lane0_event = 3'd0;
    assign lane1_event = 3'd0;

    integer index;
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= S_IDLE;
            pc <= 0;
            done <= 0;
            error <= 0;
            error_code <= 0;
            coordinate0 <= 0;
            stride0 <= 0;
            repeats_remaining <= 0;
            loop_sp <= 0;
            retired_words <= 0;
            retired_tokens <= 0;
            for (index = 0; index < 2; index = index + 1) begin
                loop_pc[index] <= 0;
                loop_remaining[index] <= 0;
                loop_bias0[index] <= 0;
                loop_step0[index] <= 0;
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
                    retired_words <= 0;
                    retired_tokens <= 0;
                    if(job_entry>=program_count || job_entry>=32) begin
                        error<=1;error_code<=ERR_TOKEN;state<=S_IDLE;
                    end else state <= S_FETCH;
                end
                S_FETCH: begin
                    if (pc >= program_count || pc >= 32) begin
                        error <= 1;
                        error_code <= ERR_TOKEN;
                        state <= S_IDLE;
                    end else begin token<=program_data;state <= S_LOAD;end
                end
                S_LOAD: begin
                    saved_template<=template_data;
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
                                pc <= pc - loop_back_count;
                            end else begin
                                loop_bias0[loop_sp-1] <= 0;
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
                            loop_step0[loop_sp] <= loop_delta0;
                            loop_sp <= loop_sp + 1'b1;
                            pc <= pc - loop_back_count;
                            retired_tokens <= retired_tokens + 1'b1;
                            state <= S_FETCH;
                        end
                    end else if ((token_kind == TOKEN_HALT && halt_payload)
                            || (token_kind != TOKEN_HALT && issue_reserved)
                            || (token_kind == TOKEN_SINGLE
                                && (token_repeat_minus_one != 0
                                    || token_stride0 != 0))
                            || (token_kind == TOKEN_RUN
                                && token_repeat_minus_one == 0)
                            || (token_kind != TOKEN_HALT
                                && !template_in_range)
                            || (token_kind != TOKEN_HALT
                                && (template_data[127:124] != OP_ISSUE
                                    || |template_data[123:117] || |template_data[115:109]
                                    || !template_data[107] || |template_data[106:100]
                                    || |template_data[75:4] || !template_data[3]
                                    || |template_data[2:0]))
                            || initial_coord0[24]) begin
                        error <= 1;
                        error_code <= token_kind == TOKEN_HALT
                            ? ERR_TOKEN : ERR_TEMPLATE;
                        state <= S_IDLE;
                    end else begin
                        coordinate0 <= initial_coord0[23:0];
                        stride0 <= token_stride0;
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
