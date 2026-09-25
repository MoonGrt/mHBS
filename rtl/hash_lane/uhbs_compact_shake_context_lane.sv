`timescale 1ns/1ps
`default_nettype none

// Signer-specialized SHAKE lane: one sponge/permutation state and a compact
// statically sized chain template.  The two top-level instances remain identical.
module uhbs_compact_shake_context_lane #(
    parameter integer UNROLL = 2, N = 16, DIGEST_BYTES = 34,
    parameter bit STREAM_CHAIN_ENABLE = 1, REUSE_FAST_FEEDBACK = 0
) (
    input  wire          clk,
    input  wire          rst_n,
    input wire [5:0] node_bytes,
    input wire [(N+32)*8-1:0] chain_prefix_data,
    input  wire          context_valid,
    output wire          context_ready,
    input  wire          fast_block_valid,
    output wire          fast_block_ready,
    input  wire [1087:0] fast_block_data,
    input  wire          chain_enable,
    input  wire          chain_prefix,
    input  wire          chain_prefix_preserve_counter,
    input  wire [2:0]    chain_prefix_domain,
    input  wire [4:0]    chain_count,
    input  wire          capture_enable,
    input  wire [4:0]    capture_after,
    input  wire          block_valid,
    output wire          block_ready,
    input  wire [127:0]  block_data,
    input  wire          block_last,
    output logic         response_valid,
    output wire [DIGEST_BYTES*8-1:0]  response_digest,
    output wire          chain_feedback_valid,
    output wire [3:0]    chain_feedback_counter,
    output wire          finish_valid,
    output wire [DIGEST_BYTES*8-1:0]  finish_digest,
    output wire [N*8-1:0]  capture_digest,
    output logic         capture_valid,
    output logic         error
);
    localparam logic [1:0] IDLE = 2'd0;
    localparam logic [1:0] WAIT_BLOCK = 2'd1;
    localparam logic [1:0] RUN = 2'd2;

    logic [1:0] lane_state;
    logic saved_chain_enable;
    logic saved_chain_prefix;
    logic saved_chain_prefix_preserve_counter;
    logic [2:0] saved_chain_prefix_domain;
    logic [4:0] saved_chain_count;
    logic saved_capture_enable;
    logic [4:0] saved_capture_after;
    logic first_block;
    logic running_last;
    logic [3:0] append_index;

    logic [1599:0] sponge_state;
    logic [(N+32)*8-1:0] chain_template;
    // Recipe request fields stay stable through the response handshake.
    // The production lane therefore reuses its live prefix without copying it.
    wire [(N+32)*8-1:0] active_chain_template = STREAM_CHAIN_ENABLE ? chain_template : chain_prefix_data;
    logic [4:0] chains_remaining;
    logic [3:0] chain_counter;
    logic [4:0] chain_iteration;
    logic [N*8-1:0] captured_value;
    logic [4:0] round_index;
    wire [1599:0] round_state [0:UNROLL];
    wire [1599:0] advanced_state = round_state[UNROLL];
    logic [1599:0] next_chain_state;
    wire [3:0] counter_next = chain_counter + 1'b1;
    wire [3:0] transition_counter =
        saved_chain_prefix && chain_iteration == 1
            ? chain_counter : counter_next;
    genvar round_step;

    function automatic [63:0] rotl64;
        input [63:0] value;
        input integer amount;
        begin
            rotl64 = amount == 0 ? value
                : (value << amount) | (value >> (64-amount));
        end
    endfunction

    function automatic integer rho_offset;
        input integer x;
        input integer y;
        begin
            case (x + 5*y)
                 0: rho_offset =  0;  1: rho_offset =  1;
                 2: rho_offset = 62;  3: rho_offset = 28;
                 4: rho_offset = 27;  5: rho_offset = 36;
                 6: rho_offset = 44;  7: rho_offset =  6;
                 8: rho_offset = 55;  9: rho_offset = 20;
                10: rho_offset =  3; 11: rho_offset = 10;
                12: rho_offset = 43; 13: rho_offset = 25;
                14: rho_offset = 39; 15: rho_offset = 41;
                16: rho_offset = 45; 17: rho_offset = 15;
                18: rho_offset = 21; 19: rho_offset =  8;
                20: rho_offset = 18; 21: rho_offset =  2;
                22: rho_offset = 61; 23: rho_offset = 56;
                24: rho_offset = 14;
                default: rho_offset = 0;
            endcase
        end
    endfunction

    function automatic [63:0] round_constant;
        input [4:0] index;
        begin
            case (index)
                 0: round_constant = 64'h0000000000000001;
                 1: round_constant = 64'h0000000000008082;
                 2: round_constant = 64'h800000000000808a;
                 3: round_constant = 64'h8000000080008000;
                 4: round_constant = 64'h000000000000808b;
                 5: round_constant = 64'h0000000080000001;
                 6: round_constant = 64'h8000000080008081;
                 7: round_constant = 64'h8000000000008009;
                 8: round_constant = 64'h000000000000008a;
                 9: round_constant = 64'h0000000000000088;
                10: round_constant = 64'h0000000080008009;
                11: round_constant = 64'h000000008000000a;
                12: round_constant = 64'h000000008000808b;
                13: round_constant = 64'h800000000000008b;
                14: round_constant = 64'h8000000000008089;
                15: round_constant = 64'h8000000000008003;
                16: round_constant = 64'h8000000000008002;
                17: round_constant = 64'h8000000000000080;
                18: round_constant = 64'h000000000000800a;
                19: round_constant = 64'h800000008000000a;
                20: round_constant = 64'h8000000080008081;
                21: round_constant = 64'h8000000000008080;
                22: round_constant = 64'h0000000080000001;
                23: round_constant = 64'h8000000080008008;
                default: round_constant = 64'h0;
            endcase
        end
    endfunction

    function automatic [1599:0] keccak_round;
        input [1599:0] input_state;
        input [4:0] index;
        reg [63:0] a [0:24];
        reg [63:0] b [0:24];
        reg [63:0] c [0:4];
        reg [63:0] d [0:4];
        reg [1599:0] result;
        integer x;
        integer y;
        integer destination;
        begin
            for (y = 0; y < 5; y = y + 1)
                for (x = 0; x < 5; x = x + 1)
                    a[x+5*y] = input_state[64*(x+5*y) +: 64];
            for (x = 0; x < 5; x = x + 1)
                c[x] = a[x] ^ a[x+5] ^ a[x+10] ^ a[x+15] ^ a[x+20];
            for (x = 0; x < 5; x = x + 1)
                d[x] = c[(x+4)%5] ^ rotl64(c[(x+1)%5], 1);
            for (y = 0; y < 5; y = y + 1)
                for (x = 0; x < 5; x = x + 1)
                    a[x+5*y] = a[x+5*y] ^ d[x];
            for (y = 0; y < 5; y = y + 1)
                for (x = 0; x < 5; x = x + 1) begin
                    destination = y + 5*((2*x+3*y)%5);
                    b[destination] = rotl64(a[x+5*y], rho_offset(x,y));
                end
            for (y = 0; y < 5; y = y + 1)
                for (x = 0; x < 5; x = x + 1)
                    a[x+5*y] = b[x+5*y]
                        ^ ((~b[((x+1)%5)+5*y]) & b[((x+2)%5)+5*y]);
            a[0] = a[0] ^ round_constant(index);
            result = '0;
            for (y = 0; y < 5; y = y + 1)
                for (x = 0; x < 5; x = x + 1)
                    result[64*(x+5*y) +: 64] = a[x+5*y];
            keccak_round = result;
        end
    endfunction

    assign round_state[0] = sponge_state;
    generate for (round_step = 0; round_step < UNROLL;
                  round_step = round_step + 1) begin : generated_rounds
        localparam logic [4:0] ROUND_OFFSET = round_step;
        (* keep_hierarchy="yes" *) uhbs_keccak round_logic (
            .state_in(round_state[round_step]),
            .round_index(round_index + ROUND_OFFSET),
            .state_out(round_state[round_step+1])
        );
    end endgenerate

    always_comb begin
        next_chain_state='0;
        if(REUSE_FAST_FEEDBACK) next_chain_state={512'd0,fast_block_data};
        else case(node_bytes)
            6'd16: begin
        next_chain_state = '0;
        next_chain_state[(16+32)*8-1:0] = active_chain_template[383:0];
        if (saved_chain_prefix)
            next_chain_state[8*(16+16) +: 32] =
                {5'b0, saved_chain_prefix_domain, 24'b0};
        if (!saved_chain_prefix_preserve_counter)
            next_chain_state[8*(16+28) +: 32] =
                {4'b0, transition_counter, 24'b0};
        next_chain_state[8*(16+32) +: 16*8] = advanced_state[16*8-1:0];
        next_chain_state[8*(2*16+32) +: 8] = 8'h1f;
        next_chain_state[1087] = 1'b1;
            end
            6'd24: begin
        next_chain_state = '0;
        next_chain_state[(24+32)*8-1:0] = active_chain_template[447:0];
        if (saved_chain_prefix)
            next_chain_state[8*(24+16) +: 32] =
                {5'b0, saved_chain_prefix_domain, 24'b0};
        if (!saved_chain_prefix_preserve_counter)
            next_chain_state[8*(24+28) +: 32] =
                {4'b0, transition_counter, 24'b0};
        next_chain_state[8*(24+32) +: 24*8] = advanced_state[24*8-1:0];
        next_chain_state[8*(2*24+32) +: 8] = 8'h1f;
        next_chain_state[1087] = 1'b1;
            end
            6'd32: begin
        next_chain_state = '0;
        next_chain_state[(32+32)*8-1:0] = active_chain_template[511:0];
        if (saved_chain_prefix)
            next_chain_state[8*(32+16) +: 32] =
                {5'b0, saved_chain_prefix_domain, 24'b0};
        if (!saved_chain_prefix_preserve_counter)
            next_chain_state[8*(32+28) +: 32] =
                {4'b0, transition_counter, 24'b0};
        next_chain_state[8*(32+32) +: 32*8] = advanced_state[32*8-1:0];
        next_chain_state[8*(2*32+32) +: 8] = 8'h1f;
        next_chain_state[1087] = 1'b1;
            end
            default: next_chain_state='0;
        endcase
    end

    assign context_ready = lane_state == IDLE;
    assign block_ready = lane_state == WAIT_BLOCK;
    assign fast_block_ready = (lane_state == IDLE && context_valid)
        || (lane_state == WAIT_BLOCK && first_block && append_index == 0);
    assign response_digest = sponge_state[DIGEST_BYTES*8-1:0];
    assign finish_valid = lane_state == RUN
        && round_index + UNROLL >= 24
        && (!saved_chain_enable || chains_remaining <= 1)
        && running_last;
    assign finish_digest = advanced_state[DIGEST_BYTES*8-1:0];
    assign capture_digest = captured_value;

    initial begin
        if (UNROLL < 1 || UNROLL > 24 || (24 % UNROLL) != 0)
            $error("compact SHAKE lane UNROLL must divide 24");
    end

    // Mutually exclusive word updates expose one data mux instead of a
    // priority network for whole-state loads mixed with partial absorption.
    wire take_fast=(lane_state==IDLE && context_valid && fast_block_valid)
        || (lane_state==WAIT_BLOCK && fast_block_valid && fast_block_ready);
    wire take_stream=lane_state==WAIT_BLOCK && !take_fast && block_valid;
    wire clear_stream=take_stream && first_block && append_index==0;
    wire take_feedback=lane_state==RUN && round_index+UNROLL>=24
        && saved_chain_enable && chains_remaining>1;
    assign chain_feedback_valid=REUSE_FAST_FEEDBACK && take_feedback;
    assign chain_feedback_counter=transition_counter;
    wire take_round=lane_state==RUN && !take_feedback;
    genvar word_index;
    generate for(word_index=0;word_index<25;word_index=word_index+1) begin: state_words
        wire select_stream=word_index<17 && take_stream && append_index==word_index/2;
        wire [63:0] fast_word;
        if(word_index<17) assign fast_word=fast_block_data[word_index*64 +:64];
        else assign fast_word=64'd0;
        wire [63:0] stream_word=word_index%2==0 ? block_data[63:0] : block_data[127:64];
        // The register enable suppresses idle cycles. The default data can
        // therefore be the permutation result without a 1,600-bit RUN mask.
        wire [63:0] round_or_clear=clear_stream ? 64'd0
            : advanced_state[word_index*64 +:64];
        wire [63:0] absorb_word=stream_word ^
            (sponge_state[word_index*64 +:64] & {64{!clear_stream}});
        wire [63:0] next_word;
        if(REUSE_FAST_FEEDBACK) begin: common_fast_data
            assign next_word=(take_fast || take_feedback) ? fast_word
                : select_stream ? absorb_word : round_or_clear;
        end else begin: separate_feedback_data
            assign next_word=take_fast ? fast_word
                : take_feedback ? next_chain_state[word_index*64 +:64]
                : select_stream ? absorb_word : round_or_clear;
        end
        always_ff @(posedge clk)
            if(rst_n && (lane_state==RUN || take_fast || select_stream || clear_stream))
                sponge_state[word_index*64 +:64]<=next_word;
    end endgenerate

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            lane_state <= IDLE;
            saved_chain_enable <= 1'b0;
            saved_chain_prefix <= 1'b0;
            saved_chain_prefix_preserve_counter <= 1'b0;
            saved_chain_prefix_domain <= '0;
            saved_chain_count <= '0;
            saved_capture_enable <= 1'b0;
            saved_capture_after <= '0;
            first_block <= 1'b1;
            running_last <= 1'b0;
            append_index <= 0;
            chains_remaining <= '0;
            chain_counter <= '0;
            chain_iteration <= '0;
            round_index <= '0;
            response_valid <= 1'b0;
            capture_valid <= 1'b0;
            error <= 1'b0;
        end else begin
            response_valid <= 1'b0;
            capture_valid <= 1'b0;
            error <= 1'b0;
            case (lane_state)
                IDLE: if (context_valid) begin
                    saved_chain_enable <= chain_enable;
                    saved_chain_prefix <= chain_prefix;
                    saved_chain_prefix_preserve_counter
                        <= chain_prefix_preserve_counter;
                    saved_chain_prefix_domain <= chain_prefix_domain;
                    saved_chain_count <= chain_count;
                    saved_capture_enable <= capture_enable;
                    saved_capture_after <= capture_after;
                    first_block <= 1'b1;
                    append_index <= 0;
                    if (fast_block_valid) begin
                        chain_template <= fast_block_data[(N+32)*8-1:0];
                        running_last <= 1'b1;
                        chains_remaining <= chain_enable
                            ? chain_count : 5'd1;
                        chain_counter <= 0;
                        chain_iteration <= 1;
                        round_index <= 0;
                        lane_state <= RUN;
                    end else
                        lane_state <= WAIT_BLOCK;
                end
                WAIT_BLOCK: if (fast_block_valid && fast_block_ready) begin
                    // Generic pre-padded one-rate-block path.  The recipe
                    // executor builds fixed-format blocks while this lane is
                    // idle, avoiding nine serial append cycles per context.
                    chain_template <= fast_block_data[(N+32)*8-1:0];
                    running_last <= 1'b1;
                    chains_remaining <= saved_chain_enable
                        ? saved_chain_count : 5'd1;
                    chain_counter <= 0;
                    chain_iteration <= 1;
                    round_index <= 0;
                    lane_state <= RUN;
                end else if (block_valid) begin
                    if(STREAM_CHAIN_ENABLE && saved_chain_enable) begin
                        case(append_index)
                            0:chain_template[127:0]<=block_data;
                            1:chain_template[255:128]<=block_data;
                            2:chain_template[383:256]<=block_data;
                            default:begin end
                        endcase
                    end
                    if (append_index == 8) begin
                        running_last <= block_last;
                        append_index <= 0;
                        if (saved_chain_enable && !block_last) begin
                            error <= 1'b1;
                            lane_state <= IDLE;
                        end else begin
                            chains_remaining <= saved_chain_enable
                                ? saved_chain_count : 5'd1;
                            chain_counter <= 0;
                            chain_iteration <= 1;
                            round_index <= 0;
                            lane_state <= RUN;
                        end
                    end else begin
                        append_index <= append_index + 1'b1;
                    end
                end
                RUN: begin
                    if (round_index + UNROLL >= 24) begin
                        if (saved_capture_enable
                            && saved_capture_after == chain_iteration)
                            captured_value <= advanced_state[N*8-1:0];
                        if (saved_chain_enable && chains_remaining > 1) begin
                            chain_template <= next_chain_state[(N+32)*8-1:0];
                            chains_remaining <= chains_remaining - 1'b1;
                            if (!saved_chain_prefix_preserve_counter
                                && !(saved_chain_prefix
                                     && chain_iteration == 1))
                                chain_counter <= chain_counter + 1'b1;
                            chain_iteration <= chain_iteration + 1'b1;
                            round_index <= 0;
                        end else begin
                            if (running_last) begin
                                response_valid <= 1'b1;
                                capture_valid <= saved_capture_enable;
                                lane_state <= IDLE;
                            end else begin
                                first_block <= 1'b0;
                                lane_state <= WAIT_BLOCK;
                            end
                        end
                    end else begin
                        round_index <= round_index + UNROLL;
                    end
                end
                default: lane_state <= IDLE;
            endcase
        end
    end
endmodule

`default_nettype wire
