`timescale 1ns/1ps
`default_nettype none

// Bounded single-port 64-bit scratchpad with an explicit full-memory scrub.
// The memory array intentionally has no reset so FPGA block RAM can be used.
module micro_hbs_scratchpad64 #(
    parameter integer WORDS = 512,
    parameter integer ADDRESS_WIDTH = 16
) (
    input  wire                     clk,
    input  wire                     rst_n,
    input  wire                     request_valid,
    output logic                    request_ready,
    input  wire                     request_write,
    input  wire [ADDRESS_WIDTH-1:0] request_address,
    input  wire [63:0]              request_write_data,
    output logic                    response_valid,
    output logic [63:0]             response_read_data,
    output logic                    bounds_error,
    input  wire                     scrub_start,
    output logic                    scrub_busy,
    output logic                    scrub_done
);
    localparam integer INTERNAL_ADDRESS_WIDTH = (WORDS <= 2) ? 1 : $clog2(WORDS);
    (* ram_style = "block" *) logic [63:0] memory [0:WORDS-1];
    logic [INTERNAL_ADDRESS_WIDTH-1:0] scrub_address;
    wire memory_write_enable;
    wire [INTERNAL_ADDRESS_WIDTH-1:0] memory_write_address;
    wire [63:0] memory_write_data;
    wire memory_read_enable;
    wire [INTERNAL_ADDRESS_WIDTH-1:0] memory_read_address;

    assign request_ready = !scrub_busy && !scrub_start;
    assign memory_write_enable = scrub_busy
        || (request_valid && request_ready && request_address < WORDS && request_write);
    assign memory_write_address = scrub_busy
        ? scrub_address : request_address[INTERNAL_ADDRESS_WIDTH-1:0];
    assign memory_write_data = scrub_busy ? 64'b0 : request_write_data;
    assign memory_read_enable = request_valid && request_ready
        && request_address < WORDS && !request_write;
    assign memory_read_address = request_address[INTERNAL_ADDRESS_WIDTH-1:0];

    initial begin
        if (WORDS < 1 || WORDS > (1 << ADDRESS_WIDTH))
            $error("invalid scratchpad WORDS/ADDRESS_WIDTH");
    end

    // Keep the RAM in a reset-free, single-clock process for block-RAM inference.
    always_ff @(posedge clk) begin
        if (memory_write_enable)
            memory[memory_write_address] <= memory_write_data;
        if (memory_read_enable)
            response_read_data <= memory[memory_read_address];
    end

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            response_valid <= 1'b0;
            bounds_error <= 1'b0;
            scrub_busy <= 1'b0;
            scrub_done <= 1'b0;
            scrub_address <= '0;
        end else begin
            response_valid <= memory_read_enable;
            bounds_error <= 1'b0;
            scrub_done <= 1'b0;

            if (scrub_busy) begin
                if (scrub_address == WORDS-1) begin
                    scrub_busy <= 1'b0;
                    scrub_done <= 1'b1;
                    scrub_address <= '0;
                end else begin
                    scrub_address <= scrub_address + 1'b1;
                end
            end else if (scrub_start) begin
                scrub_busy <= 1'b1;
                scrub_address <= '0;
            end else if (request_valid) begin
                if (request_address >= WORDS) begin
                    bounds_error <= 1'b1;
                end
            end
        end
    end
endmodule

`default_nettype wire
