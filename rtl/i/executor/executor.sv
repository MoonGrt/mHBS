`timescale 1ns / 1ps
`default_nettype none
`include "rtl/i/executor/instructions.svh"
// K1U1 template executor. Each HASH launches one complete recipe; software
// controls chain steps, captures, endpoint reduction, trees and authentication.
// verilog_format: off
module executor #(parameter integer UNROLL=1,PIPELINE=1)(
`ifndef SYNTHESIS
 output logic [15:0] error_code, output logic [63:0] cycles,
 output wire [63:0] hash_count,permutation_count,
`endif
 input wire clk,rst,input wire [63:0] image_header,profile_descriptor,
 output wire [7:0] program_address,input wire [63:0] program_data,
 output wire [4:0] template_address,input wire [63:0] template_data,
 output wire [9:0] descriptor_addresses,input wire [127:0] descriptor_data,
 input wire [6:0] job_entry,input wire [1:0] job_operation,
 input wire job_valid,output wire job_ready,input wire [6:0] job_message_length,
 input wire [31:0] job_index,input wire [127:0] job_identifier,
 input wire [255:0] job_secret_seed,job_secret_prf,job_public_seed,job_public_root,job_randomizer,
 input wire message_valid,output wire message_ready,input wire [63:0] message_data,
 input wire verify_valid,output wire verify_ready,input wire [255:0] verify_data,output logic verify_pass,
 output wire out_valid,output wire [255:0] out_data,output wire [5:0] out_bytes,
 output wire busy,output logic done,error
);
// verilog_format: on
    localparam integer N=32,W=256,V=392,INDEX_BITS=8,MAX_MESSAGE_BYTES=87,DIGEST_BYTES=49;
    localparam integer FORS_DIGEST_BITS=320,WORKSPACE_DEPTH=128;
    wire valid_image_header=image_header[63:57]==`CHAIN_HEADER_MAGIC &&
        image_header[42:36]==0 && image_header[49:43]==1 && image_header[56:50]==2;
    wire [4:0] config_code=profile_descriptor[4:0];
    wire decoded_stateful=config_code>=5'h18 && config_code<=5'h1d;
    wire decoded_xmss=decoded_stateful && config_code<5'h1b;
`ifdef MHBS_SHA2
    wire valid_profile=profile_descriptor[63:6]==0 && profile_descriptor[5] &&
        (decoded_stateful || config_code==0 || config_code==4);
`else
    wire valid_profile=profile_descriptor[63:5]==0 && (decoded_stateful ||
        config_code==0 || config_code==1 || config_code==2 || config_code==4 || config_code==5 || config_code==6);
`endif
    wire [4:0] decoded_height=(config_code==5'h18 || config_code==5'h1b) ? 5'd10 :
        config_code==5'h19 ? 5'd16 : config_code==5'h1c ? 5'd15 : 5'd20;
    typedef enum logic [4:0] {
        IDLE,MESSAGE,LAUNCH,FETCH,LOAD_DESCRIPTOR,DECODE,HASH_ISSUE,HASH_WAIT,HASH_RESULT,
        ROUTE,TRANSFORM,EMIT,EMIT_NEXT,OUTPUT_CHUNK,DRAIN,FINISH,VERIFY_INPUT,VERIFY_RANDOM,
        FAILED,SF_RANDOM,CONTROL_LOAD,CONTROL_STORE,CONTROL_INPUT,CONTROL_OUTPUT,CONTROL_OPERANDS
    } state_t;
    state_t state,continuation;
    logic abort_execution;
    wire execution_rst=rst || abort_execution;
    logic [1:0] operation;
    wire verifying=operation==2;
    logic stateful,xmss,small_signature;
    logic [4:0] stateful_height;
    logic [1:0] profile_code;
    logic [5:0] node_bytes;
    wire [3:0] FORS_A=small_signature ? (profile_code==0 ? 4'd12 : 4'd14) :
        profile_code==0 ? 4'd6 : profile_code==1 ? 4'd8 : 4'd9;
    wire [7:0] LEN1={1'b0,node_bytes,1'b0};
    logic [MAX_MESSAGE_BYTES*8-1:0] message_buffer;
    logic [6:0] message_length,message_received;
    wire [255:0] secret_seed=job_secret_seed,secret_prf=job_secret_prf;
    wire [255:0] public_seed=job_public_seed,randomizer=job_randomizer;
    logic [255:0] value[0:3];
    logic [FORS_DIGEST_BITS-W-1:0] fors_digest_tail;
    logic [63:0] scalar_tree;
    logic [19:0] scalar_leaf;
    logic [11:0] checksum;
    logic [7:0] transform_index,lt_count,lt_cursor;
    logic [3:0] lt_level;
    logic [4:0] layer,node_level,tree_height,auth_level;
    logic [5:0] group_index;
    logic [20:0] leaf_cursor,node_index,target,target_at_level,control_base,control_limit;
    logic [3:0] control_flags;
    logic [1:0] indexing;
    logic [3:0] macro_op;
    logic [4:0] macro_desc,macro_route;
    logic [63:0] saved_descriptor;
    wire [63:0] descriptor=saved_descriptor;
    wire [63:0] route_descriptor=descriptor_data[127:64];
    logic [255:0] node_value,emit_value;
    logic [V-1:0] result;
    logic [5:0] emit_length;
    logic [7:0] emit_base;
    logic [3:0] emit_count,emit_cursor;
    logic seq_start,seq_complete,control_complete;
    wire seq_ready,seq_done,seq_error,cmd_valid,command_keep_coordinates,control_valid,control_condition;
    wire [47:0] cmd;
    wire [63:0] control;
    // verilog_format: off
    sequencer sequencer(.clk,.rst(execution_rst),.start(seq_start),.entry(job_entry),.ready(seq_ready),
        .done(seq_done),.error(seq_error),.program_address,.program_data,.template_address,.template_data,
        .command_valid(cmd_valid),.command_ready(state==FETCH),.command_done(seq_complete),.command(cmd),
        .command_keep_coordinates,.control_valid,.control,.control_ready(state==FETCH),
        .control_done(control_complete || immediate_control_complete),.control_condition);
    // verilog_format: on
    wire [4:0] hash_recipe_id=state==EMIT ? 5'(emit_base+emit_cursor) : macro_desc;
    assign descriptor_addresses={macro_route,hash_recipe_id};
    logic [63:0] task_recipe;
    logic [19:0] task_leaf;
    logic [7:0] task_a;
    logic [20:0] task_b;
    wire lane_ready,lane_valid,lane_error;
    wire [V-1:0] lane_value;
    wire [7:0] lane_list_next;
`ifndef SYNTHESIS
    wire [63:0] lane_hashes,lane_permutations;
    logic [63:0] hash_base,permutation_base;
    assign hash_count=lane_hashes-hash_base;
    assign permutation_count=lane_permutations-permutation_base;
`endif
    logic endpoint_write;
    logic [7:0] endpoint_address,endpoint_read_address;
    logic [255:0] endpoint_data;
    wire [255:0] endpoint_value0,endpoint_value1;
    wire [7:0] endpoint_read0=endpoint_read_address;
    wire [7:0] endpoint_read1=endpoint_read_address==127 ? 8'd126 : endpoint_read_address+1'b1;
    // verilog_format: off
    (* keep_hierarchy="yes" *) value #(.WIDTH(W),.DEPTH(WORKSPACE_DEPTH),.ADDRESS_BITS(INDEX_BITS)) endpoints(
        .clk,.write_enable(endpoint_write),.write_address(endpoint_address),.write_data(endpoint_data),
        .read0(endpoint_read0),.read1(endpoint_read1),.value0(endpoint_value0),.value1(endpoint_value1));
    recipe #(.N(N),.DIGEST_BYTES(DIGEST_BYTES),.INDEX_BITS(INDEX_BITS),.UNROLL(UNROLL),.PIPELINE(PIPELINE),
        .MAX_MESSAGE_BYTES(MAX_MESSAGE_BYTES),.SHARED_STATE(1'b1),.RECIPE_MASK(16'hfffe)) lane(
`ifndef SYNTHESIS
        .hash_count(lane_hashes),.permutation_count(lane_permutations),.batch_hashes(),.batch_permutations(),
`endif
        .clk,.rst(execution_rst),.node_bytes,.identifier(job_identifier),
        .batch_mode(1'b0),.batch_request_valid(1'b0),.batch_request_ready(),.batch_request_tag(1'b0),
        .batch_steps(5'd0),.batch_capture_after(5'd0),.batch_capture_enable(1'b0),
        .batch_leaf(20'd0),.batch_a(8'd0),.batch_b(32'd0),.batch_family(2'd0),.batch_no_seed(1'b0),
        .batch_start(4'd0),.batch_initial_value(256'd0),.batch_fixed_shape(4'd0),.batch_pair(1'b0),
        .batch_right(256'd0),.batch_seed_domain(8'd0),.batch_step_domain(8'd0),
        .batch_response_valid(),.batch_response_ready(1'b0),.batch_response_tag(),.batch_response_digest(),
        .batch_response_capture(),.batch_read_tag(1'b0),.batch_read_digest(),.batch_read_capture(),
        .request_valid(state==HASH_ISSUE),.request_ready(lane_ready),.request_recipe(task_recipe),
        .request_step_recipe(64'd0),.request_chain(1'b0),.request_steps(5'd0),
        .request_capture_after(5'd0),.request_capture(1'b0),
        .secret_seed,.secret_prf,.public_seed,.root(value[3]),
        .randomizer((task_recipe[59:56]==4 || task_recipe[59:56]==6 || (verifying && stateful)) ? value[0] : randomizer),
        .message_buffer,.message_length,.request_layer(layer),.request_tree(scalar_tree),.request_leaf(task_leaf),
        .request_a(task_a),.request_b({11'd0,task_b}),.request_left(result[255:0]),.request_right(node_value),
        .list_index0(),.list_index1(),.list_next_index0(lane_list_next),
        .list_data0(endpoint_value0),.list_data1(endpoint_value1),.response_valid(lane_valid),
        .response_ready(state==HASH_WAIT),.response_value(lane_value),.response_capture(),.error(lane_error));
    // verilog_format: on
    assign job_ready=state==IDLE;
    assign message_ready=state==MESSAGE;
    assign verify_ready=verifying && (state==VERIFY_INPUT || state==CONTROL_INPUT);
    assign out_valid=state==OUTPUT_CHUNK;
    assign out_data=emit_value;
    assign out_bytes=emit_length;
    assign busy=state!=IDLE;
    localparam logic [1:0] ROUTE_HASH=0,ROUTE_NODE=1,ROUTE_EMIT=3;
    logic [1:0] route_source;
    wire [V-1:0] route_value=route_source==ROUTE_HASH ? result :
        {{(V-W){1'b0}},route_source==ROUTE_NODE ? node_value : emit_value};
    function automatic [31:0] be32(input [31:0] x);
        be32 = {x[7:0], x[15:8], x[23:16], x[31:24]};
    endfunction
    function automatic [4:0] digit(input [7:0] index);
        reg [7:0] checksum_index;
        begin
            checksum_index = index - LEN1;
            digit = 0;
            if (index < LEN1) begin
                digit = {1'b0, value[2][{(index[5:0]^6'd1), 2'b0}+:4]};
            end else begin
                case (checksum_index)
                    0: digit = {1'b0, checksum[11:8]};
                    1: digit = {1'b0, checksum[7:4]};
                    2: digit = {1'b0, checksum[3:0]};
                    default: digit = 0;
                endcase
            end
        end
    endfunction
    // Software selects chain digits with A; checksum visits message digits only.
    wire [3:0] transform_digit = value[2][{(transform_index[5:0] ^ 6'd1), 2'b0}+:4];
    wire [3:0] checksum_increment = ~transform_digit;
`ifndef SYNTHESIS
    always @(posedge clk) begin : debug_checksum_increment
        if (!execution_rst && state == TRANSFORM && descriptor[59:56] == 1) begin
            if (transform_index >= LEN1 || {1'b0, transform_digit} !== digit(transform_index))
                $fatal(1, "checksum loop exceeded message digits");
            if ({1'b0, checksum_increment} !== 5'd15 - digit(transform_index))
                $fatal(1, "checksum nibble complement changed its value");
        end
    end
`endif
    wire [FORS_DIGEST_BITS-1:0] fors_digest = {fors_digest_tail, value[1]};
    wire [FORS_DIGEST_BITS-1:0] fors_bitstream;
    genvar fb;
    generate
        for (fb = 0; fb < FORS_DIGEST_BITS; fb = fb + 1) begin : fors_bit_order
            assign fors_bitstream[fb] = fors_digest[(fb/8)*8+7-(fb%8)];
        end
    endgenerate
    function automatic [9:0] fors_group_offset(input [5:0] group_number);
        begin
            case (FORS_A)
                6: fors_group_offset = ({group_number, 2'b0} + {group_number, 1'b0});
                8: fors_group_offset = {group_number, 3'b0};
                9: fors_group_offset = ({group_number, 3'b0} + group_number);
                12: fors_group_offset = ({group_number, 3'b0} + {group_number, 2'b0});
                default: fors_group_offset = ({group_number, 4'b0} - {group_number, 1'b0});
            endcase
        end
    endfunction
    function automatic [13:0] fors_target(input [9:0] offset);
        reg [13:0] segment;
        begin
            segment = fors_bitstream >> offset;
            // verilog_format: off
            case (FORS_A)
                6: fors_target = {8'd0,segment[0],segment[1],segment[2],segment[3],segment[4],segment[5]};
                8: fors_target = {6'd0,segment[0],segment[1],segment[2],segment[3],segment[4],segment[5],segment[6],segment[7]};
                9: fors_target = {5'd0,segment[0],segment[1],segment[2],segment[3],segment[4],segment[5],segment[6],segment[7],segment[8]};
                12: fors_target = {2'd0,segment[0],segment[1],segment[2],segment[3],segment[4],segment[5],segment[6],segment[7],segment[8],segment[9],segment[10],segment[11]};
                default: fors_target = {segment[0],segment[1],segment[2],segment[3],segment[4],segment[5],segment[6],segment[7],segment[8],segment[9],segment[10],segment[11],segment[12],segment[13]};
            endcase
            // verilog_format: on
        end
    endfunction
    function automatic [63:0] parsed_tree(input [V-1:0] digest);
        reg [63:0] bytes;
        integer j;
        begin
            if (small_signature) begin
                case (node_bytes)
                    16: bytes = {digest[168+:56], 8'd0};
                    24: bytes = {digest[240+:56], 8'd0};
                    default: bytes = {digest[312+:56], 8'd0};
                endcase
            end else
                case (node_bytes)
                    16: bytes = digest[200+:64];
                    24: bytes = digest[264+:64];
                    default: bytes = digest[320+:64];
                endcase
            for (j = 0; j < 8; j = j + 1) parsed_tree[(7-j)*8+:8] = bytes[j*8+:8];
            if (small_signature && node_bytes != 32) parsed_tree[63:54] = 0;
            else if (!small_signature && node_bytes != 32) parsed_tree[63] = 0;
        end
    endfunction
    function automatic [9:0] parsed_leaf(input [V-1:0] digest);
        begin
            if (small_signature) begin
                case (node_bytes)
                    16: parsed_leaf = {1'b0, digest[224], digest[232+:8]};
                    24: parsed_leaf = {1'b0, digest[296], digest[304+:8]};
                    default: parsed_leaf = {2'b0, digest[368+:8]};
                endcase
            end else
                parsed_leaf=node_bytes==16 ? {7'b0,digest[264 +:3]}
                : node_bytes==24 ? {7'b0,digest[328 +:3]} : {6'b0,digest[384 +:4]};
        end
    endfunction

    function automatic [20:0] narrow_register_read(input [4:0] selector);
        begin
            case(selector)
                `CTX_LEAF:narrow_register_read={1'b0,task_leaf};
                `CTX_A:narrow_register_read={13'd0,task_a};
                `CTX_B:narrow_register_read=task_b;
                `CTX_CURSOR:narrow_register_read=leaf_cursor;
                `CTX_INDEX:narrow_register_read=node_index;
                `CTX_LEVEL:narrow_register_read={16'd0,node_level};
                `CTX_TARGET:narrow_register_read=target;
                `CTX_PATH:narrow_register_read=target_at_level;
                `CTX_BASE:narrow_register_read=control_base;
                `CTX_HEIGHT:narrow_register_read={16'd0,tree_height};
                `CTX_LIMIT:narrow_register_read=control_limit;
                `CTX_LAYER:narrow_register_read={16'd0,layer};
                `CTX_GROUP:narrow_register_read={15'd0,group_index};
                `CTX_AUTH_LEVEL:narrow_register_read={16'd0,auth_level};
                `CTX_FLAGS:narrow_register_read={17'd0,control_flags};
                `CTX_MODE:narrow_register_read={19'd0,indexing};
                `CTX_Q:narrow_register_read={1'b0,job_index[19:0]};
                `CTX_SCALAR_LEAF:narrow_register_read={1'b0,scalar_leaf};
                `CTX_PROFILE_HEIGHT:narrow_register_read={16'd0,stateful_height};
                `CTX_ZERO:narrow_register_read=0;
                `CTX_ONE:narrow_register_read=1;
                `CTX_OPERATION:narrow_register_read={19'd0,operation};
                `CTX_XMSS:narrow_register_read={20'd0,xmss};
                `CTX_STATEFUL:narrow_register_read={20'd0,stateful};
                `CTX_LT_COUNT:narrow_register_read={13'd0,lt_count};
                `CTX_LT_CURSOR:narrow_register_read={13'd0,lt_cursor};
                `CTX_LT_LEVEL:narrow_register_read={17'd0,lt_level};
                default:narrow_register_read=0;
            endcase
        end
    endfunction
    // Only the slow capture port can observe FORS extraction or the WOTS digit lookup.
    // It is deliberately absent from narrow_register_read, so no combinational
    // digest/group lookup can reach arithmetic or a context write-enable.
    function automatic [20:0] narrow_read(input [4:0] selector);
        if(selector==`CTX_FORS_TARGET)
            narrow_read={7'd0,fors_target(fors_group_offset(group_index))};
        else if(selector==`CTX_DIGIT) narrow_read={16'd0,digit(task_a)};
        else narrow_read=narrow_register_read(selector);
    endfunction
    function automatic [20:0] narrow_mask(input [4:0] selector);
        case(selector)
            `CTX_LEAF:narrow_mask=21'hfffff;
            `CTX_A,`CTX_LT_COUNT,`CTX_LT_CURSOR:narrow_mask=21'hff;
            `CTX_LT_LEVEL:narrow_mask=21'hf;
            `CTX_LEVEL,`CTX_HEIGHT,`CTX_LAYER,`CTX_AUTH_LEVEL:narrow_mask=21'h1f;
            `CTX_GROUP:narrow_mask=21'h3f;
            `CTX_FLAGS:narrow_mask=21'hf;
            `CTX_MODE:narrow_mask=21'h3;
            default:narrow_mask=21'h1fffff;
        endcase
    endfunction
    task automatic narrow_write(input [4:0] selector,input [20:0] data);
        begin
            case(selector)
                `CTX_LEAF:task_leaf<=data[19:0];
                `CTX_A:task_a<=data[7:0];
                `CTX_B:task_b<=data;
                `CTX_CURSOR:leaf_cursor<=data;
                `CTX_INDEX:node_index<=data;
                `CTX_LEVEL:node_level<=data[4:0];
                `CTX_TARGET:target<=data;
                `CTX_PATH:target_at_level<=data;
                `CTX_BASE:control_base<=data;
                `CTX_HEIGHT:tree_height<=data[4:0];
                `CTX_LIMIT:control_limit<=data;
                `CTX_LAYER:layer<=data[4:0];
                `CTX_GROUP:group_index<=data[5:0];
                `CTX_AUTH_LEVEL:auth_level<=data[4:0];
                `CTX_FLAGS:control_flags<=data[3:0];
                `CTX_MODE:indexing<=data[1:0];
                `CTX_LT_COUNT:lt_count<=data[7:0];
                `CTX_LT_CURSOR:lt_cursor<=data[7:0];
                `CTX_LT_LEVEL:lt_level<=data[3:0];
                default:begin end
            endcase
        end
    endtask
    function automatic [255:0] wide_read(input [4:0] selector);
        case(selector)
            `WIDE_NODE:wide_read=node_value;
            `WIDE_LEFT:wide_read=result[255:0];
            `WIDE_V0:wide_read=value[0];
            `WIDE_V1:wide_read=value[1];
            `WIDE_V2:wide_read=value[2];
            `WIDE_V3:wide_read=value[3];
            `WIDE_EMIT:wide_read=emit_value;
            default:wide_read=0;
        endcase
    endfunction
    // Storage, input and register moves share one write-data selector.
    wire [255:0] control_wide_data =
        (endpoint_value0 & {256{state==CONTROL_LOAD}}) |
        (verify_data & {256{state==CONTROL_INPUT}}) |
        (wide_read(control[51:47]) & {256{state==FETCH}});
    task automatic wide_write(input [4:0] selector,input [255:0] data);
        begin
            case(selector)
                `WIDE_NODE:node_value<=data;
                `WIDE_LEFT:result<={{(V-W){1'b0}},data};
                `WIDE_V0:value[0]<=data;
                `WIDE_V1:value[1]<=data;
                `WIDE_V2:value[2]<=data;
                `WIDE_V3:value[3]<=data;
                `WIDE_EMIT:emit_value<=data;
                default:begin end
            endcase
        end
    endtask
    wire [4:0] control_op=control[61:57],control_dst=control[56:52];
    wire [4:0] control_src=control[51:47],control_aux=control[46:42];
    wire [20:0] control_immediate=control[41:21];
    wire [3:0] control_cond=control[12:9];
    wire pure_control=(control_op>=`CTRL_SET && control_op<=`CTRL_RET) ||
        control_op==`CTRL_WMOV || control_op==`CTRL_SHL;
    wire immediate_control_complete=pure_control &&
        ((state==FETCH && control_valid && !register_control_operands) || state==CONTROL_OPERANDS);

    // At most two narrow sources are live in any instruction. MOV/ADD
    // read SRC on port 0; all other instructions read DST there.
    wire source_on_port0=control_op==`CTRL_MOV || control_op==`CTRL_ADD;
    wire [4:0] control_selector0=source_on_port0 ? control_src : control_dst;
    wire [4:0] control_selector1=control_op==`CTRL_ADD ? control_aux : control_src;
    wire [20:0] live_control_read0=narrow_read(control_selector0);
    wire [20:0] live_control_read1=narrow_read(control_selector1);
    // FORS digest extraction is a wide dynamic lookup. Register it before
    // arithmetic/condition/legality/writeback, rather than extending the
    // group-index path through the complete software execution cone.
    wire register_control_operands=control_selector0==`CTX_FORS_TARGET ||
        control_selector1==`CTX_FORS_TARGET || control_selector0==`CTX_DIGIT || control_selector1==`CTX_DIGIT;
    logic [20:0] staged_control_read0,staged_control_read1;
    wire [20:0] control_read0=state==CONTROL_OPERANDS ? staged_control_read0 : narrow_register_read(control_selector0);
    wire [20:0] control_read1=state==CONTROL_OPERANDS ? staged_control_read1 : narrow_register_read(control_selector1);
    wire [20:0] control_dst_value=control_read0;
    wire [20:0] control_src_value=control_read0;
    wire [20:0] control_aux_value=control_read1;
    logic [40:0] control_alu;
    always_comb begin
        case(control_op)
            `CTRL_SET:control_alu={20'd0,control_immediate};
            `CTRL_MOV:control_alu={20'd0,control_src_value};
            `CTRL_INC:control_alu={20'd0,control_dst_value}+41'd1;
            `CTRL_SHR:control_alu={20'd0,control_dst_value}>>control_immediate[4:0];
            `CTRL_SHL:control_alu={20'd0,control_dst_value}<<control_immediate[4:0];
            `CTRL_XOR1:control_alu={20'd0,control_dst_value}^41'd1;
            `CTRL_ADD:control_alu={20'd0,control_src_value}+{20'd0,control_aux_value};
            default:control_alu=0;
        endcase
    end
    wire [20:0] branch_left=control_read0;
    wire [20:0] branch_right=control[46:42]==1 ? control[41:21] : control_read1;
    logic branch_taken;
    always_comb begin
        case(control[12:9])
            `COND_ALWAYS:branch_taken=1;
            `COND_EQ:branch_taken=branch_left==branch_right;
            `COND_NE:branch_taken=branch_left!=branch_right;
            `COND_LT:branch_taken=branch_left<branch_right;
            `COND_GE:branch_taken=branch_left>=branch_right;
            `COND_ODD:branch_taken=branch_left[0];
            `COND_ZERO:branch_taken=branch_left==0;
            `COND_BITSET:branch_taken=(branch_left&control[41:21])!=0;
            `COND_SIBLING:branch_taken=branch_left==(branch_right^21'd1);
            `COND_SAME_PARENT:branch_taken=branch_left[20:1]==branch_right[20:1];
            default:branch_taken=0;
        endcase
    end
    logic [7:0] control_store_slot;
    // Both fast and registered-operand branches retire on their execution
    // edge, so the condition always corresponds to the currently read data.
    assign control_condition=branch_taken;
    wire [21:0] control_load_address={1'b0,control_read1}+{1'b0,control_immediate};
    wire [21:0] control_store_address={1'b0,control_dst_value}+{1'b0,control_immediate};
    wire [63:0] emit_descriptor=descriptor_data[63:0];
    logic [255:0] emit_source;
    always_comb begin
        case(emit_descriptor[59:56])
            0:emit_source=secret_seed;
            1:emit_source=secret_prf;
            2:emit_source=public_seed;
            3:emit_source=value[3];
            4:emit_source=xmss ? value[0] : randomizer;
            5:emit_source={128'd0,job_identifier};
            6:emit_source={224'd0,be32(job_index)};
            7:emit_source={224'd0,be32(emit_descriptor[31:0])};
            default:emit_source=0;
        endcase
    end
    always_comb begin
        endpoint_write=0;endpoint_address=0;endpoint_data=0;
        if(state==CONTROL_STORE) begin
            endpoint_write=1;endpoint_address=control_store_slot;
            endpoint_data=wide_read(control_src);
        end else if(state==ROUTE && macro_route!=0 && route_descriptor[53]) begin
            endpoint_write=1;endpoint_address={2'd0,group_index};endpoint_data=route_value[255:0];
        end
    end
    task automatic fail;
        begin error<=1;abort_execution<=1;state<=FAILED;end
    endtask
    task automatic complete_macro;
        begin seq_complete<=1;state<=FETCH;end
    endtask
    task automatic complete_control;
        begin
            if(state!=FETCH && state!=CONTROL_OPERANDS) control_complete<=1;
            state<=FETCH;
        end
    endtask
    task automatic route_result(input [1:0] source);
        begin route_source<=source;state<=ROUTE;end
    endtask
    task automatic start_hash(input [63:0] selected_recipe,input state_t ret);
        begin task_recipe<=selected_recipe;continuation<=ret;state<=HASH_ISSUE;end
    endtask
    task automatic start_output(input [255:0] data,input [5:0] length,input state_t ret);
        begin emit_value<=data;emit_length<=length;continuation<=ret;state<=OUTPUT_CHUNK;end
    endtask
    task automatic read_verify_node(input state_t ret);
        begin continuation<=ret;state<=VERIFY_INPUT;end
    endtask
    task automatic execute_control;
        begin
                    case(control_op)
                        `CTRL_SET,`CTRL_MOV,`CTRL_INC,`CTRL_SHR,`CTRL_XOR1,`CTRL_ADD,`CTRL_SHL:begin
                            if((control_dst>15 && (control_dst<26 || control_dst>28)) ||
                                (control_op==`CTRL_MOV && control_src>28) ||
                                (control_op==`CTRL_ADD && (control_src>28 || control_aux>28)) ||
                                ((control_op==`CTRL_SHR || control_op==`CTRL_SHL) &&
                                    (control_immediate==0 || control_immediate>20)) ||
                                (|control_alu[40:21]) || (control_alu[20:0]&~narrow_mask(control_dst))!=0 ||
                                ((control_dst==`CTX_HEIGHT || control_dst==`CTX_LEVEL || control_dst==`CTX_AUTH_LEVEL) && control_alu>20) ||
                                (control_dst==`CTX_MODE && control_alu>2)) fail();
                            else begin narrow_write(control_dst,control_alu[20:0]);complete_control();end
                        end
                        `CTRL_BR:begin
                            if(control_cond>9 || control_aux>1 || control_dst>28 || control_src>28 ||
                                ((control_cond==`COND_SIBLING || control_cond==`COND_SAME_PARENT) && control_aux!=0)) fail();
                            else begin
                                complete_control();
                            end
                        end
                        `CTRL_CALL,`CTRL_RET:complete_control();
                        `CTRL_LOAD:begin
                            if(control_dst>6 || control_src>28 || control_load_address>=108) fail();
                            else state<=CONTROL_LOAD;
                        end
                        `CTRL_STORE:begin
                            if(control_src>7 || control_dst>28 || control_store_address>=108) fail();
                            else begin
                                control_store_slot<=control_store_address[7:0];
                                state<=CONTROL_STORE;
                            end
                        end
                        `CTRL_INPUT:begin
                            if(!verifying || control_dst>6) fail();else state<=CONTROL_INPUT;
                        end
                        `CTRL_OUTPUT:begin
                            if(verifying || control_src>7) fail();else begin
                                start_output(wide_read(control_src),node_bytes,CONTROL_OUTPUT);
                            end
                        end
                        `CTRL_WMOV:begin
                            if(control_dst>6 || control_src>7) fail();
                            else begin wide_write(control_dst,control_wide_data);complete_control();end
                        end
                        default:fail();
                    endcase
        end
    endtask
    always_ff @(posedge clk) begin
        if(rst) endpoint_read_address<=0;
        else begin
            case(state)
                HASH_ISSUE,HASH_WAIT:endpoint_read_address<=lane_list_next;
                CONTROL_OPERANDS:if(control_op==`CTRL_LOAD && control_load_address<108)
                    endpoint_read_address<=control_load_address[7:0];
                FETCH:if(control_valid && !register_control_operands && control_op==`CTRL_LOAD && control_load_address<108)
                    endpoint_read_address<=control_load_address[7:0];
                default:begin end
            endcase
        end
    end
`ifndef SYNTHESIS
    initial if(UNROLL!=1 || PIPELINE!=1) $fatal(1,"image-soft-chain is K1U1 only");
    logic [15:0] diagnostic_reason;
    always_comb begin
        diagnostic_reason=0;
        if(state==IDLE && job_valid) begin
            if(!valid_image_header) diagnostic_reason=16'h3010;
            else if(!valid_profile) diagnostic_reason=16'h3009;
            else if(decoded_stateful && job_index>=(32'd1<<decoded_height)) diagnostic_reason=16'h3008;
        end else if(seq_error) diagnostic_reason=16'h3011;
        else if(state==HASH_WAIT && lane_valid && lane_error) diagnostic_reason=16'h3007;
    end
    always_ff @(posedge clk) begin : debug_statistics
        if(rst) begin cycles<=0;hash_base<=0;permutation_base<=0;error_code<=0;end
        else begin
            if(state==IDLE && job_valid) begin
                cycles<=0;hash_base<=lane_hashes;permutation_base<=lane_permutations;error_code<=0;
            end else if(state!=IDLE && state!=FAILED) cycles<=cycles+1'b1;
            if(diagnostic_reason!=0) error_code<=diagnostic_reason;
            else if(state==FAILED && error_code==0) error_code<=16'h3012;
        end
    end
    always @(posedge clk) begin : debug_workspace
        if(!execution_rst) begin
            if(endpoint_write && endpoint_address>=WORKSPACE_DEPTH) $fatal(1,"workspace write out of range");
            if(endpoint_read_address>=WORKSPACE_DEPTH) $fatal(1,"workspace read out of range");
        end
    end
`endif

    always_ff @(posedge clk) begin
        if(rst) begin
            state<=IDLE;continuation<=IDLE;done<=0;error<=0;abort_execution<=0;
            seq_start<=0;seq_complete<=0;control_complete<=0;verify_pass<=0;
            stateful<=0;xmss<=0;small_signature<=0;stateful_height<=10;
            profile_code<=0;node_bytes<=16;operation<=0;message_length<=0;message_received<=0;
            scalar_tree<=0;scalar_leaf<=0;layer<=0;group_index<=0;
            leaf_cursor<=0;node_index<=0;node_level<=0;target<=0;target_at_level<=0;
            tree_height<=0;auth_level<=0;control_base<=0;control_limit<=0;control_flags<=0;indexing<=0;
            macro_op<=0;macro_desc<=0;macro_route<=0;
            saved_descriptor<=0;task_recipe<=0;task_leaf<=0;task_a<=0;task_b<=0;
            lt_count<=0;lt_cursor<=0;lt_level<=0;checksum<=0;transform_index<=0;
            route_source<=0;emit_length<=0;emit_base<=0;emit_count<=0;emit_cursor<=0;
            control_store_slot<=0;
        end else begin
            done<=0;seq_start<=0;seq_complete<=0;control_complete<=0;abort_execution<=0;
            if(seq_error && state!=IDLE && state!=FAILED) fail();
            else case(state)
                IDLE:if(job_valid) begin
                    error<=0;operation<=job_operation;stateful<=decoded_stateful;xmss<=decoded_xmss;
                    stateful_height<=decoded_height;small_signature<=!decoded_stateful && config_code[2];
                    profile_code<=config_code[1:0];
                    node_bytes<=decoded_stateful ? 6'd32 : config_code[1:0]==0 ? 6'd16 : config_code[1:0]==1 ? 6'd24 : 6'd32;
                    verify_pass<=0;message_length<=job_message_length;message_received<=0;
                    scalar_tree<=0;scalar_leaf<=decoded_stateful ? job_index[19:0] : 0;
                    layer<=0;group_index<=0;value[3]<=job_public_root;
                    task_leaf<=decoded_stateful ? job_index[19:0] : 0;task_a<=0;task_b<=0;
                    if(!valid_image_header || !valid_profile ||
                        (decoded_stateful && job_index>=(32'd1<<decoded_height))) fail();
                    else if(job_operation!=0 && job_message_length!=0) state<=MESSAGE;
                    else state<=LAUNCH;
                end
                MESSAGE:if(message_valid) begin
                    message_buffer[{message_received[6:3],6'b0}+:64]<=message_data;
                    message_received<=message_received+7'd8;
                    if(message_received+7'd8>=message_length) state<=LAUNCH;
                end
                LAUNCH:if(seq_ready) begin seq_start<=1;state<=FETCH;end
                FETCH:begin
                    if(seq_done) begin
                        if(verifying) verify_pass<=value[2][127:0]==job_public_root[127:0] &&
                            (node_bytes==16 || value[2][191:128]==job_public_root[191:128]) &&
                            (node_bytes!=32 || value[2][255:192]==job_public_root[255:192]);
                        state<=DRAIN;
                    end else if(control_valid) begin
                        if(register_control_operands) begin
                            staged_control_read0<=live_control_read0;
                            staged_control_read1<=live_control_read1;
                            state<=CONTROL_OPERANDS;
                        end else execute_control();
                    end
                    else if(cmd_valid) begin
                        macro_op<=cmd[47:44];macro_desc<=cmd[40:36];macro_route<=cmd[32:28];
                        if(!command_keep_coordinates) begin layer<=cmd[23:19];group_index<=cmd[18:13];end
                        state<=LOAD_DESCRIPTOR;
                    end
                end
                // The descriptor address was registered on command acceptance.
                // Decode on its capture edge; task_recipe remains registered
                // before the lane handshake, so no ROM-to-Keccak bypass exists.
                LOAD_DESCRIPTOR:begin
                    saved_descriptor<=descriptor_data[63:0];
                    case(macro_op)
                    1:begin
                        if(verifying && stateful && (descriptor_data[59:56]==5 || descriptor_data[59:56]==11))
                            read_verify_node(SF_RANDOM);
                        else if(verifying && descriptor_data[59:56]==3) read_verify_node(VERIFY_RANDOM);
                        else start_hash(descriptor_data[63:0],HASH_RESULT);
                    end
                    4:begin checksum<=0;transform_index<=0;state<=TRANSFORM;end
                    5:if(verifying && stateful) complete_macro();
                    else begin emit_base<=descriptor_data[59:52];emit_count<=descriptor_data[51:48];emit_cursor<=0;state<=EMIT;end
                    default:fail();
                    endcase
                end
                SF_RANDOM:begin
                    value[0]<=emit_value;
                    if(xmss) complete_macro();
                    else start_hash(saved_descriptor,HASH_RESULT);
                end
                HASH_ISSUE:if(lane_ready) state<=HASH_WAIT;
                HASH_WAIT:if(lane_valid) begin
                    result<=lane_value;
                    if(lane_error) fail();
                    else if(continuation==HASH_RESULT) begin
                        // result is captured on this edge. Plain HASH with an
                        // identity route needs no extra result/route bubbles.
                        // Nonidentity routes retain the result register boundary.
                        route_source<=ROUTE_HASH;
                        if(macro_route==0) complete_macro();else state<=ROUTE;
                    end else state<=continuation;
                end
                HASH_RESULT:route_result(ROUTE_HASH);
                ROUTE:begin
                    if(macro_route!=0) begin
                        if(!route_descriptor[53]) begin
                            value[route_descriptor[57:56]]<=route_value[255:0];
                            if(route_descriptor[57:56]==1) fors_digest_tail<=route_value[FORS_DIGEST_BITS-1:W];
                        end
                        if(route_descriptor[54]) begin scalar_tree<=parsed_tree(route_value);scalar_leaf<=parsed_leaf(route_value);end
                        if(!verifying && route_descriptor[55]) start_output(route_value[255:0],node_bytes,FETCH);
                        else state<=FETCH;
                        seq_complete<=1;
                    end else complete_macro();
                end
                TRANSFORM:begin
                    if(descriptor[59:56]==2) begin
                        scalar_leaf<=20'(scalar_tree&((64'd1<<descriptor[43:40])-1));
                        scalar_tree<=scalar_tree>>descriptor[43:40];complete_macro();
                    end else if(descriptor[59:56]==1) begin
                        checksum<=checksum+{8'd0,checksum_increment};
                        if(transform_index+1==LEN1) complete_macro();
                        else transform_index<=transform_index+1'b1;
                    end else fail();
                end
                EMIT:start_output(emit_source,emit_descriptor[53:48],EMIT_NEXT);
                EMIT_NEXT:begin
                    if(emit_cursor+1<emit_count) begin emit_cursor<=emit_cursor+1'b1;state<=EMIT;end
                    else complete_macro();
                end
                VERIFY_INPUT:if(verify_valid) begin emit_value<=verify_data;state<=continuation;end
                VERIFY_RANDOM:route_result(ROUTE_EMIT);
                OUTPUT_CHUNK:state<=continuation;
                CONTROL_OPERANDS:execute_control();
                CONTROL_LOAD:begin wide_write(control_dst,control_wide_data);complete_control();end
                CONTROL_STORE:complete_control();
                CONTROL_INPUT:if(verify_valid) begin wide_write(control_dst,control_wide_data);complete_control();end
                CONTROL_OUTPUT:complete_control();
                DRAIN:state<=FINISH;
                FINISH:begin done<=1;state<=IDLE;end
                FAILED:state<=IDLE;
                default:fail();
            endcase
        end
    end
endmodule
`default_nettype wire
