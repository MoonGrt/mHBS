`timescale 1ns/1ps
`default_nettype none

// Runtime-height TREEHASH_MIN engine.
//
// Storage is elaborated once for MAX_TREE_HEIGHT.  Each accepted start locks a
// tree_height in 1..MAX_TREE_HEIGHT and target_leaf for that transaction.  No
// run-time allocation or software-supplied per-level work is required.
//
// Unlike the legacy fixed-height module, authentication nodes are committed to
// the output only after the root has completed successfully.  A leaf-order or
// parent-response fault therefore clears the partial stack/path without
// exposing a partial authentication path.  start while busy is cancellation;
// if a parent request was already accepted, its untagged response is drained
// before ready is reasserted.  A new tree can then start without global reset.
module micro_hbs_treehash_min_dynamic #(
    parameter integer MAX_TREE_HEIGHT = 10
) (
    input  wire         clk,
    input  wire         rst_n,
    input  wire         start,
    output wire         ready,
    input  wire [7:0]   tree_height,
    input  wire [15:0]  target_leaf,

    input  wire         leaf_valid,
    output wire         leaf_ready,
    input  wire [15:0]  leaf_index,
    input  wire [255:0] leaf_value,

    output wire         parent_req_valid,
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
    output wire         busy,
    output logic        error,
    output logic [15:0] error_code,
    output logic [15:0] accepted_leaves,
    output logic [15:0] parent_hashes,
    output logic [7:0]  peak_stack_nodes
);
    localparam integer STACK_INDEX_WIDTH = (MAX_TREE_HEIGHT <= 1)
        ? 1 : $clog2(MAX_TREE_HEIGHT + 1);
    localparam integer AUTH_INDEX_WIDTH = (MAX_TREE_HEIGHT <= 2)
        ? 1 : $clog2(MAX_TREE_HEIGHT);

    localparam logic [15:0] ERR_TARGET_RANGE = 16'h0201;
    localparam logic [15:0] ERR_LEAF_ORDER = 16'h0202;
    localparam logic [15:0] ERR_STACK_OVERFLOW = 16'h0203;
    localparam logic [15:0] ERR_PARENT_RESPONSE = 16'h0204;
    localparam logic [15:0] ERR_HEIGHT_RANGE = 16'h0205;

    typedef enum logic [2:0] {
        S_IDLE, S_ACCEPT, S_MERGE, S_PARENT_REQ, S_PARENT_WAIT,
        S_ABORT_DRAIN, S_EMIT_AUTH
    } state_t;
    state_t state;

    logic [255:0] stack_value [0:MAX_TREE_HEIGHT];
    logic [7:0] stack_height [0:MAX_TREE_HEIGHT];
    logic [15:0] stack_start [0:MAX_TREE_HEIGHT];
    logic [255:0] auth_buffer [0:MAX_TREE_HEIGHT-1];
    logic [MAX_TREE_HEIGHT-1:0] auth_buffer_valid;

    logic [7:0] stack_sp;
    logic [255:0] work_value;
    logic [7:0] work_height;
    logic [15:0] work_start;
    logic [15:0] next_leaf;
    logic [7:0] tree_height_latched;
    logic [15:0] target_leaf_latched;
    logic capture_auth;
    logic [255:0] capture_node;
    logic [7:0] captured_auth_nodes;
    logic [7:0] auth_emit_level;
    integer index;

    wire start_height_valid;
    wire start_target_valid;
    wire [15:0] selected_leaf_count;
    wire [STACK_INDEX_WIDTH-1:0] stack_write_index;
    wire [AUTH_INDEX_WIDTH-1:0] parent_auth_index;
    wire [AUTH_INDEX_WIDTH-1:0] auth_emit_index;

    assign ready = state == S_IDLE;
    assign busy = state != S_IDLE;
    assign leaf_ready = state == S_ACCEPT;
    assign parent_req_valid = state == S_PARENT_REQ;
    assign start_height_valid = tree_height >= 1
        && tree_height <= 8'(MAX_TREE_HEIGHT);
    assign start_target_valid = start_height_valid
        && ({1'b0, target_leaf} < (17'd1 << tree_height));
    assign selected_leaf_count = 16'd1 << tree_height_latched;
    assign stack_write_index = stack_sp[STACK_INDEX_WIDTH-1:0];
    assign parent_auth_index
        = parent_req_height[AUTH_INDEX_WIDTH-1:0] - 1'b1;
    assign auth_emit_index = auth_emit_level[AUTH_INDEX_WIDTH-1:0];

    initial begin
        if (MAX_TREE_HEIGHT < 1 || MAX_TREE_HEIGHT > 15)
            $error("MAX_TREE_HEIGHT must be in 1..15");
    end

    task automatic clear_transaction;
        integer clear_index;
        begin
            stack_sp <= '0;
            work_value <= '0;
            work_height <= '0;
            work_start <= '0;
            next_leaf <= '0;
            tree_height_latched <= '0;
            target_leaf_latched <= '0;
            parent_req_height <= '0;
            parent_req_start_leaf <= '0;
            parent_req_left <= '0;
            parent_req_right <= '0;
            capture_auth <= 1'b0;
            capture_node <= '0;
            auth_buffer_valid <= '0;
            captured_auth_nodes <= '0;
            auth_emit_level <= '0;
            auth_level <= '0;
            auth_node <= '0;
            root <= '0;
            for (clear_index = 0; clear_index <= MAX_TREE_HEIGHT;
                 clear_index = clear_index + 1) begin
                stack_value[clear_index] <= '0;
                stack_height[clear_index] <= '0;
                stack_start[clear_index] <= '0;
            end
            for (clear_index = 0; clear_index < MAX_TREE_HEIGHT;
                 clear_index = clear_index + 1)
                auth_buffer[clear_index] <= '0;
        end
    endtask

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= S_IDLE;
            stack_sp <= '0;
            work_value <= '0;
            work_height <= '0;
            work_start <= '0;
            next_leaf <= '0;
            tree_height_latched <= '0;
            target_leaf_latched <= '0;
            parent_req_height <= '0;
            parent_req_start_leaf <= '0;
            parent_req_left <= '0;
            parent_req_right <= '0;
            capture_auth <= 1'b0;
            capture_node <= '0;
            auth_buffer_valid <= '0;
            captured_auth_nodes <= '0;
            auth_emit_level <= '0;
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
            for (index = 0; index <= MAX_TREE_HEIGHT; index = index + 1) begin
                stack_value[index] <= '0;
                stack_height[index] <= '0;
                stack_start[index] <= '0;
            end
            for (index = 0; index < MAX_TREE_HEIGHT; index = index + 1)
                auth_buffer[index] <= '0;
        end else begin
            auth_valid <= 1'b0;
            root_valid <= 1'b0;

            // Cancellation never admits a replacement transaction in the
            // same cycle.  If an untagged parent response is outstanding, it
            // is drained before the next start can observe ready.
            if (start && state != S_IDLE && state != S_ABORT_DRAIN) begin
                clear_transaction();
                accepted_leaves <= '0;
                parent_hashes <= '0;
                peak_stack_nodes <= '0;
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
                        clear_transaction();
                        accepted_leaves <= '0;
                        parent_hashes <= '0;
                        peak_stack_nodes <= '0;
                        error <= 1'b0;
                        error_code <= '0;
                        if (!start_height_valid) begin
                            error <= 1'b1;
                            error_code <= ERR_HEIGHT_RANGE;
                        end else if (!start_target_valid) begin
                            error <= 1'b1;
                            error_code <= ERR_TARGET_RANGE;
                        end else begin
                            tree_height_latched <= tree_height;
                            target_leaf_latched <= target_leaf;
                            state <= S_ACCEPT;
                        end
                    end
                end

                S_ACCEPT: begin
                    if (leaf_valid) begin
                        if (leaf_index != next_leaf
                            || ({1'b0, leaf_index}
                                >= (17'd1 << tree_height_latched))) begin
                            clear_transaction();
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
                    if (stack_sp != 0
                        && stack_height[stack_sp-1] == work_height) begin
                        parent_req_height <= work_height + 1'b1;
                        parent_req_start_leaf <= stack_start[stack_sp-1];
                        parent_req_left <= stack_value[stack_sp-1];
                        parent_req_right <= work_value;
                        if (target_leaf_latched >= stack_start[stack_sp-1]
                            && target_leaf_latched < work_start) begin
                            capture_auth <= 1'b1;
                            capture_node <= work_value;
                        end else if (target_leaf_latched >= work_start
                            && target_leaf_latched
                                < work_start + (16'd1 << work_height)) begin
                            capture_auth <= 1'b1;
                            capture_node <= stack_value[stack_sp-1];
                        end else begin
                            capture_auth <= 1'b0;
                            capture_node <= '0;
                        end
                        state <= S_PARENT_REQ;
                    end else if (work_height == tree_height_latched) begin
                        if (stack_sp != 0
                            || accepted_leaves != selected_leaf_count
                            || captured_auth_nodes
                                != tree_height_latched) begin
                            clear_transaction();
                            error <= 1'b1;
                            error_code <= ERR_LEAF_ORDER;
                            state <= S_IDLE;
                        end else begin
                            root <= work_value;
                            root_valid <= 1'b1;
                            auth_emit_level <= '0;
                            state <= S_EMIT_AUTH;
                        end
                    end else if (stack_sp > tree_height_latched
                        || stack_sp > 8'(MAX_TREE_HEIGHT)) begin
                        clear_transaction();
                        error <= 1'b1;
                        error_code <= ERR_STACK_OVERFLOW;
                        state <= S_IDLE;
                    end else begin
                        stack_value[stack_write_index] <= work_value;
                        stack_height[stack_write_index] <= work_height;
                        stack_start[stack_write_index] <= work_start;
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
                            auth_buffer[parent_auth_index] <= capture_node;
                            auth_buffer_valid[parent_auth_index] <= 1'b1;
                            captured_auth_nodes <= captured_auth_nodes + 1'b1;
                        end
                        state <= S_PARENT_WAIT;
                    end
                end

                S_PARENT_WAIT: begin
                    if (parent_rsp_error) begin
                        clear_transaction();
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

                S_EMIT_AUTH: begin
                    // The count check at root commit guarantees all selected
                    // levels were captured.  The valid map remains an extra
                    // fail-closed guard against an impossible internal hole.
                    if (!auth_buffer_valid[auth_emit_index]) begin
                        clear_transaction();
                        error <= 1'b1;
                        error_code <= ERR_STACK_OVERFLOW;
                        state <= S_IDLE;
                    end else begin
                        auth_valid <= 1'b1;
                        auth_level <= auth_emit_level;
                        auth_node <= auth_buffer[auth_emit_index];
                        if (auth_emit_level + 1'b1
                            == tree_height_latched)
                            state <= S_IDLE;
                        else
                            auth_emit_level <= auth_emit_level + 1'b1;
                    end
                end

                default: begin
                    clear_transaction();
                    error <= 1'b1;
                    error_code <= ERR_STACK_OVERFLOW;
                    state <= S_IDLE;
                end
            endcase
        end
    end
endmodule

`default_nettype wire
