`timescale 1ns/1ps
`default_nettype none

// RFC 8391 XMSS-SHAKE256_10_256 WOTS+ public-key and L-tree leaf engine.
//
// One accepted request autonomously performs:
//   67 PRF_keygen calls, 67 * 15 randomized-F chain steps, and
//   66 randomized-H L-tree reductions.
// It has no task ingress, run-time scheduler, or externally supplied chain
// decisions. Byte zero of every packed byte string is in bits [7:0].
module micro_hbs_xmss_wots_leaf #(
    parameter integer UNROLL = 2
) (
    input  wire         clk,
    input  wire         rst_n,
    input  wire         req_valid,
    output wire         req_ready,
    input  wire [255:0] sk_seed,
    input  wire [255:0] pub_seed,
    input  wire [255:0] address_template,
    input  wire [31:0]  leaf_index,
    output logic        rsp_valid,
    input  wire         rsp_ready,
    output logic [255:0] leaf,
    output logic        rsp_error,
    output logic [31:0] prf_keygen_calls,
    output logic [31:0] chain_steps,
    output logic [31:0] ltree_parents,
    output logic [31:0] shake_calls
);
    localparam integer WOTS_LEN = 67;
    localparam integer WOTS_STEPS = 15;

    typedef enum logic [3:0] {
        S_IDLE, S_PRF_START, S_PRF_WAIT, S_F_START, S_F_WAIT,
        S_L_CHECK, S_H_START, S_H_WAIT, S_L_CARRY, S_RESP
    } state_t;
    state_t state;

    logic [255:0] saved_sk_seed;
    logic [255:0] saved_pub_seed;
    logic [255:0] saved_address;
    logic [31:0] saved_leaf_index;
    logic [6:0] chain_index;
    logic [3:0] chain_step;
    logic [6:0] node_count;
    logic [6:0] pair_index;
    logic [2:0] ltree_height;
    logic [255:0] work_node;
    (* ram_style = "distributed" *) logic [255:0] nodes [0:WOTS_LEN-1];

    logic [1087:0] prf_message;
    logic prf_start;
    wire prf_ready, prf_done, prf_error;
    wire [255:0] prf_digest;

    logic f_start;
    wire f_ready, f_done, f_error;
    wire [255:0] f_digest;
    wire [2:0] f_hash_calls;
    logic [255:0] f_address;

    logic h_start;
    wire h_ready, h_done, h_error;
    wire [255:0] h_digest;
    wire [2:0] h_hash_calls;
    logic [255:0] h_address;
    logic [511:0] h_nodes;
    integer byte_index;

    assign req_ready = (state == S_IDLE);
    assign prf_start = (state == S_PRF_START) && prf_ready;
    assign f_start = (state == S_F_START) && f_ready;
    assign h_start = (state == S_H_START) && h_ready;

    function automatic [255:0] set_address_word;
        input [255:0] original;
        input integer word_index;
        input [31:0] value;
        reg [255:0] result;
        begin
            result = original;
            // RFC address words are serialized most-significant byte first.
            result[8*(4*word_index+0) +: 8] = value[31:24];
            result[8*(4*word_index+1) +: 8] = value[23:16];
            result[8*(4*word_index+2) +: 8] = value[15:8];
            result[8*(4*word_index+3) +: 8] = value[7:0];
            set_address_word = result;
        end
    endfunction

    always_comb begin
        f_address = saved_address;
        f_address = set_address_word(f_address, 3, 32'd0);
        f_address = set_address_word(f_address, 4, saved_leaf_index);
        f_address = set_address_word(f_address, 5, {25'b0, chain_index});
        f_address = set_address_word(f_address, 6, {28'b0, chain_step});
        f_address = set_address_word(f_address, 7, 32'd0);

        h_address = saved_address;
        h_address = set_address_word(h_address, 3, 32'd1);
        h_address = set_address_word(h_address, 4, saved_leaf_index);
        h_address = set_address_word(h_address, 5,
                                     {29'b0, ltree_height});
        h_address = set_address_word(h_address, 6,
                                     {25'b0, pair_index});
        h_address = set_address_word(h_address, 7, 32'd0);

        h_nodes = {nodes[2*pair_index+1], nodes[2*pair_index]};

        prf_message = '0;
        // toByte(4, 32) || SK.seed || PUB.seed || ADRS
        prf_message[8*31 +: 8] = 8'h04;
        for (byte_index = 0; byte_index < 32; byte_index = byte_index + 1) begin
            prf_message[8*(32+byte_index) +: 8] =
                saved_sk_seed[8*byte_index +: 8];
            prf_message[8*(64+byte_index) +: 8] =
                saved_pub_seed[8*byte_index +: 8];
            prf_message[8*(96+byte_index) +: 8] =
                f_address[8*byte_index +: 8];
        end
    end

    micro_hbs_shake256_single_block #(.UNROLL(UNROLL)) prf_keygen (
        .clk, .rst_n, .start(prf_start), .ready(prf_ready),
        .message(prf_message), .message_length(8'd128),
        .digest(prf_digest), .done(prf_done), .error(prf_error)
    );

    micro_hbs_randomized_hash #(.NODE_COUNT(1), .UNROLL(UNROLL)) chain_f (
        .clk, .rst_n, .start(f_start), .ready(f_ready),
        .pub_seed(saved_pub_seed), .address(f_address),
        .node_data({256'b0, work_node}), .digest(f_digest), .done(f_done),
        .error(f_error), .hash_calls(f_hash_calls)
    );

    micro_hbs_randomized_hash #(.NODE_COUNT(2), .UNROLL(UNROLL)) ltree_h (
        .clk, .rst_n, .start(h_start), .ready(h_ready),
        .pub_seed(saved_pub_seed), .address(h_address),
        .node_data(h_nodes), .digest(h_digest), .done(h_done),
        .error(h_error), .hash_calls(h_hash_calls)
    );

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= S_IDLE;
            saved_sk_seed <= '0;
            saved_pub_seed <= '0;
            saved_address <= '0;
            saved_leaf_index <= '0;
            chain_index <= '0;
            chain_step <= '0;
            node_count <= '0;
            pair_index <= '0;
            ltree_height <= '0;
            work_node <= '0;
            rsp_valid <= 1'b0;
            leaf <= '0;
            rsp_error <= 1'b0;
            prf_keygen_calls <= '0;
            chain_steps <= '0;
            ltree_parents <= '0;
            shake_calls <= '0;
        end else begin
            case (state)
                S_IDLE: begin
                    rsp_valid <= 1'b0;
                    rsp_error <= 1'b0;
                    if (req_valid) begin
                        saved_sk_seed <= sk_seed;
                        saved_pub_seed <= pub_seed;
                        saved_address <= address_template;
                        saved_leaf_index <= leaf_index;
                        chain_index <= '0;
                        chain_step <= '0;
                        node_count <= '0;
                        pair_index <= '0;
                        ltree_height <= '0;
                        leaf <= '0;
                        prf_keygen_calls <= '0;
                        chain_steps <= '0;
                        ltree_parents <= '0;
                        shake_calls <= '0;
                        state <= S_PRF_START;
                    end
                end

                S_PRF_START: if (prf_ready) state <= S_PRF_WAIT;
                S_PRF_WAIT: begin
                    if (prf_error) begin
                        leaf <= '0;
                        rsp_error <= 1'b1;
                        rsp_valid <= 1'b1;
                        state <= S_RESP;
                    end else if (prf_done) begin
                        work_node <= prf_digest;
                        chain_step <= '0;
                        prf_keygen_calls <= prf_keygen_calls + 1'b1;
                        shake_calls <= shake_calls + 1'b1;
                        state <= S_F_START;
                    end
                end

                S_F_START: if (f_ready) state <= S_F_WAIT;
                S_F_WAIT: begin
                    if (f_error) begin
                        leaf <= '0;
                        rsp_error <= 1'b1;
                        rsp_valid <= 1'b1;
                        state <= S_RESP;
                    end else if (f_done) begin
                        work_node <= f_digest;
                        chain_steps <= chain_steps + 1'b1;
                        shake_calls <= shake_calls + f_hash_calls;
                        if (chain_step == WOTS_STEPS-1) begin
                            nodes[chain_index] <= f_digest;
                            if (chain_index == WOTS_LEN-1) begin
                                node_count <= WOTS_LEN;
                                pair_index <= '0;
                                ltree_height <= '0;
                                state <= S_L_CHECK;
                            end else begin
                                chain_index <= chain_index + 1'b1;
                                // PRF_keygen requires hash address/keyAndMask
                                // words 6/7 to be zero for every new chain.
                                chain_step <= '0;
                                state <= S_PRF_START;
                            end
                        end else begin
                            chain_step <= chain_step + 1'b1;
                            state <= S_F_START;
                        end
                    end
                end

                S_L_CHECK: begin
                    if (node_count == 1) begin
                        leaf <= nodes[0];
                        rsp_error <= 1'b0;
                        rsp_valid <= 1'b1;
                        state <= S_RESP;
                    end else if (pair_index < (node_count >> 1)) begin
                        state <= S_H_START;
                    end else if (node_count[0]) begin
                        state <= S_L_CARRY;
                    end else begin
                        node_count <= node_count >> 1;
                        pair_index <= '0;
                        ltree_height <= ltree_height + 1'b1;
                    end
                end

                S_H_START: if (h_ready) state <= S_H_WAIT;
                S_H_WAIT: begin
                    if (h_error) begin
                        leaf <= '0;
                        rsp_error <= 1'b1;
                        rsp_valid <= 1'b1;
                        state <= S_RESP;
                    end else if (h_done) begin
                        nodes[pair_index] <= h_digest;
                        pair_index <= pair_index + 1'b1;
                        ltree_parents <= ltree_parents + 1'b1;
                        shake_calls <= shake_calls + h_hash_calls;
                        state <= S_L_CHECK;
                    end
                end

                S_L_CARRY: begin
                    nodes[node_count >> 1] <= nodes[node_count-1];
                    node_count <= (node_count >> 1) + 1'b1;
                    pair_index <= '0;
                    ltree_height <= ltree_height + 1'b1;
                    state <= S_L_CHECK;
                end

                S_RESP: if (rsp_ready) begin
                    rsp_valid <= 1'b0;
                    rsp_error <= 1'b0;
                    state <= S_IDLE;
                end

                default: begin
                    leaf <= '0;
                    rsp_error <= 1'b1;
                    rsp_valid <= 1'b1;
                    state <= S_RESP;
                end
            endcase
        end
    end
endmodule

`default_nettype wire
