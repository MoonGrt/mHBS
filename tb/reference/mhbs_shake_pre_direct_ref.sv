`timescale 1ns/1ps
`default_nettype none

// Signer-specialized SHAKE lane: one sponge/permutation state and a compact
// statically sized chain template.  The two top-level instances remain identical.
module mhbs_shake_pre_direct_ref #(
    parameter integer UNROLL = 2, PIPELINE = 1, N = 16, DIGEST_BYTES = 34,
    parameter bit STREAM_CHAIN_ENABLE = 1, REUSE_FAST_FEEDBACK = 0, SHARED_STATE=0
) (
    input  wire          clk,
    input  wire          rst,
    input wire batch_mode,batch_valid,output wire batch_ready,
    input wire [1599:0] batch_state,input wire [1:0] batch_tag,
    output wire batch_done,output wire [1599:0] batch_digest,output wire [1:0] batch_result_tag,
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

    wire [24:0] state_write_enable;
    wire [1599:0] state_write_data;
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
    wire [1599:0] advanced_state;
    wire round_complete;
    wire round_update;
    logic [1599:0] next_chain_state;
    wire [3:0] counter_next = chain_counter + 1'b1;
    wire [3:0] transition_counter =
        saved_chain_prefix && chain_iteration == 1
            ? chain_counter : counter_next;
    genvar round_step;

    // One P-stage datapath for both serial and interleaved execution. P1
    // writes its sole state through the sponge word enables, without launch
    // or return bubbles. P>1 carries valid/round/tag through the same stages.
    localparam integer ROUNDS=UNROLL*PIPELINE;
    logic [1599:0] state_reg [0:PIPELINE-1];
    logic [PIPELINE-1:0] stage_valid;
    logic [4:0] stage_base [0:PIPELINE-1];
    logic [1:0] stage_tag [0:PIPELINE-1];
    logic sent;
    wire recycle=PIPELINE>1 && stage_valid[PIPELINE-1]
        && stage_base[PIPELINE-1]+ROUNDS<24;
    wire ready=!rst && !recycle;
    wire finished=PIPELINE>1 && !rst && stage_valid[PIPELINE-1] && !recycle;
    wire normal_valid=lane_state==RUN && !sent;
    wire issue_valid=batch_mode ? batch_valid : normal_valid;
    wire [1599:0] issue_state=batch_mode ? batch_state : sponge_state;
    wire [1:0] issue_tag=batch_mode ? batch_tag : 2'd0;
    wire [1599:0] finished_state=state_reg[PIPELINE-1];
    wire [1599:0] stage_result[0:PIPELINE-1];
    for(genvar s=0;s<PIPELINE;s=s+1)begin: stages
        wire [1599:0] rounds[0:UNROLL];
        wire [4:0] start_round;
        wire [1:0] source_tag;
        wire source_valid;
        if(s==0)begin: input_stage
            assign rounds[0]=PIPELINE==1 ? sponge_state
                : recycle ? state_reg[PIPELINE-1] : issue_state;
            assign start_round=PIPELINE==1 ? round_index
                : recycle ? stage_base[PIPELINE-1]+5'(ROUNDS) : 5'd0;
            assign source_tag=recycle ? stage_tag[PIPELINE-1] : issue_tag;
            assign source_valid=PIPELINE>1 && (recycle || issue_valid);
        end else begin: following_stage
            assign rounds[0]=state_reg[s-1];
            assign start_round=stage_base[s-1];
            assign source_tag=stage_tag[s-1];
            assign source_valid=stage_valid[s-1];
        end
        for(genvar r=0;r<UNROLL;r=r+1)begin: unrolled
            mhbs_keccak round_logic(.state_in(rounds[r]),
                .round_index(start_round+5'(s*UNROLL+r)),.state_out(rounds[r+1]));
        end
        assign stage_result[s]=rounds[UNROLL];
        for(genvar w=0;w<25;w=w+1)begin: words
            always_ff @(posedge clk)if(!rst)begin
                if((PIPELINE==1 || (SHARED_STATE && s==PIPELINE-1)) && state_write_enable[w])
                    state_reg[s][64*w +:64]<=state_write_data[64*w +:64];
                else if(source_valid)state_reg[s][64*w +:64]<=rounds[UNROLL][64*w +:64];
            end
        end
        always_ff @(posedge clk)begin
            if(rst)stage_valid[s]<=0;
            else begin
                stage_valid[s]<=source_valid;
                if(source_valid)begin stage_base[s]<=start_round;stage_tag[s]<=source_tag;end
            end
        end
    end
    assign batch_ready=PIPELINE>1 && batch_mode && ready;
    assign batch_done=PIPELINE>1 && batch_mode && finished;
    assign batch_digest=PIPELINE>1 ? finished_state : 1600'd0;
    assign batch_result_tag=PIPELINE>1 ? stage_tag[PIPELINE-1] : 2'd0;
    if(PIPELINE==1 || SHARED_STATE)assign sponge_state=finished_state;
    assign advanced_state=PIPELINE==1 ? stage_result[0] : finished_state;
    assign round_complete=PIPELINE==1 ? round_index+UNROLL>=24 : !batch_mode && finished;
    assign round_update=lane_state==RUN && (PIPELINE==1 || round_complete);
    always_ff @(posedge clk)begin
        if(rst)sent<=0;
        else if(!batch_mode)begin
            if(normal_valid && ready)sent<=1;
            if(finished)sent<=0;
        end
    end
    // synthesis translate_off
    always @(posedge clk)if(!rst && PIPELINE>1 && SHARED_STATE && |state_write_enable)
        if(|(stage_valid & ~(finished ? PIPELINE'(1 << (PIPELINE-1)) : {PIPELINE{1'b0}})))$fatal(1,"sponge write while pipeline occupied");
    // synthesis translate_on
    wire permutation_complete=lane_state==RUN && round_complete;
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
        && round_complete
        && (!saved_chain_enable || chains_remaining <= 1)
        && running_last;
    assign finish_digest = advanced_state[DIGEST_BYTES*8-1:0];
    assign capture_digest = captured_value;

    initial begin
        if (UNROLL < 1 || PIPELINE < 1 || PIPELINE > 4 || ROUNDS > 24 || (24 % ROUNDS) != 0)
            $error("compact SHAKE lane UNROLL must divide 24");
    end

    // Mutually exclusive word updates expose one data mux instead of a
    // priority network for whole-state loads mixed with partial absorption.
    wire take_fast=(lane_state==IDLE && context_valid && fast_block_valid)
        || (lane_state==WAIT_BLOCK && fast_block_valid && fast_block_ready);
    wire take_stream=lane_state==WAIT_BLOCK && !take_fast && block_valid;
    wire clear_stream=take_stream && first_block && append_index==0;
    wire take_feedback=lane_state==RUN && round_complete
        && saved_chain_enable && chains_remaining>1;
    assign chain_feedback_valid=REUSE_FAST_FEEDBACK && take_feedback;
    assign chain_feedback_counter=transition_counter;
    wire take_round=round_update && !take_feedback;
    // One selected rate pair is absorbed per stream beat. Share that XOR
    // before distributing the result to the enabled state words.
    logic [127:0] previous_rate;
    always @* begin
        case(append_index)
            0:previous_rate=sponge_state[0 +:128];
            1:previous_rate=sponge_state[128 +:128];
            2:previous_rate=sponge_state[256 +:128];
            3:previous_rate=sponge_state[384 +:128];
            4:previous_rate=sponge_state[512 +:128];
            5:previous_rate=sponge_state[640 +:128];
            6:previous_rate=sponge_state[768 +:128];
            7:previous_rate=sponge_state[896 +:128];
            default:previous_rate={64'd0,sponge_state[1024 +:64]};
        endcase
    end
    wire [127:0] absorbed_block=block_data ^ (previous_rate & {128{!clear_stream}});
    genvar word_index;
    generate for(word_index=0;word_index<25;word_index=word_index+1) begin: state_words
        wire select_stream=word_index<17 && take_stream && append_index==word_index/2;
        wire [63:0] fast_word;
        if(word_index<17) assign fast_word=fast_block_data[word_index*64 +:64];
        else assign fast_word=64'd0;
        // The register enable suppresses idle cycles. The default data can
        // therefore be the permutation result without a 1,600-bit RUN mask.
        wire [63:0] round_or_clear=(clear_stream || (SHARED_STATE && PIPELINE>1)) ? 64'd0
            : advanced_state[word_index*64 +:64];
        wire [63:0] absorb_word=word_index%2==0 ? absorbed_block[63:0] : absorbed_block[127:64];
        wire [63:0] next_word;
        if(REUSE_FAST_FEEDBACK) begin: common_fast_data
            assign next_word=(take_fast || take_feedback) ? fast_word
                : select_stream ? absorb_word : round_or_clear;
        end else begin: separate_feedback_data
            assign next_word=take_fast ? fast_word
                : take_feedback ? next_chain_state[word_index*64 +:64]
                : select_stream ? absorb_word : round_or_clear;
        end
        assign state_write_data[word_index*64 +:64]=next_word;
        // A completed permutation already resides in the shared register.
        // Only absorption, initialization or a new chain block needs a write.
        assign state_write_enable[word_index]=!rst &&
            (((SHARED_STATE && PIPELINE>1) ? take_feedback : round_update) || take_fast || select_stream || clear_stream);
        if(!SHARED_STATE && PIPELINE>1)begin: private_state
            always_ff @(posedge clk)
                if(state_write_enable[word_index])sponge_state[word_index*64 +:64]<=next_word;
        end
    end endgenerate

    always_ff @(posedge clk) begin
        if (rst) begin
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
                    if (round_complete) begin
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
                    end else if(PIPELINE==1) begin
                        round_index <= round_index + UNROLL;
                    end
                end
                default: lane_state <= IDLE;
            endcase
        end
    end
endmodule

`default_nettype wire
