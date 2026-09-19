`timescale 1ns/1ps
`default_nettype none

// 67x256 endpoint scratch. Writes from the two equivalent lanes are
// serialized by one pending entry.  The default implementation is
// distributed memory: at this depth it has a lower Equivalent-Slice cost
// than the four width-banked RAMB36s inferred by a 256-bit block-RAM port.
// The controller may still register/prefetch this asynchronous read.
module micro_hbs_endpoint_scratch256 (
    input wire clk,
    input wire rst_n,
    input wire write0_valid,
    input wire [6:0] write0_index,
    input wire [255:0] write0_data,
    input wire write1_valid,
    input wire [6:0] write1_index,
    input wire [255:0] write1_data,
    output wire write_idle,
    input wire [6:0] read_index,
    output wire [255:0] read_data
);
    logic pending_valid;
    logic [6:0] pending_index;
    logic [255:0] pending_data;
    (* ram_style = "distributed" *) logic [255:0] memory [0:127];

    wire direct0 = !pending_valid && write0_valid;
    wire direct1 = !pending_valid && !write0_valid && write1_valid;
    wire ram_write = pending_valid || direct0 || direct1;
    wire [6:0] ram_write_index = pending_valid ? pending_index
        : (direct0 ? write0_index : write1_index);
    wire [255:0] ram_write_data = pending_valid ? pending_data
        : (direct0 ? write0_data : write1_data);
    assign write_idle = !pending_valid && !write0_valid && !write1_valid;
    assign read_data = memory[read_index];

    always_ff @(posedge clk) begin
        if (ram_write)
            memory[ram_write_index] <= ram_write_data;
    end

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            pending_valid <= 1'b0;
        end else begin
            if (pending_valid)
                pending_valid <= 1'b0;
            else if (write0_valid && write1_valid) begin
                pending_valid <= 1'b1;
                pending_index <= write1_index;
                pending_data <= write1_data;
            end
        end
    end

`ifndef SYNTHESIS
    always_ff @(posedge clk)
        if (pending_valid && (write0_valid || write1_valid))
            $error("endpoint scratch pending-write overflow");
`endif
endmodule

`default_nettype wire
