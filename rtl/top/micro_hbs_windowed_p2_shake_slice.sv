`timescale 1ns/1ps
`default_nettype none

// One-Job, windowed P=2/U2 vertical slice.  Program and message records are
// host-writable only before Job acceptance.  Once busy, the sequencer alone
// generates pair requests and the adapter alone reads both message banks.
module micro_hbs_windowed_p2_shake_slice #(
    parameter integer PROGRAM_WORDS = 64,
    parameter integer PAIR_CAPACITY = 8,
    parameter integer UNROLL = 2
) (
    input  wire         clk,
    input  wire         rst_n,
    input  wire         program_we,
    input  wire [8:0]   program_addr,
    input  wire [63:0]  program_wdata,

    input  wire         host_message_write_valid,
    output logic        host_message_write_ready,
    input  wire         host_message_bank,
    input  wire [15:0]  host_message_address,
    input  wire [63:0]  host_message_write_data,
    output logic        host_message_bounds_error,

    input  wire         job_valid,
    output logic        job_ready,
    input  wire [8:0]   job_entry,
    output logic        busy,
    output logic        done,
    output logic        error,
    output logic [15:0] error_code,

    input  wire [15:0]  result_read_pair,
    output logic [255:0] result_lane0,
    output logic [255:0] result_lane1,
    output logic [1:0]  result_lane_mask,

    output logic        pair_dispatch_valid,
    output logic [1:0]  pair_dispatch_lane_mask,
    output logic [15:0] pair_dispatch_index,
    output logic [31:0] accepted_job_commands,
    output logic [31:0] host_control_writes_during_busy,
    output logic [31:0] host_message_writes_rejected_busy,
    output logic [31:0] issued_hash_requests,
    output logic [31:0] retired_instructions,
    output logic [31:0] lane0_active_cycles,
    output logic [31:0] lane0_idle_cycles,
    output logic [31:0] lane1_active_cycles,
    output logic [31:0] lane1_idle_cycles,
    output logic [31:0] compose_cycles
);
    localparam integer RECORD_WORDS = 18;
    localparam integer WORDS_PER_BANK = PAIR_CAPACITY * RECORD_WORDS;

    logic seq_job_ready;
    wire seq_job_valid;
    wire job_accept;
    wire bank_engine_active;

    logic hash_req_valid;
    logic hash_req_ready;
    logic [15:0] hash_layout_id;
    logic [1:0] hash_lane_mask;
    logic [7:0] hash_dest;
    logic [7:0] hash_index_reg;
    logic [31:0] hash_index_value;
    logic hash_rsp_valid;
    logic hash_rsp_error;
    logic [15:0] hash_rsp_error_code;

    logic bank0_read_valid;
    logic bank0_read_ready;
    logic [15:0] bank0_read_address;
    logic bank0_response_valid;
    logic [63:0] bank0_read_data;
    logic bank0_bounds_error;
    logic bank1_read_valid;
    logic bank1_read_ready;
    logic [15:0] bank1_read_address;
    logic bank1_response_valid;
    logic [63:0] bank1_read_data;
    logic bank1_bounds_error;
    logic adapter_composing;
    logic [1:0] adapter_lane_active_mask;

    assign seq_job_valid = job_valid && !host_message_write_valid && !program_we;
    assign job_ready = seq_job_ready && !host_message_write_valid && !program_we;
    assign job_accept = seq_job_valid && seq_job_ready;
    assign bank_engine_active = busy || job_accept;

    micro_hbs_sequencer #(.PROGRAM_WORDS(PROGRAM_WORDS)) sequencer (
        .clk, .rst_n, .program_we, .program_addr, .program_wdata,
        .job_valid(seq_job_valid), .job_ready(seq_job_ready), .job_entry,
        .busy, .done, .error, .error_code,
        .hash_req_valid, .hash_req_ready, .hash_layout_id, .hash_lane_mask,
        .hash_dest, .hash_index_reg, .hash_index_value, .hash_rsp_valid,
        .hash_rsp_error, .hash_rsp_error_code,
        .dynamic_bound_req(), .dynamic_bound_addr(),
        .dynamic_bound_valid(1'b0), .dynamic_bound_value(8'h00),
        .dynamic_bound_error(1'b0), .dynamic_bound_error_code(16'h0000),
        .data_req_valid(), .data_req_ready(1'b1), .data_req_opcode(),
        .data_req_flags(), .data_req_rd(), .data_req_rs(), .data_req_imm(),
        .data_req_rs_value(), .data_rsp_valid(1'b0), .data_rsp_error(1'b1),
        .data_rsp_error_code(16'h0104),
        .data_rsp_reg_write(1'b0), .data_rsp_reg_index(8'h00),
        .data_rsp_reg_value(32'h00000000),
        .tree_req_valid(), .tree_req_ready(1'b1), .tree_req_flags(),
        .tree_req_rd(), .tree_req_rs(), .tree_req_imm(), .tree_req_rs_value(),
        .tree_rsp_valid(1'b0), .tree_rsp_error(1'b1),
        .tree_rsp_error_code(16'h0104),
        .accepted_job_commands, .host_control_writes_during_busy,
        .issued_hash_requests, .issued_data_requests(), .issued_tree_requests(),
        .retired_instructions
    );

    micro_hbs_dual_message_bank64 #(
        .WORDS_PER_BANK(WORDS_PER_BANK)
    ) message_banks (
        .clk, .rst_n, .engine_active(bank_engine_active),
        .host_write_valid(host_message_write_valid),
        .host_write_ready(host_message_write_ready),
        .host_bank_select(host_message_bank),
        .host_write_address(host_message_address),
        .host_write_data(host_message_write_data),
        .host_bounds_error(host_message_bounds_error),
        .engine0_read_valid(bank0_read_valid),
        .engine0_read_ready(bank0_read_ready),
        .engine0_read_address(bank0_read_address),
        .engine0_response_valid(bank0_response_valid),
        .engine0_read_data(bank0_read_data),
        .engine0_bounds_error(bank0_bounds_error),
        .engine1_read_valid(bank1_read_valid),
        .engine1_read_ready(bank1_read_ready),
        .engine1_read_address(bank1_read_address),
        .engine1_response_valid(bank1_response_valid),
        .engine1_read_data(bank1_read_data),
        .engine1_bounds_error(bank1_bounds_error)
    );

    micro_hbs_static_p2_window_adapter #(
        .PAIR_CAPACITY(PAIR_CAPACITY), .UNROLL(UNROLL)
    ) adapter (
        .clk, .rst_n, .job_begin(job_accept),
        .req_valid(hash_req_valid), .req_ready(hash_req_ready),
        .layout_id(hash_layout_id), .lane_mask(hash_lane_mask),
        .index_value(hash_index_value), .rsp_valid(hash_rsp_valid),
        .rsp_error(hash_rsp_error), .rsp_error_code(hash_rsp_error_code),
        .bank0_read_valid, .bank0_read_ready, .bank0_read_address,
        .bank0_response_valid, .bank0_read_data, .bank0_bounds_error,
        .bank1_read_valid, .bank1_read_ready, .bank1_read_address,
        .bank1_response_valid, .bank1_read_data, .bank1_bounds_error,
        .result_read_pair, .result_lane0, .result_lane1, .result_lane_mask,
        .composing(adapter_composing),
        .lane_active_mask(adapter_lane_active_mask),
        .pair_dispatch_valid, .pair_dispatch_lane_mask,
        .pair_dispatch_index
    );

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            host_message_writes_rejected_busy <= '0;
            lane0_active_cycles <= '0;
            lane0_idle_cycles <= '0;
            lane1_active_cycles <= '0;
            lane1_idle_cycles <= '0;
            compose_cycles <= '0;
        end else begin
            if (host_message_write_valid && busy)
                host_message_writes_rejected_busy
                    <= host_message_writes_rejected_busy + 1'b1;

            if (job_accept) begin
                lane0_active_cycles <= 0;
                lane0_idle_cycles <= 0;
                lane1_active_cycles <= 0;
                lane1_idle_cycles <= 0;
                compose_cycles <= 0;
            end else if (busy) begin
                if (adapter_lane_active_mask[0])
                    lane0_active_cycles <= lane0_active_cycles + 1'b1;
                else
                    lane0_idle_cycles <= lane0_idle_cycles + 1'b1;
                if (adapter_lane_active_mask[1])
                    lane1_active_cycles <= lane1_active_cycles + 1'b1;
                else
                    lane1_idle_cycles <= lane1_idle_cycles + 1'b1;
                if (adapter_composing)
                    compose_cycles <= compose_cycles + 1'b1;
            end
        end
    end
endmodule

`default_nettype wire
