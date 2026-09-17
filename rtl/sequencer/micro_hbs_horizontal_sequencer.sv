`timescale 1ns/1ps
`default_nettype none

// 128-bit static horizontal word:
//   [127:124] opcode, [123:116] wait mask, [115:108] consume mask,
//   [107] lane0 valid, [106] lane1 valid,
//   [105:103] lane0 completion event, [102:100] lane1 event,
//   [99:52] lane0 generic context command, [51:4] lane1 command,
//   [3] lane0 event tracking, [2] lane1 tracking, [1:0] reserved.
// All dependency selection is performed offline.  Runtime control is a
// sequential PC plus the eight-event scoreboard.
module micro_hbs_horizontal_sequencer #(
    parameter integer PROGRAM_WORDS = 1024,
    parameter integer ADDRESS_WIDTH = $clog2(PROGRAM_WORDS)
) (
    input  wire                     clk,
    input  wire                     rst_n,
    input  wire                     program_we,
    input  wire [ADDRESS_WIDTH-1:0] program_addr,
    input  wire [127:0]             program_wdata,
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
    output logic [31:0]             issued_lane0,
    output logic [31:0]             issued_lane1,
    output logic [31:0]             wait_cycles
);
    localparam logic [3:0] OP_NOP   = 4'h0;
    localparam logic [3:0] OP_ISSUE = 4'h1;
    localparam logic [3:0] OP_WAIT  = 4'h2;
    localparam logic [3:0] OP_HALT  = 4'hf;

    localparam logic [7:0] ERR_PC         = 8'h01;
    localparam logic [7:0] ERR_OPCODE     = 8'h02;
    localparam logic [7:0] ERR_EVENT      = 8'h03;
    localparam logic [7:0] ERR_DUP_EVENT  = 8'h04;
    localparam logic [7:0] ERR_BUSY_WRITE = 8'h05;

    typedef enum logic [1:0] {S_IDLE, S_FETCH, S_RUN} state_t;
    state_t state;
    logic [ADDRESS_WIDTH-1:0] pc;
    wire [127:0] instruction;
    wire [3:0] opcode = instruction[127:124];
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

    wire scoreboard_wait_ready;
    wire scoreboard_error;
    wire [2:0] scoreboard_error_code;
    wire issue_opcode = state == S_RUN && opcode == OP_ISSUE;
    wire requested_lanes_ready = (!word_lane0_valid || lane0_ready)
        && (!word_lane1_valid || lane1_ready);
    wire issue_fire = issue_opcode && scoreboard_wait_ready
        && requested_lanes_ready && !duplicate_event;
    wire wait_fire = state == S_RUN && opcode == OP_WAIT
        && scoreboard_wait_ready;
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
    wire scoreboard_clear = (state == S_IDLE && job_valid && job_ready);

    micro_hbs_horizontal_program_store #(
        .PROGRAM_WORDS(PROGRAM_WORDS), .ADDRESS_WIDTH(ADDRESS_WIDTH)
    ) program_store (
        .clk,
        .write_enable(program_we && state == S_IDLE && !job_valid),
        .write_address(program_addr), .write_data(program_wdata),
        .read_address(pc), .read_data(instruction)
    );

    micro_hbs_event_scoreboard #(.EVENTS(8)) scoreboard (
        .clk, .rst_n, .clear(scoreboard_clear),
        .allocate_valid(issue_fire), .allocate_mask,
        .complete_valid((lane0_done_valid && lane0_track_active)
            || (lane1_done_valid && lane1_track_active)),
        .complete_mask,
        .consume_valid(issue_fire || wait_fire), .consume_mask,
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
            done <= 1'b0;
            error <= 1'b0;
            error_code <= '0;
            retired_words <= '0;
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
            end else if (program_we && state != S_IDLE) begin
                error <= 1'b1;
                error_code <= ERR_BUSY_WRITE;
                state <= S_IDLE;
            end else case (state)
                S_IDLE: if (job_valid && job_ready && !program_we) begin
                    pc <= job_entry;
                    retired_words <= '0;
                    issued_lane0 <= '0;
                    issued_lane1 <= '0;
                    wait_cycles <= '0;
                    lane0_track_active <= 1'b0;
                    lane1_track_active <= 1'b0;
                    state <= S_FETCH;
                end
                S_FETCH: state <= S_RUN;
                S_RUN: begin
                    case (opcode)
                        OP_NOP: begin
                            pc <= pc + 1'b1;
                            retired_words <= retired_words + 1'b1;
                            state <= S_FETCH;
                        end
                        OP_ISSUE: begin
                            if (duplicate_event) begin
                                error <= 1'b1;
                                error_code <= ERR_DUP_EVENT;
                                state <= S_IDLE;
                            end else if (issue_fire) begin
                                pc <= pc + 1'b1;
                                retired_words <= retired_words + 1'b1;
                                issued_lane0 <= issued_lane0
                                    + word_lane0_valid;
                            issued_lane1 <= issued_lane1
                                    + word_lane1_valid;
                                if (word_lane0_valid)
                                    lane0_track_active <= word_lane0_track;
                                if (word_lane1_valid)
                                    lane1_track_active <= word_lane1_track;
                                state <= S_FETCH;
                            end else
                                wait_cycles <= wait_cycles + 1'b1;
                        end
                        OP_WAIT: begin
                            if (wait_fire) begin
                                pc <= pc + 1'b1;
                                retired_words <= retired_words + 1'b1;
                                state <= S_FETCH;
                            end else
                                wait_cycles <= wait_cycles + 1'b1;
                        end
                        OP_HALT: begin
                            if (pending_events == 0) begin
                                retired_words <= retired_words + 1'b1;
                                done <= 1'b1;
                                state <= S_IDLE;
                            end else
                                wait_cycles <= wait_cycles + 1'b1;
                        end
                        default: begin
                            error <= 1'b1;
                            error_code <= ERR_OPCODE;
                            state <= S_IDLE;
                        end
                    endcase
                end
                default: begin
                    error <= 1'b1;
                    error_code <= ERR_PC;
                    state <= S_IDLE;
                end
            endcase
        end
    end
endmodule

`default_nettype wire
