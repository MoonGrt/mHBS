`timescale 1ns/1ps
`default_nettype none

module micro_hbs_hash_latency_stub #(
    parameter int LATENCY = 3
) (
    input  wire         clk,
    input  wire         rst_n,
    input  wire         req_valid,
    output logic        req_ready,
    input  wire  [15:0] layout_id,
    input  wire  [1:0]  lane_mask,
    input  wire  [7:0]  dest,
    input  wire  [7:0]  index_reg,
    output logic        rsp_valid
);
    localparam int COUNT_W = (LATENCY < 2) ? 1 : $clog2(LATENCY + 1);
    logic [COUNT_W-1:0] count;
    logic active;

    assign req_ready = !active;

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            count <= '0;
            active <= 1'b0;
            rsp_valid <= 1'b0;
        end else begin
            rsp_valid <= 1'b0;
            if (req_valid && req_ready) begin
                active <= 1'b1;
                count <= LATENCY[COUNT_W-1:0];
            end else if (active && count > 1) begin
                count <= count - 1'b1;
            end else if (active) begin
                active <= 1'b0;
                count <= '0;
                rsp_valid <= 1'b1;
            end
        end
    end
endmodule

`default_nettype wire
