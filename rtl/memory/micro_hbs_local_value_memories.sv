`timescale 1ns/1ps
`default_nettype none

// Small parity-banked 128-bit value store.  Consecutive dual writes are the
// native access pattern of the two horizontal lanes, so each physical bank
// has one write port.  Asynchronous reads deliberately map to distributed RAM
// and avoid a scheduler bubble for H-parent issue.
module micro_hbs_local_array128_4r (
    input  wire         clk,
    input  wire         write0_valid,
    input  wire [5:0]   write0_address,
    input  wire [127:0] write0_data,
    input  wire         write1_valid,
    input  wire [5:0]   write1_address,
    input  wire [127:0] write1_data,
    input  wire [5:0]   read0_address,
    input  wire [5:0]   read1_address,
    input  wire [5:0]   read2_address,
    input  wire [5:0]   read3_address,
    output wire [127:0] read0_data,
    output wire [127:0] read1_data,
    output wire [127:0] read2_data,
    output wire [127:0] read3_data
);
    (* ram_style = "distributed" *) logic [127:0] even_bank [0:31];
    (* ram_style = "distributed" *) logic [127:0] odd_bank [0:31];
    wire even_write = (write0_valid && !write0_address[0])
        || (write1_valid && !write1_address[0]);
    wire odd_write = (write0_valid && write0_address[0])
        || (write1_valid && write1_address[0]);
    wire [4:0] even_address = write0_valid && !write0_address[0]
        ? write0_address[5:1] : write1_address[5:1];
    wire [4:0] odd_address = write0_valid && write0_address[0]
        ? write0_address[5:1] : write1_address[5:1];
    wire [127:0] even_data = write0_valid && !write0_address[0]
        ? write0_data : write1_data;
    wire [127:0] odd_data = write0_valid && write0_address[0]
        ? write0_data : write1_data;

    always_ff @(posedge clk) begin
        if (even_write) even_bank[even_address] <= even_data;
        if (odd_write) odd_bank[odd_address] <= odd_data;
    end

    assign read0_data = read0_address[0]
        ? odd_bank[read0_address[5:1]] : even_bank[read0_address[5:1]];
    assign read1_data = read1_address[0]
        ? odd_bank[read1_address[5:1]] : even_bank[read1_address[5:1]];
    assign read2_data = read2_address[0]
        ? odd_bank[read2_address[5:1]] : even_bank[read2_address[5:1]];
    assign read3_data = read3_address[0]
        ? odd_bank[read3_address[5:1]] : even_bank[read3_address[5:1]];
endmodule

module micro_hbs_local_array128_1r (
    input  wire         clk,
    input  wire         write0_valid,
    input  wire [5:0]   write0_address,
    input  wire [127:0] write0_data,
    input  wire         write1_valid,
    input  wire [5:0]   write1_address,
    input  wire [127:0] write1_data,
    input  wire [5:0]   read_address,
    output wire [127:0] read_data
);
    (* ram_style = "distributed" *) logic [127:0] even_bank [0:31];
    (* ram_style = "distributed" *) logic [127:0] odd_bank [0:31];
    wire even_write = (write0_valid && !write0_address[0])
        || (write1_valid && !write1_address[0]);
    wire odd_write = (write0_valid && write0_address[0])
        || (write1_valid && write1_address[0]);
    wire [4:0] even_address = write0_valid && !write0_address[0]
        ? write0_address[5:1] : write1_address[5:1];
    wire [4:0] odd_address = write0_valid && write0_address[0]
        ? write0_address[5:1] : write1_address[5:1];
    wire [127:0] even_data = write0_valid && !write0_address[0]
        ? write0_data : write1_data;
    wire [127:0] odd_data = write0_valid && write0_address[0]
        ? write0_data : write1_data;

    always_ff @(posedge clk) begin
        if (even_write) even_bank[even_address] <= even_data;
        if (odd_write) odd_bank[odd_address] <= odd_data;
    end
    assign read_data = read_address[0]
        ? odd_bank[read_address[5:1]] : even_bank[read_address[5:1]];
endmodule

`default_nettype wire
