// Frozen combinational reference from a76c7a44; no DUT pipeline control.
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

