`timescale 1ns/1ps
`default_nettype none

// Iterative Keccak-f[1600] permutation lane. UNROLL may be any positive
// divisor of 24 so one RTL can explore the area/latency frontier.
module micro_hbs_keccak_f1600 #(
    parameter integer UNROLL = 1
) (
    input  wire          clk,
    input  wire          rst_n,
    input  wire          start,
    output logic         ready,
    input  wire [1599:0] state_in,
    input  wire          chain_enable,
    input  wire          chain_prefix,
    input  wire          chain_prefix_preserve_counter,
    input  wire [2:0]    chain_prefix_domain,
    input  wire [7:0]    chain_count,
    input  wire [7:0]    chain_counter_offset,
    input  wire [7:0]    chain_feedback_offset,
    input  wire [5:0]    chain_feedback_bytes,
    input  wire [31:0]   chain_counter_start,
    input  wire          capture_enable,
    input  wire [7:0]    capture_after,
    output logic [1599:0] state_out,
    output logic         done,
    output logic [255:0] capture_digest,
    output logic         capture_valid,
    output logic [5:0]   rounds_executed
);
    logic [1599:0] state_reg;
    logic [4:0] round_index;
    logic active;
    logic [1599:0] chain_template;
    logic [7:0] chains_remaining;
    logic [31:0] chain_counter;
    logic [7:0] chain_iteration;
    wire [31:0] chain_counter_next = chain_counter + 1'b1;
    wire [31:0] chain_transition_counter
        = chain_prefix && chain_iteration == 1
        ? chain_counter : chain_counter_next;
    wire [1599:0] advanced_state;
    logic [1599:0] next_chain_state;
    wire [1599:0] round_state [0:UNROLL];
    genvar round_step;

    function automatic [63:0] rotl64;
        input [63:0] value;
        input integer amount;
        begin
            if (amount == 0)
                rotl64 = value;
            else
                rotl64 = (value << amount) | (value >> (64 - amount));
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
                    a[x + 5*y] = input_state[64*(x + 5*y) +: 64];

            for (x = 0; x < 5; x = x + 1)
                c[x] = a[x] ^ a[x+5] ^ a[x+10] ^ a[x+15] ^ a[x+20];
            for (x = 0; x < 5; x = x + 1)
                d[x] = c[(x+4)%5] ^ rotl64(c[(x+1)%5], 1);
            for (y = 0; y < 5; y = y + 1)
                for (x = 0; x < 5; x = x + 1)
                    a[x + 5*y] = a[x + 5*y] ^ d[x];

            for (y = 0; y < 5; y = y + 1)
                for (x = 0; x < 5; x = x + 1) begin
                    destination = y + 5*((2*x + 3*y) % 5);
                    b[destination] = rotl64(a[x + 5*y], rho_offset(x, y));
                end

            for (y = 0; y < 5; y = y + 1)
                for (x = 0; x < 5; x = x + 1)
                    a[x + 5*y] = b[x + 5*y]
                                   ^ ((~b[((x+1)%5) + 5*y]) & b[((x+2)%5) + 5*y]);
            a[0] = a[0] ^ round_constant(index);

            result = '0;
            for (y = 0; y < 5; y = y + 1)
                for (x = 0; x < 5; x = x + 1)
                    result[64*(x + 5*y) +: 64] = a[x + 5*y];
            keccak_round = result;
        end
    endfunction

    assign round_state[0] = state_reg;
    generate
        for (round_step = 0; round_step < UNROLL;
             round_step = round_step + 1) begin : generate_rounds
            assign round_state[round_step + 1] = keccak_round(
                round_state[round_step], round_index + round_step
            );
        end
    endgenerate
    assign advanced_state = round_state[UNROLL];
    assign ready = !active;

    // state_in is already a padded SHAKE rate block.  The implemented repeat
    // recipe is the 64-byte HBS chain block used by the descriptor composer:
    // a BE32 step counter at byte 44 and 16 feedback bytes at byte 48.  Keep
    // these slices static so synthesis does not infer a 1600-bit variable
    // byte crossbar.  The composer rejects every other repeat geometry.
    always_comb begin
        next_chain_state = chain_template;
        if (chain_prefix)
            next_chain_state[8*32 +: 32]
                = {5'b0, chain_prefix_domain, 24'b0};
        if (!chain_prefix_preserve_counter)
            next_chain_state[8*44 +: 32] = {
                chain_transition_counter[7:0],
                chain_transition_counter[15:8],
                chain_transition_counter[23:16],
                chain_transition_counter[31:24]
            };
        next_chain_state[8*48 +: 128] = advanced_state[127:0];
    end

    initial begin
        if (UNROLL < 1 || UNROLL > 24 || (24 % UNROLL) != 0)
            $error("micro_hbs_keccak_f1600 UNROLL must divide 24");
    end

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state_reg <= '0;
            state_out <= '0;
            round_index <= '0;
            rounds_executed <= '0;
            active <= 1'b0;
            chain_template <= '0;
            chains_remaining <= '0;
            chain_counter <= '0;
            chain_iteration <= '0;
            done <= 1'b0;
            capture_digest <= '0;
            capture_valid <= 1'b0;
        end else begin
            done <= 1'b0;
            capture_valid <= 1'b0;
            if (start && ready) begin
                state_reg <= state_in;
                chain_template <= state_in;
                chains_remaining <= chain_enable ? chain_count : 8'd1;
                chain_counter <= chain_counter_start;
                chain_iteration <= 8'd1;
                if (capture_enable && capture_after == 0)
                    capture_digest <= '0;
                round_index <= '0;
                rounds_executed <= '0;
                active <= 1'b1;
            end else if (active) begin
                state_reg <= advanced_state;
                rounds_executed <= rounds_executed + UNROLL;
                if (round_index + UNROLL >= 24) begin
                    if (capture_enable && capture_after == chain_iteration)
                        capture_digest <= advanced_state[255:0];
                    if (chain_enable && chains_remaining > 1) begin
                        state_reg <= next_chain_state;
                        chain_template <= next_chain_state;
                        chains_remaining <= chains_remaining - 1'b1;
                        if (!chain_prefix_preserve_counter
                            && !(chain_prefix && chain_iteration == 1))
                            chain_counter <= chain_counter + 1'b1;
                        chain_iteration <= chain_iteration + 1'b1;
                        round_index <= '0;
                    end else begin
                        state_out <= advanced_state;
                        active <= 1'b0;
                        done <= 1'b1;
                        capture_valid <= capture_enable;
                    end
                end else begin
                    round_index <= round_index + UNROLL;
                end
            end
        end
    end
endmodule

`default_nettype wire
