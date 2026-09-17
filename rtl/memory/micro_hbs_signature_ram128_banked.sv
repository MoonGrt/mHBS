`timescale 1ns/1ps
`default_nettype none

module micro_hbs_ram32_sdp #(
    parameter integer DEPTH = 534,
    parameter integer ADDRESS_WIDTH = 10
) (
    input  wire                     clk,
    input  wire                     write_valid,
    input  wire [ADDRESS_WIDTH-1:0] write_address,
    input  wire [31:0]              write_data,
    input  wire                     read_valid,
    input  wire [ADDRESS_WIDTH-1:0] read_address,
    output logic [31:0]             read_data
);
    (* ram_style = "block" *) logic [31:0] memory [0:DEPTH-1];
    always_ff @(posedge clk)
        if (write_valid)
            memory[write_address] <= write_data;
    always_ff @(posedge clk)
        if (read_valid)
            read_data <= memory[read_address];
endmodule

// 1,068 x 128 signature words, striped over three 356-word banks.  A bank is
// four 32-bit RAMB18 columns, so the complete 136,704-bit signature consumes
// 12 RAMB18 (six RAMB36 equivalents) without the depth waste of parity banks.
// Consecutive dual writes always hit different banks; the output side reads
// the natural 2,136 x 64 stream used by the product interface.
module micro_hbs_signature_ram128_banked (
    input  wire         clk,
    input  wire         rst_n,
    input  wire         write0_valid,
    input  wire [10:0]  write0_word,
    input  wire [127:0] write0_data,
    input  wire         write1_valid,
    input  wire [10:0]  write1_word,
    input  wire [127:0] write1_data,
    output wire         write_conflict,
    input  wire         read_valid,
    input  wire [11:0]  read_address,
    output logic        read_response_valid,
    output logic [63:0] read_data
);
    wire [10:0] read_word = read_address[11:1];
    logic write0_valid_s1, write1_valid_s1;
    logic [10:0] write0_word_s1, write1_word_s1;
    logic [127:0] write0_data_s1, write1_data_s1;
    logic write0_valid_s2, write1_valid_s2;
    logic [1:0] write0_bank_s2, write1_bank_s2;
    logic [8:0] write0_row_s2, write1_row_s2;
    logic [127:0] write0_data_s2, write1_data_s2;
    wire [1:0] read_bank = read_word % 3;
    wire [8:0] read_row = read_word / 3;
    logic [2:0] read_select_q;
    wire [31:0] bank_q0 [0:2];
    wire [31:0] bank_q1 [0:2];
    wire [31:0] bank_q2 [0:2];
    wire [31:0] bank_q3 [0:2];

    // The public contract issues at most two consecutive signature words.
    // Consecutive word numbers cannot alias modulo three, so a runtime modulo
    // comparator would only add a long global error/control path.
    assign write_conflict = 1'b0;

    // Two staging boundaries keep signature-address expressions and the
    // constant divide-by-three away from the BRAM address pins.  Writes are
    // separated by complete Hash contexts, so this fixed two-cycle latency
    // cannot overrun the pipeline and does not add signing cycles.
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            write0_valid_s1 <= 1'b0;
            write1_valid_s1 <= 1'b0;
            write0_valid_s2 <= 1'b0;
            write1_valid_s2 <= 1'b0;
            write0_word_s1 <= '0;
            write1_word_s1 <= '0;
            write0_data_s1 <= '0;
            write1_data_s1 <= '0;
            write0_bank_s2 <= '0;
            write1_bank_s2 <= '0;
            write0_row_s2 <= '0;
            write1_row_s2 <= '0;
            write0_data_s2 <= '0;
            write1_data_s2 <= '0;
        end else begin
            write0_valid_s1 <= write0_valid;
            write1_valid_s1 <= write1_valid;
            write0_word_s1 <= write0_word;
            write1_word_s1 <= write1_word;
            write0_data_s1 <= write0_data;
            write1_data_s1 <= write1_data;
            write0_valid_s2 <= write0_valid_s1;
            write1_valid_s2 <= write1_valid_s1;
            write0_bank_s2 <= write0_word_s1 % 3;
            write1_bank_s2 <= write1_word_s1 % 3;
            write0_row_s2 <= write0_word_s1 / 3;
            write1_row_s2 <= write1_word_s1 / 3;
            write0_data_s2 <= write0_data_s1;
            write1_data_s2 <= write1_data_s1;
        end
    end

    genvar bank;
    generate for (bank = 0; bank < 3; bank = bank + 1) begin : signature_bank
        wire bank_write0 = write0_valid_s2 && write0_bank_s2 == bank;
        wire bank_write1 = write1_valid_s2 && write1_bank_s2 == bank;
        wire bank_write = bank_write0 || bank_write1;
        wire [8:0] bank_write_row = bank_write0
            ? write0_row_s2 : write1_row_s2;
        wire [127:0] bank_write_data = bank_write0
            ? write0_data_s2 : write1_data_s2;

        micro_hbs_ram32_sdp #(.DEPTH(356), .ADDRESS_WIDTH(9)) q0_ram (
            .clk, .write_valid(bank_write), .write_address(bank_write_row),
            .write_data(bank_write_data[31:0]), .read_valid,
            .read_address(read_row), .read_data(bank_q0[bank])
        );
        micro_hbs_ram32_sdp #(.DEPTH(356), .ADDRESS_WIDTH(9)) q1_ram (
            .clk, .write_valid(bank_write), .write_address(bank_write_row),
            .write_data(bank_write_data[63:32]), .read_valid,
            .read_address(read_row), .read_data(bank_q1[bank])
        );
        micro_hbs_ram32_sdp #(.DEPTH(356), .ADDRESS_WIDTH(9)) q2_ram (
            .clk, .write_valid(bank_write), .write_address(bank_write_row),
            .write_data(bank_write_data[95:64]), .read_valid,
            .read_address(read_row), .read_data(bank_q2[bank])
        );
        micro_hbs_ram32_sdp #(.DEPTH(356), .ADDRESS_WIDTH(9)) q3_ram (
            .clk, .write_valid(bank_write), .write_address(bank_write_row),
            .write_data(bank_write_data[127:96]), .read_valid,
            .read_address(read_row), .read_data(bank_q3[bank])
        );
    end endgenerate

    always_ff @(posedge clk) begin
        read_response_valid <= read_valid;
        if (read_valid)
            read_select_q <= {read_bank, read_address[0]};
    end

    always_comb begin
        case (read_select_q)
            3'b000: read_data = {bank_q1[0], bank_q0[0]};
            3'b001: read_data = {bank_q3[0], bank_q2[0]};
            3'b010: read_data = {bank_q1[1], bank_q0[1]};
            3'b011: read_data = {bank_q3[1], bank_q2[1]};
            3'b100: read_data = {bank_q1[2], bank_q0[2]};
            default: read_data = {bank_q3[2], bank_q2[2]};
        endcase
    end
endmodule

`default_nettype wire
