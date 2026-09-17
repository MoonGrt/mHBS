`timescale 1ns/1ps
`default_nettype none

// One 128-bit write-through line holding the first two words of the most
// recent hash result. Lookup happens once, before component emission; no
// cache comparator is placed on the Scratchpad request-enable path.
module micro_hbs_hash_feedback_cache #(
    parameter integer ADDRESS_WIDTH = 16
) (
    input  wire                         clk,
    input  wire                         rst_n,
    input  wire                         clear,
    input  wire                         fill_valid,
    input  wire [ADDRESS_WIDTH-1:0]     fill_base_address,
    input  wire [1:0]                   fill_words,
    input  wire [127:0]                 fill_data,
    input  wire                         invalidate_valid,
    input  wire [ADDRESS_WIDTH-1:0]     lookup_base_address,
    input  wire [1:0]                   lookup_words,
    output wire                         lookup_hit,
    output wire [127:0]                 lookup_data
);
    logic valid;
    logic [ADDRESS_WIDTH-1:0] base_address;
    logic [1:0] word_count;
    logic [127:0] data;

    assign lookup_hit = valid && base_address == lookup_base_address
        && lookup_words != 0 && lookup_words <= word_count;
    assign lookup_data = data;

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            valid <= 1'b0;
            base_address <= '0;
            word_count <= '0;
            data <= '0;
        end else if (clear) begin
            valid <= 1'b0;
        end else begin
            if (invalidate_valid)
                valid <= 1'b0;
            if (fill_valid) begin
                valid <= 1'b1;
                base_address <= fill_base_address;
                word_count <= fill_words;
                data <= fill_data;
            end
        end
    end
endmodule

`default_nettype wire
