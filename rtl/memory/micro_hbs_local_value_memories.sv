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

// Area-oriented tree store.  SLH parent reduction may issue one parent at a
// time; consecutive children then require one read from each parity bank and
// completed leaves/parents require only one write.
module micro_hbs_local_array128_serial_tree (
    input  wire         clk,
    input  wire         write_valid,
    input  wire [5:0]   write_address,
    input  wire [127:0] write_data,
    input  wire [5:0]   read_address,
    output wire [127:0] read0_data,
    output wire [127:0] read1_data
);
    (* ram_style = "distributed" *) logic [127:0] even_bank [0:31];
    (* ram_style = "distributed" *) logic [127:0] odd_bank [0:31];

    always_ff @(posedge clk) begin
        if (write_valid && !write_address[0])
            even_bank[write_address[5:1]] <= write_data;
        if (write_valid && write_address[0])
            odd_bank[write_address[5:1]] <= write_data;
    end

    wire [4:0] even_read_address = read_address[5:1] + read_address[0];
    wire [127:0] even_read_data = even_bank[even_read_address];
    wire [127:0] odd_read_data = odd_bank[read_address[5:1]];
    assign read0_data = read_address[0] ? odd_read_data : even_read_data;
    assign read1_data = read_address[0] ? even_read_data : odd_read_data;
endmodule

// Consecutive-pair view used by endpoint compression.  A pair always touches
// one even and one odd bank, so unlike the generic four-read store neither
// bank needs to be replicated for a second asynchronous read port.
module micro_hbs_local_array128_pair_read (
    input  wire         clk,
    input  wire         write0_valid,
    input  wire [5:0]   write0_address,
    input  wire [127:0] write0_data,
    input  wire         write1_valid,
    input  wire [5:0]   write1_address,
    input  wire [127:0] write1_data,
    input  wire [5:0]   read_address,
    output wire [127:0] read0_data,
    output wire [127:0] read1_data
);
    (* ram_style = "distributed" *) logic [127:0] even_bank [0:31];
    (* ram_style = "distributed" *) logic [127:0] odd_bank [0:31];
    wire even_write = (write0_valid && !write0_address[0])
        || (write1_valid && !write1_address[0]);
    wire odd_write = (write0_valid && write0_address[0])
        || (write1_valid && write1_address[0]);
    wire [4:0] even_write_address = write0_valid && !write0_address[0]
        ? write0_address[5:1] : write1_address[5:1];
    wire [4:0] odd_write_address = write0_valid && write0_address[0]
        ? write0_address[5:1] : write1_address[5:1];
    wire [127:0] even_write_data = write0_valid && !write0_address[0]
        ? write0_data : write1_data;
    wire [127:0] odd_write_data = write0_valid && write0_address[0]
        ? write0_data : write1_data;

    always_ff @(posedge clk) begin
        if (even_write)
            even_bank[even_write_address] <= even_write_data;
        if (odd_write)
            odd_bank[odd_write_address] <= odd_write_data;
    end

    wire [4:0] even_read_address = read_address[5:1] + read_address[0];
    wire [127:0] even_read_data = even_bank[even_read_address];
    wire [127:0] odd_read_data = odd_bank[read_address[5:1]];
    assign read0_data = read_address[0] ? odd_read_data : even_read_data;
    assign read1_data = read_address[0] ? even_read_data : odd_read_data;
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
