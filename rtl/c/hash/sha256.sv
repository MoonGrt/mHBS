`timescale 1ns / 1ps
`default_nettype none

// One SHA-256 compression lane. The first message word and H0 occupy the
// most significant bits. P stages execute U rounds each and recycle until
// all 64 rounds have run; unused rounds in the last traversal are bypassed.
// verilog_format: off
module sha256 #(
    parameter integer PIPELINE=1, UNROLL=1,
    parameter integer TAG_BITS=PIPELINE>1 ? $clog2(PIPELINE) : 1
) (
    input wire clk, rst,
    input wire input_valid, output wire input_ready,
    input wire [255:0] input_cv, input wire [511:0] input_block,
    input wire [TAG_BITS-1:0] input_tag,
    output logic output_valid, input wire output_ready,
    output logic [255:0] output_cv, output logic [TAG_BITS-1:0] output_tag
);
// verilog_format: on
    localparam integer ROUNDS = PIPELINE * UNROLL;
    localparam integer TRAVERSALS = (64 + ROUNDS - 1) / ROUNDS;
    localparam integer TRAVERSAL_BITS = TRAVERSALS > 1 ? $clog2(TRAVERSALS) : 1;

    function automatic [31:0] rotate(input [31:0] value, input integer amount);
        rotate = (value >> amount) | (value << (32 - amount));
    endfunction

    function automatic [31:0] constant_word(input [6:0] round_index);
        case (round_index)
             0: constant_word=32'h428a2f98;  1: constant_word=32'h71374491;
             2: constant_word=32'hb5c0fbcf;  3: constant_word=32'he9b5dba5;
             4: constant_word=32'h3956c25b;  5: constant_word=32'h59f111f1;
             6: constant_word=32'h923f82a4;  7: constant_word=32'hab1c5ed5;
             8: constant_word=32'hd807aa98;  9: constant_word=32'h12835b01;
            10: constant_word=32'h243185be; 11: constant_word=32'h550c7dc3;
            12: constant_word=32'h72be5d74; 13: constant_word=32'h80deb1fe;
            14: constant_word=32'h9bdc06a7; 15: constant_word=32'hc19bf174;
            16: constant_word=32'he49b69c1; 17: constant_word=32'hefbe4786;
            18: constant_word=32'h0fc19dc6; 19: constant_word=32'h240ca1cc;
            20: constant_word=32'h2de92c6f; 21: constant_word=32'h4a7484aa;
            22: constant_word=32'h5cb0a9dc; 23: constant_word=32'h76f988da;
            24: constant_word=32'h983e5152; 25: constant_word=32'ha831c66d;
            26: constant_word=32'hb00327c8; 27: constant_word=32'hbf597fc7;
            28: constant_word=32'hc6e00bf3; 29: constant_word=32'hd5a79147;
            30: constant_word=32'h06ca6351; 31: constant_word=32'h14292967;
            32: constant_word=32'h27b70a85; 33: constant_word=32'h2e1b2138;
            34: constant_word=32'h4d2c6dfc; 35: constant_word=32'h53380d13;
            36: constant_word=32'h650a7354; 37: constant_word=32'h766a0abb;
            38: constant_word=32'h81c2c92e; 39: constant_word=32'h92722c85;
            40: constant_word=32'ha2bfe8a1; 41: constant_word=32'ha81a664b;
            42: constant_word=32'hc24b8b70; 43: constant_word=32'hc76c51a3;
            44: constant_word=32'hd192e819; 45: constant_word=32'hd6990624;
            46: constant_word=32'hf40e3585; 47: constant_word=32'h106aa070;
            48: constant_word=32'h19a4c116; 49: constant_word=32'h1e376c08;
            50: constant_word=32'h2748774c; 51: constant_word=32'h34b0bcb5;
            52: constant_word=32'h391c0cb3; 53: constant_word=32'h4ed8aa4a;
            54: constant_word=32'h5b9cca4f; 55: constant_word=32'h682e6ff3;
            56: constant_word=32'h748f82ee; 57: constant_word=32'h78a5636f;
            58: constant_word=32'h84c87814; 59: constant_word=32'h8cc70208;
            60: constant_word=32'h90befffa; 61: constant_word=32'ha4506ceb;
            62: constant_word=32'hbef9a3f7; 63: constant_word=32'hc67178f2;
            default: constant_word=32'd0;
        endcase
    endfunction

    // Keep intermediate sums in carry-save form. Only each result word's
    // final addition propagates a carry across all 32 bits; in particular,
    // neither T1 nor T2 introduces a carry chain before the a/e additions.
    function automatic [63:0] carry_save(input [31:0] x, y, z);
        reg [31:0] sum, carry;
        begin
            sum = x ^ y ^ z;
            carry = ((x & y) | ((x ^ y) & z)) << 1;
            carry_save = {carry, sum};
        end
    endfunction

    function automatic [63:0] prepared_prefix(input [31:0] h, word_value, k);
        // Preserve both carry-save terms. A complete addition here would
        // precede the nonlinear round on a newly injected compression block.
        prepared_prefix = carry_save(h, word_value, k);
    endfunction

    function automatic [767:0] advance_round(input [767:0] value,
        input [31:0] round_constant, input [63:0] prefix,
        input prefix_ready, round_active);
        reg [31:0] a, b, c, d, e, f, g, h, next_a, next_e;
        reg [31:0] sigma_a, sigma_e, choose, majority;
        reg [31:0] w0, w1, w9, w14, new_word;
        reg [63:0] t1_first, t1_second, t1_pair, a_first, a_pair, e_pair;
        reg [63:0] schedule_first, schedule_pair;
        begin
            {a,b,c,d,e,f,g,h} = value[767:512];
            w0=value[511:480]; w1=value[479:448];
            w9=value[223:192]; w14=value[63:32];
            sigma_e = rotate(e,6) ^ rotate(e,11) ^ rotate(e,25);
            choose = (e & f) ^ (~e & g);
            sigma_a = rotate(a,2) ^ rotate(a,13) ^ rotate(a,22);
            majority = (a & b) ^ (a & c) ^ (b & c);

            // H/K/W reduction is prepared alongside the preceding stage.
            // Fresh inputs use the same carry-save reduction, with no added
            // carry-propagating addition before this round's A/E results.
            t1_first = prefix_ready ? prefix : carry_save(h, round_constant, w0);
            // Ch is one Boolean level, whereas Sigma(E) rotates and XORs.
            // Reduce the early prefix/Ch terms before the later Sigma(E).
            // Keep the shared T1 pair and the A-side compressor depth.
            t1_second = carry_save(t1_first[31:0], t1_first[63:32], choose);
            t1_pair = carry_save(t1_second[31:0], t1_second[63:32], sigma_e);
            e_pair = carry_save(d, t1_pair[31:0], t1_pair[63:32]);
            a_first = carry_save(sigma_a, majority, t1_pair[31:0]);
            a_pair = carry_save(a_first[31:0], a_first[63:32], t1_pair[63:32]);
            next_a = a_pair[31:0] + a_pair[63:32];
            next_e = e_pair[31:0] + e_pair[63:32];

            schedule_first = carry_save(
                rotate(w14,17) ^ rotate(w14,19) ^ (w14 >> 10),
                w9, rotate(w1,7) ^ rotate(w1,18) ^ (w1 >> 3));
            schedule_pair = carry_save(schedule_first[31:0],
                schedule_first[63:32], w0);
            new_word = schedule_pair[31:0] + schedule_pair[63:32];
            advance_round = round_active ?
                {next_a,a,b,c,next_e,e,f,g,value[479:0],new_word} : value;
        end
    endfunction

    logic [767:0] state[0:PIPELINE-1];
    // Feed-forward CVs do not change during a compression. Store them once
    // per accepted token, rather than shifting 256 bits through every stage.
    // Allocation follows token order and is independent of external tag values.
    localparam integer CV_SLOT_BITS = PIPELINE > 1 ? $clog2(PIPELINE) : 1;
    (* ram_style = "distributed" *) logic [255:0] initial_cv[0:PIPELINE-1];
    logic [CV_SLOT_BITS-1:0] cv_slot[0:PIPELINE-1];
    logic [CV_SLOT_BITS-1:0] cv_write_slot;
    logic [TRAVERSAL_BITS-1:0] traversal[0:PIPELINE-1];
    logic [TAG_BITS-1:0] tag[0:PIPELINE-1];
    logic [PIPELINE-1:0] valid;
    logic [31:0] next_constant[0:PIPELINE-1][0:UNROLL-1];
    localparam integer PREFIX_ROUNDS = UNROLL < 4 ? UNROLL : 4;
    logic [63:0] next_prefix[0:PIPELINE-1][0:PREFIX_ROUNDS-1];
    logic return_pending;
    wire stalled = output_valid && !output_ready;
    wire recycle = return_pending;
    wire finished = valid[PIPELINE-1] && !recycle;
    assign input_ready = !rst && !stalled && !recycle;
    always_ff @(posedge clk) begin
        if (rst) cv_write_slot <= '0;
        else if (input_valid && input_ready) begin
            initial_cv[cv_write_slot] <= input_cv;
            cv_write_slot <= cv_write_slot == CV_SLOT_BITS'(PIPELINE-1) ?
                CV_SLOT_BITS'(0) : cv_write_slot + 1'b1;
        end
    end

    for (genvar stage=0; stage<PIPELINE; stage=stage+1) begin : stages
        wire [767:0] source_state;
        wire [CV_SLOT_BITS-1:0] source_cv_slot;
        wire [TRAVERSAL_BITS-1:0] source_traversal;
        wire [TAG_BITS-1:0] source_tag;
        wire source_valid;
        if (stage == 0) begin : first
            assign source_state = recycle ? state[PIPELINE-1] : {input_cv,input_block};
            assign source_cv_slot = recycle ? cv_slot[PIPELINE-1] : cv_write_slot;
            assign source_traversal = recycle ? traversal[PIPELINE-1] + 1'b1 : '0;
            assign source_tag = recycle ? tag[PIPELINE-1] : input_tag;
            assign source_valid = recycle || (input_valid && input_ready);
        end else begin : following
            assign source_state = state[stage-1];
            assign source_cv_slot = cv_slot[stage-1];
            assign source_traversal = traversal[stage-1];
            assign source_tag = tag[stage-1];
            assign source_valid = valid[stage-1];
        end
        for (genvar r=0; r<UNROLL; r=r+1) begin : unrolled
            localparam integer ROUND_OFFSET = stage * UNROLL + r;

            localparam integer NEXT_OFFSET = ((stage + 1) % PIPELINE) * UNROLL + r;
            localparam integer NEXT_TRAVERSAL = stage == PIPELINE-1 ? 1 : 0;

            // Decode the constants for the next physical stage in parallel
            // with this stage's arithmetic. At the ring boundary, the same
            // token advances to its next traversal before consuming them.
            function automatic [31:0] following_constant(
                input [TRAVERSAL_BITS-1:0] index);
                integer visit;
                begin
                    following_constant = 32'd0;
                    for (visit=0; visit<TRAVERSALS; visit=visit+1)
                        if (index == TRAVERSAL_BITS'(visit))
                            following_constant = constant_word(
                                7'((visit + NEXT_TRAVERSAL) * ROUNDS + NEXT_OFFSET));
                end
            endfunction

            wire round_active;
            if ((TRAVERSALS-1) * ROUNDS + ROUND_OFFSET < 64) begin : full_tail
                assign round_active = 1'b1;
            end else begin : partial_tail
                assign round_active = source_traversal != TRAVERSAL_BITS'(TRAVERSALS - 1);
            end
            wire [31:0] round_constant;
            wire [63:0] round_prefix;
            if (r < PREFIX_ROUNDS) begin : prepared_round
                wire [767:0] completed_state = unrolled[UNROLL-1].result;
                // During the first four rounds, H is the source H/G/F/E,
                // and W is already present in the source schedule window.
                // Thus next-stage prefixes need no future round arithmetic.
                always_ff @(posedge clk) begin
                    if (!rst && !stalled && source_valid)
                        next_prefix[stage][r] <= prepared_prefix(
                            completed_state[512+32*r+:32],
                            completed_state[511-32*r-:32],
                            following_constant(source_traversal));
                end
                if (stage == 0) begin : entering_prefix
                    assign round_prefix = recycle ? next_prefix[PIPELINE-1][r] :
                        prepared_prefix(input_cv[32*r+:32],
                            input_block[511-32*r-:32], constant_word(7'(r)));
                end else begin : advancing_prefix
                    assign round_prefix = next_prefix[stage-1][r];
                end
                assign round_constant = 32'd0;
            end else begin : ordinary_round
                if (stage == 0) begin : entering_constant
                    assign round_constant = recycle ? next_constant[PIPELINE-1][r] :
                        constant_word(7'(r));
                end else begin : advancing_constant
                    assign round_constant = next_constant[stage-1][r];
                end
                always_ff @(posedge clk) begin
                    if (!rst && !stalled && source_valid)
                        next_constant[stage][r] <= following_constant(source_traversal);
                end
                assign round_prefix = 64'd0;
            end
`ifndef SYNTHESIS
            always_ff @(posedge clk) begin
                if (!rst && !stalled && source_valid) begin
                    if (r < PREFIX_ROUNDS) begin
                        if (round_prefix !== prepared_prefix(source_state[512+32*r+:32],
                            source_state[511-32*r-:32],
                            constant_word(7'(int'(source_traversal) * ROUNDS + ROUND_OFFSET))))
                            $fatal(1, "SHA256 lookahead prefix lost token alignment");
                    end else if (round_constant !== constant_word(
                        7'(int'(source_traversal) * ROUNDS + ROUND_OFFSET)))
                        $fatal(1, "SHA256 lookahead constant lost token alignment");
                end
            end
`endif
            wire [767:0] result;
            if (r == 0) begin : first_round
                assign result = advance_round(source_state, round_constant,
                    round_prefix, r < PREFIX_ROUNDS, round_active);
            end else begin : following_round
                assign result = advance_round(unrolled[r-1].result,
                    round_constant, round_prefix, r < PREFIX_ROUNDS, round_active);
            end
        end
        if (stage == PIPELINE-1) begin : returning_control
            // Register both ownership and continuation. A bubble clears the
            // return token, so the wide ring selector needs no valid gate;
            // global stalls hold this bit together with state, tag and valid.
            always_ff @(posedge clk) begin
                if (rst) return_pending <= 1'b0;
                else if (!stalled)
                    return_pending <= source_valid &&
                        source_traversal != TRAVERSAL_BITS'(TRAVERSALS - 1);
            end
        end
        always_ff @(posedge clk) begin
            if (rst) valid[stage] <= 0;
            else if (!stalled) begin
                valid[stage] <= source_valid;
                if (source_valid) begin
                    state[stage] <= unrolled[UNROLL-1].result;
                    cv_slot[stage] <= source_cv_slot;
                    traversal[stage] <= source_traversal;
                    tag[stage] <= source_tag;
                end
            end
        end
    end

    // Feed-forward is deliberately separate from the last round and its
    // feedback mux. This register also holds a response during backpressure.
    always_ff @(posedge clk) begin
        if (rst) output_valid <= 0;
        else if (!stalled) begin
            output_valid <= finished;
            if (finished) begin
                output_tag <= tag[PIPELINE-1];
                for (integer word_index=0; word_index<8; word_index=word_index+1)
                    output_cv[32*word_index+:32] <=
                        state[PIPELINE-1][512+32*word_index+:32] +
                        initial_cv[cv_slot[PIPELINE-1]][32*word_index+:32];
            end
        end
    end

`ifndef SYNTHESIS
    always_ff @(posedge clk) begin
        if (!rst && return_pending !== (valid[PIPELINE-1] &&
            traversal[PIPELINE-1] != TRAVERSAL_BITS'(TRAVERSALS - 1)))
            $fatal(1, "SHA256 registered return token lost valid/round alignment");
    end
    initial begin
        if (PIPELINE < 1 || PIPELINE > 24 || UNROLL < 1 || ROUNDS > 24 ||
            24 % ROUNDS != 0 || TAG_BITS < 1)
            $fatal(1, "Unsupported SHA256 P/U or tag width");
    end
`endif
endmodule
`default_nettype wire
