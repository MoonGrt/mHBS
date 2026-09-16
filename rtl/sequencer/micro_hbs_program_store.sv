`timescale 1ns/1ps
`default_nettype none

module micro_hbs_program_store #(
    parameter int PROGRAM_WORDS = 512,
    parameter PROGRAM_INIT_FILE = "",
    parameter int PROGRAM_INIT_WORDS = PROGRAM_WORDS
) (
    input  wire         clk,
    input  wire         write_enable,
    input  wire  [8:0]  write_address,
    input  wire  [63:0] write_data,
    input  wire  [8:0]  read_address,
    output logic [63:0] read_data
);
    (* ram_style = "block" *) logic [63:0] memory [0:PROGRAM_WORDS-1];

    // PROGRAM_INIT_FILE is produced offline from a verified JSON program.
    // An empty string keeps the development-time idle-only load behavior.
    initial begin
        if (PROGRAM_INIT_WORDS < 1 || PROGRAM_INIT_WORDS > PROGRAM_WORDS)
            $error("PROGRAM_INIT_WORDS must be in 1..PROGRAM_WORDS");
        if (PROGRAM_INIT_FILE != "")
            $readmemh(PROGRAM_INIT_FILE, memory, 0, PROGRAM_INIT_WORDS-1);
    end

    always_ff @(posedge clk) begin
        if (write_enable)
            memory[write_address] <= write_data;
        read_data <= memory[read_address];
    end
endmodule

`default_nettype wire
