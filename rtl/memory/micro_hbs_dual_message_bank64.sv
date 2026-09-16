`timescale 1ns/1ps
`default_nettype none

// Two independent 64-bit message banks.  Software can populate one bank at a
// time only while engine_active is low.  During a Job, the two engine ports
// read the banks concurrently and the host port is rejected by construction.
module micro_hbs_dual_message_bank64 #(
    parameter integer WORDS_PER_BANK = 144,
    parameter integer ADDRESS_WIDTH = 16
) (
    input  wire                         clk,
    input  wire                         rst_n,
    input  wire                         engine_active,

    input  wire                         host_write_valid,
    output logic                        host_write_ready,
    input  wire                         host_bank_select,
    input  wire [ADDRESS_WIDTH-1:0]     host_write_address,
    input  wire [63:0]                  host_write_data,
    output logic                        host_bounds_error,

    input  wire                         engine0_read_valid,
    output logic                        engine0_read_ready,
    input  wire [ADDRESS_WIDTH-1:0]     engine0_read_address,
    output logic                        engine0_response_valid,
    output logic [63:0]                 engine0_read_data,
    output logic                        engine0_bounds_error,

    input  wire                         engine1_read_valid,
    output logic                        engine1_read_ready,
    input  wire [ADDRESS_WIDTH-1:0]     engine1_read_address,
    output logic                        engine1_response_valid,
    output logic [63:0]                 engine1_read_data,
    output logic                        engine1_bounds_error
);
    localparam integer INTERNAL_ADDRESS_WIDTH =
        (WORDS_PER_BANK <= 2) ? 1 : $clog2(WORDS_PER_BANK);
    localparam logic [ADDRESS_WIDTH-1:0] WORDS_PER_BANK_LIMIT =
        ADDRESS_WIDTH'(WORDS_PER_BANK);

    (* ram_style = "block" *) logic [63:0] bank0 [0:WORDS_PER_BANK-1];
    (* ram_style = "block" *) logic [63:0] bank1 [0:WORDS_PER_BANK-1];

    wire host_write_accept;
    wire engine0_read_accept;
    wire engine1_read_accept;

    assign host_write_ready = rst_n && !engine_active;
    assign engine0_read_ready = rst_n && engine_active;
    assign engine1_read_ready = rst_n && engine_active;
    assign host_write_accept = host_write_valid && host_write_ready;
    assign engine0_read_accept = engine0_read_valid && engine0_read_ready;
    assign engine1_read_accept = engine1_read_valid && engine1_read_ready;

    initial begin
        if (WORDS_PER_BANK < 1 || WORDS_PER_BANK > (1 << ADDRESS_WIDTH))
            $error("invalid dual message-bank dimensions");
    end

    // Reset-free memories preserve block-RAM inference.  Host and engine
    // accesses are mutually exclusive through engine_active.
    always_ff @(posedge clk) begin
        if (host_write_accept && host_write_address < WORDS_PER_BANK_LIMIT) begin
            if (host_bank_select)
                bank1[host_write_address[INTERNAL_ADDRESS_WIDTH-1:0]]
                    <= host_write_data;
            else
                bank0[host_write_address[INTERNAL_ADDRESS_WIDTH-1:0]]
                    <= host_write_data;
        end

        if (engine0_read_accept && engine0_read_address < WORDS_PER_BANK_LIMIT)
            engine0_read_data
                <= bank0[engine0_read_address[INTERNAL_ADDRESS_WIDTH-1:0]];
        if (engine1_read_accept && engine1_read_address < WORDS_PER_BANK_LIMIT)
            engine1_read_data
                <= bank1[engine1_read_address[INTERNAL_ADDRESS_WIDTH-1:0]];
    end

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            host_bounds_error <= 1'b0;
            engine0_response_valid <= 1'b0;
            engine0_bounds_error <= 1'b0;
            engine1_response_valid <= 1'b0;
            engine1_bounds_error <= 1'b0;
        end else begin
            host_bounds_error <= host_write_accept
                && host_write_address >= WORDS_PER_BANK_LIMIT;
            engine0_response_valid <= engine0_read_accept
                && engine0_read_address < WORDS_PER_BANK_LIMIT;
            engine0_bounds_error <= engine0_read_accept
                && engine0_read_address >= WORDS_PER_BANK_LIMIT;
            engine1_response_valid <= engine1_read_accept
                && engine1_read_address < WORDS_PER_BANK_LIMIT;
            engine1_bounds_error <= engine1_read_accept
                && engine1_read_address >= WORDS_PER_BANK_LIMIT;
        end
    end
endmodule

`default_nettype wire
