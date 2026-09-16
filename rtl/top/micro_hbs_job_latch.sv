`timescale 1ns/1ps
`default_nettype none

module micro_hbs_job_latch (
    input  wire         clk,
    input  wire         rst_n,
    input  wire         accept,
    input  wire  [7:0]  in_operation,
    input  wire  [15:0] in_parameter_set,
    input  wire  [31:0] in_message_base,
    input  wire  [31:0] in_message_length,
    input  wire  [31:0] in_secret_key_base,
    input  wire  [31:0] in_public_key_base,
    input  wire  [31:0] in_output_base,
    input  wire  [31:0] in_state_handle,
    input  wire  [15:0] in_flags,
    output logic [7:0]  operation,
    output logic [15:0] parameter_set,
    output logic [31:0] message_base,
    output logic [31:0] message_length,
    output logic [31:0] secret_key_base,
    output logic [31:0] public_key_base,
    output logic [31:0] output_base,
    output logic [31:0] state_handle,
    output logic [15:0] flags
);
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            operation <= '0;
            parameter_set <= '0;
            message_base <= '0;
            message_length <= '0;
            secret_key_base <= '0;
            public_key_base <= '0;
            output_base <= '0;
            state_handle <= '0;
            flags <= '0;
        end else if (accept) begin
            operation <= in_operation;
            parameter_set <= in_parameter_set;
            message_base <= in_message_base;
            message_length <= in_message_length;
            secret_key_base <= in_secret_key_base;
            public_key_base <= in_public_key_base;
            output_base <= in_output_base;
            state_handle <= in_state_handle;
            flags <= in_flags;
        end
    end
endmodule

`default_nettype wire
