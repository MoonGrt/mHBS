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

    function automatic [767:0] advance_round(input [767:0] value,
        input [6:0] round_index);
        reg [31:0] a, b, c, d, e, f, g, h, t1, t2, next_a, next_e;
        reg [31:0] w0, w1, w9, w14, new_word;
        begin
            {a,b,c,d,e,f,g,h} = value[767:512];
            w0=value[511:480]; w1=value[479:448];
            w9=value[223:192]; w14=value[63:32];
            t1 = h + (rotate(e,6) ^ rotate(e,11) ^ rotate(e,25)) +
                ((e & f) ^ (~e & g)) + constant_word(round_index) + w0;
            t2 = (rotate(a,2) ^ rotate(a,13) ^ rotate(a,22)) +
                ((a & b) ^ (a & c) ^ (b & c));
            next_a=t1+t2; next_e=d+t1;
            new_word = (rotate(w14,17) ^ rotate(w14,19) ^ (w14 >> 10)) +
                w9 + (rotate(w1,7) ^ rotate(w1,18) ^ (w1 >> 3)) + w0;
            advance_round = round_index < 64 ?
                {next_a,a,b,c,next_e,e,f,g,value[479:0],new_word} : value;
        end
    endfunction

    logic [767:0] state[0:PIPELINE-1];
    logic [255:0] initial_cv[0:PIPELINE-1];
    logic [6:0] base[0:PIPELINE-1];
    logic [TAG_BITS-1:0] tag[0:PIPELINE-1];
    logic [PIPELINE-1:0] valid;
    wire stalled = output_valid && !output_ready;
    wire recycle = valid[PIPELINE-1] && base[PIPELINE-1] + 7'(ROUNDS) < 64;
    wire finished = valid[PIPELINE-1] && !recycle;
    assign input_ready = !rst && !stalled && !recycle;

    for (genvar stage=0; stage<PIPELINE; stage=stage+1) begin : stages
        wire [767:0] source_state;
        wire [255:0] source_cv;
        wire [6:0] source_base;
        wire [TAG_BITS-1:0] source_tag;
        wire source_valid;
        if (stage == 0) begin : first
            assign source_state = recycle ? state[PIPELINE-1] : {input_cv,input_block};
            assign source_cv = recycle ? initial_cv[PIPELINE-1] : input_cv;
            assign source_base = recycle ? base[PIPELINE-1] + 7'(ROUNDS) : 7'd0;
            assign source_tag = recycle ? tag[PIPELINE-1] : input_tag;
            assign source_valid = recycle || (input_valid && input_ready);
        end else begin : following
            assign source_state = state[stage-1];
            assign source_cv = initial_cv[stage-1];
            assign source_base = base[stage-1];
            assign source_tag = tag[stage-1];
            assign source_valid = valid[stage-1];
        end
        for (genvar r=0; r<UNROLL; r=r+1) begin : unrolled
            wire [767:0] result;
            if (r == 0) begin : first_round
                assign result = advance_round(source_state, source_base + 7'(stage*UNROLL));
            end else begin : following_round
                assign result = advance_round(unrolled[r-1].result,
                    source_base + 7'(stage*UNROLL+r));
            end
        end
        always_ff @(posedge clk) begin
            if (rst) valid[stage] <= 0;
            else if (!stalled) begin
                valid[stage] <= source_valid;
                if (source_valid) begin
                    state[stage] <= unrolled[UNROLL-1].result;
                    initial_cv[stage] <= source_cv;
                    base[stage] <= source_base;
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
                        initial_cv[PIPELINE-1][32*word_index+:32];
            end
        end
    end

`ifndef SYNTHESIS
    initial begin
        if (PIPELINE < 1 || PIPELINE > 24 || UNROLL < 1 || ROUNDS > 24 ||
            24 % ROUNDS != 0 || TAG_BITS < 1)
            $fatal(1, "Unsupported SHA256 P/U or tag width");
    end
`endif
endmodule
`default_nettype wire
