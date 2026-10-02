`timescale 1ns/1ps
`default_nettype none
// ABI 5: ROM schedules node operations. No hardware TREE traversal.
module mhbs_hbs #(
    parameter integer UNROLL=2, LANES=2,
    parameter bit PROFILE_ENABLE=0, SWAP_PHYSICAL_LANES=0
) (
    input wire [63:0] image_header, profile_descriptor,
    output wire [6:0] program_address,
    output wire [3:0] template_address,
    input wire [63:0] program_data, template_data,
    input wire [3:0] job_entry,
    output wire [9:0] descriptor_addresses,
    input wire [127:0] descriptor_data,
    input wire clk, rst,
    input wire job_valid, output wire job_ready, input wire [1:0] job_operation,
    input wire [6:0] job_message_length,
    input wire [255:0] job_secret_seed, job_secret_prf, job_public_seed, job_randomizer, job_public_root,
    input wire message_valid, output wire message_ready,
    input wire [63:0] message_data,
    input wire verify_valid, output wire verify_ready,
    input wire [255:0] verify_data,
    output logic verify_pass,
    output wire out_valid, output wire [255:0] out_data,
    output wire [5:0] out_bytes,
    output wire busy, output logic done, error, output logic [15:0] error_code,
    output wire [31:0] hash_count, permutation_count,
    output logic [31:0] cycles
);
    localparam integer N=32, W=256, V=392, INDEX_BITS=7, MAX_MESSAGE_BYTES=87;
    localparam integer DIGEST_BYTES=49;
    // Six supported profiles need at most ceil(35*9/8)=40 FORS bytes.
    // Tree/leaf indices still consume the full V-bit transient Hmsg result.
    localparam integer FORS_DIGEST_BITS=320;
    wire [1:0] profile_code=profile_descriptor[1:0];
    wire small_signature=profile_descriptor[2];
    wire [5:0] node_bytes=profile_code==0 ? 6'd16
        : profile_code==1 ? 6'd24 : 6'd32;
    wire [3:0] FORS_A=small_signature ? (profile_code==0 ? 4'd12 : 4'd14)
        : profile_code==0 ? 4'd6 : profile_code==1 ? 4'd8 : 4'd9;
    wire [3:0] HP=small_signature ? (profile_code[1] ? 4'd8 : 4'd9)
        : profile_code[1] ? 4'd4 : 4'd3;
    wire [7:0] LEN1={1'b0,node_bytes,1'b0};
    wire [63:0] descriptors [0:7];
    // Two reads are sufficient: request recipe plus chain-step recipe.
    // Macro and tree/chain descriptors are already latched in setup states.
    assign descriptors[0]=descriptor_data[63:0];
    assign descriptors[1]=descriptor_data[127:64];
    assign descriptors[2]=64'd0;
    assign descriptors[3]=descriptor_data[63:0];
    assign descriptors[4]=descriptor_data[63:0];
    assign descriptors[5]=descriptor_data[127:64];
    assign descriptors[6]=descriptor_data[63:0];
    assign descriptors[7]=descriptor_data[63:0];
    typedef enum logic [5:0] {
        IDLE=0, MESSAGE=1, LAUNCH=2, FETCH=3, LOAD_DESCRIPTOR=4, DECODE=5,
        CHAIN_SETUP=7, CHAIN_STORE=8, CHAIN_OUTPUT0=10, CHAIN_OUTPUT1=11,
        CHAIN_NEXT=14, REDUCE_SETUP=15, LEAF_SETUP=16, NODE_HASH_DONE=19,
        HASH_ISSUE=22, HASH_WAIT=23, HASH_RESULT=24, ROUTE=25, TRANSFORM=26,
        EMIT=27, EMIT_NEXT=28, OUTPUT_CHUNK=29, DRAIN=30, FINISH=31, FAILED=32,
        VERIFY_INPUT=33, VERIFY_RANDOM=34, VERIFY_CHAIN_INPUT=35,
        VERIFY_CHAIN_RUN=36, VERIFY_CHAIN_ADVANCE=37
    } state_t;
    state_t state, hash_return, output_return;
    task automatic enter_state(input state_t next_state);
        begin state<=next_state;end
    endtask
    // Abort outstanding execution on an error. The autonomous wrapper halts
    // until reset; this benchmark does not track index consumption.
    // The main controller uses return-state registers and need not synthesize
    // as a one-hot FSM. Never drive asynchronous reset from its binary decode.
    (* dont_touch="yes" *) logic abort_execution;
    wire execution_rst=rst || abort_execution;
    logic [1:0] operation;
    wire verifying = operation==2;
    state_t verify_return;
    logic verify_lane;
    // Boot loader owns immutable Job registers for this reset epoch.
    wire [255:0] secret_seed=job_secret_seed, secret_prf=job_secret_prf;
    wire [255:0] public_seed=job_public_seed, randomizer=job_randomizer;
    logic [MAX_MESSAGE_BYTES*8-1:0] message_buffer;
    logic [6:0] message_length, message_received;
    logic [W-1:0] value [0:3];
    logic [FORS_DIGEST_BITS-W-1:0] fors_digest_tail;
    logic [63:0] scalar_tree;
    logic [9:0] scalar_leaf;
    logic [11:0] checksum;
    logic [6:0] transform_index;
    logic [4:0] layer;
    logic [5:0] group_index;
    logic [3:0] macro_op, macro_flags;
    logic [4:0] macro_desc, macro_route;
    logic [63:0] saved_descriptor, saved_chain_descriptor;
    wire [63:0] descriptor = saved_descriptor;
    wire [63:0] route_descriptor = descriptors[1];

    logic [6:0] micro_pc,return_pc;
    logic return_valid;
    logic [31:0] scalar_temp;
    wire [7:0] uop=program_data[63:56], ua=program_data[55:48], ub=program_data[47:40], uc=program_data[39:32];
    wire [31:0] immediate=program_data[31:0];
    assign program_address=micro_pc;
    assign template_address=0;
    logic [4:0] chain_id, parent_id;
    wire [63:0] chain_descriptor = saved_chain_descriptor;
    logic pair_pending;
    logic [3:0] height_limit, node_level;
    logic [1:0] indexing;
    logic [13:0] target, leaf_cursor, node_index;
    logic [INDEX_BITS-1:0] chain_cursor, endpoint_count;
    logic [1:0] chain_batch_mask;
    always_comb begin
        chain_batch_mask=0;
        for(int lane_index=0; lane_index<2; lane_index=lane_index+1)
            if(indexing==1 || chain_cursor+lane_index<endpoint_count)
                chain_batch_mask[lane_index]=1;
    end
    logic [255:0] node_value;
    (* ram_style="distributed" *) logic [255:0] stack [0:15];
    (* ram_style="distributed" *) logic [255:0] auth_path [0:15];

    logic [4:0] hash_recipe_id;
    assign descriptor_addresses={state==CHAIN_SETUP ? chain_descriptor[48:44] : macro_route,hash_recipe_id[4:0]};
    always @* begin
        hash_recipe_id=macro_desc;
        case(state)
            EMIT: hash_recipe_id=emit_base+emit_cursor;
            CHAIN_SETUP: hash_recipe_id=chain_descriptor[59:52];
            VERIFY_CHAIN_RUN: hash_recipe_id=chain_descriptor[48:44];
            REDUCE_SETUP: hash_recipe_id=chain_descriptor[43:36];
            default: begin end
        endcase
    end
    logic [63:0] task_recipe, task_step;
    logic task_chain;
    logic [1:0] task_capture;
    logic [4:0] task_steps [0:1], task_capture_after [0:1];
    logic [9:0] task_leaf [0:1];
    logic [INDEX_BITS-1:0] task_a [0:1];
    logic [31:0] task_b [0:1];
    logic [255:0] task_left0;
    // Explicit node moves select operands before a HASH_PAIR instruction.
    // Both operands remain stable until that single Hash finishes.
    wire [255:0] parent_right = node_value;
    // Results stay stable for each outstanding request. Only verification
    // leaf/chain hashes take their input from these existing result registers.
    wire verify_chain_source = verifying &&
        (hash_return==VERIFY_CHAIN_ADVANCE || (hash_return==LEAF_SETUP && indexing==1));
    logic [1:0] active_mask, launch_pending, response_pending;
    wire [1:0] verify_step_mask = {chain_batch_mask[1] && task_b[1][3:0]!=15,
                                 chain_batch_mask[0] && task_b[0][3:0]!=15};
    wire [1:0] lane_ready, lane_valid, lane_error;
    wire [V-1:0] lane_value [0:1];
    wire [255:0] lane_capture [0:1];
    wire [INDEX_BITS-1:0] lane_list0 [0:1], lane_list1 [0:1];
    wire [31:0] lane_hashes [0:1], lane_permutations [0:1];
    logic [31:0] hash_base, permutation_base;
    logic [V-1:0] result [0:1];
    // ROUTE consumes these registers before it can update any source. Keep
    // the original staging cycle, but remember only the source selection.
    localparam logic [1:0] ROUTE_HASH=0, ROUTE_NODE=1, ROUTE_SAVED=2, ROUTE_EMIT=3;
    logic [1:0] route_source;
    wire [V-1:0] route_value = route_source==ROUTE_HASH ? result[0]
        : {{(V-W){1'b0}}, (route_source==ROUTE_NODE ? node_value
                        : route_source==ROUTE_SAVED ? value[3] : emit_value)};
    // The sponge retains capture through response and output stalls. No new
    // request is issued before CHAIN_OUTPUT0/1 has consumed both captures.
    wire [31:0] total_hashes = lane_hashes[0]+lane_hashes[1];
    wire [31:0] total_permutations = lane_permutations[0]+lane_permutations[1];
    assign hash_count = PROFILE_ENABLE ? total_hashes-hash_base : 32'd0;
    assign permutation_count = PROFILE_ENABLE ? total_permutations-permutation_base : 32'd0;

    logic endpoint_write0, endpoint_write1;
    logic [INDEX_BITS-1:0] endpoint_address0, endpoint_address1, endpoint_read0, endpoint_read1;
    logic [255:0] endpoint_data0, endpoint_data1;
    wire [255:0] endpoint_value0, endpoint_value1;
    // FORS roots are consumed before WOTS endpoint production begins.
    // Reuse the same parity banks; root writes use the matching physical
    // write port so the even/odd address invariants remain static.
    wire root_write=state==ROUTE && macro_route!=0 && route_descriptor[53];
    mhbs_value_store #(.WIDTH(W),.DEPTH(68),.ADDRESS_BITS(INDEX_BITS),.SINGLE_READ(1),.FIXED_BANK_WRITES(1),.SPLIT_TAIL(0)) endpoints (
        .clk, .write0(endpoint_write0), .write1(endpoint_write1),
        .address0(endpoint_address0), .address1(endpoint_address1),
        .data0(endpoint_data0), .data1(endpoint_data1),
        .read0(endpoint_read0), .read1(endpoint_read1),
        .value0(endpoint_value0), .value1(endpoint_value1)
    );
    genvar physical;
    generate for (physical=0; physical<LANES; physical=physical+1) begin: lanes
        localparam integer L=SWAP_PHYSICAL_LANES ? LANES-1-physical : physical;
        mhbs_recipe_lane #(.N(N),.DIGEST_BYTES(DIGEST_BYTES),.INDEX_BITS(INDEX_BITS),.UNROLL(UNROLL),.MAX_MESSAGE_BYTES(MAX_MESSAGE_BYTES),
            .RECIPE_MASK(L==0 ? 16'h101e : 16'h0006),
            .PROFILE_ENABLE(PROFILE_ENABLE)) lane (
            .clk,.rst(execution_rst),.node_bytes,.request_valid(state==HASH_ISSUE && launch_pending[L]),
            .request_ready(lane_ready[L]), .request_recipe(task_recipe), .request_step_recipe(task_step),
            .request_chain(task_chain), .request_steps(task_steps[L]),
            .request_capture_after(task_capture_after[L]),
            .request_capture(task_capture[L]),
            .secret_seed,.secret_prf,.public_seed,.root(value[3][W-1:0]),
            .randomizer(task_recipe[59:56]==4 ? value[0][W-1:0] : randomizer),
            .identifier(128'd0),.message_buffer,.message_length,
            .request_layer(layer),.request_tree(scalar_tree),.request_leaf(task_leaf[L]),
            .request_a(task_a[L]),.request_b(task_b[L]),.request_left(verify_chain_source ? result[L][W-1:0] : (L==0 ? task_left0 : 256'd0)),.request_right(L==0 ? parent_right : 256'd0),
            .list_index0(lane_list0[L]),.list_index1(lane_list1[L]),
            .list_data0(endpoint_value0),
            .list_data1(endpoint_value1),
            .response_valid(lane_valid[L]),.response_ready(state==HASH_WAIT && response_pending[L]),
            .response_value(lane_value[L]),.response_capture(lane_capture[L]),.error(lane_error[L]),
            .hash_count(lane_hashes[L]),.permutation_count(lane_permutations[L])
        );
    end
    endgenerate
    initial if(LANES!=2 || UNROLL!=2) $error("Production core requires K2U2");

    // Verify never emits output: share its input-node latch with the output latch.
    logic [255:0] emit_value;
    logic [5:0] emit_length;
    logic [7:0] emit_base;
    logic [3:0] emit_count, emit_cursor;
    wire [63:0] emit_descriptor = descriptors[3];
    // One node per valid cycle, low byte first. The receiver uses done to
    // delimit the job and out_bytes to discard unused high bytes.
    assign out_valid=state==OUTPUT_CHUNK;
    assign out_data=emit_value;
    assign out_bytes=emit_length;
    assign job_ready=state==IDLE;
    assign message_ready=state==MESSAGE;
    assign verify_ready=verifying && state==VERIFY_INPUT;
    assign busy=state!=IDLE;

    function automatic [31:0] be32(input [31:0] x);
        be32={x[7:0],x[15:8],x[23:16],x[31:24]};
    endfunction
    function automatic [4:0] digit(input [7:0] index);
        reg [7:0] checksum_index;
        begin
            checksum_index=index-LEN1;
            digit=0;
            if(index<LEN1) begin
                digit={1'b0,value[2][{(index[5:0]^6'd1),2'b0} +:4]};
            end else begin
                case(checksum_index)
                    0:digit={1'b0,checksum[11:8]}; 1:digit={1'b0,checksum[7:4]};
                    2:digit={1'b0,checksum[3:0]}; default:digit=0;
                endcase
            end
        end
    endfunction
    wire [FORS_DIGEST_BITS-1:0] fors_digest={fors_digest_tail,value[1]};
    wire [FORS_DIGEST_BITS-1:0] fors_bitstream;
    genvar fb;
    generate for(fb=0;fb<FORS_DIGEST_BITS;fb=fb+1) begin: fors_bit_order
        assign fors_bitstream[fb]=fors_digest[(fb/8)*8+7-(fb%8)];
    end endgenerate
    function automatic [13:0] fors_target(input [5:0] group_number);
        reg [9:0] offset;
        reg [13:0] segment;
        begin
            case(FORS_A)
                6:offset=({group_number,2'b0}+{group_number,1'b0});
                8:offset={group_number,3'b0};
                9:offset=({group_number,3'b0}+group_number);
                12:offset=({group_number,3'b0}+{group_number,2'b0});
                default:offset=({group_number,4'b0}-{group_number,1'b0});
            endcase
            segment=fors_bitstream >> offset;
            case(FORS_A)
                6:fors_target={8'd0,segment[0],segment[1],segment[2],segment[3],segment[4],segment[5]};
                8:fors_target={6'd0,segment[0],segment[1],segment[2],segment[3],segment[4],segment[5],segment[6],segment[7]};
                9:fors_target={5'd0,segment[0],segment[1],segment[2],segment[3],segment[4],segment[5],segment[6],segment[7],segment[8]};
                12:fors_target={2'd0,segment[0],segment[1],segment[2],segment[3],segment[4],segment[5],segment[6],segment[7],segment[8],segment[9],segment[10],segment[11]};
                default:fors_target={segment[0],segment[1],segment[2],segment[3],segment[4],segment[5],segment[6],segment[7],segment[8],segment[9],segment[10],segment[11],segment[12],segment[13]};
            endcase
        end
    endfunction
    function automatic [63:0] parsed_tree(input [V-1:0] digest);
        reg [63:0] bytes;
        integer j;
        begin
            if(small_signature) begin
                case(node_bytes)
                    16:bytes={digest[168 +:56],8'd0};
                    24:bytes={digest[240 +:56],8'd0};
                    default:bytes={digest[312 +:56],8'd0};
                endcase
            end else case(node_bytes)
                16:bytes=digest[200 +:64];
                24:bytes=digest[264 +:64];
                default:bytes=digest[320 +:64];
            endcase
            for(j=0;j<8;j=j+1) parsed_tree[(7-j)*8 +:8]=bytes[j*8 +:8];
            if(small_signature && node_bytes!=32) parsed_tree[63:54]=0;
            else if(!small_signature && node_bytes!=32) parsed_tree[63]=0;
        end
    endfunction
    function automatic [9:0] parsed_leaf(input [V-1:0] digest);
        begin
            if(small_signature) begin
                case(node_bytes)
                    16:parsed_leaf={1'b0,digest[224],digest[232 +:8]};
                    24:parsed_leaf={1'b0,digest[296],digest[304 +:8]};
                    default:parsed_leaf={2'b0,digest[368 +:8]};
                endcase
            end else parsed_leaf=node_bytes==16 ? {7'b0,digest[264 +:3]}
                : node_bytes==24 ? {7'b0,digest[328 +:3]} : {6'b0,digest[384 +:4]};
        end
    endfunction
    task automatic fail(input [15:0] code);
        begin error<=1; error_code<=code; abort_execution<=1; enter_state(FAILED); end
    endtask
    task automatic complete_macro;
        begin enter_state(FETCH); end
    endtask
    task automatic route_result(input [1:0] source);
        begin route_source<=source; enter_state(ROUTE); end
    endtask
    task automatic start_output(input [255:0] v, input [5:0] length, input state_t ret);
        begin emit_value<=v; emit_length<=length; output_return<=ret; enter_state(OUTPUT_CHUNK); end
    endtask
    task automatic start_hash(input [63:0] selected_recipe, input [1:0] mask, input state_t ret);
        begin
            task_recipe<=selected_recipe; active_mask<=mask;
            launch_pending<=mask; response_pending<=mask;
            hash_return<=ret; enter_state(HASH_ISSUE);
        end
    endtask
    task automatic read_verify_node(input state_t ret);
        begin
            verify_return<=ret;
            enter_state(VERIFY_INPUT);
        end
    endtask

    always_comb begin
        endpoint_write0=0; endpoint_write1=0;
        endpoint_address0=chain_cursor; endpoint_address1=chain_cursor+1'b1;
        endpoint_data0=result[0][W-1:0]; endpoint_data1=result[1][W-1:0];
        endpoint_read0=lane_list0[0]; endpoint_read1=lane_list1[0];
        if (state==CHAIN_STORE && indexing!=1) begin
            // FORS leaves go directly to the tree stack, not the list store.
            endpoint_write0=active_mask[0]; endpoint_write1=active_mask[1];
        end else if(root_write) begin
            endpoint_address0={1'b0,group_index[5:1],1'b0};
            endpoint_address1={1'b0,group_index[5:1],1'b1};
            endpoint_data0=route_value[W-1:0]; endpoint_data1=route_value[W-1:0];
            endpoint_write0=!group_index[0]; endpoint_write1=group_index[0];
        end

    end

    // Explicit STORE instructions are the only writes to node scratch memories.
    always_ff @(posedge clk) begin
        if(!execution_rst && state==FETCH && uop==15) begin
            if(ua==0) stack[scalar_c[3:0]]<=node_read(ub);
            if(ua==1) auth_path[scalar_c[3:0]]<=node_read(ub);
        end
    end

    function automatic [4:0] desc_address(input [7:0] logical_address);
        case(logical_address)
          16:desc_address=12;17:desc_address=13;
          40:desc_address=16;41:desc_address=17;42:desc_address=18;43:desc_address=19;44:desc_address=20;
          48:desc_address=21;49:desc_address=22;50:desc_address=23;
          default:desc_address=logical_address[4:0];
        endcase
    endfunction
    function automatic [31:0] scalar_read(input [7:0] a);
        case(a)
          0:scalar_read={27'd0,layer};1:scalar_read={26'd0,group_index};
          2:scalar_read={18'd0,target};3:scalar_read={18'd0,leaf_cursor};
          4:scalar_read={18'd0,node_index};5:scalar_read={28'd0,node_level};
          6:scalar_read={28'd0,height_limit};7:scalar_read={27'd0,chain_id};
          8:scalar_read={27'd0,parent_id};10:scalar_read=scalar_temp;
          11:scalar_read={28'd0,macro_flags};12:scalar_read={31'd0,pair_pending};
          13:scalar_read={30'd0,indexing};16:scalar_read={22'd0,scalar_leaf};
          17:scalar_read={18'd0,fors_target(group_index)};18:scalar_read={30'd0,operation};
          20:scalar_read={28'd0,FORS_A};21:scalar_read={28'd0,HP};
          22:scalar_read=small_signature ? (profile_code==2 ? 8 : 7) : (profile_code==2 ? 17 : 22);
          23:scalar_read=small_signature ? (profile_code==0 ? 14 : profile_code==1 ? 17 : 22) : (profile_code==2 ? 35 : 33);
          default:scalar_read=0;
        endcase
    endfunction
    wire [31:0] scalar_a=scalar_read(ua),scalar_b=scalar_read(ub),scalar_c=scalar_read(uc);
    function automatic [255:0] node_read(input [7:0] a);
        case(a)
          0:node_read=node_value;1:node_read=task_left0;2:node_read=emit_value;
          3:node_read=result[0][255:0];4:node_read=result[1][255:0];
          default:node_read=0;
        endcase
    endfunction
    task automatic scalar_write(input [7:0] a,input [31:0] v);
        case(a)
          0:layer<=v[4:0];1:group_index<=v[5:0];2:target<=v[13:0];3:leaf_cursor<=v[13:0];
          4:node_index<=v[13:0];5:node_level<=v[3:0];6:height_limit<=v[3:0];
          7:chain_id<=v[4:0];8:parent_id<=v[4:0];10:scalar_temp<=v;
          11:macro_flags<=v[3:0];12:pair_pending<=v[0];13:indexing<=v[1:0];
          default:begin end
        endcase
    endtask
    task automatic node_write(input [7:0] a,input [255:0] v);
        case(a)
          0:node_value<=v;1:task_left0<=v;2:emit_value<=v;
          default:begin end
        endcase
    endtask

    integer i;
    reg [255:0] emit_source;
    always_comb begin
        case(emit_descriptor[59:56])
            0: emit_source=secret_seed;
            1: emit_source=secret_prf;
            2: emit_source=public_seed;
            3: emit_source=value[3][W-1:0];
            4: emit_source=randomizer;
            7: emit_source=be32(emit_descriptor[31:0]);
            default: emit_source=0;
        endcase
    end

    always_ff @(posedge clk) begin
        if (rst) begin
            enter_state(IDLE); done<=0; error<=0; error_code<=0; cycles<=0;
            abort_execution<=0;
            micro_pc<=0;return_pc<=0;return_valid<=0;scalar_temp<=0;
            chain_id<=0;parent_id<=0;height_limit<=0;node_level<=0;
            target<=0;leaf_cursor<=0;node_index<=0;indexing<=0;group_index<=0;
            operation<=0; scalar_tree<=0; scalar_leaf<=0;
            verify_pass<=0;
            verify_lane<=0; verify_return<=IDLE;
            macro_op<=0; macro_desc<=0; macro_route<=0; macro_flags<=0;
            active_mask<=0; launch_pending<=0; response_pending<=0;
            task_chain<=0; task_capture<=0;
            hash_base<=0; permutation_base<=0; layer<=0;
            task_recipe<=0; task_step<=0; message_received<=0;
            pair_pending<=0;
            for(i=0;i<2;i=i+1) begin
                task_steps[i]<=0; task_capture_after[i]<=0;
                task_leaf[i]<=0; task_a[i]<=0; task_b[i]<=0;
            end
        end else begin
            done<=0; abort_execution<=0;
            if(PROFILE_ENABLE && state!=IDLE && state!=FAILED) cycles<=cycles+1;
            case(state)
                IDLE: if(job_valid) begin
                    error<=0; error_code<=0; cycles<=0; operation<=job_operation;
                    verify_pass<=0;
                    message_length<=job_message_length; message_received<=0;
                    scalar_tree<=0; scalar_leaf<=0; layer<=0; group_index<=0;
                    if(PROFILE_ENABLE) begin hash_base<=total_hashes; permutation_base<=total_permutations; end
                    value[3]<=job_public_root;
                    if(job_operation) begin
                        enter_state(MESSAGE);
                    end else begin
                        enter_state(LAUNCH);
                    end
                end
                MESSAGE: if(message_valid) begin
                    // The offline-validated private ROM stream always supplies full
                    // eight-byte beats; its last word is already zero padded.
                    message_buffer[{message_received[6:3],6'b0} +:64]<=message_data;
                    message_received<=message_received+7'd8;
                    if(message_received+7'd8>=message_length) enter_state(LAUNCH);
                end
                LAUNCH: begin micro_pc<=0;return_valid<=0;enter_state(FETCH);end
                FETCH: begin
                    micro_pc<=micro_pc+1'b1;
                    case(uop)
                      0:begin
                        if(verifying) verify_pass<=value[2][127:0]==job_public_root[127:0]
                          && (node_bytes==16 || value[2][191:128]==job_public_root[191:128])
                          && (node_bytes!=32 || value[2][255:192]==job_public_root[255:192]);
                        enter_state(DRAIN);
                      end
                      1:scalar_write(ua,immediate);
                      2:scalar_write(ua,scalar_b);
                      3:scalar_write(ua,scalar_b+immediate);
                      4:scalar_write(ua,scalar_b+scalar_c);
                      5:scalar_write(ua,scalar_b>>scalar_c);
                      6:scalar_write(ua,scalar_b<<scalar_c);
                      7:scalar_write(ua,scalar_b^immediate);
                      8:scalar_write(ua,scalar_b&immediate);
                      9:if(scalar_a==scalar_b)micro_pc<=immediate[6:0];
                      10:if(scalar_a!=scalar_b)micro_pc<=immediate[6:0];
                      11:micro_pc<=immediate[6:0];
                      12:begin return_pc<=micro_pc+1'b1;return_valid<=1;micro_pc<=immediate[6:0];end
                      13:begin micro_pc<=return_pc;return_valid<=0;end
                      14:begin
                        case(ub)
                          0:node_write(ua,stack[scalar_c[3:0]]);
                          1:node_write(ua,auth_path[scalar_c[3:0]]);
                          2:node_write(ua,value[scalar_c[1:0]]);
                          default:fail(16'h3006);
                        endcase
                      end
                      15:begin end // explicit scratch-memory write in the separate RAM process
                      16:node_write(ua,node_read(ub));
                      17:node_write(ua,256'd0);
                      18:start_output(node_read(ua),node_bytes,FETCH);
                      19:read_verify_node(FETCH); // INPUT IO, the sole external node latch
                      20,21,22,23,24:begin
                        macro_op<=uop==20 ? 1 : uop==21 ? 2 : uop==22 ? 6 : uop==23 ? 4 : 5;
                        macro_desc<=uop==21 ? desc_address({3'd0,chain_id}) : uop==22 ? parent_id : desc_address(ua);
                        macro_route<=uop==20 ? desc_address(ub) : 0;
                        task_chain<=0;task_capture<=0;
                        for(i=0;i<2;i=i+1)task_steps[i]<=0;
                        enter_state(LOAD_DESCRIPTOR);
                      end
                      25:begin macro_route<=desc_address(ua);route_result(ROUTE_NODE);end
                      default:fail(16'h3006);
                    endcase
                end
                LOAD_DESCRIPTOR: begin saved_descriptor<=descriptors[0];enter_state(DECODE);end
                DECODE: begin
                    case(macro_op)
                    1: begin
                           task_leaf[0]<=scalar_leaf;
                           task_a[0]<=0; task_b[0]<=0;
                           // The sign program starts with PRF_msg. Verification
                           // supplies that R as the first external node.
                           if(verifying && saved_descriptor[59:56]==3)
                               read_verify_node(VERIFY_RANDOM);
                           else start_hash(saved_descriptor,2'b01,HASH_RESULT);
                       end
                    2: begin
                           chain_cursor<=0;
                           endpoint_count<=descriptor[27:20];saved_chain_descriptor<=descriptor;enter_state(CHAIN_SETUP);
                       end
                    6: begin
                           task_leaf[0]<=indexing==1 ? scalar_leaf : 0;
                           task_a[0]<={3'd0,node_level};task_b[0]<=scalar_temp;
                           start_hash(saved_descriptor,2'b01,NODE_HASH_DONE);
                       end
                    4: begin checksum<=0; transform_index<=0; enter_state(TRANSFORM); end
                    5: begin emit_base<=descriptor[59:52]; emit_count<=descriptor[51:48]; emit_cursor<=0; enter_state(EMIT); end
                    default: fail(16'h3006);
                endcase
                end
                CHAIN_SETUP: begin
                    if(verifying) begin
                        task_chain<=0; task_capture<=0; task_step<=descriptors[5];
                        verify_lane<=0;
                        for(i=0;i<2;i=i+1) begin
                            task_steps[i]<=0;
                            task_leaf[i]<=scalar_leaf;
                            task_a[i]<=indexing==1 ? 0 : chain_cursor+i;
                            task_b[i]<=indexing==1 ? (group_index<<FORS_A)+target : digit(chain_cursor+i);
                        end
                        read_verify_node(VERIFY_CHAIN_INPUT);
                    end else begin
                    task_chain<=1; task_step<=descriptors[5];
                    for(i=0;i<2;i=i+1) begin
                        task_capture[i]<=(indexing==1 ? leaf_cursor+i==target : leaf_cursor==target) && macro_flags[0];
                        task_leaf[i]<=indexing==1 ? scalar_leaf : leaf_cursor;
                        task_a[i]<=indexing==1 ? 0 : chain_cursor+i;
                        task_b[i]<=indexing==1 ? (group_index<<FORS_A)+leaf_cursor+i : 0;
                        task_steps[i]<=(macro_flags[3] && leaf_cursor==target)
                            ? digit(chain_cursor+i) : chain_descriptor[19:15];
                        task_capture_after[i]<=indexing==1 ? 0 : digit(chain_cursor+i);
                    end
                    start_hash(descriptors[4],chain_batch_mask,CHAIN_STORE);
                    end
                end
                CHAIN_STORE: begin
                    task_chain<=0;
                    if(!verifying && macro_flags[0] && (leaf_cursor==target || (indexing==1 && active_mask[1] && leaf_cursor+1==target))) enter_state(CHAIN_OUTPUT0);
                    else enter_state(CHAIN_NEXT);
                end
                CHAIN_OUTPUT0: start_output(indexing==1 && active_mask[1] && target[0]
                    ? lane_capture[1] : lane_capture[0],node_bytes,
                    active_mask[1] && indexing!=1 ? CHAIN_OUTPUT1 : CHAIN_NEXT);
                CHAIN_OUTPUT1: start_output(lane_capture[1],node_bytes,CHAIN_NEXT);
                CHAIN_NEXT: begin
                    if(indexing!=1 && chain_cursor+LANES<endpoint_count) begin chain_cursor<=chain_cursor+LANES; enter_state(CHAIN_SETUP); end
                    else if(!verifying && macro_flags[3] && leaf_cursor==target) begin
                        result[0]<=0;complete_macro();
                    end else if(chain_descriptor[13:12]==0)complete_macro();
                    else enter_state(REDUCE_SETUP);
                end
                REDUCE_SETUP: begin
                    task_chain<=0; task_capture<=0; task_steps[0]<=0;
                    task_leaf[0]<=leaf_cursor; task_a[0]<=0; task_b[0]<=0;
                    start_hash(descriptors[4],2'b01,LEAF_SETUP);
                end
                LEAF_SETUP: complete_macro();
                NODE_HASH_DONE: begin node_value<=result[0][W-1:0];complete_macro();end
                HASH_ISSUE: begin
                    launch_pending<=launch_pending & ~lane_ready;
                    if((launch_pending & ~lane_ready)==0) enter_state(HASH_WAIT);
                end
                HASH_WAIT: begin
                    for(i=0;i<2;i=i+1) if(response_pending[i] && lane_valid[i]) begin
                        result[i]<=lane_value[i];
                    end
                    response_pending<=response_pending & ~lane_valid;
                    if((lane_error & response_pending & lane_valid)!=0) fail(16'h3007);
                    else if((response_pending & ~lane_valid)==0) enter_state(hash_return);
                end
                HASH_RESULT: route_result(ROUTE_HASH);
                ROUTE: begin
                    if(macro_route==0) complete_macro();
                    else begin
                        if(!route_descriptor[53]) begin
                            value[route_descriptor[57:56]]<=route_value[W-1:0];
                            if(route_descriptor[57:56]==1)
                                fors_digest_tail<=route_value[FORS_DIGEST_BITS-1:W];
                        end
                        if(route_descriptor[54]) begin
                            scalar_tree <= parsed_tree(route_value);
                            scalar_leaf <= parsed_leaf(route_value);
                        end
                        if(!verifying && route_descriptor[55]) start_output(route_value[W-1:0],node_bytes,FETCH);
                        else enter_state(FETCH);
                    end
                end
                TRANSFORM: begin
                    if(descriptor[59:56]==2) begin
                        scalar_leaf<=scalar_tree & ((1<<descriptor[43:40])-1);
                        scalar_tree<=scalar_tree>>descriptor[43:40]; complete_macro();
                    end else if(descriptor[59:56]==1) begin
                        checksum<=checksum+15-digit(transform_index);
                        if(transform_index+1==LEN1) complete_macro();
                        else transform_index<=transform_index+1'b1;
                    end else fail(16'h3006);
                end
                EMIT: begin
                    start_output(emit_source,emit_descriptor[53:48],EMIT_NEXT);
                end
                EMIT_NEXT: begin
                    if(emit_cursor+1<emit_count) begin emit_cursor<=emit_cursor+1'b1; enter_state(EMIT); end
                    else complete_macro();
                end
                VERIFY_INPUT: if(verify_valid) begin
                    emit_value<=verify_data;
                    enter_state(verify_return);
                end
                VERIFY_RANDOM: route_result(ROUTE_EMIT);
                VERIFY_CHAIN_INPUT: begin
                    // A WOTS digit of 15 already is an endpoint: zero hashes.
                    result[verify_lane]<={{(V-W){1'b0}},emit_value};
                    if(indexing==1) start_hash(task_step,2'b01,LEAF_SETUP);
                    else if(!verify_lane && chain_batch_mask[1]) begin
                        verify_lane<=1; read_verify_node(VERIFY_CHAIN_INPUT);
                    end else enter_state(VERIFY_CHAIN_RUN);
                end
                VERIFY_CHAIN_RUN: begin
                    if(verify_step_mask==0) begin
                        active_mask<=chain_batch_mask; enter_state(CHAIN_STORE);
                    end else start_hash(descriptors[0],verify_step_mask,VERIFY_CHAIN_ADVANCE);
                end
                VERIFY_CHAIN_ADVANCE: begin
                    for(i=0;i<2;i=i+1) if(active_mask[i]) begin
                        task_b[i]<={28'd0,task_b[i][3:0]+4'd1};
                    end
                    enter_state(VERIFY_CHAIN_RUN);
                end
                OUTPUT_CHUNK: enter_state(output_return);
                DRAIN: enter_state(FINISH);
                FINISH: begin
                    done<=1; enter_state(IDLE);
                end
                FAILED: enter_state(IDLE);
                default: fail(16'h3006);
            endcase
        end
    end
endmodule
`default_nettype wire
