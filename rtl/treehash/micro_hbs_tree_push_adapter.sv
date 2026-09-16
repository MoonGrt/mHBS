`timescale 1ns/1ps
`default_nettype none

// Scratchpad-backed adapter for one algorithm-independent TREE_PUSH command.
//
// A command names a node slot relative to a 64-bit scratchpad base.  The
// adapter performs all NODE_BYTES/8 reads, assembles the node with scratch word
// zero in bits [63:0], and presents exactly one leaf handshake to TreeHash.
// Descriptor and layout identifiers are correlation metadata; their meaning is
// deliberately left to the descriptor/layout layer above this module.
//
// micro_hbs_treehash_min has a fixed 256-bit leaf interface.
// Consequently NODE_BYTES is restricted to whole 64-bit words up to 32 bytes.
// Scratch failures and explicit cancellation drive TreeHash's busy-start cancel
// mechanism.  Any accepted scratch/parent response is drained before the next
// command is admitted, so recovery does not require a global reset.
module micro_hbs_tree_push_adapter #(
    parameter integer TREE_HEIGHT = 10,
    parameter integer NODE_BYTES = 32,
    parameter integer SCRATCH_WORDS = 512
) (
    input  wire         clk,
    input  wire         rst_n,
    input  tri0         cancel,

    input  wire         cmd_valid,
    output logic        cmd_ready,
    input  wire [15:0]  cmd_descriptor_id,
    input  wire [15:0]  cmd_layout_id,
    input  wire [7:0]   cmd_node_source,
    input  wire [15:0]  cmd_node_base_word,
    input  wire [15:0]  cmd_node_index,
    input  wire [15:0]  cmd_leaf_index,
    input  wire         cmd_tree_start,
    input  wire [15:0]  cmd_target_leaf,

    output logic        rsp_valid,
    output logic        rsp_error,
    output logic [15:0] rsp_error_code,
    output logic [15:0] rsp_descriptor_id,
    output logic [15:0] rsp_layout_id,

    output logic        sp_req_valid,
    input  wire         sp_req_ready,
    output logic        sp_req_write,
    output logic [15:0] sp_req_address,
    output logic [63:0] sp_req_write_data,
    input  wire         sp_rsp_valid,
    input  wire [63:0]  sp_rsp_read_data,
    input  wire         sp_rsp_error,
    input  wire [15:0]  sp_rsp_error_code,

    output wire         parent_req_valid,
    input  wire         parent_req_ready,
    output wire [7:0]   parent_req_height,
    output wire [15:0]  parent_req_start_leaf,
    output wire [255:0] parent_req_left,
    output wire [255:0] parent_req_right,
    input  wire         parent_rsp_valid,
    input  wire [255:0] parent_rsp_value,
    input  wire         parent_rsp_error,

    output wire         auth_valid,
    output wire [7:0]   auth_level,
    output wire [255:0] auth_node,
    output wire         root_valid,
    output wire [255:0] root,
    output logic        busy,
    output logic        poisoned,
    output wire [15:0]  accepted_leaves,
    output wire [15:0]  parent_hashes,
    output wire [7:0]   peak_stack_nodes
);
    localparam integer NODE_WORDS = NODE_BYTES / 8;
    localparam integer WORD_INDEX_WIDTH = (NODE_WORDS <= 1) ? 1 : $clog2(NODE_WORDS);
    localparam logic [WORD_INDEX_WIDTH-1:0] LAST_WORD_INDEX =
        WORD_INDEX_WIDTH'(NODE_WORDS-1);
    localparam logic [32:0] SCRATCH_WORDS_33 = 33'(SCRATCH_WORDS);

    localparam logic [7:0]  NODE_SOURCE_SCRATCH = 8'h00;
    localparam logic [15:0] ERR_NODE_SOURCE     = 16'h0401;
    localparam logic [15:0] ERR_SCRATCH_BOUNDS  = 16'h0402;
    localparam logic [15:0] ERR_SCRATCH_RESPONSE = 16'h0403;
    localparam logic [15:0] ERR_TREE_BUSY       = 16'h0404;
    localparam logic [15:0] ERR_TREE_INACTIVE   = 16'h0405;
    localparam logic [15:0] ERR_CANCELLED       = 16'h0406;
    localparam logic [15:0] ERR_TARGET_RANGE    = 16'h0201;
    localparam logic [15:0] ERR_INTERNAL         = 16'h04ff;

    typedef enum logic [3:0] {
        S_IDLE, S_TREE_START, S_READ_REQ, S_READ_WAIT,
        S_PUSH, S_SETTLE, S_ABORT_REQ, S_ABORT_WAIT
    } state_t;
    state_t state;

    logic [15:0] saved_leaf_index;
    logic [15:0] saved_target_leaf;
    logic [15:0] saved_start_address;
    logic [WORD_INDEX_WIDTH-1:0] word_index;
    logic [255:0] node_buffer;
    logic tree_active;
    logic scratch_outstanding;
    logic tree_abort_complete;
    logic [15:0] abort_error_code;

    wire tree_ready;
    wire tree_busy;
    wire tree_error;
    wire [15:0] tree_error_code;
    wire tree_leaf_ready;
    wire tree_start_or_cancel;
    wire tree_leaf_valid;

    wire [32:0] command_word_offset;
    wire [32:0] command_start_address;
    wire [32:0] command_end_address;
    wire command_address_valid;

    assign command_word_offset = cmd_node_index * NODE_WORDS;
    assign command_start_address = {17'b0, cmd_node_base_word} + command_word_offset;
    assign command_end_address = command_start_address + NODE_WORDS;
    assign command_address_valid = (command_start_address < SCRATCH_WORDS_33)
        && (command_end_address <= SCRATCH_WORDS_33)
        && (command_start_address <= 33'h0ffff);

    assign cmd_ready = (state == S_IDLE);
    assign busy = (state != S_IDLE);
    assign poisoned = 1'b0;

    assign sp_req_valid = (state == S_READ_REQ) && !cancel;
    assign sp_req_write = 1'b0;
    assign sp_req_address = saved_start_address
        + {{(16-WORD_INDEX_WIDTH){1'b0}}, word_index};
    assign sp_req_write_data = 64'b0;
    assign tree_start_or_cancel = ((state == S_TREE_START) && tree_ready && !cancel)
        || ((state == S_ABORT_REQ) && tree_busy);
    assign tree_leaf_valid = (state == S_PUSH) && !cancel;

    initial begin
        if (TREE_HEIGHT < 1 || TREE_HEIGHT > 15)
            $error("TREE_HEIGHT must be in 1..15");
        if (NODE_BYTES < 8 || NODE_BYTES > 32 || (NODE_BYTES % 8) != 0)
            $error("NODE_BYTES must be 8, 16, 24, or 32");
        if (SCRATCH_WORDS < NODE_WORDS || SCRATCH_WORDS > 65536)
            $error("invalid SCRATCH_WORDS for NODE_BYTES");
    end

    micro_hbs_treehash_min #(.TREE_HEIGHT(TREE_HEIGHT)) treehash_min (
        .clk,
        .rst_n,
        .start(tree_start_or_cancel),
        .ready(tree_ready),
        .target_leaf(saved_target_leaf),
        .leaf_valid(tree_leaf_valid),
        .leaf_ready(tree_leaf_ready),
        .leaf_index(saved_leaf_index),
        .leaf_value(node_buffer),
        .parent_req_valid,
        .parent_req_ready,
        .parent_req_height,
        .parent_req_start_leaf,
        .parent_req_left,
        .parent_req_right,
        .parent_rsp_valid,
        .parent_rsp_value,
        .parent_rsp_error,
        .auth_valid,
        .auth_level,
        .auth_node,
        .root_valid,
        .root,
        .busy(tree_busy),
        .error(tree_error),
        .error_code(tree_error_code),
        .accepted_leaves,
        .parent_hashes,
        .peak_stack_nodes
    );

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= S_IDLE;
            saved_leaf_index <= '0;
            saved_target_leaf <= '0;
            saved_start_address <= '0;
            word_index <= '0;
            node_buffer <= '0;
            tree_active <= 1'b0;
            scratch_outstanding <= 1'b0;
            tree_abort_complete <= 1'b0;
            abort_error_code <= '0;
            rsp_valid <= 1'b0;
            rsp_error <= 1'b0;
            rsp_error_code <= '0;
            rsp_descriptor_id <= '0;
            rsp_layout_id <= '0;
        end else begin
            rsp_valid <= 1'b0;
            rsp_error <= 1'b0;
            rsp_error_code <= '0;

            // Cancellation has priority over all active command states.  The
            // external scratch request and leaf valid are combinationally gated
            // by cancel, preventing a new handshake in the cancellation cycle.
            if (cancel && state != S_IDLE && state != S_ABORT_REQ
                && state != S_ABORT_WAIT) begin
                if (scratch_outstanding && (sp_rsp_valid || sp_rsp_error))
                    scratch_outstanding <= 1'b0;
                abort_error_code <= ERR_CANCELLED;
                tree_abort_complete <= 1'b0;
                state <= S_ABORT_REQ;
            end else case (state)
                S_IDLE: begin
                    if (cmd_valid) begin
                        rsp_descriptor_id <= cmd_descriptor_id;
                        rsp_layout_id <= cmd_layout_id;
                        if (cmd_node_source != NODE_SOURCE_SCRATCH) begin
                            rsp_valid <= 1'b1;
                            rsp_error <= 1'b1;
                            rsp_error_code <= ERR_NODE_SOURCE;
                        end else if (!command_address_valid) begin
                            rsp_valid <= 1'b1;
                            rsp_error <= 1'b1;
                            rsp_error_code <= ERR_SCRATCH_BOUNDS;
                        end else if (cmd_tree_start && (tree_active || !tree_ready)) begin
                            rsp_valid <= 1'b1;
                            rsp_error <= 1'b1;
                            rsp_error_code <= ERR_TREE_BUSY;
                        end else if (!cmd_tree_start && !tree_active) begin
                            rsp_valid <= 1'b1;
                            rsp_error <= 1'b1;
                            rsp_error_code <= ERR_TREE_INACTIVE;
                        end else if (cmd_tree_start
                                     && cmd_target_leaf >= (1 << TREE_HEIGHT)) begin
                            rsp_valid <= 1'b1;
                            rsp_error <= 1'b1;
                            rsp_error_code <= ERR_TARGET_RANGE;
                        end else begin
                            saved_leaf_index <= cmd_leaf_index;
                            saved_target_leaf <= cmd_target_leaf;
                            saved_start_address <= command_start_address[15:0];
                            word_index <= '0;
                            node_buffer <= '0;
                            scratch_outstanding <= 1'b0;
                            if (cmd_tree_start)
                                state <= S_TREE_START;
                            else
                                state <= S_READ_REQ;
                        end
                    end
                end

                S_TREE_START: begin
                    if (tree_ready && !tree_busy) begin
                        tree_active <= 1'b1;
                        state <= S_READ_REQ;
                    end
                end

                S_READ_REQ: begin
                    if (sp_rsp_error) begin
                        abort_error_code <= (sp_rsp_error_code != 0)
                            ? sp_rsp_error_code : ERR_SCRATCH_RESPONSE;
                        tree_abort_complete <= 1'b0;
                        scratch_outstanding <= 1'b0;
                        state <= S_ABORT_REQ;
                    end else if (sp_req_ready) begin
                        scratch_outstanding <= 1'b1;
                        state <= S_READ_WAIT;
                    end
                end

                S_READ_WAIT: begin
                    if (sp_rsp_error) begin
                        abort_error_code <= (sp_rsp_error_code != 0)
                            ? sp_rsp_error_code : ERR_SCRATCH_RESPONSE;
                        tree_abort_complete <= 1'b0;
                        scratch_outstanding <= 1'b0;
                        state <= S_ABORT_REQ;
                    end else if (sp_rsp_valid) begin
                        scratch_outstanding <= 1'b0;
                        node_buffer[64*word_index +: 64] <= sp_rsp_read_data;
                        if (word_index == LAST_WORD_INDEX) begin
                            word_index <= '0;
                            state <= S_PUSH;
                        end else begin
                            word_index <= word_index + 1'b1;
                            state <= S_READ_REQ;
                        end
                    end
                end

                S_PUSH: begin
                    if (tree_error) begin
                        rsp_valid <= 1'b1;
                        rsp_error <= 1'b1;
                        rsp_error_code <= tree_error_code;
                        tree_active <= 1'b0;
                        state <= S_IDLE;
                    end else if (tree_leaf_ready) begin
                        state <= S_SETTLE;
                    end
                end

                S_SETTLE: begin
                    if (tree_error) begin
                        rsp_valid <= 1'b1;
                        rsp_error <= 1'b1;
                        rsp_error_code <= tree_error_code;
                        tree_active <= 1'b0;
                        state <= S_IDLE;
                    end else if (root_valid) begin
                        rsp_valid <= 1'b1;
                        tree_active <= 1'b0;
                        state <= S_IDLE;
                    end else if (tree_leaf_ready) begin
                        rsp_valid <= 1'b1;
                        state <= S_IDLE;
                    end
                end

                S_ABORT_REQ: begin
                    // tree_start_or_cancel is asserted for this cycle when the
                    // real TreeHash is busy.  An idle TreeHash is already clean.
                    if (sp_rsp_valid || sp_rsp_error)
                        scratch_outstanding <= 1'b0;
                    tree_abort_complete <= !tree_busy;
                    state <= S_ABORT_WAIT;
                end

                S_ABORT_WAIT: begin
                    if (sp_rsp_valid || sp_rsp_error)
                        scratch_outstanding <= 1'b0;
                    if (!tree_busy)
                        tree_abort_complete <= 1'b1;

                    if ((tree_abort_complete || !tree_busy)
                        && (!scratch_outstanding
                            || sp_rsp_valid || sp_rsp_error)) begin
                        rsp_valid <= 1'b1;
                        rsp_error <= 1'b1;
                        rsp_error_code <= abort_error_code;
                        tree_active <= 1'b0;
                        scratch_outstanding <= 1'b0;
                        tree_abort_complete <= 1'b0;
                        state <= S_IDLE;
                    end
                end

                default: begin
                    abort_error_code <= ERR_INTERNAL;
                    tree_abort_complete <= 1'b0;
                    state <= S_ABORT_REQ;
                end
            endcase
        end
    end
endmodule

`default_nettype wire
