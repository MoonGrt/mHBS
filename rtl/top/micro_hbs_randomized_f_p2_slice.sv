`timescale 1ns/1ps
`default_nettype none

// Autonomous randomized-F P=2 capability slice.
//
// A Job supplies only RFC 8391 source objects: public seed, address template,
// two n-byte nodes and a public WOTS+ chain bound.  The objects are captured
// once at Job acceptance.  HASH_LAYOUT requests then bind R[index] to address
// word 6 (the WOTS+ hash/chain-step address), derive lane 1's chain address as
// lane 0's address word 5 plus one, statically enable lanes through flags[1:0],
// and feed each digest back as the next step's local node.
// Complete SHAKE preimages are never present on this module's interface.
module micro_hbs_randomized_f_p2_slice #(
    parameter integer PROGRAM_WORDS = 512,
    parameter integer UNROLL = 2
) (
    input  wire         clk,
    input  wire         rst_n,

    input  wire         program_we,
    input  wire [8:0]   program_addr,
    input  wire [63:0]  program_wdata,

    input  wire         job_valid,
    output logic        job_ready,
    input  wire [8:0]   job_entry,
    input  wire [255:0] job_pub_seed,
    input  wire [255:0] job_address_template,
    input  wire [255:0] job_node0,
    input  wire [255:0] job_node1,
    input  wire [7:0]   job_chain_bound,

    output logic        busy,
    output logic        done,
    output logic        error,
    output logic [15:0] error_code,
    output logic [255:0] result_node0,
    output logic [255:0] result_node1,

    output logic         step_valid,
    output logic [31:0]  step_index,
    output logic [1:0]   step_lane_mask,
    output logic [255:0] step_node0,
    output logic [255:0] step_node1,

    output logic [31:0] accepted_job_commands,
    output logic [31:0] host_control_writes_during_busy,
    output logic [31:0] issued_hash_requests,
    output logic [31:0] retired_instructions,
    output logic [31:0] completed_steps,
    output logic [31:0] lane0_internal_hash_calls,
    output logic [31:0] lane1_internal_hash_calls,
    output logic [31:0] lane0_active_cycles,
    output logic [31:0] lane0_idle_cycles,
    output logic [31:0] lane1_active_cycles,
    output logic [31:0] lane1_idle_cycles
);
    localparam logic [15:0] LAYOUT_RANDOMIZED_F_P2 = 16'h0300;
    localparam logic [15:0] ERR_BAD_LANE_MASK      = 16'h0401;
    localparam logic [15:0] ERR_CHAIN_BOUND        = 16'h0402;
    localparam logic [15:0] ERR_UNSUPPORTED_LAYOUT = 16'h0403;
    localparam logic [15:0] ERR_RANDOMIZED_HASH    = 16'h0404;

    typedef enum logic [1:0] {F_IDLE, F_LAUNCH, F_WAIT} f_state_t;
    f_state_t f_state;

    logic seq_job_ready;
    wire seq_job_valid;
    wire job_accept;
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

    logic [255:0] saved_pub_seed;
    logic [255:0] saved_address;
    logic [7:0] saved_chain_bound;
    logic [255:0] current_node0;
    logic [255:0] current_node1;
    logic [31:0] saved_step_index;
    logic [1:0] saved_lane_mask;
    logic [1:0] pending_mask;
    logic [1:0] lane_active_mask;
    logic [255:0] indexed_address0;
    logic [255:0] indexed_address1;
    logic [31:0] lane0_chain_index;
    logic [31:0] lane1_chain_index;

    logic lane0_start;
    logic lane1_start;
    wire lane0_ready;
    wire lane1_ready;
    wire [255:0] lane0_digest;
    wire [255:0] lane1_digest;
    wire lane0_done;
    wire lane1_done;
    wire lane0_error;
    wire lane1_error;
    wire [2:0] lane0_hash_calls;
    wire [2:0] lane1_hash_calls;

    assign seq_job_valid = job_valid && !program_we;
    assign job_ready = seq_job_ready && !program_we;
    assign job_accept = seq_job_valid && seq_job_ready;
    assign result_node0 = current_node0;
    assign result_node1 = current_node1;
    assign hash_req_ready = (f_state == F_IDLE);

    always @(*) begin
        indexed_address0 = saved_address;
        indexed_address1 = saved_address;
        lane0_chain_index = {
            saved_address[8*20 +: 8], saved_address[8*21 +: 8],
            saved_address[8*22 +: 8], saved_address[8*23 +: 8]
        };
        lane1_chain_index = lane0_chain_index + 1'b1;
        indexed_address1[8*20 +: 8] = lane1_chain_index[31:24];
        indexed_address1[8*21 +: 8] = lane1_chain_index[23:16];
        indexed_address1[8*22 +: 8] = lane1_chain_index[15:8];
        indexed_address1[8*23 +: 8] = lane1_chain_index[7:0];
        // XMSS ADRS words are serialized big-endian; packed byte zero is LSB.
        indexed_address0[8*24 +: 8] = saved_step_index[31:24];
        indexed_address0[8*25 +: 8] = saved_step_index[23:16];
        indexed_address0[8*26 +: 8] = saved_step_index[15:8];
        indexed_address0[8*27 +: 8] = saved_step_index[7:0];
        indexed_address1[8*24 +: 8] = saved_step_index[31:24];
        indexed_address1[8*25 +: 8] = saved_step_index[23:16];
        indexed_address1[8*26 +: 8] = saved_step_index[15:8];
        indexed_address1[8*27 +: 8] = saved_step_index[7:0];
    end

    micro_hbs_sequencer #(.PROGRAM_WORDS(PROGRAM_WORDS)) sequencer (
        .clk, .rst_n, .program_we, .program_addr, .program_wdata,
        .job_valid(seq_job_valid), .job_ready(seq_job_ready), .job_entry,
        .busy, .done, .error, .error_code,
        .hash_req_valid, .hash_req_ready, .hash_layout_id, .hash_lane_mask,
        .hash_dest, .hash_index_reg, .hash_index_value,
        .hash_rsp_valid, .hash_rsp_error, .hash_rsp_error_code,
        .dynamic_bound_req, .dynamic_bound_addr(),
        .dynamic_bound_valid(dynamic_bound_req
            && saved_chain_bound >= 1 && saved_chain_bound <= 15),
        .dynamic_bound_value(saved_chain_bound),
        .dynamic_bound_error(dynamic_bound_req
            && (saved_chain_bound == 0 || saved_chain_bound > 15)),
        .dynamic_bound_error_code(ERR_CHAIN_BOUND),
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

    micro_hbs_randomized_hash #(.NODE_COUNT(1), .UNROLL(UNROLL)) lane0 (
        .clk, .rst_n, .start(lane0_start), .ready(lane0_ready),
        .pub_seed(saved_pub_seed), .address(indexed_address0),
        .node_data({256'b0, current_node0}), .digest(lane0_digest),
        .done(lane0_done), .error(lane0_error),
        .hash_calls(lane0_hash_calls)
    );

    micro_hbs_randomized_hash #(.NODE_COUNT(1), .UNROLL(UNROLL)) lane1 (
        .clk, .rst_n, .start(lane1_start), .ready(lane1_ready),
        .pub_seed(saved_pub_seed), .address(indexed_address1),
        .node_data({256'b0, current_node1}), .digest(lane1_digest),
        .done(lane1_done), .error(lane1_error),
        .hash_calls(lane1_hash_calls)
    );

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            f_state <= F_IDLE;
            saved_pub_seed <= '0;
            saved_address <= '0;
            saved_chain_bound <= '0;
            current_node0 <= '0;
            current_node1 <= '0;
            saved_step_index <= '0;
            saved_lane_mask <= '0;
            pending_mask <= '0;
            lane_active_mask <= '0;
            lane0_start <= 1'b0;
            lane1_start <= 1'b0;
            hash_rsp_valid <= 1'b0;
            hash_rsp_error <= 1'b0;
            hash_rsp_error_code <= '0;
            step_valid <= 1'b0;
            step_index <= '0;
            step_lane_mask <= '0;
            step_node0 <= '0;
            step_node1 <= '0;
            completed_steps <= '0;
            lane0_internal_hash_calls <= '0;
            lane1_internal_hash_calls <= '0;
            lane0_active_cycles <= '0;
            lane0_idle_cycles <= '0;
            lane1_active_cycles <= '0;
            lane1_idle_cycles <= '0;
        end else begin
            lane0_start <= 1'b0;
            lane1_start <= 1'b0;
            hash_rsp_valid <= 1'b0;
            hash_rsp_error <= 1'b0;
            hash_rsp_error_code <= '0;
            step_valid <= 1'b0;

            if (job_accept) begin
                f_state <= F_IDLE;
                saved_pub_seed <= job_pub_seed;
                saved_address <= job_address_template;
                saved_chain_bound <= job_chain_bound;
                current_node0 <= job_node0;
                current_node1 <= job_node1;
                saved_step_index <= '0;
                saved_lane_mask <= '0;
                pending_mask <= '0;
                lane_active_mask <= '0;
                step_index <= '0;
                step_lane_mask <= '0;
                step_node0 <= '0;
                step_node1 <= '0;
                completed_steps <= 0;
                lane0_internal_hash_calls <= 0;
                lane1_internal_hash_calls <= 0;
                lane0_active_cycles <= 0;
                lane0_idle_cycles <= 0;
                lane1_active_cycles <= 0;
                lane1_idle_cycles <= 0;
            end else begin
                if (busy) begin
                    if (lane_active_mask[0])
                        lane0_active_cycles <= lane0_active_cycles + 1'b1;
                    else
                        lane0_idle_cycles <= lane0_idle_cycles + 1'b1;
                    if (lane_active_mask[1])
                        lane1_active_cycles <= lane1_active_cycles + 1'b1;
                    else
                        lane1_idle_cycles <= lane1_idle_cycles + 1'b1;
                end

                case (f_state)
                    F_IDLE: begin
                        lane_active_mask <= 2'b00;
                        pending_mask <= 2'b00;
                        if (hash_req_valid) begin
                            if (hash_layout_id != LAYOUT_RANDOMIZED_F_P2) begin
                                hash_rsp_error <= 1'b1;
                                hash_rsp_error_code <= ERR_UNSUPPORTED_LAYOUT;
                            end else if (hash_lane_mask != 2'b01
                                && hash_lane_mask != 2'b11) begin
                                hash_rsp_error <= 1'b1;
                                hash_rsp_error_code <= ERR_BAD_LANE_MASK;
                            end else begin
                                saved_step_index <= hash_index_value;
                                saved_lane_mask <= hash_lane_mask;
                                f_state <= F_LAUNCH;
                            end
                        end
                    end

                    F_LAUNCH: begin
                        if (lane0_ready
                            && (!saved_lane_mask[1] || lane1_ready)) begin
                            lane0_start <= 1'b1;
                            lane1_start <= saved_lane_mask[1];
                            pending_mask <= saved_lane_mask;
                            lane_active_mask <= saved_lane_mask;
                            f_state <= F_WAIT;
                        end
                    end

                    F_WAIT: begin
                        if ((pending_mask[0] && lane0_error)
                            || (pending_mask[1] && lane1_error)) begin
                            lane_active_mask <= 2'b00;
                            pending_mask <= 2'b00;
                            hash_rsp_error <= 1'b1;
                            hash_rsp_error_code <= ERR_RANDOMIZED_HASH;
                            f_state <= F_IDLE;
                        end else begin
                            if (pending_mask[0] && lane0_done) begin
                                current_node0 <= lane0_digest;
                                pending_mask[0] <= 1'b0;
                                lane0_internal_hash_calls
                                    <= lane0_internal_hash_calls
                                    + {{29{1'b0}}, lane0_hash_calls};
                            end
                            if (pending_mask[1] && lane1_done) begin
                                current_node1 <= lane1_digest;
                                pending_mask[1] <= 1'b0;
                                lane1_internal_hash_calls
                                    <= lane1_internal_hash_calls
                                    + {{29{1'b0}}, lane1_hash_calls};
                            end

                            if ((pending_mask
                                & ~{lane1_done, lane0_done}) == 2'b00) begin
                                step_valid <= 1'b1;
                                step_index <= saved_step_index;
                                step_lane_mask <= saved_lane_mask;
                                step_node0 <= lane0_done
                                    ? lane0_digest : current_node0;
                                step_node1 <= lane1_done
                                    ? lane1_digest : current_node1;
                                completed_steps <= completed_steps + 1'b1;
                                lane_active_mask <= 2'b00;
                                pending_mask <= 2'b00;
                                hash_rsp_valid <= 1'b1;
                                f_state <= F_IDLE;
                            end
                        end
                    end

                    default: begin
                        lane_active_mask <= 2'b00;
                        pending_mask <= 2'b00;
                        hash_rsp_error <= 1'b1;
                        hash_rsp_error_code <= ERR_RANDOMIZED_HASH;
                        f_state <= F_IDLE;
                    end
                endcase
            end
        end
    end
endmodule

`default_nettype wire
