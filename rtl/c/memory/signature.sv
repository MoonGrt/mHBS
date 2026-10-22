`timescale 1ns / 1ps
`default_nettype none

// One output node per word, without packing or execution-core backpressure.
// 1558 words cover the largest supported signature (SHAKE-256f).
// verilog_format: off
module signature (
    input wire clk,rst,finish,abort,
    input wire write_valid,input wire [255:0] write_data,input wire [5:0] write_bytes,
    input wire read_enable,input wire [10:0] read_address,
    output logic read_valid,output logic [255:0] read_data,
    output logic [5:0] node_bytes,output logic [5:0] read_bytes,
    output wire complete,output logic error,
    output logic [10:0] nodes,output logic [15:0] length
);
// verilog_format: on
    // Split the address space to avoid rounding all 1558 words up to 2048.
    (* ram_style = "block" *) logic [255:0] main_memory[0:1023];
    (* ram_style = "block" *) logic [255:0] middle_memory[0:511];
    (* ram_style = "distributed" *) logic [255:0] tail_memory[0:21];
    (* ram_style = "distributed" *) logic [5:0] byte_counts[0:1557];

    logic [255:0] main_data;
    logic [255:0] middle_data;
    logic [255:0] tail_data;
    logic [1:0] read_bank;

    // These counters and status flags are functional readback metadata.
    wire size_ok = (write_bytes == 4 || write_bytes == 16 ||
                    write_bytes == 24 || write_bytes == 32) &&
                   (write_bytes == 4 || node_bytes == 0 || write_bytes == node_bytes);
    wire writing = write_valid && !rst && !finish && !abort && !error;
    wire reading = read_enable && complete && read_address < nodes;

    assign complete = finish && !rst && !abort && !error && nodes != 0;

    // Leave array contents and data registers unreset to infer block RAM.
    always_ff @(posedge clk) begin
        if (writing && nodes < 1558 && size_ok) begin
            byte_counts[nodes] <= write_bytes;
            if (!nodes[10]) begin
                main_memory[nodes[9:0]] <= write_data;
            end else if (!nodes[9]) begin
                middle_memory[nodes[8:0]] <= write_data;
            end else begin
                tail_memory[nodes[4:0]] <= write_data;
            end
        end

        if (reading) begin
            read_bytes <= byte_counts[read_address];
            if (!read_address[10]) begin
                main_data <= main_memory[read_address[9:0]];
                read_bank <= 0;
            end else if (!read_address[9]) begin
                middle_data <= middle_memory[read_address[8:0]];
                read_bank   <= 1;
            end else begin
                tail_data <= tail_memory[read_address[4:0]];
                read_bank <= 2;
            end
        end
    end

    always_comb begin
        case (read_bank)
            0: read_data = main_data;
            1: read_data = middle_data;
            default: read_data = tail_data;
        endcase
    end

    always_ff @(posedge clk) begin
        if (rst) begin
            nodes <= 0;
            length <= 0;
            node_bytes <= 0;
            error <= 0;
            read_valid <= 0;
        end else begin
            read_valid <= reading;
            if (abort) error <= 1;

            if (writing) begin
                if (nodes >= 1558 || !size_ok) begin
                    error <= 1;
                end else begin
                    nodes  <= nodes + 1'b1;
                    length <= length + {10'd0, write_bytes};
                    if (write_bytes != 4) node_bytes <= write_bytes;
                end
            end
        end
    end
endmodule

`default_nettype wire
