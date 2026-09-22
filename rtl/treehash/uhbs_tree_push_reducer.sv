`timescale 1ns/1ps
`default_nettype none

// Algorithm-independent streaming Merkle reducer.  A push supplies one leaf
// (or one endpoint for a nested reducer context).  Equal-height nodes are
// folded through the external Hash service until the new node can be parked.
// Two contexts allow an endpoint L-tree and an outer Merkle tree to share the
// same control without teaching the RTL either algorithm.
module uhbs_tree_push_reducer #(
    parameter integer VALUE_BITS = 256,
    parameter integer TREE_HEIGHT = 10,
    parameter integer CONTEXTS = 2
) (
    input  wire clk,
    input  wire rst_n,

    input  wire push_valid,
    output wire push_ready,
    input  wire [$clog2(CONTEXTS)-1:0] push_context,
    input  wire push_clear,
    input  wire push_last,
    input  wire push_promote_odd,
    input  wire [$clog2(TREE_HEIGHT+1)-1:0] push_root_height,
    input  wire [TREE_HEIGHT-1:0] push_index,
    input  wire [VALUE_BITS-1:0] push_value,
    input  wire [TREE_HEIGHT-1:0] push_target_index,
    input  wire push_capture_auth,
    input  wire push_cache_all,
    output logic push_done,

    output wire parent_valid,
    input  wire parent_ready,
    output wire [$clog2(CONTEXTS)-1:0] parent_context,
    output wire [$clog2(TREE_HEIGHT+1)-1:0] parent_level,
    output wire [TREE_HEIGHT-1:0] parent_index,
    output wire [VALUE_BITS-1:0] parent_left,
    output wire [VALUE_BITS-1:0] parent_right,
    input  wire parent_response_valid,
    input  wire [VALUE_BITS-1:0] parent_response_value,

    output wire cache_valid,
    input  wire cache_ready,
    output wire [$clog2(CONTEXTS)-1:0] cache_context,
    output wire [$clog2(TREE_HEIGHT+1)-1:0] cache_level,
    output wire [TREE_HEIGHT-1:0] cache_index,
    output wire [VALUE_BITS-1:0] cache_value,

    output wire auth_valid,
    input  wire auth_ready,
    output wire [$clog2(CONTEXTS)-1:0] auth_context,
    output wire [$clog2(TREE_HEIGHT+1)-1:0] auth_level,
    output wire [VALUE_BITS-1:0] auth_value,

    output logic root_valid,
    input  wire root_ready,
    output logic [$clog2(CONTEXTS)-1:0] root_context,
    output logic [VALUE_BITS-1:0] root_value,
    output logic error
);
    localparam integer LEVEL_BITS = $clog2(TREE_HEIGHT+1);
    localparam integer CONTEXT_BITS = $clog2(CONTEXTS);
    localparam integer LEVEL_CAPACITY = 1 << LEVEL_BITS;
    localparam integer STACK_DEPTH = CONTEXTS * LEVEL_CAPACITY;
    localparam integer STACK_ADDR_BITS = CONTEXT_BITS + LEVEL_BITS;
    localparam logic [2:0] S_IDLE = 3'd0;
    localparam logic [2:0] S_OBSERVE = 3'd1;
    localparam logic [2:0] S_CHECK = 3'd2;
    localparam logic [2:0] S_PARENT = 3'd3;
    localparam logic [2:0] S_WAIT = 3'd4;
    localparam logic [2:0] S_ROOT = 3'd5;
    localparam logic [2:0] S_ERROR = 3'd6;

    logic [2:0] state;
    logic [TREE_HEIGHT:0] stack_valid [0:CONTEXTS-1];
    // A flattened asynchronous-read distributed RAM avoids implementing the
    // two reducer stacks as thousands of individually selected flip-flops.
    // The node index travels with the value so malformed non-adjacent pushes
    // still fail closed.
    (* ram_style = "distributed" *)
    logic [VALUE_BITS+TREE_HEIGHT-1:0] stack_memory [0:STACK_DEPTH-1];

    logic [$clog2(CONTEXTS)-1:0] current_context;
    logic [LEVEL_BITS-1:0] current_level;
    logic [TREE_HEIGHT-1:0] current_index;
    logic [VALUE_BITS-1:0] current_value;
    logic [TREE_HEIGHT-1:0] target_index;
    logic capture_auth, cache_all, last_push, promote_odd;
    logic [LEVEL_BITS-1:0] root_height;
    logic cache_sent, auth_sent;

    // Power-of-two context banks make the address a concatenation and match
    // the native 32-deep distributed-RAM inference pattern on Artix-7.
    wire [STACK_ADDR_BITS-1:0] stack_address =
        {current_context, current_level};
    wire [VALUE_BITS+TREE_HEIGHT-1:0] stack_word =
        stack_memory[stack_address];
    wire [TREE_HEIGHT-1:0] stored_index =
        stack_word[VALUE_BITS+TREE_HEIGHT-1:VALUE_BITS];
    wire auth_needed = capture_auth && current_level < TREE_HEIGHT
        && current_index
           == ((target_index >> current_level) ^ {{(TREE_HEIGHT-1){1'b0}},1'b1});
    wire parked = !stack_valid[current_context][current_level];
    wire stack_write_enable = state == S_CHECK
        && current_level != root_height && parked
        && !(last_push && promote_odd);
    wire adjacent = stored_index + 1'b1 == current_index
        && !stored_index[0];

    assign push_ready = state == S_IDLE;
    assign parent_valid = state == S_PARENT;
    assign parent_context = current_context;
    assign parent_level = current_level;
    assign parent_index = current_index >> 1;
    assign parent_left = stack_word[VALUE_BITS-1:0];
    assign parent_right = current_value;

    assign cache_valid = state == S_OBSERVE && cache_all && !cache_sent;
    assign cache_context = current_context;
    assign cache_level = current_level;
    assign cache_index = current_index;
    assign cache_value = current_value;
    assign auth_valid = state == S_OBSERVE && auth_needed && !auth_sent;
    assign auth_context = current_context;
    assign auth_level = current_level;
    assign auth_value = current_value;

    integer context_index;
    integer level_index;
    // Keep the memory write in a reset-free process.  An asynchronous reset
    // on the containing process prevents Vivado from inferring LUTRAM even
    // when the array itself is not assigned by the reset branch.
    always_ff @(posedge clk) begin
        if (stack_write_enable)
            stack_memory[stack_address] <= {current_index, current_value};
    end

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= S_IDLE;
            for (context_index = 0; context_index < CONTEXTS;
                 context_index = context_index + 1)
                stack_valid[context_index] <= '0;
            push_done <= 1'b0;
            root_valid <= 1'b0;
            root_context <= '0;
            error <= 1'b0;
            cache_sent <= 1'b0;
            auth_sent <= 1'b0;
        end else begin
            push_done <= 1'b0;
            if (root_valid && root_ready)
                root_valid <= 1'b0;
            case (state)
                S_IDLE: if (push_valid) begin
                    if (push_clear)
                        for (level_index = 0; level_index <= TREE_HEIGHT;
                             level_index = level_index + 1)
                            stack_valid[push_context][level_index] <= 1'b0;
                    current_context <= push_context;
                    current_level <= '0;
                    current_index <= push_index;
                    current_value <= push_value;
                    target_index <= push_target_index;
                    capture_auth <= push_capture_auth;
                    cache_all <= push_cache_all;
                    last_push <= push_last;
                    promote_odd <= push_promote_odd;
                    root_height <= push_root_height;
                    cache_sent <= 1'b0;
                    auth_sent <= 1'b0;
                    error <= 1'b0;
                    state <= S_OBSERVE;
                end
                S_OBSERVE: begin
                    if (cache_valid && cache_ready)
                        cache_sent <= 1'b1;
                    if (auth_valid && auth_ready)
                        auth_sent <= 1'b1;
                    if ((!cache_all || cache_sent
                         || (cache_valid && cache_ready))
                        && (!auth_needed || auth_sent
                            || (auth_valid && auth_ready)))
                        state <= S_CHECK;
                end
                S_CHECK: begin
                    if (current_level == root_height) begin
                        if (!last_push || current_index != 0) begin
                            error <= 1'b1;
                            state <= S_ERROR;
                        end else begin
                            root_context <= current_context;
                            root_value <= current_value;
                            root_valid <= 1'b1;
                            state <= S_ROOT;
                        end
                    end else if (parked) begin
                        if (last_push && promote_odd) begin
                            // L-trees promote their unpaired rightmost node
                            // until it reaches an occupied level.  This is a
                            // generic reducer option, not an algorithm state.
                            current_index <= current_index >> 1;
                            current_level <= current_level + 1'b1;
                            cache_sent <= 1'b0;
                            auth_sent <= 1'b0;
                            state <= S_OBSERVE;
                        end else begin
                            stack_valid[current_context][current_level]
                                <= 1'b1;
                            if (last_push) begin
                                error <= 1'b1;
                                state <= S_ERROR;
                            end else begin
                                push_done <= 1'b1;
                                state <= S_IDLE;
                            end
                        end
                    end else if (!adjacent) begin
                        error <= 1'b1;
                        state <= S_ERROR;
                    end else begin
                        state <= S_PARENT;
                    end
                end
                S_PARENT: if (parent_ready) begin
                    stack_valid[current_context][current_level] <= 1'b0;
                    state <= S_WAIT;
                end
                S_WAIT: if (parent_response_valid) begin
                    current_value <= parent_response_value;
                    current_index <= current_index >> 1;
                    current_level <= current_level + 1'b1;
                    cache_sent <= 1'b0;
                    auth_sent <= 1'b0;
                    state <= S_OBSERVE;
                end
                S_ROOT: if (root_valid && root_ready) begin
                    push_done <= 1'b1;
                    state <= S_IDLE;
                end
                S_ERROR: begin
                    error <= 1'b1;
                    state <= S_IDLE;
                end
                default: begin
                    error <= 1'b1;
                    state <= S_ERROR;
                end
            endcase
        end
    end
endmodule

`default_nettype wire
