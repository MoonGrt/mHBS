`timescale 1ns/1ps
`default_nettype none

// Structurally explicit Keccak-f[1600] round used to compare Vivado mapping
// against the function-inlined implementation.
module keccak (
    input  wire [1599:0] state_in,
    input  wire [4:0]    round_index,
    output wire [1599:0] state_out
);
    wire [63:0] a [0:24];
    wire [63:0] c [0:4];
    wire [63:0] d [0:4];
    wire [63:0] rotated_a [0:24];
    wire [63:0] rotated_d [0:24];
    wire [63:0] rc;
    genvar x, y;

    function automatic [63:0] rotl64;
        input [63:0] value;
        input integer amount;
        begin
            rotl64 = amount == 0 ? value
                : (value << amount) | (value >> (64-amount));
        end
    endfunction

    function automatic integer rho_offset;
        input integer lane;
        begin
            case (lane)
                 0: rho_offset=0;   1: rho_offset=1;   2: rho_offset=62;
                 3: rho_offset=28;  4: rho_offset=27;  5: rho_offset=36;
                 6: rho_offset=44;  7: rho_offset=6;   8: rho_offset=55;
                 9: rho_offset=20; 10: rho_offset=3;  11: rho_offset=10;
                12: rho_offset=43; 13: rho_offset=25; 14: rho_offset=39;
                15: rho_offset=41; 16: rho_offset=45; 17: rho_offset=15;
                18: rho_offset=21; 19: rho_offset=8;  20: rho_offset=18;
                21: rho_offset=2;  22: rho_offset=61; 23: rho_offset=56;
                24: rho_offset=14;
                default: rho_offset=0;
            endcase
        end
    endfunction

    function automatic [63:0] round_constant;
        input [4:0] index;
        begin
            case (index)
                 0: round_constant=64'h0000000000000001;
                 1: round_constant=64'h0000000000008082;
                 2: round_constant=64'h800000000000808a;
                 3: round_constant=64'h8000000080008000;
                 4: round_constant=64'h000000000000808b;
                 5: round_constant=64'h0000000080000001;
                 6: round_constant=64'h8000000080008081;
                 7: round_constant=64'h8000000000008009;
                 8: round_constant=64'h000000000000008a;
                 9: round_constant=64'h0000000000000088;
                10: round_constant=64'h0000000080008009;
                11: round_constant=64'h000000008000000a;
                12: round_constant=64'h000000008000808b;
                13: round_constant=64'h800000000000008b;
                14: round_constant=64'h8000000000008089;
                15: round_constant=64'h8000000000008003;
                16: round_constant=64'h8000000000008002;
                17: round_constant=64'h8000000000000080;
                18: round_constant=64'h000000000000800a;
                19: round_constant=64'h800000008000000a;
                20: round_constant=64'h8000000080008081;
                21: round_constant=64'h8000000000008080;
                22: round_constant=64'h0000000080000001;
                23: round_constant=64'h8000000080008008;
                default: round_constant=0;
            endcase
        end
    endfunction

    assign rc = round_constant(round_index);
    generate
        for (y=0; y<5; y=y+1) begin : map_y
            for (x=0; x<5; x=x+1) begin : map_x
                localparam integer I = x + 5*y;
                localparam integer DEST = y + 5*((2*x + 3*y) % 5);
                assign a[I] = state_in[64*I +: 64];
                localparam integer NEXT = ((x+1)%5)+5*y;
                localparam integer NEXT2 = ((x+2)%5)+5*y;
                wire [63:0] chi;
                assign rotated_a[DEST] = rotl64(a[I], rho_offset(I));
                assign rotated_d[DEST] = rotl64(d[x], rho_offset(I));
`ifdef MHBS_XILINX_LUT6
                // Theta's three XORs and Chi have exactly six inputs per bit.
                // Bind that whole function to one LUT6 instead of retaining
                // the 1,600-bit Theta intermediate as separately mapped XORs.
                for (genvar bit_index=0; bit_index<64; bit_index=bit_index+1) begin : fused
                    LUT6 #(.INIT(64'h6666966996696666)) theta_chi (
                        .I0(rotated_a[I][bit_index]), .I1(rotated_d[I][bit_index]),
                        .I2(rotated_a[NEXT][bit_index]), .I3(rotated_d[NEXT][bit_index]),
                        .I4(rotated_a[NEXT2][bit_index]), .I5(rotated_d[NEXT2][bit_index]),
                        .O(chi[bit_index])
                    );
                end
`else
                assign chi = (rotated_a[I] ^ rotated_d[I])
                    ^ ((~(rotated_a[NEXT] ^ rotated_d[NEXT]))
                        & (rotated_a[NEXT2] ^ rotated_d[NEXT2]));
`endif
                assign state_out[64*I +:64] = chi ^ (I == 0 ? rc : 64'd0);
            end
        end
        for (x=0; x<5; x=x+1) begin : columns
            assign c[x] = a[x] ^ a[x+5] ^ a[x+10] ^ a[x+15] ^ a[x+20];
            assign d[x] = c[(x+4)%5] ^ rotl64(c[(x+1)%5], 1);
        end
    endgenerate
endmodule

`ifdef MHBS_XILINX_LUT6
`ifdef VERILATOR
// Model the actual INIT table in portable simulation. Vivado resolves LUT6
// from its device library; no vendor simulation installation is required.
module LUT6 #(parameter [63:0] INIT=64'd0) (
    input wire I0,I1,I2,I3,I4,I5, output wire O
);
    assign O=INIT[{I5,I4,I3,I2,I1,I0}];
endmodule
`endif
`endif

`default_nettype wire
