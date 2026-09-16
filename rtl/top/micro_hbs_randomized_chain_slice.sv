`timescale 1ns/1ps
`default_nettype none

// Autonomous single-lane vertical slice: program store + sequencer + bounded
// Scratchpad + layout adapter + randomized F + real SHAKE256/Keccak-p[1600].
// Host Scratchpad access is permitted only while the engine is idle.
module micro_hbs_randomized_chain_slice #(
    parameter integer PROGRAM_WORDS = 512,
    parameter integer SCRATCH_WORDS = 32,
    parameter integer UNROLL = 2
) (
    input  wire         clk,
    input  wire         rst_n,
    input  wire         program_we,
    input  wire [8:0]   program_addr,
    input  wire [63:0]  program_wdata,

    input  wire         host_sp_valid,
    output logic        host_sp_ready,
    input  wire         host_sp_write,
    input  wire [15:0]  host_sp_address,
    input  wire [63:0]  host_sp_write_data,
    output logic        host_sp_response_valid,
    output logic [63:0] host_sp_read_data,
    output logic        host_sp_bounds_error,

    input  wire         job_valid,
    output logic        job_ready,
    input  wire [8:0]   job_entry,
    output logic        busy,
    output logic        done,
    output logic        error,
    output logic [15:0] error_code,
    output logic [255:0] result,
    output logic [31:0] accepted_job_commands,
    output logic [31:0] host_control_writes_during_busy,
    output logic [31:0] issued_hash_requests,
    output logic [31:0] retired_instructions,
    output logic [31:0] scratch_reads,
    output logic [31:0] scratch_writes,
    output logic [31:0] internal_hash_calls
);
    localparam logic [15:0] ERR_SCRATCH_BOUNDS = 16'h0201;
    localparam logic [1:0] OWNER_NONE = 2'd0;
    localparam logic [1:0] OWNER_HOST = 2'd1;
    localparam logic [1:0] OWNER_BOUND = 2'd2;
    localparam logic [1:0] OWNER_ADAPTER = 2'd3;

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
    logic dynamic_bound_req;
    logic [15:0] dynamic_bound_addr;
    logic dynamic_bound_valid;
    logic [7:0] dynamic_bound_value;
    logic dynamic_bound_error;

    logic adapter_sp_req_valid;
    logic adapter_sp_req_ready;
    logic adapter_sp_req_write;
    logic [15:0] adapter_sp_req_address;
    logic [63:0] adapter_sp_req_write_data;
    logic adapter_sp_rsp_valid;
    logic adapter_sp_bounds_error;

    logic sp_req_valid;
    logic sp_req_ready;
    logic sp_req_write;
    logic [15:0] sp_req_address;
    logic [63:0] sp_req_write_data;
    logic sp_rsp_valid;
    logic [63:0] sp_rsp_read_data;
    logic sp_bounds_error;
    logic [1:0] read_owner;
    wire host_selected;
    wire bound_selected;
    wire adapter_selected;

    assign host_selected = !busy && read_owner == OWNER_NONE;
    assign bound_selected = busy && read_owner == OWNER_NONE && dynamic_bound_req;
    assign adapter_selected = busy && read_owner == OWNER_NONE && !dynamic_bound_req;

    always_comb begin
        sp_req_valid = 1'b0;
        sp_req_write = 1'b0;
        sp_req_address = '0;
        sp_req_write_data = '0;
        host_sp_ready = 1'b0;
        adapter_sp_req_ready = 1'b0;

        if (host_selected) begin
            sp_req_valid = host_sp_valid;
            sp_req_write = host_sp_write;
            sp_req_address = host_sp_address;
            sp_req_write_data = host_sp_write_data;
            host_sp_ready = sp_req_ready;
        end else if (bound_selected) begin
            if (dynamic_bound_addr < SCRATCH_WORDS) begin
                sp_req_valid = 1'b1;
                sp_req_address = dynamic_bound_addr;
            end
        end else if (adapter_selected) begin
            sp_req_valid = adapter_sp_req_valid;
            sp_req_write = adapter_sp_req_write;
            sp_req_address = adapter_sp_req_address;
            sp_req_write_data = adapter_sp_req_write_data;
            adapter_sp_req_ready = sp_req_ready;
        end
    end

    assign host_sp_response_valid = sp_rsp_valid && read_owner == OWNER_HOST;
    assign host_sp_read_data = sp_rsp_read_data;
    assign host_sp_bounds_error = sp_bounds_error &&
                                  (read_owner == OWNER_HOST || host_selected);
    assign dynamic_bound_valid = sp_rsp_valid && read_owner == OWNER_BOUND;
    assign dynamic_bound_value = sp_rsp_read_data[7:0];
    assign dynamic_bound_error = dynamic_bound_req &&
                                 dynamic_bound_addr >= SCRATCH_WORDS;
    assign adapter_sp_rsp_valid = sp_rsp_valid && read_owner == OWNER_ADAPTER;
    assign adapter_sp_bounds_error = sp_bounds_error && read_owner == OWNER_ADAPTER;

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            read_owner <= OWNER_NONE;
        end else begin
            if (sp_rsp_valid || sp_bounds_error)
                read_owner <= OWNER_NONE;
            if (sp_req_valid && sp_req_ready && !sp_req_write) begin
                if (host_selected)
                    read_owner <= OWNER_HOST;
                else if (bound_selected)
                    read_owner <= OWNER_BOUND;
                else
                    read_owner <= OWNER_ADAPTER;
            end
        end
    end

    micro_hbs_sequencer #(.PROGRAM_WORDS(PROGRAM_WORDS)) sequencer (
        .clk, .rst_n, .program_we, .program_addr, .program_wdata,
        .job_valid, .job_ready, .job_entry, .busy, .done, .error, .error_code,
        .hash_req_valid, .hash_req_ready, .hash_layout_id, .hash_lane_mask,
        .hash_dest, .hash_index_reg, .hash_index_value, .hash_rsp_valid,
        .hash_rsp_error, .hash_rsp_error_code, .dynamic_bound_req,
        .dynamic_bound_addr, .dynamic_bound_valid, .dynamic_bound_value,
        .dynamic_bound_error, .dynamic_bound_error_code(ERR_SCRATCH_BOUNDS),
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

    micro_hbs_randomized_f_scratch_adapter #(
        .SCRATCH_WORDS(SCRATCH_WORDS), .UNROLL(UNROLL)
    ) adapter (
        .clk, .rst_n, .req_valid(hash_req_valid), .req_ready(hash_req_ready),
        .layout_id(hash_layout_id), .lane_mask(hash_lane_mask),
        .destination(hash_dest), .index_value(hash_index_value),
        .rsp_valid(hash_rsp_valid), .rsp_error(hash_rsp_error),
        .rsp_error_code(hash_rsp_error_code),
        .sp_req_valid(adapter_sp_req_valid), .sp_req_ready(adapter_sp_req_ready),
        .sp_req_write(adapter_sp_req_write), .sp_req_address(adapter_sp_req_address),
        .sp_req_write_data(adapter_sp_req_write_data),
        .sp_rsp_valid(adapter_sp_rsp_valid), .sp_rsp_read_data(sp_rsp_read_data),
        .sp_bounds_error(adapter_sp_bounds_error), .last_digest(result),
        .scratch_reads, .scratch_writes, .internal_hash_calls
    );

    micro_hbs_scratchpad64 #(.WORDS(SCRATCH_WORDS)) scratchpad (
        .clk, .rst_n, .request_valid(sp_req_valid), .request_ready(sp_req_ready),
        .request_write(sp_req_write), .request_address(sp_req_address),
        .request_write_data(sp_req_write_data), .response_valid(sp_rsp_valid),
        .response_read_data(sp_rsp_read_data), .bounds_error(sp_bounds_error),
        .scrub_start(1'b0), .scrub_busy(), .scrub_done()
    );
endmodule

`default_nettype wire
