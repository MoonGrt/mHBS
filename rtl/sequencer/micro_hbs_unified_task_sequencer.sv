`timescale 1ns/1ps
`default_nettype none

// One physical product ROM and one token sequencer for all three profiles.
// The algorithm/operation inputs are consumed only while loading the profile
// directory; execution thereafter is driven entirely by ROM contents.
module micro_hbs_unified_task_sequencer #(
    parameter ROM_INIT_FILE = "rtl/microcode/unified_hbs_product_rom64.mem"
) (
    input  wire         clk,
    input  wire         rst_n,
    input  wire         job_valid,
    output wire         job_ready,
    input  wire [1:0]   job_algorithm,
    input  wire [1:0]   job_operation,
    output logic        done,
    output wire         busy,
    output logic        error,
    output logic [7:0]  error_code,
    output wire         lane0_valid,
    input  wire         lane0_ready,
    output wire [47:0]  lane0_command,
    output wire [63:0]  lane0_descriptor,
    output wire [2:0]   lane0_event,
    output wire         lane1_valid,
    input  wire         lane1_ready,
    output wire [47:0]  lane1_command,
    output wire [2:0]   lane1_event,
    input  wire         lane0_done_valid,
    input  wire [2:0]   lane0_done_event,
    input  wire         lane1_done_valid,
    input  wire [2:0]   lane1_done_event,
    input  wire         descriptor_request_valid,
    output wire         descriptor_request_ready,
    input  wire [7:0]   descriptor_request_index,
    output logic        descriptor_response_valid,
    output logic [63:0] descriptor_response_data,
    output logic [7:0]  descriptor_base,
    output logic [7:0]  descriptor_count,
    output logic [5:0]  profile_n_bytes,
    output logic [4:0]  profile_height,
    output logic        profile_stateful,
    output wire [7:0]   pending_events,
    output logic [31:0] retired_words,
    output logic [31:0] retired_tokens
);
    localparam logic [1:0] TOKEN_SINGLE = 2'b00;
    localparam logic [1:0] TOKEN_RUN    = 2'b01;
    localparam logic [1:0] TOKEN_LOOP   = 2'b10;
    localparam logic [1:0] TOKEN_HALT   = 2'b11;
    localparam logic [3:0] OP_ISSUE = 4'h1;
    localparam logic [7:0] ERR_JOB = 8'h41;
    localparam logic [7:0] ERR_DIRECTORY = 8'h42;
    localparam logic [7:0] ERR_TOKEN = 8'h43;
    localparam logic [7:0] ERR_TEMPLATE = 8'h44;
    localparam logic [7:0] ERR_EVENT = 8'h45;
    localparam logic [7:0] ERR_LOOP = 8'h46;

    typedef enum logic [3:0] {
        Q_IDLE, Q_DIR_WAIT, Q_DIR_LOAD, Q_TOKEN_WAIT, Q_TOKEN_LOAD,
        Q_TEMPLATE_WAIT, Q_TEMPLATE_LOAD,
        Q_ISSUE_DESC_WAIT, Q_ISSUE_DESC_LOAD, Q_RUN
    } state_t;
    state_t state;

    logic [7:0] rom_address;
    logic rom_request_valid;
    wire rom_request_ready, rom_data_valid;
    wire [127:0] rom_data;
    micro_hbs_unified_program_rom #(.INIT_FILE(ROM_INIT_FILE)) program_rom (
        .clk, .rst_n, .request_valid(rom_request_valid),
        .request_ready(rom_request_ready), .address(rom_address),
        .data_valid(rom_data_valid), .data(rom_data)
    );

    logic [7:0] token_base, token_count, template_base, template_count;
    logic [8:0] pc;
    logic [127:0] token;
    logic [127:0] template_word;
    logic [23:0] coordinate0, coordinate1, stride0, stride1;
    logic [5:0] repeats_remaining;
    logic [1:0] loop_sp;
    logic [8:0] loop_pc [0:1];
    logic [5:0] loop_remaining [0:1];
    logic [23:0] loop_bias0 [0:1], loop_bias1 [0:1];
    logic [23:0] loop_step0 [0:1], loop_step1 [0:1];
    logic descriptor_pending, descriptor_half;
    logic [63:0] prefetched_descriptor;

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
    wire [24:0] total_bias0 = {1'b0, loop_bias0[0]}
        + {1'b0, loop_bias0[1]};
    wire [24:0] total_bias1 = {1'b0, loop_bias1[0]}
        + {1'b0, loop_bias1[1]};
    wire [24:0] initial_coord0 = {1'b0, token_coord0} + total_bias0;
    wire [24:0] initial_coord1 = {1'b0, token_coord1} + total_bias1;

    logic [127:0] instruction;
    always_comb begin
        instruction = template_word;
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
    wire issue_fire = state == Q_RUN && token_kind != TOKEN_HALT
        && !descriptor_pending
        && scoreboard_ready && requested_ready;

    micro_hbs_event_scoreboard #(.EVENTS(8)) scoreboard (
        .clk, .rst_n, .clear(state == Q_IDLE && job_valid && job_ready),
        .allocate_valid(issue_fire), .allocate_mask,
        .complete_valid(lane0_done_valid || lane1_done_valid),
        .complete_mask, .consume_valid(issue_fire), .consume_mask,
        .wait_mask, .wait_ready(scoreboard_ready), .pending(pending_events),
        .completed(), .error(scoreboard_error),
        .error_code(scoreboard_error_code)
    );

    assign job_ready = state == Q_IDLE && !error;
    assign busy = state != Q_IDLE;
    assign descriptor_request_ready = state == Q_RUN && !descriptor_pending
        && rom_request_ready
        && descriptor_request_index < descriptor_count;
    assign lane0_valid = issue_fire && word_lane0_valid;
    assign lane1_valid = issue_fire && word_lane1_valid;
    assign lane0_command = instruction[99:52];
    assign lane0_descriptor = prefetched_descriptor;
    assign lane1_command = instruction[51:4];
    assign lane0_event = word_lane0_event;
    assign lane1_event = word_lane1_event;

    integer index;
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= Q_IDLE;
            rom_address <= 0;
            rom_request_valid <= 0;
            token_base <= 0;
            token_count <= 0;
            template_base <= 0;
            template_count <= 0;
            descriptor_base <= 0;
            descriptor_count <= 0;
            profile_n_bytes <= 0;
            profile_height <= 0;
            profile_stateful <= 0;
            pc <= 0;
            token <= 0;
            template_word <= 0;
            coordinate0 <= 0;
            coordinate1 <= 0;
            stride0 <= 0;
            stride1 <= 0;
            repeats_remaining <= 0;
            loop_sp <= 0;
            done <= 0;
            error <= 0;
            error_code <= 0;
            retired_words <= 0;
            retired_tokens <= 0;
            descriptor_pending <= 0;
            descriptor_half <= 0;
            descriptor_response_valid <= 0;
            descriptor_response_data <= 0;
            prefetched_descriptor <= 0;
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
            rom_request_valid <= 0;
            descriptor_response_valid <= 0;
            if (descriptor_pending) begin
                if (rom_data_valid) begin
                    descriptor_response_data <= descriptor_half
                        ? rom_data[127:64] : rom_data[63:0];
                    descriptor_response_valid <= 1;
                    descriptor_pending <= 0;
                end
            end else if (descriptor_request_valid
                    && descriptor_request_ready) begin
                rom_address <= descriptor_base
                    + {1'b0, descriptor_request_index[7:1]};
                rom_request_valid <= 1;
                descriptor_half <= descriptor_request_index[0];
                descriptor_pending <= 1;
            end
            if (scoreboard_error && !error) begin
                error <= 1;
                error_code <= ERR_EVENT + {5'b0, scoreboard_error_code};
                state <= Q_IDLE;
            end else case (state)
                Q_IDLE: if (job_valid && job_ready) begin
                    if (job_algorithm == 2'd3 || job_operation > 2'd1) begin
                        error <= 1;
                        error_code <= ERR_JOB;
                    end else begin
                        rom_address <= {6'b0, job_algorithm} + 1'b1;
                        rom_request_valid <= 1;
                        retired_words <= 0;
                        retired_tokens <= 0;
                        descriptor_pending <= 0;
                        loop_sp <= 0;
                        loop_bias0[0] <= 0;
                        loop_bias0[1] <= 0;
                        loop_bias1[0] <= 0;
                        loop_bias1[1] <= 0;
                        // Keep the operation until the directory is returned.
                        pc <= {7'b0, job_operation};
                        state <= Q_DIR_WAIT;
                    end
                end
                Q_DIR_WAIT: if (rom_data_valid) state <= Q_DIR_LOAD;
                Q_DIR_LOAD: begin
                    if (rom_data[1:0] == 2'd3
                            || rom_data[29:22] == 0
                            || rom_data[45:38] == 0
                            || rom_data[61:54] == 0) begin
                        error <= 1;
                        error_code <= ERR_DIRECTORY;
                        state <= Q_IDLE;
                    end else begin
                        profile_stateful <= rom_data[2];
                        profile_n_bytes <= rom_data[8:3];
                        profile_height <= rom_data[13:9];
                        token_base <= rom_data[21:14];
                        token_count <= rom_data[29:22];
                        template_base <= rom_data[37:30];
                        template_count <= rom_data[45:38];
                        descriptor_base <= rom_data[53:46];
                        descriptor_count <= rom_data[61:54];
                        pc <= pc[0] ? rom_data[79:71] : rom_data[70:62];
                        rom_address <= rom_data[21:14]
                            + (pc[0] ? rom_data[79:71] : rom_data[70:62]);
                        rom_request_valid <= 1;
                        state <= Q_TOKEN_WAIT;
                    end
                end
                Q_TOKEN_WAIT: if (rom_data_valid) state <= Q_TOKEN_LOAD;
                Q_TOKEN_LOAD: begin
                    token <= rom_data;
                    if (rom_data[127:126] == TOKEN_LOOP) begin
                        // Decode LOOP directly from the returned word.
                        if (|rom_data[59:0] || rom_data[113:108] == 0
                                || (rom_data[125:114] + 1'b1) > pc) begin
                            error <= 1;
                            error_code <= ERR_TOKEN;
                            state <= Q_IDLE;
                        end else if (loop_sp != 0
                                && loop_pc[loop_sp-1] == pc) begin
                            if (loop_remaining[loop_sp-1] > 1) begin
                                loop_remaining[loop_sp-1]
                                    <= loop_remaining[loop_sp-1] - 1'b1;
                                loop_bias0[loop_sp-1] <= loop_bias0[loop_sp-1]
                                    + loop_step0[loop_sp-1];
                                loop_bias1[loop_sp-1] <= loop_bias1[loop_sp-1]
                                    + loop_step1[loop_sp-1];
                                pc <= pc - (rom_data[125:114] + 1'b1);
                                rom_address <= token_base + pc
                                    - (rom_data[125:114] + 1'b1);
                                rom_request_valid <= 1;
                            end else begin
                                loop_bias0[loop_sp-1] <= 0;
                                loop_bias1[loop_sp-1] <= 0;
                                loop_sp <= loop_sp - 1'b1;
                                pc <= pc + 1'b1;
                                rom_address <= token_base + pc + 1'b1;
                                rom_request_valid <= 1;
                            end
                            retired_tokens <= retired_tokens + 1'b1;
                            state <= Q_TOKEN_WAIT;
                        end else if (loop_sp == 2) begin
                            error <= 1;
                            error_code <= ERR_LOOP;
                            state <= Q_IDLE;
                        end else begin
                            loop_pc[loop_sp] <= pc;
                            loop_remaining[loop_sp] <= rom_data[113:108];
                            loop_bias0[loop_sp] <= rom_data[107:84];
                            loop_bias1[loop_sp] <= rom_data[83:60];
                            loop_step0[loop_sp] <= rom_data[107:84];
                            loop_step1[loop_sp] <= rom_data[83:60];
                            loop_sp <= loop_sp + 1'b1;
                            pc <= pc - (rom_data[125:114] + 1'b1);
                            rom_address <= token_base + pc
                                - (rom_data[125:114] + 1'b1);
                            rom_request_valid <= 1;
                            retired_tokens <= retired_tokens + 1'b1;
                            state <= Q_TOKEN_WAIT;
                        end
                    end else if ((rom_data[127:126] == TOKEN_HALT
                                  && |rom_data[125:0])
                            || (rom_data[127:126] != TOKEN_HALT
                                && |rom_data[17:0])
                            || (rom_data[127:126] == TOKEN_SINGLE
                                && (rom_data[71:66] != 0
                                    || rom_data[65:18] != 0))
                            || (rom_data[127:126] == TOKEN_RUN
                                && rom_data[71:66] == 0)) begin
                        error <= 1;
                        error_code <= ERR_TOKEN;
                        state <= Q_IDLE;
                    end else if (rom_data[127:126] == TOKEN_HALT) begin
                        template_word <= 0;
                        state <= Q_RUN;
                    end else if (rom_data[125:120] >= template_count) begin
                        error <= 1;
                        error_code <= ERR_TEMPLATE;
                        state <= Q_IDLE;
                    end else begin
                        rom_address <= template_base + rom_data[125:120];
                        rom_request_valid <= 1;
                        state <= Q_TEMPLATE_WAIT;
                    end
                end
                Q_TEMPLATE_WAIT: if (rom_data_valid)
                    state <= Q_TEMPLATE_LOAD;
                Q_TEMPLATE_LOAD: begin
                    if (rom_data[127:124] != OP_ISSUE
                            || initial_coord0[24] || initial_coord1[24]) begin
                        error <= 1;
                        error_code <= ERR_TEMPLATE;
                        state <= Q_IDLE;
                    end else begin
                        template_word <= rom_data;
                        coordinate0 <= initial_coord0[23:0];
                        coordinate1 <= initial_coord1[23:0];
                        stride0 <= token_stride0;
                        stride1 <= token_stride1;
                        repeats_remaining <= token_repeat_minus_one;
                        if (profile_stateful && rom_data[107]) begin
                            rom_address <= descriptor_base
                                + {1'b0, rom_data[95:89]};
                            descriptor_half <= rom_data[88];
                            rom_request_valid <= 1;
                            state <= Q_ISSUE_DESC_WAIT;
                        end else
                            state <= Q_RUN;
                    end
                end
                Q_ISSUE_DESC_WAIT: if (rom_data_valid)
                    state <= Q_ISSUE_DESC_LOAD;
                Q_ISSUE_DESC_LOAD: begin
                    prefetched_descriptor <= descriptor_half
                        ? rom_data[127:64] : rom_data[63:0];
                    state <= Q_RUN;
                end
                Q_RUN: begin
                    if (token_kind == TOKEN_HALT) begin
                        if (pending_events == 0) begin
                            done <= 1;
                            retired_tokens <= retired_tokens + 1'b1;
                            state <= Q_IDLE;
                        end
                    end else if (issue_fire) begin
                        retired_words <= retired_words + 1'b1;
                        if (repeats_remaining != 0) begin
                            coordinate0 <= coordinate0 + stride0;
                            coordinate1 <= coordinate1 + stride1;
                            repeats_remaining <= repeats_remaining - 1'b1;
                        end else begin
                            pc <= pc + 1'b1;
                            rom_address <= token_base + pc + 1'b1;
                            rom_request_valid <= 1;
                            retired_tokens <= retired_tokens + 1'b1;
                            state <= Q_TOKEN_WAIT;
                        end
                    end
                end
                default: begin
                    error <= 1;
                    error_code <= ERR_TOKEN;
                    state <= Q_IDLE;
                end
            endcase
        end
    end
endmodule

`default_nettype wire
