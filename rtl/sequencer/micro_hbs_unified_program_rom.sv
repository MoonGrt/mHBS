`timescale 1ns/1ps
`default_nettype none

// Single-port synchronous 32-Kibit product microcode ROM.  All three profile
// directories, token streams, templates and descriptors occupy this image.
module micro_hbs_unified_program_rom #(
    parameter INIT_FILE = "rtl/microcode/unified_hbs_product_rom64.mem"
) (
    input  wire         clk,
    input  wire         rst_n,
    input  wire         request_valid,
    output wire         request_ready,
    input  wire [7:0]   address,
    output logic         data_valid,
    output logic [127:0] data
);
    // A 128-bit-wide 256-word array consumes two RAMB36 primitives on 7-series.
    // Serialize the two 64-bit halves so the same logical 32-Kibit image fits
    // in one physical RAMB36 without changing the product ABI.
    (* rom_style = "block" *) logic [63:0] memory [0:511];
    initial $readmemh(INIT_FILE, memory);

    typedef enum logic [2:0] {
        R_IDLE, R_LOW_WAIT, R_LOW_CAPTURE, R_HIGH_WAIT, R_HIGH_CAPTURE
    } rom_state_t;
    rom_state_t state;
    logic [8:0] physical_address;
    logic [63:0] memory_data;
    logic [63:0] low_half;
    assign request_ready = state == R_IDLE;

    // Keep the memory read in the canonical one-port synchronous form.  The
    // control FSM never reads the array directly; it only consumes the
    // registered output.  This is required for Vivado to infer one RAMB36.
    always_ff @(posedge clk)
        memory_data <= memory[physical_address];

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= R_IDLE;
            data_valid <= 0;
        end else begin
            data_valid <= 0;
            case (state)
                R_IDLE: if (request_valid) begin
                    physical_address <= {address, 1'b0};
                    state <= R_LOW_WAIT;
                end
                R_LOW_WAIT: state <= R_LOW_CAPTURE;
                R_LOW_CAPTURE: begin
                    low_half <= memory_data;
                    physical_address[0] <= 1'b1;
                    state <= R_HIGH_WAIT;
                end
                R_HIGH_WAIT: state <= R_HIGH_CAPTURE;
                R_HIGH_CAPTURE: begin
                    data <= {memory_data, low_half};
                    data_valid <= 1;
                    state <= R_IDLE;
                end
                default: state <= R_IDLE;
            endcase
        end
    end
endmodule

`default_nettype wire
