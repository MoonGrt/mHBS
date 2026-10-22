`timescale 1ns/1ps
// A single executable loads all six profiles and three entrypoints at runtime.
module tb;
    `include "rtl/executor/instructions.svh"
    import "DPI-C" function void micro_trace_reset();
    import "DPI-C" function void micro_trace_sample(input longint unsigned recipe,
        input int unsigned layer,input longint unsigned tree,
        input int unsigned leaf,input int unsigned a,input int unsigned b,input bit [391:0] result);
    import "DPI-C" function void micro_trace_sample_stateful(input longint unsigned recipe,
        input int unsigned layer,input longint unsigned tree,
        input int unsigned leaf,input int unsigned a,input int unsigned b,
        input bit [391:0] result,input int unsigned address_type);
    import "DPI-C" function string micro_trace_digest();
    import "DPI-C" function int unsigned micro_trace_samples();
    import "DPI-C" function void micro_owner_sample(input int unsigned owner,
        input int unsigned instance_id,input int unsigned kind,input int unsigned mode,
        input int unsigned stage,input int unsigned leaf,input int unsigned chain,
        input int unsigned level,input int unsigned step);
    import "DPI-C" function string micro_owner_digest();
    import "DPI-C" function int unsigned micro_owner_samples();
    parameter bit SWAP=0,PROFILE_ENABLE=1;
    logic clk=0,rst=1;
    always #5 clk=~clk;
    logic [63:0] program_memory[0:511],descriptor_memory[0:31];
    wire [8:0] program_address;logic [63:0] program_data;
    wire [4:0] descriptor_address;wire [63:0] descriptor_data=descriptor_memory[descriptor_address];
    always @(posedge clk)program_data<=program_memory[program_address];
    reg [255:0] job[0:9];
    wire [31:0] job_index=job[8][31:0];
    wire [127:0] job_identifier=job[9][127:0];
    wire [255:0] job_lms_c=job[3];
    wire is_stateful=descriptor_memory[1][4:0]>=8;
    wire is_xmss=descriptor_memory[1][4:0]>=8 && descriptor_memory[1][4:0]<=10;
    wire [255:0] job_secret_seed=job[0],job_secret_prf=job[1],job_public_seed=job[2],
        job_randomizer=job[3],job_public_root=job[4];
    wire [1:0] job_operation=job[5][1:0];
    wire [6:0] message_length=job[6][6:0];
    wire [5:0] node_bytes=job[7][5:0];
    logic message_valid=0,verify_valid=0;
    logic [63:0] message_data=0;logic [255:0] verify_data=0;
    wire message_ready,verify_ready,verify_pass,busy,done,keygen_done,error,out_valid;
    wire [1:0] result_kind;wire [15:0] error_code;
    wire [63:0] boot_cycles,keygen_cycles,sign_cycles,hash_count,permutation_count;
    wire [255:0] out_data;wire [5:0] out_bytes;
    common #(.SWAP_PHYSICAL_LANES(SWAP),.PROFILE_ENABLE(PROFILE_ENABLE)) dut(.*);
    reg [7:0] message_bytes[0:86],expected_bytes[0:65535];
    reg [255:0] signature[0:2047];reg [63:0] metadata[0:5];
    integer sent=0,node_sent=0,cursor=0,stall=0,replay=0,cut=0;
    longint unsigned cycles=0,waits=0;
    integer flip=-1,bad_message=0,expected=1,interrupt_run=0,chain_interrupt=0,fault=0;
    longint unsigned watchdog=500000000;
    integer tree_interrupt=0,tree_snapshot_test=0,lms_snapshot_test=0;
    integer root_bit=-1,root_noise=0,node_noise=0,tail_noise=0,bad_length=-1,bad_operation=-1;
    longint unsigned retired=0,hash_waits=0,overlap=0,round_cycles[0:1];
    longint unsigned observed_hashes=0,observed_permutations=0,operation_cycles=0;
    integer entry_pc=0;
    wire [1:0] round_active,round_end,hash_end,context_start;
    integer issue_credit[0:1];
    longint unsigned authorized_hashes=0,started_hashes=0;
    logic outstanding_issue=0,snapshot_valid=0,macro_owned=0,tree_owned=0,child_owned=0;
    longint unsigned observed_macros=0,observed_macro_cycles=0,observed_macro_hashes=0,completed_macros=0;
    longint unsigned macro_budget=0,macro_starts=0,macro_responses=0;
    integer macro_mode_snapshot=0;
    logic macro_slot_snapshot=0;
    logic [3:0] macro_digit_snapshot=0;
    logic [4:0] macro_layer_snapshot=0;
    logic [63:0] macro_tree_snapshot=0;
    logic [19:0] macro_leaf_snapshot=0;
    logic [6:0] macro_chain_snapshot=0;
    logic [63:0] macro_prf_recipe=0,macro_f_recipe=0;
    longint unsigned observed_trees=0,observed_tree_cycles=0,observed_tree_hashes=0,observed_tree_chains=0;
    longint unsigned observed_tree_input_waits=0,completed_trees=0,tree_budget=0,tree_chain_budget=0;
    longint unsigned observed_tree_child_cycles=0;
    longint unsigned tree_starts=0,tree_responses=0,tree_children=0,tree_children_done=0;
    integer tree_kind_snapshot=0,tree_mode_snapshot=0,tree_height_snapshot=0;
    logic tree_shortcut_snapshot=0;
    logic [4:0] tree_layer_snapshot=0;
    logic [63:0] tree_address_snapshot=0;
    logic [19:0] tree_leaf_snapshot=0;
    logic [5:0] tree_group_snapshot=0;
    logic [8:0] tree_offset_snapshot=0;
    logic [19:0] tree_target_snapshot=0;
    logic [255:0] tree_v_snapshot[0:3];
    logic [391:0] tree_digest_snapshot=0;
    logic [255:0] tree_digit_message_snapshot=0;
    logic [11:0] tree_checksum_snapshot=0;
    logic tree_hmsg_valid_snapshot=0,tree_digits_valid_snapshot=0;
    logic [63:0] tree_recipe_snapshot[0:10];
    integer request_owner=0,normal_instances=0;
    logic [252:0] request_snapshot;
    wire [252:0] request_context={dut.core.group_recipe,dut.core.group_tree,dut.core.group_layer,
        dut.core.group_leaf[0],dut.core.group_leaf[1],dut.core.group_a[0],dut.core.group_a[1],
        dut.core.group_b[0],dut.core.group_b[1],dut.core.group_mask};
    wire [252:0] launch_context={dut.core.physical_recipe,dut.core.group_tree,dut.core.group_layer,
        dut.core.group_leaf[0],dut.core.group_leaf[1],dut.core.group_a[0],dut.core.group_a[1],
        dut.core.physical_b_value,dut.core.physical_b_value,dut.core.physical_mask};
    logic [193:0] sf_request_snapshot=0;
    wire [193:0] sf_request_context={dut.core.lanes[0].lane.request_recipe,
        dut.core.lanes[0].lane.request_tree,dut.core.lanes[0].lane.request_layer,
        dut.core.lanes[0].lane.request_leaf,dut.core.lanes[0].lane.request_a,
        dut.core.lanes[0].lane.request_b,dut.core.lanes[0].lane.request_address_type};
    function automatic integer sf_digit(input integer index);
        if(index<64) sf_digit=integer'(dut.core.digit_message[(index^1)*4+:4]);
        else if(index==64) sf_digit=integer'(dut.core.digit_checksum[11:8]);
        else if(index==65) sf_digit=integer'(dut.core.digit_checksum[7:4]);
        else sf_digit=integer'(dut.core.digit_checksum[3:0]);
    endfunction
    // One physical Hash lane serves two logical result slots. A normal ISSUE
    // authorizes one Hash; CHAIN and TREE each own a bounded request sequence.
    // A TREE child chain remains owned by TREE and is never double counted.
    wire physical_start=dut.core.lanes[0].lane.sponge.context_valid
        && dut.core.lanes[0].lane.sponge.context_ready;
    wire active_logical=dut.core.physical_mask[1];
    assign context_start={physical_start && active_logical,physical_start && !active_logical};
    always @(posedge clk)if(!rst && !error && physical_start)begin
        if(dut.core.physical_mask!=1 && dut.core.physical_mask!=2)
            $fatal(1,"physical Hash start requires one-hot image authorization");
        if({dut.core.lanes[0].lane.request_recipe,dut.core.lanes[0].lane.request_tree,
            dut.core.lanes[0].lane.request_layer,dut.core.lanes[0].lane.request_leaf,
            dut.core.lanes[0].lane.request_a,dut.core.lanes[0].lane.request_b}
            !=={dut.core.physical_recipe,dut.core.group_tree,dut.core.group_layer,
                dut.core.group_leaf[active_logical],dut.core.group_a[active_logical],
                dut.core.physical_b_value})
            $fatal(1,"Hash launch context differs from issue snapshot logical=%0d",active_logical);
    end
    // Independent ownership scoreboard: XMSS KEY and LMS C/I share SLH's
    // inactive H_msg bank, and no stateful image can parse that bank as H_msg.
    logic sf_key_valid=0,sf_lms_inputs_valid=0;
    logic [255:0] sf_key_value=0,sf_lms_c=0;
    logic [127:0] sf_lms_i=0;
    always @(posedge clk)begin: stateful_storage_owner
        if(rst)begin
            sf_key_valid=0;sf_key_value=0;sf_lms_inputs_valid=0;sf_lms_c=0;sf_lms_i=0;
        end else if(is_stateful && !error)begin
            if(!is_xmss && sf_lms_inputs_valid)begin
                if(dut.core.accepted_identifier!==sf_lms_i
                    || dut.core.runtime_randomizer!==sf_lms_c)
                    $fatal(1,"LMS immutable C/I snapshot changed during its Job");
            end
            if(!is_xmss && dut.core.job_accept)begin
                sf_lms_c=job_randomizer;sf_lms_i=job_identifier;sf_lms_inputs_valid=1;
            end
            if(dut.core.hmsg_valid)$fatal(1,"stateful KEY scratch escaped as a parseable SLH H_msg");
            if(dut.core.retire && dut.core.opcode==OP_PARSE)
                $fatal(1,"stateful image retired forbidden SLH PARSE");
            for(integer lane=0;lane<2;lane=lane+1)
                if(dut.core.trace_hash_valid[lane] && dut.core.trace_recipe[59:56]==5
                    && dut.core.trace_recipe[55:48]==2)begin
                    sf_key_value=dut.core.trace_result[lane][255:0];sf_key_valid=1;
                end
            if(physical_start && (dut.core.lanes[0].lane.request_recipe[59:56]==6
                || dut.core.lanes[0].lane.request_recipe[59:56]==7))begin
                if(!sf_key_valid || dut.core.lanes[0].lane.request_key!==sf_key_value)
                    $fatal(1,"XMSS F/H KEY was missing or overwritten by an intervening MASK");
            end
        end
    end
    // The message store has one dedicated word port. Check accepted payload
    // bytes independently of its storage representation; padding may replace
    // the remaining bytes in the last word. No issue can modify the store.
    always @(posedge clk) begin : message_word_monitor
        integer source_word,source_byte;
        if(!rst && !error) begin
            if(dut.core.group_valid && dut.core.message_write)
                $fatal(1,"message RAM write during outstanding Hash");
            source_word=integer'(dut.core.lanes[0].lane.position[12:3])
                -integer'(dut.core.lanes[0].lane.message_prefix_words);
            if(dut.core.lanes[0].lane.state==1
                && (dut.core.group_recipe[59:56]==3 || dut.core.group_recipe[59:56]==4)
                && source_word>=0 && source_word*8<message_length) begin
                if(integer'(dut.core.message_word_address)!=source_word)
                    $fatal(1,"message word address differs from recipe offset");
                for(integer byte_index=0;byte_index<8;byte_index=byte_index+1) begin
                    source_byte=source_word*8+byte_index;
                    if(source_byte<message_length
                        && dut.core.message_word_data[byte_index*8+:8]!==message_bytes[source_byte])
                        $fatal(1,"message word payload changed byte=%0d",source_byte);
                end
            end
        end
    end
    assign round_active={1'b0,dut.core.lanes[0].lane.sponge.state==2};
    assign round_end={1'b0,round_active[0]
        && dut.core.lanes[0].lane.sponge.round_index+1>=24};
    assign hash_end={1'b0,round_end[0] && dut.core.lanes[0].lane.sponge.running_last};
    reg [31:0] rng=32'h15c0ffee;
    string image_dir,vector_dir,trace_path;integer trace_file=0;
    logic signature_read_enable=0;logic [10:0] signature_read_address=0;
    wire signature_read_valid,signature_valid,signature_error;
    wire [255:0] signature_read_data;wire [5:0] signature_node_bytes;
    wire [10:0] signature_nodes;wire [15:0] signature_length;
    signature storage (
        .clk,.rst,.finish(done && job_operation==1),.abort(error),
        .write_valid(out_valid && job_operation==1),.write_data(out_data),.write_bytes(out_bytes),
        .read_enable(signature_read_enable),.read_address(signature_read_address),
        .read_valid(signature_read_valid),.read_data(signature_read_data),
        .node_bytes(signature_node_bytes),.complete(signature_valid),.error(signature_error),
        .nodes(signature_nodes),.length(signature_length)
    );
    task tick;begin @(posedge clk);#1;end endtask
    function automatic integer digit_at(input integer chain_index);
        integer len1;
        begin
            len1=integer'(dut.core.node_bytes)*2;
            if(chain_index<len1)
                digit_at=integer'(dut.core.digit_message[(chain_index^1)*4+:4]);
            else if(chain_index==len1)digit_at=integer'(dut.core.digit_checksum[11:8]);
            else if(chain_index==len1+1)digit_at=integer'(dut.core.digit_checksum[7:4]);
            else digit_at=integer'(dut.core.digit_checksum[3:0]);
        end
    endfunction
    task begin_chain(input bit child);
        integer expected_mode,expected_leaf,expected_chain;
        begin
            if(child)begin
                if(!tree_owned || macro_owned || child_owned || snapshot_valid)
                    $fatal(1,"TREE child CHAIN overlaps another request owner");
                child_owned=1;observed_tree_chains=observed_tree_chains+1;
            end else begin
                if(outstanding_issue || macro_owned || tree_owned || child_owned || issue_credit[0] || issue_credit[1])
                    $fatal(1,"CHAIN overlaps another authorization");
                macro_owned=1;observed_macros=observed_macros+1;
            end
            macro_mode_snapshot=integer'(dut.core.chain_mode);
            macro_slot_snapshot=dut.core.chain_slot;
            macro_digit_snapshot=dut.core.chain_digit;
            macro_layer_snapshot=dut.core.ctx_layer;macro_tree_snapshot=dut.core.ctx_tree;
            macro_leaf_snapshot=child ? dut.core.group_leaf[macro_slot_snapshot]
                : dut.core.b==1 ? dut.core.ctx_leaf : dut.core.ctx_cursor[19:0];
            macro_chain_snapshot=dut.core.ctx_chain+7'(macro_slot_snapshot);
            macro_prf_recipe=child ? tree_recipe_snapshot[7] : descriptor_memory[7];
            macro_f_recipe=child ? tree_recipe_snapshot[8] : descriptor_memory[8];
            macro_budget=macro_mode_snapshot==3 ? 15-integer'(macro_digit_snapshot)
                : macro_mode_snapshot==2 ? 1+integer'(macro_digit_snapshot) : 16;
            if(integer'(dut.core.chain_expected_hashes)!=macro_budget)
                $fatal(1,"CHAIN claimed budget differs from mode/digit");
            if(!child && macro_slot_snapshot!==(dut.core.a==2 ? 1'b1 : dut.core.a==1 ? 1'b0 : dut.core.ctx_mask[1]))
                $fatal(1,"CHAIN logical slot differs from instruction selector");
            if(child)begin
                expected_chain=tree_children%integer'(dut.core.tree_chain_count);
                expected_leaf=tree_mode_snapshot==2 ? integer'(tree_leaf_snapshot)
                    : tree_children/integer'(dut.core.tree_chain_count);
                expected_mode=tree_mode_snapshot==2 ? 3 : tree_mode_snapshot==1
                    && expected_leaf==integer'(tree_target_snapshot) ? (tree_shortcut_snapshot ? 2 : 1) : 0;
                if(tree_kind_snapshot!=0 || integer'(macro_chain_snapshot)!=expected_chain
                    || integer'(macro_leaf_snapshot)!=expected_leaf || macro_mode_snapshot!=expected_mode)
                    $fatal(1,"TREE child escaped leaf/chain ordering or mode");
                tree_children=tree_children+1;
            end
            macro_starts=0;macro_responses=0;
        end
    endtask
    always @(negedge clk) begin
        if(rst)begin message_valid=0;verify_valid=0;rng=32'h15c0ffee;end
        else begin
            rng={rng[30:0],rng[31]^rng[21]^rng[1]^rng[0]};
            if(!(message_valid && !message_ready))begin
                message_valid=sent<message_length && (!stall || rng[2:0]!=0);
                message_data=tail_noise ? 64'ha5a5a5a5a5a5a5a5 : 0;
                for(integer b=0;b<8;b=b+1)
                    if(sent+b<message_length)message_data[8*b+:8]=message_bytes[sent+b];
            end
            if(!(verify_valid && !verify_ready))begin
                verify_valid=job_operation==2 && node_sent<metadata[5]
                    && (!cut || node_sent<cut) && (!stall || rng[1:0]!=0);
                verify_data=signature[node_sent];
                if(node_noise)for(integer b=0;b<32;b=b+1)if(b>=node_bytes)verify_data[b*8+:8]=8'ha5;
            end
        end
    end
    always @(posedge clk)begin
        if(rst)begin
            sent=0;node_sent=0;cursor=0;cycles=0;waits=0;micro_trace_reset();
            retired=0;hash_waits=0;overlap=0;round_cycles[0]=0;round_cycles[1]=0;
            observed_hashes=0;observed_permutations=0;
            issue_credit[0]=0;issue_credit[1]=0;authorized_hashes=0;started_hashes=0;
            outstanding_issue=0;snapshot_valid=0;request_snapshot=0;macro_owned=0;
            tree_owned=0;child_owned=0;request_owner=0;normal_instances=0;
            observed_macros=0;observed_macro_cycles=0;observed_macro_hashes=0;completed_macros=0;
            macro_budget=0;macro_starts=0;macro_responses=0;
            observed_trees=0;observed_tree_cycles=0;observed_tree_hashes=0;observed_tree_chains=0;
            observed_tree_input_waits=0;completed_trees=0;tree_budget=0;tree_chain_budget=0;
            observed_tree_child_cycles=0;
            tree_starts=0;tree_responses=0;tree_children=0;tree_children_done=0;
        end
        else begin
            if(!is_stateful)begin
            if(error)begin
                if(physical_start || (|dut.core.trace_hash_valid) || dut.core.chain_issue || dut.core.tree_issue
                    || out_valid || verify_ready)
                    $fatal(1,"Hash work continued after architectural fault");
                issue_credit[0]=0;issue_credit[1]=0;outstanding_issue=0;snapshot_valid=0;macro_owned=0;
                tree_owned=0;child_owned=0;
            end else begin
                if(dut.core.chain_active && !dut.core.tree_active)observed_macro_cycles=observed_macro_cycles+1;
                if(dut.core.tree_active)observed_tree_cycles=observed_tree_cycles+1;
                if(dut.core.tree_active && dut.core.chain_active)observed_tree_child_cycles=observed_tree_child_cycles+1;
                if(dut.core.tree_active && verify_ready && !verify_valid)
                    observed_tree_input_waits=observed_tree_input_waits+1;
                if(dut.core.retire && dut.core.opcode==OP_HASH)begin
                    if(outstanding_issue || macro_owned || tree_owned)$fatal(1,"nested Hash authorization");
                    if(dut.core.issue_mask!=1 && dut.core.issue_mask!=2)
                        $fatal(1,"K1U1 image retired a non-one-hot ISSUE");
                    outstanding_issue=1;
                    normal_instances=normal_instances+1;
                    for(integer lane=0;lane<2;lane=lane+1)if(dut.core.issue_mask[lane])begin
                        if(issue_credit[lane])$fatal(1,"unconsumed Hash authorization lane=%0d",lane);
                        issue_credit[lane]=1;authorized_hashes=authorized_hashes+1;
                    end
                end
                if(dut.core.tree_start)begin : tree_start_monitor
                    integer leaves,chains,digit_sum;
                    if(outstanding_issue || macro_owned || tree_owned || child_owned || snapshot_valid)
                        $fatal(1,"TREE overlaps another request owner");
                    tree_owned=1;observed_trees=observed_trees+1;
                    tree_kind_snapshot=integer'(dut.core.tree_kind);
                    tree_mode_snapshot=integer'(dut.core.tree_mode);
                    tree_height_snapshot=integer'(dut.core.tree_height);
                    tree_shortcut_snapshot=dut.core.tree_flags[0];
                    tree_layer_snapshot=dut.core.ctx_layer;tree_address_snapshot=dut.core.ctx_tree;
                    tree_leaf_snapshot=dut.core.ctx_leaf;tree_group_snapshot=dut.core.ctx_group;
                    tree_offset_snapshot=dut.core.ctx_fors_offset;tree_target_snapshot=dut.core.ctx_target;
                    for(integer i=0;i<4;i=i+1)tree_v_snapshot[i]=dut.core.node[i];
                    tree_digest_snapshot=dut.core.hmsg_digest;
                    tree_digit_message_snapshot=dut.core.digit_message;tree_checksum_snapshot=dut.core.digit_checksum;
                    tree_hmsg_valid_snapshot=dut.core.hmsg_valid;tree_digits_valid_snapshot=dut.core.digits_valid;
                    for(integer i=0;i<=10;i=i+1)tree_recipe_snapshot[i]=descriptor_memory[i];
                    leaves=1<<tree_height_snapshot;chains=integer'(dut.core.tree_chain_count);digit_sum=0;
                    for(integer i=0;i<chains;i=i+1)digit_sum=digit_sum+digit_at(i);
                    if(tree_kind_snapshot==1)begin
                        tree_budget=tree_mode_snapshot==1 ? 3*leaves-1 : tree_height_snapshot+1;
                        tree_chain_budget=0;
                    end else begin
                        tree_chain_budget=(tree_mode_snapshot==2 ? 1 : leaves)*chains;
                        if(tree_mode_snapshot==2)tree_budget=15*chains-digit_sum+1+tree_height_snapshot;
                        else if(tree_shortcut_snapshot)tree_budget=(leaves-1)*(16*chains+1)
                            +digit_sum+chains+leaves-1-tree_height_snapshot;
                        else tree_budget=leaves*(16*chains+1)+leaves-1;
                    end
                    tree_starts=0;tree_responses=0;tree_children=0;tree_children_done=0;
                end
                if(dut.core.chain_start)begin_chain(0);
                if(dut.core.chain_child_start)begin_chain(1);
                if(snapshot_valid && request_context!==request_snapshot)
                    $fatal(1,"single-Hash request snapshot changed while outstanding");
                if(dut.core.group_valid && !outstanding_issue && !macro_owned && !tree_owned)
                    $fatal(1,"Hash group without explicit instruction ownership");
                if(dut.core.chain_issue && (!(macro_owned || child_owned) || !physical_start))
                    $fatal(1,"CHAIN issue signal without owned physical Hash start");
                if(dut.core.tree_issue && (!tree_owned || !physical_start))
                    $fatal(1,"TREE issue signal without owned physical Hash start");
                // Drain the owned response before accepting its successor on
                // the same edge. The old snapshot and trace remain intact.
                for(integer lane=0;lane<2;lane=lane+1)if(dut.core.trace_hash_valid[lane])begin
                    if(!snapshot_valid)$fatal(1,"Hash trace without a unique outstanding physical request");
                    if(integer'(dut.core.trace_owner)!=request_owner)
                        $fatal(1,"response owner differs from accepted physical request");
                    if(tree_owned)begin
                        if(tree_responses>=tree_starts)$fatal(1,"TREE response without a request");
                        tree_responses=tree_responses+1;
                    end
                    if(macro_owned || child_owned)begin
                        if(lane!=integer'(macro_slot_snapshot) || macro_responses>=macro_starts)
                            $fatal(1,"CHAIN response has no matching owned request");
                        macro_responses=macro_responses+1;
                    end
                    snapshot_valid=0;
                end
                for(integer lane=0;lane<2;lane=lane+1)if(context_start[lane])begin
                    if(snapshot_valid)$fatal(1,"another physical Hash before its predecessor completed");
                    if(tree_owned)begin : tree_request_monitor
                        integer recipe_id;
                        if(!dut.core.tree_issue || tree_starts>=tree_budget)
                            $fatal(1,"TREE physical Hash exceeds its owner budget");
                        if(dut.core.group_layer!==tree_layer_snapshot || dut.core.group_tree!==tree_address_snapshot)
                            $fatal(1,"TREE physical Hash escaped captured layer/tree");
                        case(integer'(dut.core.trace_tree_stage))
                            0:recipe_id=7;1:recipe_id=8;2:recipe_id=9;3:recipe_id=10;
                            4:recipe_id=4;5:recipe_id=5;6:recipe_id=6;
                            default:$fatal(1,"unknown TREE Hash stage");
                        endcase
                        if(dut.core.physical_recipe!==tree_recipe_snapshot[recipe_id])
                            $fatal(1,"TREE Hash recipe differs from its preflight snapshot");
                        if((tree_kind_snapshot==0 && recipe_id<7) || (tree_kind_snapshot==1 && recipe_id>6))
                            $fatal(1,"TREE Hash escaped its HT/FORS kind");
                        if(tree_kind_snapshot==1 && dut.core.group_leaf[lane]!==tree_leaf_snapshot)
                            $fatal(1,"FORS Hash escaped captured leaf address");
                        tree_starts=tree_starts+1;observed_tree_hashes=observed_tree_hashes+1;
                        authorized_hashes=authorized_hashes+1;request_owner=2;
                        micro_owner_sample(2,observed_trees,tree_kind_snapshot,tree_mode_snapshot,
                            integer'(dut.core.trace_tree_stage),integer'(dut.core.ctx_cursor),
                            integer'(dut.core.ctx_chain),integer'(dut.core.ctx_level),dut.core.physical_b_value);
                    end
                    if(macro_owned || child_owned)begin
                        if(!dut.core.chain_issue || lane!=integer'(macro_slot_snapshot) || macro_starts>=macro_budget)
                            $fatal(1,"CHAIN physical Hash exceeds owner/slot/budget");
                        if(dut.core.group_layer!==macro_layer_snapshot || dut.core.group_tree!==macro_tree_snapshot
                            || dut.core.group_leaf[lane]!==macro_leaf_snapshot || dut.core.group_a[lane]!==macro_chain_snapshot)
                            $fatal(1,"CHAIN Hash escaped its captured HBS address");
                        if(macro_mode_snapshot!=3 && macro_starts==0)begin
                            if(dut.core.chain_hash_stage || dut.core.chain_reissue
                                || dut.core.physical_recipe!==macro_prf_recipe || dut.core.physical_b_value!=0)
                                $fatal(1,"CHAIN must begin with exactly one address PRF");
                        end else begin
                            if(!(dut.core.chain_hash_stage || dut.core.chain_reissue)
                                || dut.core.physical_recipe!==macro_f_recipe
                                || integer'(dut.core.physical_b_value)!=(macro_mode_snapshot==3
                                    ? integer'(macro_digit_snapshot)+macro_starts : macro_starts-1))
                                $fatal(1,"CHAIN F step/recipe differs from bounded owner sequence");
                        end
                        macro_starts=macro_starts+1;
                        if(macro_owned)begin
                            observed_macro_hashes=observed_macro_hashes+1;authorized_hashes=authorized_hashes+1;
                            request_owner=1;
                            micro_owner_sample(1,observed_macros,0,macro_mode_snapshot,
                                integer'(dut.core.chain_hash_stage || dut.core.chain_reissue),
                                integer'(macro_leaf_snapshot),integer'(macro_chain_snapshot),0,dut.core.physical_b_value);
                        end
                    end else if(!tree_owned)begin
                        if(!outstanding_issue || issue_credit[lane]!=1)
                            $fatal(1,"Hash start without image authorization lane=%0d",lane);
                        issue_credit[lane]=0;
                        request_owner=0;
                        micro_owner_sample(0,normal_instances,0,0,0,integer'(dut.core.group_leaf[lane]),
                            integer'(dut.core.group_a[lane]),0,dut.core.physical_b_value);
                    end
                    started_hashes=started_hashes+1;
                    request_snapshot=launch_context;snapshot_valid=1;
                end
                if(dut.core.chain_complete)begin
                    if(!macro_owned || macro_starts!=macro_budget || macro_responses!=macro_budget || snapshot_valid)
                        $fatal(1,"CHAIN retired without its exact bounded Hash sequence");
                    if(!dut.core.retire || dut.core.opcode!=OP_CHAIN)
                        $fatal(1,"CHAIN completion did not retire its owning instruction");
                    macro_owned=0;completed_macros=completed_macros+1;
                end
                if(dut.core.chain_child_complete)begin
                    if(!tree_owned || !child_owned || macro_starts!=macro_budget
                        || macro_responses!=macro_budget || snapshot_valid || dut.core.retire)
                        $fatal(1,"TREE child CHAIN retired PC or missed its bounded Hash sequence");
                    child_owned=0;tree_children_done=tree_children_done+1;
                end
                if(dut.core.tree_complete)begin
                    if(!tree_owned || child_owned || snapshot_valid || tree_starts!=tree_budget
                        || tree_responses!=tree_budget || tree_children!=tree_chain_budget
                        || tree_children_done!=tree_chain_budget || !dut.core.retire || dut.core.opcode!=OP_TREE)
                        $fatal(1,"TREE retired without exact Hash/child budget and unique owner");
                    if(dut.core.ctx_layer!==tree_layer_snapshot || dut.core.ctx_tree!==tree_address_snapshot
                        || dut.core.ctx_leaf!==tree_leaf_snapshot || dut.core.ctx_group!==tree_group_snapshot
                        || dut.core.ctx_target!==tree_target_snapshot || dut.core.ctx_fors_offset!==tree_offset_snapshot
                        || dut.core.hmsg_digest!==tree_digest_snapshot || dut.core.hmsg_valid!==tree_hmsg_valid_snapshot
                        || dut.core.digit_message!==tree_digit_message_snapshot || dut.core.digit_checksum!==tree_checksum_snapshot
                        || dut.core.digits_valid!==tree_digits_valid_snapshot)
                        $fatal(1,"TREE changed its preserved outer context/digest/digits");
                    for(integer i=0;i<4;i=i+1)if(dut.core.node[i]!==tree_v_snapshot[i])
                        $fatal(1,"TREE changed preserved V object %0d",i);
                    if({dut.core.ctx_cursor,dut.core.ctx_chain,dut.core.ctx_step[0],dut.core.ctx_step[1],
                        dut.core.ctx_digit[0],dut.core.ctx_digit[1],dut.core.ctx_height,dut.core.ctx_level,
                        dut.core.ctx_index,dut.core.ctx_path,dut.core.ctx_fors_base,dut.core.ctx_reduce_index,
                        dut.core.ctx_reduce_span,dut.core.ctx_digit_valid}!='0 || dut.core.ctx_mask!=1)
                        $fatal(1,"TREE retired with live working metadata");
                    for(integer i=0;i<2;i=i+1)if({dut.core.addr_leaf[i],dut.core.addr_a[i],dut.core.addr_b[i]}!='0)
                        $fatal(1,"TREE retired with a live ADRS");
                    tree_owned=0;completed_trees=completed_trees+1;
                end
                if(tree_owned && dut.core.retire && !dut.core.tree_complete)
                    $fatal(1,"instruction retired while TREE owned execution");
                if(dut.core.retire && dut.core.opcode==OP_WAIT)begin
                    if(!outstanding_issue || issue_credit[0] || issue_credit[1] || snapshot_valid)
                        $fatal(1,"WAIT without exactly one completed Hash per active lane");
                    outstanding_issue=0;
                end
            end
            end else begin
            if(error)begin
                if(physical_start || (|dut.core.trace_hash_valid) || dut.core.chain_issue || dut.core.tree_issue)
                    $fatal(1,"stateful Hash activity after architectural fault");
                outstanding_issue=0;macro_owned=0;snapshot_valid=0;
                issue_credit[0]=0;issue_credit[1]=0;tree_owned=0;child_owned=0;
            end else begin
                if(dut.core.chain_active && !dut.core.tree_active) observed_macro_cycles=observed_macro_cycles+1;
                if(dut.core.tree_active)observed_tree_cycles=observed_tree_cycles+1;
                if(dut.core.tree_active && dut.core.chain_active)observed_tree_child_cycles=observed_tree_child_cycles+1;
                if(dut.core.tree_active && verify_ready && !verify_valid)observed_tree_input_waits=observed_tree_input_waits+1;
                if(dut.core.retire && dut.core.opcode==OP_HASH)begin
                    if(outstanding_issue || macro_owned || tree_owned || snapshot_valid)
                        $fatal(1,"stateful ISSUE overlaps another owner");
                    if(dut.core.issue_mask!=1 && dut.core.issue_mask!=2)
                        $fatal(1,"stateful ISSUE requires one logical slot");
                    outstanding_issue=1;
                    for(integer lane=0;lane<2;lane=lane+1)if(dut.core.issue_mask[lane])begin
                        issue_credit[lane]=1;authorized_hashes=authorized_hashes+1;
                    end
                end
                if(dut.core.tree_start)begin: sf_tree_start
                    longint unsigned leaves,chain_work,leaf_work;
                    integer digit_sum;
                    if(outstanding_issue || macro_owned || tree_owned || child_owned || snapshot_valid)
                        $fatal(1,"stateful TREE overlaps another owner");
                    tree_owned=1;observed_trees=observed_trees+1;
                    tree_height_snapshot=integer'(dut.core.tree_height);
                    tree_mode_snapshot=integer'(dut.core.tree_mode);tree_kind_snapshot=0;
                    leaves=64'd1<<tree_height_snapshot;digit_sum=0;
                    for(integer i=0;i<67;i=i+1)digit_sum=digit_sum+sf_digit(i);
                    if(tree_mode_snapshot==2)begin
                        tree_chain_budget=67;
                        chain_work=(is_xmss ? 3 : 1)*(15*67-digit_sum);
                        tree_budget=chain_work+(is_xmss ? 4*66+4*tree_height_snapshot : 2+tree_height_snapshot);
                    end else begin
                        tree_chain_budget=leaves*67;
                        leaf_work=is_xmss ? 67*46+4*66 : 67*16+2;
                        tree_budget=leaves*leaf_work+(leaves-1)*(is_xmss ? 4 : 1);
                    end
                    tree_starts=0;tree_responses=0;tree_children=0;tree_children_done=0;
                end
                if(dut.core.chain_start || dut.core.chain_child_start)begin: sf_chain_start
                    integer steps;
                    if(macro_owned || child_owned || snapshot_valid || outstanding_issue)
                        $fatal(1,"stateful CHAIN overlaps another request owner");
                    if(dut.core.chain_start)begin macro_owned=1;observed_macros=observed_macros+1;end
                    if(dut.core.chain_child_start)begin
                        if(!tree_owned)$fatal(1,"stateful child CHAIN has no TREE owner");
                        child_owned=1;tree_children=tree_children+1;observed_tree_chains=observed_tree_chains+1;
                    end
                    macro_mode_snapshot=integer'(dut.core.chain_mode);
                    macro_slot_snapshot=dut.core.chain_slot;macro_digit_snapshot=dut.core.chain_digit;
                    macro_layer_snapshot=dut.core.group_layer;macro_tree_snapshot=dut.core.group_tree;
                    macro_leaf_snapshot=dut.core.group_leaf[macro_slot_snapshot];
                    macro_chain_snapshot=dut.core.group_a[macro_slot_snapshot];
                    steps=macro_mode_snapshot==3 ? 15-integer'(macro_digit_snapshot)
                        : macro_mode_snapshot==2 ? integer'(macro_digit_snapshot) : 15;
                    macro_budget=(macro_mode_snapshot==3 ? 0 : 1)+(is_xmss ? 3 : 1)*steps;
                    if(dut.core.chain_expected_hashes!=macro_budget)
                        $fatal(1,"stateful CHAIN independent Hash budget differs");
                    macro_starts=0;macro_responses=0;
                end
                if(snapshot_valid && !(|dut.core.trace_hash_valid) && sf_request_context!==sf_request_snapshot)
                    $fatal(1,"stateful outstanding physical request address changed old=%h new=%h trace=%0b phase=%0d",sf_request_snapshot,sf_request_context,|dut.core.trace_hash_valid,dut.core.phase);
                // Retire the predecessor before accepting a same-edge successor.
                for(integer lane=0;lane<2;lane=lane+1)if(dut.core.trace_hash_valid[lane])begin
                    if(!snapshot_valid)$fatal(1,"stateful Hash completion has no accepted request");
                    snapshot_valid=0;
                    if(tree_owned)begin
                        if(dut.core.trace_owner!=2 || tree_responses>=tree_starts)$fatal(1,"stateful TREE completion owner mismatch");
                        tree_responses=tree_responses+1;
                    end
                    if(macro_owned || child_owned)begin
                        if(lane!=integer'(macro_slot_snapshot) || macro_responses>=macro_starts)
                            $fatal(1,"stateful CHAIN response owner mismatch");
                        macro_responses=macro_responses+1;
                    end
                end
                for(integer lane=0;lane<2;lane=lane+1)if(context_start[lane])begin: sf_launch
                    integer work_index,step,kind;
                    if(snapshot_valid)$fatal(1,"stateful physical Hash lane accepted two tasks");
                    if(tree_owned)begin
                        if(!dut.core.tree_issue || tree_starts>=tree_budget)$fatal(1,"stateful TREE Hash budget exceeded");
                        tree_starts=tree_starts+1;observed_tree_hashes=observed_tree_hashes+1;authorized_hashes=authorized_hashes+1;
                    end
                    if(macro_owned || child_owned)begin
                        if(!dut.core.chain_issue || lane!=integer'(macro_slot_snapshot) || macro_starts>=macro_budget)
                            $fatal(1,"stateful CHAIN Hash exceeds bounded authorization");
                        work_index=integer'(macro_starts)-(macro_mode_snapshot==3 ? 0 : 1);
                        if(work_index<0)begin
                            if(dut.core.physical_recipe[59:56]!=(is_xmss ? 5 : 9)
                                || dut.core.physical_recipe[55:48]!=0)
                                $fatal(1,"stateful CHAIN does not start with its SECRET Hash");
                        end else begin
                            step=(macro_mode_snapshot==3 ? integer'(macro_digit_snapshot) : 0)
                                +(is_xmss ? work_index/3 : work_index);
                            kind=is_xmss ? work_index%3 : 2;
                            if(dut.core.physical_b_value!=step
                                || dut.core.physical_recipe[59:56]!=(is_xmss ? (kind==2 ? 6 : 5) : 10)
                                || dut.core.physical_recipe[55:48]!=(is_xmss && kind!=2 ? kind+2 : 0))
                                $fatal(1,"stateful CHAIN KEY/MASK/F sequence or step differs");
                        end
                        if(dut.core.group_layer!==macro_layer_snapshot || dut.core.group_tree!==macro_tree_snapshot
                            || dut.core.group_leaf[lane]!==macro_leaf_snapshot || dut.core.group_a[lane]!==macro_chain_snapshot)
                            $fatal(1,"stateful CHAIN escaped captured ADRS");
                        macro_starts=macro_starts+1;
                        if(macro_owned)begin
                            observed_macro_hashes=observed_macro_hashes+1;authorized_hashes=authorized_hashes+1;
                        end
                    end else if(!tree_owned)begin
                        if(!outstanding_issue || issue_credit[lane]!=1)
                            $fatal(1,"stateful Hash lacks one explicit ISSUE authorization");
                        issue_credit[lane]=0;
                    end
                    micro_owner_sample(tree_owned ? 2 : macro_owned ? 1 : 0,
                        tree_owned ? int'(observed_trees) : macro_owned ? int'(observed_macros) : 0,
                        0,tree_owned ? tree_mode_snapshot : macro_mode_snapshot,
                        tree_owned ? int'(dut.core.trace_tree_stage) : int'(dut.core.chain_hash_kind),
                        int'(dut.core.group_leaf[lane]),int'(dut.core.group_a[lane]),
                        int'(dut.core.ctx_level),dut.core.physical_b_value);
                    started_hashes=started_hashes+1;sf_request_snapshot=sf_request_context;snapshot_valid=1;
                end
                if(dut.core.chain_complete)begin
                    if(!macro_owned || snapshot_valid || macro_starts!=macro_budget || macro_responses!=macro_budget
                        || !dut.core.retire || dut.core.opcode!=OP_CHAIN)
                        $fatal(1,"stateful CHAIN retired without exact authorized work");
                    macro_owned=0;completed_macros=completed_macros+1;
                end
                if(dut.core.chain_child_complete)begin
                    if(!tree_owned || !child_owned || snapshot_valid || macro_starts!=macro_budget || macro_responses!=macro_budget)
                        $fatal(1,"stateful TREE child retired without exact chain work");
                    child_owned=0;tree_children_done=tree_children_done+1;
                end
                if(dut.core.tree_complete)begin
                    if(!tree_owned || child_owned || snapshot_valid || tree_starts!=tree_budget || tree_responses!=tree_budget
                        || tree_children!=tree_chain_budget || tree_children_done!=tree_chain_budget
                        || !dut.core.retire || dut.core.opcode!=OP_TREE)
                        $fatal(1,"stateful TREE retired without exact bounded Hash/chain work");
                    tree_owned=0;completed_trees=completed_trees+1;
                end
                if(dut.core.retire && dut.core.opcode==OP_WAIT)begin
                    if(!outstanding_issue || snapshot_valid || issue_credit[0] || issue_credit[1])
                        $fatal(1,"stateful WAIT has no uniquely completed ISSUE");
                    outstanding_issue=0;
                end
            end
            end
            if(dut.core.retire)retired=retired+1;
            if(dut.core.ir_valid && dut.core.opcode==OP_WAIT && !dut.core.group_complete)hash_waits=hash_waits+1;
            if(dut.core.group_valid && dut.core.retire && typed_metadata(dut.core.opcode))overlap=overlap+1;
            for(integer lane=0;lane<2;lane=lane+1)begin
                if(round_active[lane])round_cycles[lane]=round_cycles[lane]+1;
                if(round_end[lane])observed_permutations=observed_permutations+1;
                if(hash_end[lane])observed_hashes=observed_hashes+1;
            end
            for(integer lane=0;lane<2;lane=lane+1)if(dut.core.trace_hash_valid[lane]) begin
                if(trace_file) $fdisplay(trace_file,"%016h %0d %016h %0d %0d %0d %0d %098h",
                    dut.core.trace_recipe,int'(dut.core.trace_layer),dut.core.trace_tree,
                    int'(dut.core.trace_leaf[lane]),int'(dut.core.trace_a[lane]),
                    dut.core.trace_b[lane],int'(dut.core.trace_address_type),dut.core.trace_result[lane]);
                if(dut.core.trace_stateful)
                    micro_trace_sample_stateful(dut.core.trace_recipe,int'(dut.core.trace_layer),dut.core.trace_tree,
                        int'(dut.core.trace_leaf[lane]),int'(dut.core.trace_a[lane]),
                        dut.core.trace_b[lane],dut.core.trace_result[lane],int'(dut.core.trace_address_type));
                else micro_trace_sample(dut.core.trace_recipe,int'(dut.core.trace_layer),dut.core.trace_tree,
                    int'(dut.core.trace_leaf[lane]),int'(dut.core.trace_a[lane]),
                    dut.core.trace_b[lane],dut.core.trace_result[lane]);
            end
            cycles=cycles+1;
            if(message_valid && message_ready)sent=sent+8;
            if(verify_valid && verify_ready)node_sent=node_sent+1;
            if((message_ready&&!message_valid)||(verify_ready&&!verify_valid))waits=waits+1;
            if(cycles>watchdog)$fatal(1,"micro timeout");
            if(error && !fault)$fatal(1,"micro error=%h cycles=%0d",error_code,cycles);
            if(out_valid)begin
                if(job_operation==2 || result_kind!=job_operation || out_bytes!=node_bytes)
                    $fatal(1,"unexpected output/width");
                for(integer b=0;b<32;b=b+1)if(b<out_bytes)begin
                    if(cursor>=metadata[0] || out_data[b*8+:8]!==expected_bytes[cursor])
                        $fatal(1,"micro output byte=%0d actual=%h expected=%h",cursor,out_data[b*8+:8],expected_bytes[cursor]);
                    cursor=cursor+1;
                end
            end
        end
    end
    initial begin
        if($value$plusargs("TRACE=%s",trace_path))trace_file=$fopen(trace_path,"w");
        if(!$value$plusargs("IMAGE=%s",image_dir))$fatal(1,"IMAGE required");
        if(!$value$plusargs("VECTOR=%s",vector_dir))$fatal(1,"VECTOR required");
        if($value$plusargs("STALL=%d",stall))begin end
        if($value$plusargs("REPLAY=%d",replay))begin end
        if($value$plusargs("CUT=%d",cut))begin end
        if($value$plusargs("FLIP=%d",flip))begin end
        if($value$plusargs("BAD_MESSAGE=%d",bad_message))begin end
        if($value$plusargs("EXPECT=%d",expected))begin end
        if($value$plusargs("INTERRUPT=%d",interrupt_run))begin end
        if($value$plusargs("CHAIN_INTERRUPT=%d",chain_interrupt))begin end
        if($value$plusargs("TREE_INTERRUPT=%d",tree_interrupt))begin end
        if($value$plusargs("TREE_SNAPSHOT=%d",tree_snapshot_test))begin end
        if($value$plusargs("LMS_SNAPSHOT=%d",lms_snapshot_test))begin end
        if($value$plusargs("FAULT=%d",fault))begin end
        if($value$plusargs("ROOT_BIT=%d",root_bit))begin end
        if($value$plusargs("ROOT_NOISE=%d",root_noise))begin end
        if($value$plusargs("NOISE=%d",node_noise))begin end
        if($value$plusargs("TAIL_NOISE=%d",tail_noise))begin end
        if($value$plusargs("BAD_LENGTH=%d",bad_length))begin end
        if($value$plusargs("BAD_OPERATION=%d",bad_operation))begin end
        if($value$plusargs("WATCHDOG=%d",watchdog))begin end
        $readmemh({image_dir,"/program.mem"},program_memory);
        $readmemh({image_dir,"/descriptor.mem"},descriptor_memory);
        for(integer i=0;i<10;i=i+1)job[i]=0;
        $readmemh({vector_dir,"/job.mem"},job);
        $readmemh({vector_dir,"/metadata.mem"},metadata);
        // Read the just-loaded array directly: continuous aliases settle in a
        // later delta cycle and cannot select files in this initial block.
        if(job[5]!=2)$readmemh({vector_dir,"/expected.mem"},expected_bytes,0,metadata[0]-1);
        if(job[6])$readmemh({vector_dir,"/message.mem"},message_bytes,0,int'(job[6])-1);
        if(job[5]==2)$readmemh({vector_dir,"/nodes.mem"},signature,0,metadata[5]-1);
        if(flip>=0)signature[flip][0]=~signature[flip][0];
        if(bad_message)message_bytes[0]=message_bytes[0]^bad_message[7:0];
        if(root_bit>=0)job[4][root_bit]=~job[4][root_bit];
        if(root_noise)for(integer b=0;b<32;b=b+1)if(b>=job[7])job[4][b*8+:8]=8'ha5;
        if(bad_length>=0)job[6]=256'(bad_length);
        if(bad_operation>=0)job[5]=256'(bad_operation);
        entry_pc=job[5]==0 ? descriptor_memory[0][26:18]
            : job[5]==1 ? descriptor_memory[0][17:9] : descriptor_memory[0][8:0];
        if(fault==1)program_memory[entry_pc]=0;
        if(fault==4)descriptor_memory[0][31:27]=5'd1;
        if(fault==9)descriptor_memory[0][31:27]=5'd2;
        if(fault==10)descriptor_memory[0][31:27]=5'd3;
        // Known opcodes with malformed private operands must fault before writeback.
        if(fault==5)program_memory[entry_pc]={OP_GROUP_INIT,8'd0,8'd1,8'd0,32'd0};
        if(fault==6)program_memory[entry_pc]={OP_LOAD,8'd0,8'd1,IDX_CHAIN0,32'd0};
        if(fault==7)begin
            program_memory[entry_pc+0]={OP_HEIGHT,8'd2,8'd0,8'd0,32'd1};
            program_memory[entry_pc+1]={OP_CURSOR_INIT,56'd0};
            program_memory[entry_pc+2]={OP_CURSOR_NEXT,24'd0,32'd2};
            program_memory[entry_pc+3]={OP_CURSOR_NEXT,24'd0,32'd1};
        end
        if(fault==8)begin
            program_memory[entry_pc+0]={OP_MASK,24'd0,32'd3};
            program_memory[entry_pc+1]={OP_HASH,8'd2,48'd0};
        end
        if(fault==11)program_memory[entry_pc]={OP_TREE,8'd2,8'd2,8'd0,32'd0};
        if(fault==12)program_memory[entry_pc]={OP_TREE,8'd1,8'd0,8'd0,32'd0};
        if(fault==13)program_memory[entry_pc]={OP_TREE,8'd0,8'd2,8'd1,32'd0};
        if(fault==14)descriptor_memory[5][59:56]=4'd3;
        if(fault==17)descriptor_memory[1][63]=1'b1;
        repeat(4)tick();rst=0;
        if(interrupt_run)begin repeat(1000)tick();rst=1;repeat(4)tick();rst=0;end
        if(chain_interrupt)begin
            while(!(dut.core.chain_active && round_active[0]
                && dut.core.lanes[0].lane.sponge.round_index>=3))tick();
            rst=1;repeat(4)tick();rst=0;
        end
        if(tree_interrupt)begin
            while(!(dut.core.tree_active && round_active[0]
                && dut.core.lanes[0].lane.sponge.round_index>=3))tick();
            rst=1;repeat(4)tick();rst=0;
        end
        if(lms_snapshot_test)begin : lms_snapshot_poison
            if(!is_stateful || is_xmss)$fatal(1,"LMS snapshot requires an LMS Job");
            while(!(dut.core.job_valid && dut.core.job_ready))tick();
            tick();
            @(negedge clk);
            job[3]=~job[3];job[9]=~job[9];
        end
        if(tree_snapshot_test)begin : tree_snapshot_poison
            logic [63:0] saved[0:14];
            // Poison the descriptor source after the HT preflight has
            // finished. Child chains must reuse the parent's snapshots.
            while(!(dut.core.tree_active && !dut.core.tree_kind && tree_owned))tick();
            @(negedge clk);
            for(integer i=4;i<=10;i=i+1)begin saved[i]=descriptor_memory[i];descriptor_memory[i]=0;end
            saved[14]=descriptor_memory[14];descriptor_memory[14]=0;
            while(!dut.core.tree_complete)tick();
            @(negedge clk);
            for(integer i=4;i<=10;i=i+1)descriptor_memory[i]=saved[i];
            descriptor_memory[14]=saved[14];
        end
        if(cut)begin
            while(node_sent<cut)tick();repeat(3000)tick();
            if(done || error || !busy || !verify_ready || verify_pass)$fatal(1,"truncated input completed");
            rst=1;repeat(4)tick();cut=0;rst=0;
        end
        if(fault)begin
            if(fault==2 || fault==16)begin
                if(fault==16)while(!(dut.core.tree_active && cursor>0 && signature_nodes>0))tick();
                while(!( |(dut.core.lane_valid & dut.core.response_pending)))tick();
                force dut.core.lanes[0].lane.error=1;
            end
            while(!error)tick();
            if((fault==2 || fault==16) && error_code!=16'h3007)$fatal(1,"lane error propagation");
            if(fault==3 && error_code!=16'h3002)$fatal(1,"invalid job input");
            if((fault==4 || fault==9 || fault==10) && error_code!=16'h3101)$fatal(1,"old ABI accepted");
            if(fault>=5 && fault!=9 && fault!=10 && fault!=16 && error_code!=16'h3006)
                $fatal(1,"typed operand/range fault");
            if(fault==17 && (authorized_hashes || started_hashes || observed_hashes || cursor || node_sent))
                $fatal(1,"reserved profile bits changed architectural data before rejection");
            if(fault==8 && (authorized_hashes || started_hashes || observed_hashes))
                $fatal(1,"paired ISSUE caused a physical Hash start before its fault");
            if(fault>=11 && fault<=14 && (observed_trees || node_sent!=(fault==14 ? 1 : 0) || cursor))
                $fatal(1,"invalid TREE preflight modified nodes or used stream I/O");
            repeat(30)begin tick();if(out_valid || busy || done)$fatal(1,"fault did not halt");end
            if(fault==16 && (signature_valid || !signature_error || !signature_nodes))
                $fatal(1,"TREE fault did not invalidate a partial signature cache");
            $display("MICRO_FAULT_PASS code=%h",error_code);$finish;
        end
        for(integer run=0;run<=replay;run=run+1)begin
            while(!done)tick();
            operation_cycles=cycles;
            if(outstanding_issue || macro_owned || tree_owned || child_owned || snapshot_valid || issue_credit[0] || issue_credit[1]
                || completed_macros!=observed_macros || micro_trace_samples()!=observed_hashes
                || completed_trees!=observed_trees || micro_owner_samples()!=observed_hashes
                || authorized_hashes!=started_hashes || started_hashes!=observed_hashes)
                $fatal(1,"Hash authorization/start/completion counts differ");
            if(cursor!=metadata[0] || error)$fatal(1,"micro output length");
            if(job_operation==2 && (verify_pass!==expected[0] || node_sent!=metadata[5]))
                $fatal(1,"verify pass=%0d expected=%0d input=%0d/%0d",verify_pass,expected,node_sent,metadata[5]);
            if(flip<0 && !bad_message && root_bit<0 &&
                (observed_hashes!=metadata[1] || observed_permutations!=metadata[2]))
                $fatal(1,"observed hash/permutation counts");
            if(PROFILE_ENABLE &&
                (hash_count!=observed_hashes || permutation_count!=observed_permutations))
                $fatal(1,"micro hash counts %0d/%0d expected %0d/%0d",hash_count,permutation_count,metadata[1],metadata[2]);
            if(PROFILE_ENABLE && (dut.core.macro_count!=observed_macros
                || dut.core.macro_busy_cycles!=observed_macro_cycles || dut.core.macro_hashes!=observed_macro_hashes))
                $fatal(1,"macro profile counters differ from independent ownership monitor");
            if(PROFILE_ENABLE && (dut.core.tree_count!=observed_trees || dut.core.tree_busy_cycles!=observed_tree_cycles
                || dut.core.tree_hashes!=observed_tree_hashes || dut.core.tree_chains!=observed_tree_chains
                || dut.core.tree_input_wait_cycles!=observed_tree_input_waits
                || dut.core.tree_child_busy_cycles!=observed_tree_child_cycles))
                $fatal(1,"TREE profile counters differ from independent ownership monitor");
            if(!PROFILE_ENABLE && {boot_cycles,keygen_cycles,sign_cycles,hash_count,permutation_count,
                dut.core.macro_count,dut.core.macro_busy_cycles,dut.core.macro_hashes,
                dut.core.tree_count,dut.core.tree_busy_cycles,dut.core.tree_hashes,dut.core.tree_chains,
                dut.core.tree_input_wait_cycles,dut.core.tree_child_busy_cycles}!=='0)
                $fatal(1,"statistics not pruned");
            if(job_operation==1)begin
                if(!signature_valid || signature_error || signature_length!=metadata[0])$fatal(1,"signature metadata");
                for(integer i=0;i<signature_nodes;i=i+1)begin
                    signature_read_enable=1;signature_read_address=11'(i);tick();
                    if(!signature_read_valid)$fatal(1,"signature read latency");
                    for(integer b=0;b<32;b=b+1)if(b<node_bytes)
                        if(signature_read_data[8*b+:8]!==expected_bytes[i*int'(node_bytes)+b])
                            $fatal(1,"signature read data");
                end
                signature_read_enable=0;
            end
            $display("MICRO_RTL_PASS operation=%0d n=%0d bytes=%0d nodes=%0d hashes=%0d permutations=%0d cycles=%0d waits=%0d swap=%0d stats=%0d",job_operation,node_bytes,cursor,node_sent,hash_count,permutation_count,operation_cycles,waits,SWAP,PROFILE_ENABLE);
            $display("MICRO_METRICS instructions=%0d hash_waits=%0d overlap=%0d lane0_round_cycles=%0d lane1_round_cycles=%0d",retired,hash_waits,overlap,round_cycles[0],round_cycles[1]);
            $display("MICRO_MACRO_METRICS macro_count=%0d macro_busy_cycles=%0d macro_hashes=%0d",
                dut.core.macro_count,dut.core.macro_busy_cycles,dut.core.macro_hashes);
            $display("MICRO_TREE_METRICS tree_count=%0d tree_busy_cycles=%0d tree_hashes=%0d tree_chains=%0d tree_input_wait_cycles=%0d tree_child_busy_cycles=%0d",
                dut.core.tree_count,dut.core.tree_busy_cycles,dut.core.tree_hashes,dut.core.tree_chains,
                dut.core.tree_input_wait_cycles,dut.core.tree_child_busy_cycles);
            $display("MICRO_OWNER_TRACE %s",micro_owner_digest());
            $display("MICRO_HASH_TRACE %s",micro_trace_digest());
            repeat(30)begin tick();if(!done || busy || out_valid || message_ready || verify_ready)$fatal(1,"completion halt");end
            if(run<replay)begin rst=1;repeat(4)tick();rst=0;end
        end
        $finish;
    end
    // The common RAM remains 1R1W. Monitor the independent owner decodes
    // instead of relying on an implicit priority between 256-bit sources.
    always @(posedge clk) if(!rst && !dut.core.error) begin
        if(!$onehot0({dut.core.tree_memory_write,dut.core.scratch_write,
            dut.core.execute && dut.core.opcode==OP_STORE,dut.core.result_write,
            dut.core.chain_private_write,dut.core.chain_capture_write,
            dut.core.chain_cap_commit,dut.core.chain_result_commit}))
            $fatal(1,"overlapping node RAM write owners");
        if(!$onehot0({dut.core.tree_write_ram,dut.core.tree_write_verify,
            dut.core.tree_write_hash,dut.core.tree_write_right,
            dut.core.tree_write_root,dut.core.tree_write_xor}))
            $fatal(1,"overlapping TREE node RAM data sources");
    end
endmodule
