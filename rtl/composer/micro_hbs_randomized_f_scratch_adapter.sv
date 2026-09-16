`timescale 1ns/1ps
`default_nettype none

// Scratchpad-backed implementation of one versioned layout capability.
//
// Layout 0x0100:
//   words 0..3  = 32-byte public seed
//   words 4..7  = 32-byte address template
//   words dest..dest+3 = 32-byte input/output node
//   address word 6 is bound to HASH_LAYOUT's index register value
//
// The adapter performs every memory read, randomized-F sub-hash and writeback
// after one sequencer request. It has no algorithm selector or task ingress.
module micro_hbs_randomized_f_scratch_adapter #(
    parameter integer SCRATCH_WORDS = 32,
    parameter integer UNROLL = 2
) (
    input  wire         clk,
    input  wire         rst_n,

    input  wire         req_valid,
    output logic        req_ready,
    input  wire [15:0]  layout_id,
    input  wire [1:0]   lane_mask,
    input  wire [7:0]   destination,
    input  wire [31:0]  index_value,
    output logic        rsp_valid,
    output logic        rsp_error,
    output logic [15:0] rsp_error_code,

    output logic        sp_req_valid,
    input  wire         sp_req_ready,
    output logic        sp_req_write,
    output logic [15:0] sp_req_address,
    output logic [63:0] sp_req_write_data,
    input  wire         sp_rsp_valid,
    input  wire [63:0]  sp_rsp_read_data,
    input  wire         sp_bounds_error,

    output logic [255:0] last_digest,
    output logic [31:0]  scratch_reads,
    output logic [31:0]  scratch_writes,
    output logic [31:0]  internal_hash_calls
);
    localparam logic [15:0] LAYOUT_RANDOMIZED_F_ADDR_WORD6 = 16'h0100;
    localparam logic [15:0] ERR_UNSUPPORTED_LAYOUT = 16'h0101;
    localparam logic [15:0] ERR_BAD_LANE_MASK      = 16'h0103;
    localparam logic [15:0] ERR_SCRATCH_BOUNDS     = 16'h0201;
    localparam logic [15:0] ERR_HASH               = 16'h0301;

    typedef enum logic [2:0] {
        S_IDLE, S_READ_REQ, S_READ_WAIT, S_HASH_START, S_HASH_WAIT,
        S_WRITE_REQ
    } state_t;
    state_t state;

    logic [7:0] saved_destination;
    logic [31:0] saved_index;
    logic [4:0] transfer_index;
    logic [255:0] saved_seed;
    logic [255:0] saved_address;
    logic [255:0] saved_node;
    logic randomized_start;
    wire randomized_ready;
    wire [255:0] randomized_digest;
    wire randomized_done;
    wire randomized_error;
    wire [2:0] randomized_hash_calls;
    logic [255:0] indexed_address;

    assign req_ready = (state == S_IDLE);
    assign randomized_start = (state == S_HASH_START) && randomized_ready;

    always @* begin
        indexed_address = saved_address;
        // Packed byte zero is bits [7:0]. XMSS address words are big endian.
        indexed_address[8*24 +: 8] = saved_index[31:24];
        indexed_address[8*25 +: 8] = saved_index[23:16];
        indexed_address[8*26 +: 8] = saved_index[15:8];
        indexed_address[8*27 +: 8] = saved_index[7:0];

        sp_req_valid = 1'b0;
        sp_req_write = 1'b0;
        sp_req_address = '0;
        sp_req_write_data = '0;
        if (state == S_READ_REQ) begin
            sp_req_valid = 1'b1;
            if (transfer_index < 4)
                sp_req_address = transfer_index;
            else if (transfer_index < 8)
                sp_req_address = transfer_index;
            else
                sp_req_address = saved_destination + transfer_index - 8;
        end else if (state == S_WRITE_REQ) begin
            sp_req_valid = 1'b1;
            sp_req_write = 1'b1;
            sp_req_address = saved_destination + transfer_index;
            sp_req_write_data = last_digest[64*transfer_index +: 64];
        end
    end

    micro_hbs_randomized_hash #(.NODE_COUNT(1), .UNROLL(UNROLL)) randomized_f (
        .clk,
        .rst_n,
        .start(randomized_start),
        .ready(randomized_ready),
        .pub_seed(saved_seed),
        .address(indexed_address),
        .node_data({256'b0, saved_node}),
        .digest(randomized_digest),
        .done(randomized_done),
        .error(randomized_error),
        .hash_calls(randomized_hash_calls)
    );

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= S_IDLE;
            saved_destination <= '0;
            saved_index <= '0;
            transfer_index <= '0;
            saved_seed <= '0;
            saved_address <= '0;
            saved_node <= '0;
            rsp_valid <= 1'b0;
            rsp_error <= 1'b0;
            rsp_error_code <= '0;
            last_digest <= '0;
            scratch_reads <= '0;
            scratch_writes <= '0;
            internal_hash_calls <= '0;
        end else begin
            rsp_valid <= 1'b0;
            rsp_error <= 1'b0;
            rsp_error_code <= '0;
            case (state)
                S_IDLE: if (req_valid) begin
                    if (layout_id != LAYOUT_RANDOMIZED_F_ADDR_WORD6) begin
                        rsp_error <= 1'b1;
                        rsp_error_code <= ERR_UNSUPPORTED_LAYOUT;
                    end else if (lane_mask != 2'b01) begin
                        rsp_error <= 1'b1;
                        rsp_error_code <= ERR_BAD_LANE_MASK;
                    end else if (destination < 8 || destination + 4 > SCRATCH_WORDS) begin
                        rsp_error <= 1'b1;
                        rsp_error_code <= ERR_SCRATCH_BOUNDS;
                    end else begin
                        saved_destination <= destination;
                        saved_index <= index_value;
                        transfer_index <= '0;
                        state <= S_READ_REQ;
                    end
                end

                S_READ_REQ: if (sp_req_ready) begin
                    state <= S_READ_WAIT;
                end

                S_READ_WAIT: begin
                    if (sp_bounds_error) begin
                        rsp_error <= 1'b1;
                        rsp_error_code <= ERR_SCRATCH_BOUNDS;
                        state <= S_IDLE;
                    end else if (sp_rsp_valid) begin
                        if (transfer_index < 4)
                            saved_seed[64*transfer_index +: 64] <= sp_rsp_read_data;
                        else if (transfer_index < 8)
                            saved_address[64*(transfer_index-4) +: 64] <= sp_rsp_read_data;
                        else
                            saved_node[64*(transfer_index-8) +: 64] <= sp_rsp_read_data;
                        scratch_reads <= scratch_reads + 1'b1;
                        if (transfer_index == 11) begin
                            transfer_index <= '0;
                            state <= S_HASH_START;
                        end else begin
                            transfer_index <= transfer_index + 1'b1;
                            state <= S_READ_REQ;
                        end
                    end
                end

                S_HASH_START: if (randomized_ready) begin
                    state <= S_HASH_WAIT;
                end

                S_HASH_WAIT: begin
                    if (randomized_error) begin
                        rsp_error <= 1'b1;
                        rsp_error_code <= ERR_HASH;
                        state <= S_IDLE;
                    end else if (randomized_done) begin
                        last_digest <= randomized_digest;
                        internal_hash_calls <= internal_hash_calls + randomized_hash_calls;
                        transfer_index <= '0;
                        state <= S_WRITE_REQ;
                    end
                end

                S_WRITE_REQ: begin
                    if (sp_bounds_error) begin
                        rsp_error <= 1'b1;
                        rsp_error_code <= ERR_SCRATCH_BOUNDS;
                        state <= S_IDLE;
                    end else if (sp_req_ready) begin
                        scratch_writes <= scratch_writes + 1'b1;
                        if (transfer_index == 3) begin
                            rsp_valid <= 1'b1;
                            state <= S_IDLE;
                        end else begin
                            transfer_index <= transfer_index + 1'b1;
                        end
                    end
                end

                default: begin
                    rsp_error <= 1'b1;
                    rsp_error_code <= ERR_HASH;
                    state <= S_IDLE;
                end
            endcase
        end
    end
endmodule

`default_nettype wire
