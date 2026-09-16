`timescale 1ns/1ps
`default_nettype none

// Descriptor-driven SLH-DSA TREE_PUSH adapter for 16-byte nodes.
// Descriptor [63:56] version, [55:48] height, [47:40] ADRS type,
// [39] keypair from register, [38:36] keypair register,
// [35:20] root destination physical word, [19:0] reserved.
module micro_hbs_slh_dsa_tree_adapter #(
    parameter integer DESCRIPTOR_COUNT = 32,
    parameter integer SCRATCH_WORDS = 1024,
    parameter integer MAX_TREE_HEIGHT = 6,
    parameter integer UNROLL = 2
) (
    input wire clk, input wire rst_n, input wire engine_busy,
    input wire cfg_valid, output wire cfg_ready,
    input wire [15:0] cfg_id, input wire [63:0] cfg_data,
    output logic cfg_error, output logic [15:0] cfg_error_code,
    input wire cmd_valid, output wire cmd_ready,
    input wire [7:0] cmd_flags,
    input wire [7:0] cmd_rd, input wire [31:0] cmd_imm,
    input wire [31:0] cmd_leaf_index,
    input wire [255:0] cmd_registers,
    input wire [127:0] public_seed,
    output wire rsp_valid, output logic rsp_error,
    output logic [15:0] rsp_error_code,
    output wire scratch_request_valid,
    input wire scratch_request_ready,
    output logic scratch_request_write,
    output logic [15:0] scratch_request_address,
    output logic [63:0] scratch_request_write_data,
    input wire scratch_response_valid,
    input wire [63:0] scratch_response_data,
    input wire scratch_response_error,
    output wire busy,
    output wire [15:0] accepted_leaves,
    output wire [15:0] parent_hashes,
    output logic [31:0] total_parent_hashes
);
    localparam integer INDEX_W = DESCRIPTOR_COUNT <= 2
        ? 1 : $clog2(DESCRIPTOR_COUNT);
    localparam logic [15:0] ERR_CFG = 16'h1201;
    localparam logic [15:0] ERR_CMD = 16'h1202;
    localparam logic [15:0] ERR_CONTEXT = 16'h1203;
    localparam logic [15:0] ERR_SCRATCH = 16'h1204;
    localparam logic [15:0] ERR_PARENT = 16'h1205;

    typedef enum logic [3:0] {
        S_IDLE, S_CONTEXT0_REQ, S_CONTEXT0_WAIT,
        S_CONTEXT1_REQ, S_CONTEXT1_WAIT, S_TREE_START,
        S_LEAF0_REQ, S_LEAF0_WAIT, S_LEAF1_REQ, S_LEAF1_WAIT,
        S_PUSH, S_SETTLE, S_ROOT0, S_ROOT1, S_RESPONSE
    } state_t;
    state_t state;

    logic [63:0] descriptors [0:DESCRIPTOR_COUNT-1];
    logic [DESCRIPTOR_COUNT-1:0] configured;
    logic [63:0] active_descriptor;
    logic [15:0] active_id;
    logic active_tree;
    logic [15:0] leaf_base_word;
    logic [15:0] leaf_index_latched;
    logic [255:0] registers_latched;
    logic [63:0] tree_word0, tree_word1;
    logic [127:0] leaf_value;
    logic [127:0] root_latched;

    wire [7:0] d_height = active_descriptor[55:48];
    wire [7:0] d_address_type = active_descriptor[47:40];
    wire d_keypair_from_reg = active_descriptor[39];
    wire [2:0] d_keypair_reg = active_descriptor[38:36];
    wire [15:0] d_root_word = active_descriptor[35:20];
    wire descriptor_match = cmd_imm < DESCRIPTOR_COUNT
        && configured[cmd_imm[INDEX_W-1:0]];
    // The JSON TREE_PUSH contract is sequential by default.  flags[0]
    // optionally selects an explicit R[rs] leaf index for diagnostics or
    // non-sequential producers; normal algorithm microcode needs no index.
    wire [31:0] effective_leaf_index = cmd_flags[0]
        ? cmd_leaf_index : (active_tree ? {16'b0, accepted_leaves} : 32'b0);

    wire tree_start = state == S_TREE_START;
    wire tree_ready, tree_busy, tree_error;
    wire [15:0] tree_error_code;
    wire tree_leaf_ready;
    wire parent_req_valid, parent_req_ready;
    wire [7:0] parent_req_height;
    wire [15:0] parent_req_start_leaf;
    wire [255:0] parent_req_left, parent_req_right;
    wire parent_rsp_valid, parent_rsp_error;
    wire [127:0] parent_rsp_value;
    wire auth_valid, root_valid;
    wire [7:0] auth_level;
    wire [255:0] auth_node, tree_root;

    wire [31:0] layer_value = registers_latched[32*4 +: 32];
    wire [31:0] keypair_value = d_keypair_from_reg
        ? registers_latched[32*d_keypair_reg +: 32] : 32'b0;
    wire [31:0] subtree_start = registers_latched[32*3 +: 32];
    wire [31:0] parent_index =
        (subtree_start + parent_req_start_leaf) >> parent_req_height;

    function automatic [31:0] pack_be32(input [31:0] value);
        pack_be32 = {value[7:0], value[15:8], value[23:16], value[31:24]};
    endfunction

    wire [255:0] parent_address = {
        pack_be32(parent_index), pack_be32({24'b0, parent_req_height}),
        pack_be32(keypair_value), pack_be32({24'b0, d_address_type}),
        tree_word1[31:0], tree_word0, pack_be32(layer_value)
    };

    assign cfg_ready = !engine_busy && state == S_IDLE && !active_tree;
    assign cmd_ready = state == S_IDLE;
    assign rsp_valid = state == S_RESPONSE;
    assign busy = state != S_IDLE || active_tree;
    assign scratch_request_valid = state == S_CONTEXT0_REQ
        || state == S_CONTEXT1_REQ || state == S_LEAF0_REQ
        || state == S_LEAF1_REQ || state == S_ROOT0 || state == S_ROOT1;

    always_comb begin
        scratch_request_write = 1'b0;
        scratch_request_address = '0;
        scratch_request_write_data = '0;
        case (state)
            S_CONTEXT0_REQ: scratch_request_address = 16'd464;
            S_CONTEXT1_REQ: scratch_request_address = 16'd465;
            S_LEAF0_REQ: scratch_request_address = leaf_base_word;
            S_LEAF1_REQ: scratch_request_address = leaf_base_word + 1'b1;
            S_ROOT0: begin
                scratch_request_write = 1'b1;
                scratch_request_address = d_root_word;
                scratch_request_write_data = root_latched[63:0];
            end
            S_ROOT1: begin
                scratch_request_write = 1'b1;
                scratch_request_address = d_root_word + 1'b1;
                scratch_request_write_data = root_latched[127:64];
            end
            default: begin end
        endcase
    end

    micro_hbs_treehash_min_dynamic #(
        .MAX_TREE_HEIGHT(MAX_TREE_HEIGHT)
    ) treehash (
        .clk, .rst_n, .start(tree_start), .ready(tree_ready),
        .tree_height(d_height), .target_leaf(16'b0),
        .leaf_valid(state == S_PUSH), .leaf_ready(tree_leaf_ready),
        .leaf_index(leaf_index_latched),
        .leaf_value({128'b0, leaf_value}),
        .parent_req_valid, .parent_req_ready, .parent_req_height,
        .parent_req_start_leaf, .parent_req_left, .parent_req_right,
        .parent_rsp_valid,
        .parent_rsp_value({128'b0, parent_rsp_value}), .parent_rsp_error,
        .auth_valid, .auth_level, .auth_node, .root_valid,
        .root(tree_root), .busy(tree_busy), .error(tree_error),
        .error_code(tree_error_code), .accepted_leaves, .parent_hashes,
        .peak_stack_nodes()
    );

    micro_hbs_slh_dsa_tree_parent #(.UNROLL(UNROLL)) parent (
        .clk, .rst_n, .req_valid(parent_req_valid),
        .req_ready(parent_req_ready), .req_public_seed(public_seed),
        .req_address(parent_address),
        .req_left_node(parent_req_left[127:0]),
        .req_right_node(parent_req_right[127:0]),
        .rsp_valid(parent_rsp_valid), .rsp_ready(1'b1),
        .rsp_parent(parent_rsp_value), .rsp_error(parent_rsp_error)
    );

    always_ff @(posedge clk) begin
        if (cfg_valid && cfg_ready && cfg_id < DESCRIPTOR_COUNT
            && cfg_data[63:56] == 8'h01 && cfg_data[19:0] == 0)
            descriptors[cfg_id[INDEX_W-1:0]] <= cfg_data;
    end

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= S_IDLE;
            configured <= '0;
            active_descriptor <= '0;
            active_id <= '0;
            active_tree <= 1'b0;
            leaf_base_word <= '0;
            leaf_index_latched <= '0;
            registers_latched <= '0;
            tree_word0 <= '0;
            tree_word1 <= '0;
            leaf_value <= '0;
            root_latched <= '0;
            cfg_error <= 1'b0;
            cfg_error_code <= '0;
            rsp_error <= 1'b0;
            rsp_error_code <= '0;
            total_parent_hashes <= '0;
        end else begin
            if (parent_rsp_valid)
                total_parent_hashes <= total_parent_hashes + 1'b1;
            cfg_error <= 1'b0;
            cfg_error_code <= '0;
            if (cfg_valid) begin
                if (!cfg_ready || cfg_id >= DESCRIPTOR_COUNT
                    || cfg_data[63:56] != 8'h01
                    || cfg_data[55:48] == 0
                    || cfg_data[55:48] > MAX_TREE_HEIGHT
                    || cfg_data[19:0] != 0
                    || cfg_data[35:20] + 1 >= SCRATCH_WORDS
                    || configured[cfg_id[INDEX_W-1:0]]) begin
                    cfg_error <= 1'b1;
                    cfg_error_code <= ERR_CFG;
                end else
                    configured[cfg_id[INDEX_W-1:0]] <= 1'b1;
            end

            case (state)
                S_IDLE: if (cmd_valid) begin
                    rsp_error <= 1'b0;
                    rsp_error_code <= '0;
                    if (!descriptor_match || cmd_flags[7:1] != 0
                        || effective_leaf_index[31:16] != 0
                        || ({1'b0, cmd_rd} * 2 + 1) >= SCRATCH_WORDS) begin
                        rsp_error <= 1'b1;
                        rsp_error_code <= ERR_CMD;
                        state <= S_RESPONSE;
                    end else if (active_tree
                        && (active_id != cmd_imm[15:0]
                            || effective_leaf_index == 0)) begin
                        rsp_error <= 1'b1;
                        rsp_error_code <= ERR_CONTEXT;
                        state <= S_RESPONSE;
                    end else begin
                        active_descriptor <= descriptors[cmd_imm[INDEX_W-1:0]];
                        active_id <= cmd_imm[15:0];
                        leaf_base_word <= {8'b0, cmd_rd} * 2;
                        leaf_index_latched <= effective_leaf_index[15:0];
                        leaf_value <= '0;
                        if (!active_tree) begin
                            if (effective_leaf_index != 0) begin
                                rsp_error <= 1'b1;
                                rsp_error_code <= ERR_CONTEXT;
                                state <= S_RESPONSE;
                            end else begin
                                registers_latched <= cmd_registers;
                                state <= S_CONTEXT0_REQ;
                            end
                        end else
                            state <= S_LEAF0_REQ;
                    end
                end
                S_CONTEXT0_REQ: if (scratch_request_ready)
                    state <= S_CONTEXT0_WAIT;
                S_CONTEXT0_WAIT: begin
                    if (scratch_response_error) begin
                        rsp_error <= 1'b1; rsp_error_code <= ERR_SCRATCH;
                        state <= S_RESPONSE;
                    end else if (scratch_response_valid) begin
                        tree_word0 <= scratch_response_data;
                        state <= S_CONTEXT1_REQ;
                    end
                end
                S_CONTEXT1_REQ: if (scratch_request_ready)
                    state <= S_CONTEXT1_WAIT;
                S_CONTEXT1_WAIT: begin
                    if (scratch_response_error) begin
                        rsp_error <= 1'b1; rsp_error_code <= ERR_SCRATCH;
                        state <= S_RESPONSE;
                    end else if (scratch_response_valid) begin
                        tree_word1 <= scratch_response_data;
                        state <= S_TREE_START;
                    end
                end
                S_TREE_START: if (tree_ready) begin
                    active_tree <= 1'b1;
                    state <= S_LEAF0_REQ;
                end
                S_LEAF0_REQ: if (scratch_request_ready)
                    state <= S_LEAF0_WAIT;
                S_LEAF0_WAIT: begin
                    if (scratch_response_error) begin
                        rsp_error <= 1'b1; rsp_error_code <= ERR_SCRATCH;
                        state <= S_RESPONSE;
                    end else if (scratch_response_valid) begin
                        leaf_value[63:0] <= scratch_response_data;
                        state <= S_LEAF1_REQ;
                    end
                end
                S_LEAF1_REQ: if (scratch_request_ready)
                    state <= S_LEAF1_WAIT;
                S_LEAF1_WAIT: begin
                    if (scratch_response_error) begin
                        rsp_error <= 1'b1; rsp_error_code <= ERR_SCRATCH;
                        state <= S_RESPONSE;
                    end else if (scratch_response_valid) begin
                        leaf_value[127:64] <= scratch_response_data;
                        state <= S_PUSH;
                    end
                end
                S_PUSH: if (tree_leaf_ready)
                    state <= S_SETTLE;
                S_SETTLE: begin
                    if (tree_error) begin
                        rsp_error <= 1'b1;
                        rsp_error_code <= tree_error_code != 0
                            ? tree_error_code : ERR_PARENT;
                        active_tree <= 1'b0;
                        state <= S_RESPONSE;
                    end else if (root_valid) begin
                        root_latched <= tree_root[127:0];
                        active_tree <= 1'b0;
                        state <= S_ROOT0;
                    end else if (tree_leaf_ready)
                        state <= S_RESPONSE;
                end
                S_ROOT0: if (scratch_request_ready) state <= S_ROOT1;
                S_ROOT1: if (scratch_request_ready) state <= S_RESPONSE;
                S_RESPONSE: begin
                    state <= S_IDLE;
                    rsp_error <= 1'b0;
                    rsp_error_code <= '0;
                end
                default: begin
                    rsp_error <= 1'b1;
                    rsp_error_code <= ERR_CMD;
                    active_tree <= 1'b0;
                    state <= S_RESPONSE;
                end
            endcase
        end
    end
endmodule

`default_nettype wire
