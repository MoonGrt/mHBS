`timescale 1ns/1ps
`default_nettype none
// ABI 4 byte recipes and local chain feedback. Both physical lanes use this
// module. The dispatcher keeps all request fields stable through response.
(* black_box="yes" *) module uhbs_recipe_lane #(
    parameter integer N = 16,
    parameter integer DIGEST_BYTES = N==16 ? 34 : 32, INDEX_BITS = 7,
    parameter integer UNROLL = 2,
    parameter integer MAX_MESSAGE_BYTES = 87,
    parameter [15:0] RECIPE_MASK = 16'hffff,
    parameter bit PROFILE_ENABLE = 0
) (
    input wire clk, rst_n,
    input wire [5:0] node_bytes,
    input wire request_valid, output wire request_ready,
    input wire [63:0] request_recipe, request_step_recipe,
    input wire request_chain,
    input wire [4:0] request_steps, request_capture_after,
    input wire request_capture,
    input wire [N*8-1:0] secret_seed, secret_prf, public_seed, root, randomizer,
    input wire [127:0] identifier,
    input wire [MAX_MESSAGE_BYTES*8-1:0] message_buffer,
    input wire [6:0] message_length,
    input wire [4:0] request_layer,
    input wire [63:0] request_tree,
    input wire [9:0] request_leaf,
    input wire [INDEX_BITS-1:0] request_a,
    input wire [31:0] request_b,
    input wire [N*8-1:0] request_left, request_right,
    output wire [INDEX_BITS-1:0] list_index0, list_index1,
    input wire [N*8-1:0] list_data0, list_data1,
    output wire response_valid, input wire response_ready,
    output wire [DIGEST_BYTES*8-1:0] response_value,
    output wire [N*8-1:0] response_capture,
    output logic error,
    output logic [31:0] hash_count, permutation_count
);
endmodule
