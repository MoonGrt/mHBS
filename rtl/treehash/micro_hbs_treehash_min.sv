`timescale 1ns/1ps
`default_nettype none

// Streaming TREEHASH_MIN controller. It stores at most TREE_HEIGHT+1 nodes and
// emits parent-hash requests; the hash function/domain layout stays external.
// start while ready begins a tree.  start while busy cancels the active tree;
// an already accepted parent request is drained before ready is reasserted.
module micro_hbs_treehash_min #(
    parameter integer TREE_HEIGHT = 10
) (
    input  wire         clk,
    input  wire         rst_n,
    input  wire         start,
    output logic        ready,
    input  wire [15:0]  target_leaf,
    input  wire         leaf_valid,
    output logic        leaf_ready,
    input  wire [15:0]  leaf_index,
    input  wire [255:0] leaf_value,
    output logic        parent_req_valid,
    input  wire         parent_req_ready,
    output logic [7:0]  parent_req_height,
    output logic [15:0] parent_req_start_leaf,
    output logic [255:0] parent_req_left,
    output logic [255:0] parent_req_right,
    input  wire         parent_rsp_valid,
    input  wire [255:0] parent_rsp_value,
    input  wire         parent_rsp_error,
    output logic        auth_valid,
    output logic [7:0]  auth_level,
    output logic [255:0] auth_node,
    output logic        root_valid,
    output logic [255:0] root,
    output logic        busy,
    output logic        error,
    output logic [15:0] error_code,
    output logic [15:0] accepted_leaves,
    output logic [15:0] parent_hashes,
    output logic [7:0]  peak_stack_nodes
);
    localparam logic [15:0] ERR_TARGET_RANGE = 16'h0201;
    localparam logic [15:0] ERR_LEAF_ORDER = 16'h0202;
    localparam logic [15:0] ERR_STACK_OVERFLOW = 16'h0203;
    localparam logic [15:0] ERR_PARENT_RESPONSE = 16'h0204;

    typedef enum logic [2:0] {
        S_IDLE, S_ACCEPT, S_MERGE, S_PARENT_REQ, S_PARENT_WAIT, S_ABORT_DRAIN
    } state_t;
    state_t state;
    logic [255:0] stack_value [0:TREE_HEIGHT];
    logic [7:0] stack_height [0:TREE_HEIGHT];
    logic [15:0] stack_start [0:TREE_HEIGHT];
    logic [7:0] stack_sp;
    logic [255:0] work_value;
    logic [7:0] work_height;
    logic [15:0] work_start;
    logic [15:0] next_leaf;
    logic [15:0] target_leaf_latched;
    logic capture_auth;
    logic [255:0] capture_node;
    integer index;

    task automatic clear_working_state;
        integer clear_index;
        begin
            stack_sp <= '0;
            work_value <= '0;
            work_height <= '0;
            work_start <= '0;
            next_leaf <= '0;
            target_leaf_latched <= '0;
            parent_req_height <= '0;
            parent_req_start_leaf <= '0;
            parent_req_left <= '0;
            parent_req_right <= '0;
            capture_auth <= 1'b0;
            capture_node <= '0;
            for (clear_index = 0; clear_index <= TREE_HEIGHT;
                 clear_index = clear_index + 1) begin
                stack_value[clear_index] <= '0;
                stack_height[clear_index] <= '0;
                stack_start[clear_index] <= '0;
            end
        end
    endtask

    assign ready = (state == S_IDLE);
    assign busy = (state != S_IDLE);
    assign leaf_ready = (state == S_ACCEPT);
    assign parent_req_valid = (state == S_PARENT_REQ);

    initial begin
        if (TREE_HEIGHT < 1 || TREE_HEIGHT > 15)
            $error("TREE_HEIGHT must be in 1..15");
    end

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= S_IDLE;
            stack_sp <= '0;
            work_value <= '0;
            work_height <= '0;
            work_start <= '0;
            next_leaf <= '0;
            target_leaf_latched <= '0;
            parent_req_height <= '0;
            parent_req_start_leaf <= '0;
            parent_req_left <= '0;
            parent_req_right <= '0;
            capture_auth <= 1'b0;
            capture_node <= '0;
            auth_valid <= 1'b0;
            auth_level <= '0;
            auth_node <= '0;
            root_valid <= 1'b0;
            root <= '0;
            error <= 1'b0;
            error_code <= '0;
            accepted_leaves <= '0;
            parent_hashes <= '0;
            peak_stack_nodes <= '0;
            for (index = 0; index <= TREE_HEIGHT; index = index + 1) begin
                stack_value[index] <= '0;
                stack_height[index] <= '0;
                stack_start[index] <= '0;
            end
        end else begin
            auth_valid <= 1'b0;
            root_valid <= 1'b0;
            // The parent interface has no response tag.  If cancellation races
            // an accepted request, keep the tree unavailable until that one
            // response is consumed so it cannot reach the next transaction.
            if (start && state != S_IDLE && state != S_ABORT_DRAIN) begin
                clear_working_state();
                error <= 1'b0;
                error_code <= '0;
                if ((state == S_PARENT_WAIT
                     && !(parent_rsp_valid || parent_rsp_error))
                    || (state == S_PARENT_REQ && parent_req_ready))
                    state <= S_ABORT_DRAIN;
                else
                    state <= S_IDLE;
            end else case (state)
                S_IDLE: begin
                    if (start) begin
                        if (target_leaf >= (1 << TREE_HEIGHT)) begin
                            clear_working_state();
                            error <= 1'b1;
                            error_code <= ERR_TARGET_RANGE;
                        end else begin
                            stack_sp <= '0;
                            next_leaf <= '0;
                            target_leaf_latched <= target_leaf;
                            error <= 1'b0;
                            error_code <= '0;
                            accepted_leaves <= '0;
                            parent_hashes <= '0;
                            peak_stack_nodes <= '0;
                            state <= S_ACCEPT;
                        end
                    end
                end
                S_ACCEPT: begin
                    if (leaf_valid) begin
                        if (leaf_index != next_leaf || leaf_index >= (1 << TREE_HEIGHT)) begin
                            clear_working_state();
                            error <= 1'b1;
                            error_code <= ERR_LEAF_ORDER;
                            state <= S_IDLE;
                        end else begin
                            work_value <= leaf_value;
                            work_height <= '0;
                            work_start <= leaf_index;
                            next_leaf <= next_leaf + 1'b1;
                            accepted_leaves <= accepted_leaves + 1'b1;
                            state <= S_MERGE;
                        end
                    end
                end
                S_MERGE: begin
                    if (stack_sp != 0 && stack_height[stack_sp-1] == work_height) begin
                        parent_req_height <= work_height + 1'b1;
                        parent_req_start_leaf <= stack_start[stack_sp-1];
                        parent_req_left <= stack_value[stack_sp-1];
                        parent_req_right <= work_value;
                        if (target_leaf_latched >= stack_start[stack_sp-1]
                            && target_leaf_latched < work_start) begin
                            capture_auth <= 1'b1;
                            capture_node <= work_value;
                        end else if (target_leaf_latched >= work_start
                                     && target_leaf_latched < work_start + (1 << work_height)) begin
                            capture_auth <= 1'b1;
                            capture_node <= stack_value[stack_sp-1];
                        end else begin
                            capture_auth <= 1'b0;
                            capture_node <= '0;
                        end
                        state <= S_PARENT_REQ;
                    end else if (work_height == TREE_HEIGHT) begin
                        if (stack_sp != 0 || accepted_leaves != (1 << TREE_HEIGHT)) begin
                            clear_working_state();
                            error <= 1'b1;
                            error_code <= ERR_LEAF_ORDER;
                        end else begin
                            root <= work_value;
                            root_valid <= 1'b1;
                        end
                        state <= S_IDLE;
                    end else if (stack_sp > TREE_HEIGHT) begin
                        clear_working_state();
                        error <= 1'b1;
                        error_code <= ERR_STACK_OVERFLOW;
                        state <= S_IDLE;
                    end else begin
                        stack_value[stack_sp] <= work_value;
                        stack_height[stack_sp] <= work_height;
                        stack_start[stack_sp] <= work_start;
                        stack_sp <= stack_sp + 1'b1;
                        if (stack_sp + 1'b1 > peak_stack_nodes)
                            peak_stack_nodes <= stack_sp + 1'b1;
                        state <= S_ACCEPT;
                    end
                end
                S_PARENT_REQ: begin
                    if (parent_req_ready) begin
                        stack_sp <= stack_sp - 1'b1;
                        parent_hashes <= parent_hashes + 1'b1;
                        if (capture_auth) begin
                            auth_valid <= 1'b1;
                            auth_level <= parent_req_height - 1'b1;
                            auth_node <= capture_node;
                        end
                        state <= S_PARENT_WAIT;
                    end
                end
                S_PARENT_WAIT: begin
                    if (parent_rsp_error) begin
                        clear_working_state();
                        error <= 1'b1;
                        error_code <= ERR_PARENT_RESPONSE;
                        state <= S_IDLE;
                    end else if (parent_rsp_valid) begin
                        work_value <= parent_rsp_value;
                        work_height <= parent_req_height;
                        work_start <= parent_req_start_leaf;
                        state <= S_MERGE;
                    end
                end
                S_ABORT_DRAIN: begin
                    if (parent_rsp_valid || parent_rsp_error)
                        state <= S_IDLE;
                end
                default: begin
                    clear_working_state();
                    error <= 1'b1;
                    error_code <= ERR_STACK_OVERFLOW;
                    state <= S_IDLE;
                end
            endcase
        end
    end
endmodule

`default_nettype wire
