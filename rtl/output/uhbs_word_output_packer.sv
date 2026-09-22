`timescale 1ns/1ps
`default_nettype none
// Appends 1..8 bytes per cycle, preserving partial headers between chunks.
module uhbs_word_output_packer (
    input wire clk, rst_n, clear,
    input wire in_valid, output wire in_ready,
    input wire [63:0] in_data, input wire [3:0] in_bytes,
    input wire in_last,
    output wire out_valid, input wire out_ready,
    output wire [63:0] out_data, output wire [7:0] out_keep,
    output wire out_last, output wire idle
);
    logic [127:0] buffer;
    logic [4:0] count;
    logic final_chunk;
    wire pop = out_valid && out_ready;
    wire [4:0] removed = pop ? (count >= 8 ? 8 : count) : 0;
    wire [4:0] remaining = count-removed;
    wire push = in_valid && in_ready;
    wire [127:0] shifted = pop ? buffer >> (removed*8) : buffer;
    wire [63:0] masked_input = in_data & (64'hffffffffffffffff >> ((8-in_bytes)*8));
    assign in_ready = !final_chunk && remaining <= 8;
    assign out_valid = count >= 8 || (final_chunk && count != 0);
    assign out_data = buffer[63:0];
    assign out_keep = count >= 8 ? 8'hff : (8'hff >> (8-count));
    assign out_last = final_chunk && count <= 8;
    assign idle = count == 0;
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin count<=0; buffer<=0; final_chunk<=0; end
        else if (clear) begin count<=0; buffer<=0; final_chunk<=0; end
        else begin
            if (push) begin
                buffer <= shifted | ({64'd0,masked_input} << (remaining*8));
                count <= remaining+in_bytes;
                final_chunk <= in_last;
            end else if (pop) begin
                buffer <= shifted;
                count <= remaining;
                if (out_last) final_chunk <= 0;
            end
        end
    end
endmodule
`default_nettype wire
