`timescale 1ns/1ps
`default_nettype none

// Synthesizable SHA-256 for one bounded message of 0..119 bytes.
//
// The bound guarantees that SHA-256 padding occupies one or two 64-byte
// blocks.  Packed byte zero is in bits [7:0], matching the other micro-HBS
// hash lanes.  One request may be outstanding and the response is held until
// rsp_ready.  An out-of-range length is accepted as an error transaction and
// returns a zero digest without starting compression.
module micro_hbs_sha256_bounded (
    input  wire         clk,
    input  wire         rst_n,

    input  wire         req_valid,
    output logic        req_ready,
    input  wire [951:0] req_message,
    input  wire [6:0]   req_length,

    output logic        rsp_valid,
    input  wire         rsp_ready,
    output logic [255:0] rsp_digest,
    output logic        rsp_error
);
    typedef enum logic [1:0] {S_IDLE, S_LOAD, S_ROUND, S_RESPONSE} state_t;
    state_t state;

    logic [1023:0] padded_message;
    logic use_two_blocks;
    logic block_index;
    logic [5:0] round_index;
    // The message schedule is retained as a 16-word circular window.  At
    // round t, entries t-2/t-7/t-15/t-16 are still resident modulo 16.
    logic [31:0] schedule [0:15];

    logic [31:0] hash0, hash1, hash2, hash3;
    logic [31:0] hash4, hash5, hash6, hash7;
    logic [31:0] work_a, work_b, work_c, work_d;
    logic [31:0] work_e, work_f, work_g, work_h;

    logic [31:0] round_word;
    logic [31:0] temp1, temp2;
    logic [31:0] next_a, next_b, next_c, next_d;
    logic [31:0] next_e, next_f, next_g, next_h;
    integer word_index;

    function automatic [31:0] rotate_right(
        input [31:0] value,
        input integer amount
    );
        rotate_right = (value >> amount) | (value << (32-amount));
    endfunction

    function automatic [31:0] small_sigma0(input [31:0] value);
        small_sigma0 = rotate_right(value, 7) ^ rotate_right(value, 18)
            ^ (value >> 3);
    endfunction

    function automatic [31:0] small_sigma1(input [31:0] value);
        small_sigma1 = rotate_right(value, 17) ^ rotate_right(value, 19)
            ^ (value >> 10);
    endfunction

    function automatic [31:0] big_sigma0(input [31:0] value);
        big_sigma0 = rotate_right(value, 2) ^ rotate_right(value, 13)
            ^ rotate_right(value, 22);
    endfunction

    function automatic [31:0] big_sigma1(input [31:0] value);
        big_sigma1 = rotate_right(value, 6) ^ rotate_right(value, 11)
            ^ rotate_right(value, 25);
    endfunction

    function automatic [31:0] choose(
        input [31:0] x,
        input [31:0] y,
        input [31:0] z
    );
        choose = (x & y) ^ (~x & z);
    endfunction

    function automatic [31:0] majority(
        input [31:0] x,
        input [31:0] y,
        input [31:0] z
    );
        majority = (x & y) ^ (x & z) ^ (y & z);
    endfunction

    function automatic [31:0] round_constant(input [5:0] index);
        begin
            case (index)
                6'd0: round_constant=32'h428a2f98;  6'd1: round_constant=32'h71374491;
                6'd2: round_constant=32'hb5c0fbcf;  6'd3: round_constant=32'he9b5dba5;
                6'd4: round_constant=32'h3956c25b;  6'd5: round_constant=32'h59f111f1;
                6'd6: round_constant=32'h923f82a4;  6'd7: round_constant=32'hab1c5ed5;
                6'd8: round_constant=32'hd807aa98;  6'd9: round_constant=32'h12835b01;
                6'd10: round_constant=32'h243185be; 6'd11: round_constant=32'h550c7dc3;
                6'd12: round_constant=32'h72be5d74; 6'd13: round_constant=32'h80deb1fe;
                6'd14: round_constant=32'h9bdc06a7; 6'd15: round_constant=32'hc19bf174;
                6'd16: round_constant=32'he49b69c1; 6'd17: round_constant=32'hefbe4786;
                6'd18: round_constant=32'h0fc19dc6; 6'd19: round_constant=32'h240ca1cc;
                6'd20: round_constant=32'h2de92c6f; 6'd21: round_constant=32'h4a7484aa;
                6'd22: round_constant=32'h5cb0a9dc; 6'd23: round_constant=32'h76f988da;
                6'd24: round_constant=32'h983e5152; 6'd25: round_constant=32'ha831c66d;
                6'd26: round_constant=32'hb00327c8; 6'd27: round_constant=32'hbf597fc7;
                6'd28: round_constant=32'hc6e00bf3; 6'd29: round_constant=32'hd5a79147;
                6'd30: round_constant=32'h06ca6351; 6'd31: round_constant=32'h14292967;
                6'd32: round_constant=32'h27b70a85; 6'd33: round_constant=32'h2e1b2138;
                6'd34: round_constant=32'h4d2c6dfc; 6'd35: round_constant=32'h53380d13;
                6'd36: round_constant=32'h650a7354; 6'd37: round_constant=32'h766a0abb;
                6'd38: round_constant=32'h81c2c92e; 6'd39: round_constant=32'h92722c85;
                6'd40: round_constant=32'ha2bfe8a1; 6'd41: round_constant=32'ha81a664b;
                6'd42: round_constant=32'hc24b8b70; 6'd43: round_constant=32'hc76c51a3;
                6'd44: round_constant=32'hd192e819; 6'd45: round_constant=32'hd6990624;
                6'd46: round_constant=32'hf40e3585; 6'd47: round_constant=32'h106aa070;
                6'd48: round_constant=32'h19a4c116; 6'd49: round_constant=32'h1e376c08;
                6'd50: round_constant=32'h2748774c; 6'd51: round_constant=32'h34b0bcb5;
                6'd52: round_constant=32'h391c0cb3; 6'd53: round_constant=32'h4ed8aa4a;
                6'd54: round_constant=32'h5b9cca4f; 6'd55: round_constant=32'h682e6ff3;
                6'd56: round_constant=32'h748f82ee; 6'd57: round_constant=32'h78a5636f;
                6'd58: round_constant=32'h84c87814; 6'd59: round_constant=32'h8cc70208;
                6'd60: round_constant=32'h90befffa; 6'd61: round_constant=32'ha4506ceb;
                6'd62: round_constant=32'hbef9a3f7; 6'd63: round_constant=32'hc67178f2;
                default: round_constant=32'b0;
            endcase
        end
    endfunction

    function automatic [1023:0] build_padded_message(
        input [951:0] message,
        input [6:0] length
    );
        reg [1023:0] result;
        reg [63:0] bit_length;
        integer byte_index;
        integer length_offset;
        begin
            result = '0;
            for (byte_index = 0; byte_index < 119; byte_index = byte_index + 1)
                if (byte_index < length)
                    result[8*byte_index +: 8] = message[8*byte_index +: 8];
            result[8*length +: 8] = 8'h80;
            bit_length = length * 8;
            length_offset = (length <= 55) ? 56 : 120;
            for (byte_index = 0; byte_index < 8; byte_index = byte_index + 1)
                result[8*(length_offset+byte_index) +: 8] =
                    bit_length[8*(7-byte_index) +: 8];
            build_padded_message = result;
        end
    endfunction

    function automatic [31:0] byte_swap32(input [31:0] value);
        byte_swap32 = {value[7:0], value[15:8], value[23:16], value[31:24]};
    endfunction

    function automatic [255:0] pack_digest(
        input [31:0] value0, input [31:0] value1,
        input [31:0] value2, input [31:0] value3,
        input [31:0] value4, input [31:0] value5,
        input [31:0] value6, input [31:0] value7
    );
        pack_digest = {
            byte_swap32(value7), byte_swap32(value6),
            byte_swap32(value5), byte_swap32(value4),
            byte_swap32(value3), byte_swap32(value2),
            byte_swap32(value1), byte_swap32(value0)
        };
    endfunction

    assign req_ready = (state == S_IDLE);
    assign rsp_valid = (state == S_RESPONSE);

    always @(round_index or
             schedule[0] or schedule[1] or schedule[2] or schedule[3] or
             schedule[4] or schedule[5] or schedule[6] or schedule[7] or
             schedule[8] or schedule[9] or schedule[10] or schedule[11] or
             schedule[12] or schedule[13] or schedule[14] or schedule[15] or
             work_a or work_b or work_c or work_d or
             work_e or work_f or work_g or work_h) begin
        if (round_index < 16)
            round_word = schedule[round_index[3:0]];
        else
            round_word = small_sigma1(schedule[(round_index-2) & 6'h0f])
                + schedule[(round_index-7) & 6'h0f]
                + small_sigma0(schedule[(round_index-15) & 6'h0f])
                + schedule[(round_index-16) & 6'h0f];

        temp1 = work_h + big_sigma1(work_e)
            + choose(work_e, work_f, work_g)
            + round_constant(round_index) + round_word;
        temp2 = big_sigma0(work_a) + majority(work_a, work_b, work_c);
        next_a = temp1 + temp2;
        next_b = work_a;
        next_c = work_b;
        next_d = work_c;
        next_e = work_d + temp1;
        next_f = work_e;
        next_g = work_f;
        next_h = work_g;
    end

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= S_IDLE;
            padded_message <= '0;
            use_two_blocks <= 1'b0;
            block_index <= 1'b0;
            round_index <= '0;
            hash0 <= '0; hash1 <= '0; hash2 <= '0; hash3 <= '0;
            hash4 <= '0; hash5 <= '0; hash6 <= '0; hash7 <= '0;
            work_a <= '0; work_b <= '0; work_c <= '0; work_d <= '0;
            work_e <= '0; work_f <= '0; work_g <= '0; work_h <= '0;
            rsp_digest <= '0;
            rsp_error <= 1'b0;
        end else begin
            case (state)
                S_IDLE: begin
                    if (req_valid) begin
                        rsp_digest <= '0;
                        rsp_error <= 1'b0;
                        if (req_length > 119) begin
                            rsp_error <= 1'b1;
                            state <= S_RESPONSE;
                        end else begin
                            padded_message <= build_padded_message(
                                req_message, req_length);
                            use_two_blocks <= (req_length > 55);
                            block_index <= 1'b0;
                            hash0 <= 32'h6a09e667;
                            hash1 <= 32'hbb67ae85;
                            hash2 <= 32'h3c6ef372;
                            hash3 <= 32'ha54ff53a;
                            hash4 <= 32'h510e527f;
                            hash5 <= 32'h9b05688c;
                            hash6 <= 32'h1f83d9ab;
                            hash7 <= 32'h5be0cd19;
                            state <= S_LOAD;
                        end
                    end
                end

                S_LOAD: begin
                    for (word_index = 0; word_index < 16;
                         word_index = word_index + 1) begin
                        if (!block_index)
                            schedule[word_index] <= {
                                padded_message[8*(4*word_index) +: 8],
                                padded_message[8*(4*word_index+1) +: 8],
                                padded_message[8*(4*word_index+2) +: 8],
                                padded_message[8*(4*word_index+3) +: 8]
                            };
                        else
                            schedule[word_index] <= {
                                padded_message[8*(64+4*word_index) +: 8],
                                padded_message[8*(64+4*word_index+1) +: 8],
                                padded_message[8*(64+4*word_index+2) +: 8],
                                padded_message[8*(64+4*word_index+3) +: 8]
                            };
                    end
                    work_a <= hash0; work_b <= hash1;
                    work_c <= hash2; work_d <= hash3;
                    work_e <= hash4; work_f <= hash5;
                    work_g <= hash6; work_h <= hash7;
                    round_index <= '0;
                    state <= S_ROUND;
                end

                S_ROUND: begin
                    if (round_index >= 16)
                        schedule[round_index[3:0]] <= round_word;
                    work_a <= next_a; work_b <= next_b;
                    work_c <= next_c; work_d <= next_d;
                    work_e <= next_e; work_f <= next_f;
                    work_g <= next_g; work_h <= next_h;

                    if (round_index == 63) begin
                        hash0 <= hash0 + next_a;
                        hash1 <= hash1 + next_b;
                        hash2 <= hash2 + next_c;
                        hash3 <= hash3 + next_d;
                        hash4 <= hash4 + next_e;
                        hash5 <= hash5 + next_f;
                        hash6 <= hash6 + next_g;
                        hash7 <= hash7 + next_h;
                        if (use_two_blocks && !block_index) begin
                            block_index <= 1'b1;
                            state <= S_LOAD;
                        end else begin
                            rsp_digest <= pack_digest(
                                hash0 + next_a, hash1 + next_b,
                                hash2 + next_c, hash3 + next_d,
                                hash4 + next_e, hash5 + next_f,
                                hash6 + next_g, hash7 + next_h);
                            rsp_error <= 1'b0;
                            state <= S_RESPONSE;
                        end
                    end else begin
                        round_index <= round_index + 1'b1;
                    end
                end

                S_RESPONSE: begin
                    if (rsp_ready) begin
                        rsp_digest <= '0;
                        rsp_error <= 1'b0;
                        state <= S_IDLE;
                    end
                end

                default: begin
                    rsp_digest <= '0;
                    rsp_error <= 1'b1;
                    state <= S_RESPONSE;
                end
            endcase
        end
    end
endmodule

`default_nettype wire
