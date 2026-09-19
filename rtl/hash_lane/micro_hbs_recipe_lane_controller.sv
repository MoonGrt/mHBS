`timescale 1ns/1ps
`default_nettype none

// Per-lane state for the descriptor-selected stateful recipes.  All wide
// rate-block construction is deliberately outside this module so two lanes
// can share one materializer without sharing feedback or completion state.
module micro_hbs_recipe_lane_controller (
    input  wire         clk,
    input  wire         rst_n,
    input  wire         request_valid,
    output wire         request_ready,
    input  wire [3:0]   request_recipe,
    input  wire [4:0]   request_steps,
    input  wire [255:0] request_left,
    output wire         compose_valid,
    input  wire         compose_accept,
    output wire [3:0]   compose_recipe,
    output wire [3:0]   compose_primitive,
    output wire [11:0]  compose_length,
    output wire [4:0]   compose_chain_step,
    output wire [1:0]   compose_stage,
    output wire [255:0] compose_current,
    output wire [255:0] compose_key,
    output wire [255:0] compose_mask0,
    output wire [255:0] compose_mask1,
    input  wire         digest_valid,
    input  wire [255:0] digest_value,
    input  wire         primitive_error,
    output wire         response_valid,
    input  wire         response_ready,
    output wire [255:0] response_value,
    output logic        error,
    output wire         active
);
    localparam logic [3:0] R_PRF_INDEX       = 4'd1;
    localparam logic [3:0] R_MESSAGE_ROOT    = 4'd2;
    localparam logic [3:0] R_MASKED_CHAIN    = 4'd3;
    localparam logic [3:0] R_MASKED_PARENT   = 4'd4;
    localparam logic [3:0] R_PREFIX_MESSAGE  = 4'd5;
    localparam logic [3:0] R_PREFIX_CHAIN    = 4'd6;
    localparam logic [3:0] R_PREFIX_LIST     = 4'd7;
    localparam logic [3:0] R_PREFIX_LEAF     = 4'd8;
    localparam logic [3:0] R_PREFIX_PARENT   = 4'd9;

    localparam logic [3:0] P_PRF_INDEX       = 4'd1;
    localparam logic [3:0] P_MESSAGE_ROOT    = 4'd2;
    localparam logic [3:0] P_SEED_ADDRESS    = 4'd3;
    localparam logic [3:0] P_ADDRESS_PRF     = 4'd4;
    localparam logic [3:0] P_MASKED_F        = 4'd5;
    localparam logic [3:0] P_MASKED_H        = 4'd6;
    localparam logic [3:0] P_PREFIX_MESSAGE  = 4'd7;
    localparam logic [3:0] P_PREFIX_PRIVATE  = 4'd8;
    localparam logic [3:0] P_PREFIX_CHAIN    = 4'd9;
    localparam logic [3:0] P_PREFIX_LIST     = 4'd10;
    localparam logic [3:0] P_PREFIX_LEAF     = 4'd11;
    localparam logic [3:0] P_PREFIX_PARENT   = 4'd12;

    typedef enum logic [2:0] {
        C_IDLE, C_READY, C_WAIT, C_RESPONSE, C_ERROR
    } control_state_t;
    control_state_t state;

    logic [3:0] recipe, primitive_kind;
    logic [11:0] primitive_length;
    logic [4:0] requested_steps, chain_step;
    logic [1:0] compound_stage;
    logic [255:0] current_value, temporary_key, mask0, mask1;

    assign request_ready = state == C_IDLE;
    assign compose_valid = state == C_READY;
    assign compose_recipe = recipe;
    assign compose_primitive = primitive_kind;
    assign compose_length = primitive_length;
    assign compose_chain_step = chain_step;
    assign compose_stage = compound_stage;
    assign compose_current = current_value;
    assign compose_key = temporary_key;
    assign compose_mask0 = mask0;
    assign compose_mask1 = mask1;
    assign response_valid = state == C_RESPONSE || state == C_ERROR;
    assign response_value = current_value;
    assign active = state != C_IDLE;

    task automatic next_primitive(
        input logic [3:0] next_kind,
        input logic [11:0] next_length
    );
        begin
            primitive_kind <= next_kind;
            primitive_length <= next_length;
            state <= C_READY;
        end
    endtask

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= C_IDLE;
            error <= 1'b0;
        end else if (primitive_error && state != C_IDLE) begin
            error <= 1'b1;
            state <= C_ERROR;
        end else case (state)
            C_IDLE: if (request_valid) begin
                recipe <= request_recipe;
                requested_steps <= request_steps;
                chain_step <= '0;
                compound_stage <= '0;
                error <= 1'b0;
                case (request_recipe)
                    R_PRF_INDEX:
                        next_primitive(P_PRF_INDEX, 12'd96);
                    R_MESSAGE_ROOT:
                        // The shared materializer adds the message length.
                        next_primitive(P_MESSAGE_ROOT, 12'd128);
                    R_MASKED_CHAIN:
                        next_primitive(P_SEED_ADDRESS, 12'd128);
                    R_MASKED_PARENT:
                        next_primitive(P_ADDRESS_PRF, 12'd96);
                    R_PREFIX_MESSAGE:
                        // The shared materializer adds the message length.
                        next_primitive(P_PREFIX_MESSAGE, 12'd54);
                    R_PREFIX_CHAIN:
                        next_primitive(P_PREFIX_PRIVATE, 12'd55);
                    R_PREFIX_LIST:
                        next_primitive(P_PREFIX_LIST, 12'd2166);
                    R_PREFIX_LEAF: begin
                        current_value <= request_left;
                        next_primitive(P_PREFIX_LEAF, 12'd54);
                    end
                    R_PREFIX_PARENT:
                        next_primitive(P_PREFIX_PARENT, 12'd86);
                    default: begin
                        error <= 1'b1;
                        state <= C_ERROR;
                    end
                endcase
            end
            C_READY: if (compose_accept)
                state <= C_WAIT;
            C_WAIT: if (digest_valid) begin
                case (recipe)
                    R_MASKED_CHAIN: begin
                        if (primitive_kind == P_SEED_ADDRESS) begin
                            current_value <= digest_value;
                            if (requested_steps == 0) begin
                                state <= C_RESPONSE;
                            end else begin
                                compound_stage <= 0;
                                next_primitive(P_ADDRESS_PRF, 12'd96);
                            end
                        end else if (primitive_kind == P_ADDRESS_PRF) begin
                            if (compound_stage == 0) begin
                                temporary_key <= digest_value;
                                compound_stage <= 1;
                                next_primitive(P_ADDRESS_PRF, 12'd96);
                            end else begin
                                mask0 <= digest_value;
                                next_primitive(P_MASKED_F, 12'd96);
                            end
                        end else begin
                            current_value <= digest_value;
                            if (chain_step + 1'b1 >= requested_steps) begin
                                state <= C_RESPONSE;
                            end else begin
                                chain_step <= chain_step + 1'b1;
                                compound_stage <= 0;
                                next_primitive(P_ADDRESS_PRF, 12'd96);
                            end
                        end
                    end
                    R_MASKED_PARENT: begin
                        if (primitive_kind == P_ADDRESS_PRF) begin
                            case (compound_stage)
                                0: begin
                                    temporary_key <= digest_value;
                                    compound_stage <= 1;
                                    next_primitive(P_ADDRESS_PRF, 12'd96);
                                end
                                1: begin
                                    mask0 <= digest_value;
                                    compound_stage <= 2;
                                    next_primitive(P_ADDRESS_PRF, 12'd96);
                                end
                                default: begin
                                    mask1 <= digest_value;
                                    next_primitive(P_MASKED_H, 12'd128);
                                end
                            endcase
                        end else begin
                            current_value <= digest_value;
                            state <= C_RESPONSE;
                        end
                    end
                    R_PREFIX_CHAIN: begin
                        current_value <= digest_value;
                        if (primitive_kind == P_PREFIX_PRIVATE) begin
                            if (requested_steps == 0) begin
                                state <= C_RESPONSE;
                            end else
                                next_primitive(P_PREFIX_CHAIN, 12'd55);
                        end else if (chain_step + 1'b1 >= requested_steps) begin
                            state <= C_RESPONSE;
                        end else begin
                            chain_step <= chain_step + 1'b1;
                            next_primitive(P_PREFIX_CHAIN, 12'd55);
                        end
                    end
                    default: begin
                        current_value <= digest_value;
                        state <= C_RESPONSE;
                    end
                endcase
            end
            C_RESPONSE: if (response_ready)
                state <= C_IDLE;
            C_ERROR: if (response_ready)
                state <= C_IDLE;
            default: begin
                error <= 1'b1;
                state <= C_ERROR;
            end
        endcase
    end
endmodule

`default_nettype wire
