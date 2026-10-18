`timescale 1ns/1ps
module tb_recipe;
    parameter integer UNROLL=2;
    parameter bit PROFILE=1;
    parameter [15:0] MASK=16'h101e;
    logic clk=0,rst=1,request_valid=0,response_ready=0;
    logic [5:0] node_bytes;
    wire request_ready,response_valid,error;
    logic [63:0] request_recipe;
    logic [6:0] message_length,request_a;
    logic [1:0] request_address_type;
    logic [19:0] request_leaf;
    logic [31:0] request_b,request_index;
    logic [255:0] secret_seed,secret_prf,public_seed,root,randomizer,left_value,right_value,key_value;
    logic [695:0] message_buffer;
    wire [3:0] message_word_address;
    wire [703:0] padded_message={8'd0,message_buffer};
    wire [63:0] message_word_data=message_word_address<11
        ? padded_message[message_word_address*64+:64] : 64'd0;
    wire [6:0] list_index0,list_index1;
    logic [255:0] list_data0,list_data1;
    wire [391:0] response_value;
    wire [63:0] hash_count,permutation_count;
    logic [540:0] vectors[0:1023];
    logic [391:0] retained;
    integer i,j,cycles=0,count,old_hashes,old_permutations,observed_permutations=0,old_observed;
    integer n;
    integer request_cycle,latency;
    integer accepted_requests=0,accepted_responses=0;
    integer fixed_first,fixed_next,stream_first,list_first,invalid_next,turnover_cases=0;
    integer latency_count[0:15],latency_sum[0:15],latency_min[0:15],latency_max[0:15];
    string vector_file,chain_file;
    logic [391:0] chain_expected[0:2];
    recipe #(.UNROLL(UNROLL),.RECIPE_MASK(MASK),.PROFILE_ENABLE(PROFILE)) dut (
        .clk,.rst,.node_bytes,.request_valid,.request_ready,.request_recipe,
        .secret_seed,.secret_prf,.public_seed,.root,.randomizer,
        .message_word_address,.message_word_data,.message_length,
        .request_layer(5'd9),.request_tree(64'hfedcba9876543210),
        .request_leaf,.request_address_type,.request_index,
        .request_identifier(128'hf0e0d0c0b0a090807060504030201000),.request_key(key_value),
        .request_a,.request_b,
        .request_left(left_value),.request_right(right_value),
        .list_index0,.list_index1,.list_data0,.list_data1,
        .response_valid,.response_ready,.response_value,.error,.hash_count,.permutation_count
    );
    always #5 clk=~clk;
    always @* begin
        for(integer b=0;b<32;b=b+1) begin
            list_data0[b*8+:8]=8'(32'(list_index0)*29+b*7+3);
            list_data1[b*8+:8]=8'(32'(list_index1)*29+b*7+3);
        end
    end
    always @(posedge clk) begin
        cycles<=cycles+1;
        if(cycles>1000000) $fatal(1,"single hash timeout");
        if(rst) observed_permutations<=0;
        else if(dut.sponge.state==2 && 32'(dut.sponge.round_index)+UNROLL>=24)
            observed_permutations<=observed_permutations+1;
        if(rst) begin accepted_requests<=0;accepted_responses<=0;end
        else begin
            if(request_valid && request_ready) accepted_requests<=accepted_requests+1;
            if(response_valid && response_ready) accepted_responses<=accepted_responses+1;
        end
    end
    task tick; begin @(posedge clk);#1;end endtask
    task automatic load_vector(input integer index);
        begin
            key_value=secret_prf;
            node_bytes=vectors[index][447:442];
            request_address_type=vectors[index][449:448];
            request_b=vectors[index][481:450];request_a=vectors[index][488:482];
            request_leaf=vectors[index][508:489];request_index=vectors[index][540:509];
            request_recipe=0;
            request_recipe[59:56]=vectors[index][441:438];
            request_recipe[47:40]=vectors[index][437:430];
            request_recipe[55:48]=vectors[index][429:422];
            message_length=vectors[index][421:415];
        end
    endtask
    // Both requests use the independent hashlib vector oracle. The next
    // payload is offered while the old digest is retained, then accepted on
    // exactly the edge which consumes that digest, without an idle bubble.
    task automatic turnover_pair(input integer first,input integer second,input integer stall_cycles);
        integer hashes_before,permutations_before,observed_before;
        integer requests_before,responses_before,k;
        reg [391:0] old_digest,next_digest;
        begin
            hashes_before=hash_count;permutations_before=permutation_count;
            observed_before=observed_permutations;
            requests_before=accepted_requests;responses_before=accepted_responses;
            load_vector(first);
            if(!request_ready) $fatal(1,"turnover initial request not ready first=%0d",first);
            response_ready=0;request_valid=1;tick();request_valid=0;
            while(!response_valid) tick();
            if(error || response_value!==vectors[first][391:0])
                $fatal(1,"turnover first digest mismatch first=%0d",first);
            old_digest=response_value;
            load_vector(second);request_valid=1;
            for(k=0;k<stall_cycles;k=k+1) begin
                tick();
                if(!response_valid || request_ready || response_value!==old_digest
                    || accepted_requests!=requests_before+1 || hash_count!=hashes_before+PROFILE)
                    $fatal(1,"turnover old response changed or request accepted under backpressure first=%0d next=%0d",first,second);
            end
            response_ready=1;#1;
            if(!request_ready || !response_valid || response_value!==old_digest)
                $fatal(1,"turnover failed to expose old digest and next ready on same edge first=%0d next=%0d",first,second);
            tick();response_ready=0;
            if(accepted_requests!=requests_before+2 || accepted_responses!=responses_before+1
                || hash_count!=hashes_before+(PROFILE ? (vectors[second][406] ? 1 : 2) : 0))
                $fatal(1,"turnover handshake not counted exactly once first=%0d next=%0d",first,second);
            if(!vectors[second][406] && response_valid)
                $fatal(1,"turnover exposed stale response after starting next hash first=%0d next=%0d",first,second);
            if(vectors[second][406] && (!response_valid || !error || response_value!==old_digest))
                $fatal(1,"turnover illegal next request did not return bounded error next=%0d",second);
            // Hold valid after acceptance as well: neither busy execution nor
            // response backpressure may duplicate the just accepted request.
            repeat(3) begin
                tick();
                if(request_ready || accepted_requests!=requests_before+2)
                    $fatal(1,"turnover next request accepted twice next=%0d",second);
            end
            while(!response_valid) tick();
            if(error!==vectors[second][406]
                || (!error && response_value!==vectors[second][391:0])
                || (error && response_value!==old_digest))
                $fatal(1,"turnover next digest/error mismatch first=%0d next=%0d",first,second);
            if(hash_count-hashes_before!=(PROFILE ? (vectors[second][406] ? 1 : 2) : 0)
                || permutation_count-permutations_before!=(PROFILE ? vectors[first][414:407]+vectors[second][414:407] : 0)
                || observed_permutations-observed_before!=vectors[first][414:407]+vectors[second][414:407])
                $fatal(1,"turnover Hash/permutation count mismatch first=%0d next=%0d",first,second);
            next_digest=response_value;
            repeat(3) begin
                tick();
                if(!response_valid || request_ready || response_value!==next_digest
                    || accepted_requests!=requests_before+2 || accepted_responses!=responses_before+1)
                    $fatal(1,"turnover next response changed under backpressure next=%0d",second);
            end
            request_valid=0;response_ready=1;tick();response_ready=0;
            repeat(3) begin
                tick();
                if(response_valid || !request_ready || response_value!==next_digest
                    || accepted_requests!=requests_before+2 || accepted_responses!=responses_before+2)
                    $fatal(1,"turnover response duplicated or retained digest changed next=%0d",second);
            end
            turnover_cases=turnover_cases+1;
        end
    endtask
    initial begin
        if(!$value$plusargs("VECTORS=%s",vector_file)) $fatal(1,"missing vectors");
        if(!$value$plusargs("COUNT=%d",count)) $fatal(1,"missing vector count");
        $readmemh(vector_file,vectors,0,count-1);
        if(!$value$plusargs("XMSS_CHAIN=%s",chain_file)) $fatal(1,"missing XMSS chain oracle");
        $readmemh(chain_file,chain_expected,0,2);
        for(i=0;i<16;i=i+1) begin
            latency_count[i]=0;latency_sum[i]=0;latency_min[i]=1000000;latency_max[i]=0;
        end
        for(i=0;i<32;i=i+1) begin
            secret_seed[i*8+:8]=8'(i);secret_prf[i*8+:8]=8'(32+i);
            public_seed[i*8+:8]=8'(64+i);randomizer[i*8+:8]=8'(96+i);
            root[i*8+:8]=8'(128+i);left_value[i*8+:8]=8'(160+i);right_value[i*8+:8]=8'(192+i);
        end
        for(i=0;i<87;i=i+1) message_buffer[i*8+:8]=8'(i*3+1);
        repeat(3) tick();rst=0;tick();
        for(j=0;j<count;j=j+1) begin
            load_vector(j);
            // Abort a multiblock hash, then replay it from a cleared context.
            if(j==0 && MASK[12]) begin
                node_bytes=32;request_recipe[59:56]=12;request_recipe[47:40]=128;
                request_valid=1;tick();request_valid=0;repeat(11) tick();
                rst=1;repeat(2) tick();rst=0;tick();
                load_vector(j);
            end
            old_hashes=hash_count;old_permutations=permutation_count;old_observed=observed_permutations;
            if(!request_ready) $fatal(1,"request not ready case=%0d",j);
            request_cycle=cycles;
            request_valid=1;tick();request_valid=0;
            while(!response_valid) tick();
            latency=cycles-request_cycle;
            if(!error) begin
                latency_count[request_recipe[59:56]]=latency_count[request_recipe[59:56]]+1;
                latency_sum[request_recipe[59:56]]=latency_sum[request_recipe[59:56]]+latency;
                if(latency<latency_min[request_recipe[59:56]]) latency_min[request_recipe[59:56]]=latency;
                if(latency>latency_max[request_recipe[59:56]]) latency_max[request_recipe[59:56]]=latency;
            end
            if(error!==vectors[j][406]) $fatal(1,"error case=%0d got=%0d",j,error);
            if(!error && response_value!==vectors[j][391:0]) begin
                $display("actual=%098h expected=%098h",response_value,vectors[j][391:0]);
                $fatal(1,"single hash bytes case=%0d n=%0d shape=%0d arity=%0d len=%0d",j,node_bytes,request_recipe[59:56],request_recipe[47:40],message_length);
            end
            if(hash_count-old_hashes!=(PROFILE && !error ? 1 : 0)
                || permutation_count-old_permutations!=(PROFILE ? vectors[j][414:407] : 0)
                || observed_permutations-old_observed!=vectors[j][414:407])
                $fatal(1,"single hash counts case=%0d hashes=%0d permutations=%0d observed=%0d expected=%0d",j,hash_count-old_hashes,permutation_count-old_permutations,observed_permutations-old_observed,vectors[j][414:407]);
            retained=response_value;
            request_valid=1;
            repeat(5) begin
                tick();
                if(!response_valid || request_ready || response_value!==retained)
                    $fatal(1,"response changed under backpressure case=%0d",j);
            end
            request_valid=0;response_ready=1;tick();response_ready=0;
            repeat(3) begin
                tick();
                if(response_valid || !request_ready || response_value!==retained)
                    $fatal(1,"retained result changed case=%0d",j);
            end
        end
        fixed_first=-1;fixed_next=-1;stream_first=-1;list_first=-1;invalid_next=-1;
        for(j=0;j<count;j=j+1) begin
            if(!vectors[j][406] && vectors[j][441:438]==1 && fixed_first<0) fixed_first=j;
            if(!vectors[j][406] && vectors[j][441:438]==2 && vectors[j][437:430]==2 && fixed_next<0) fixed_next=j;
            if(!vectors[j][406] && vectors[j][441:438]==4 && vectors[j][421:415]==87
                && vectors[j][414:407]>=2) stream_first=j;
            if(!vectors[j][406] && vectors[j][441:438]==12 && vectors[j][437:430]==128) list_first=j;
            if(vectors[j][406] && vectors[j][441:438]==0) invalid_next=j;
        end
        if(fixed_first<0 || fixed_next<0 || invalid_next<0) $fatal(1,"missing turnover oracle vectors");
        turnover_pair(fixed_first,fixed_next,0);
        turnover_pair(fixed_next,fixed_first,4);
        turnover_pair(fixed_first,invalid_next,2);
        if(stream_first>=0) turnover_pair(stream_first,fixed_next,0);
        if(list_first>=0) turnover_pair(list_first,fixed_first,3);
        // A chained XMSS PRF/MASK/F may hand over without an idle cycle.
        // LMS stream alignment also has to survive that same handover.
        if(MASK[5] && MASK[6] && MASK[7] && MASK[11] && MASK[15]) begin: standard_turnover
            integer xp,xf,xh,lm,ll;
            xp=-1;xf=-1;xh=-1;lm=-1;ll=-1;
            for(j=0;j<count;j=j+1) if(!vectors[j][406]) begin
                case(vectors[j][441:438])
                    5:if(vectors[j][429:422]==3) xp=j;
                    6:xf=j;
                    7:xh=j;
                    11:if(vectors[j][421:415]==87) lm=j;
                    15:ll=j;
                    default:begin end
                endcase
            end
            if(xp<0 || xf<0 || xh<0 || lm<0 || ll<0) $fatal(1,"missing standard handover vectors");
            turnover_pair(xp,xf,0);turnover_pair(xf,xp,3);
            turnover_pair(xp,xh,0);turnover_pair(lm,xp,2);
            turnover_pair(ll,lm,0);turnover_pair(xh,ll,3);
            begin: key_mask_f
                reg [255:0] saved_key,saved_mask;
                // Three successive single-Hash requests. The KEY result must
                // remain live while MASK is computed, then F consumes both.
                node_bytes=32;request_leaf=20'habcde;request_address_type=0;
                request_a=37;request_b=32'h89abcdef;request_index=32'habcde;
                request_recipe=64'h0502010000000000;request_valid=1;
                tick();request_valid=0;while(!response_valid) tick();
                if(error || response_value!==chain_expected[0]) $fatal(1,"XMSS KEY hash");
                saved_key=response_value[255:0];
                request_recipe[55:48]=3;response_ready=1;request_valid=1;#1;
                if(!request_ready) $fatal(1,"XMSS KEY to MASK handover");
                tick();response_ready=0;request_valid=0;
                while(!response_valid) tick();
                if(error || response_value!==chain_expected[1]) $fatal(1,"XMSS MASK hash");
                saved_mask=response_value[255:0];
                key_value=saved_key;left_value=left_value^saved_mask;
                request_recipe=64'h0600010000000000;response_ready=1;request_valid=1;#1;
                if(!request_ready) $fatal(1,"XMSS MASK to F handover");
                tick();response_ready=0;request_valid=0;
                while(!response_valid) tick();
                if(error || response_value!==chain_expected[2]) $fatal(1,"XMSS KEY/MASK/F result");
                response_ready=1;tick();response_ready=0;tick();
                left_value=left_value^saved_mask;key_value=secret_prf;
                $display("XMSS_KEY_MASK_F_TURNOVER_PASS");
            end
            // Discard one partially absorbed prefix and one active permutation,
            // then replay the 16-block LMS public-key list after each reset.
            for(integer cutpoint=0;cutpoint<3;cutpoint=cutpoint+1) begin
                load_vector(ll);request_valid=1;tick();request_valid=0;
                repeat(cutpoint==0 ? 3 : cutpoint==1 ? 20 : 100) tick();
                rst=1;tick();rst=0;tick();
                if(response_valid || !request_ready || hash_count!=0 || permutation_count!=0)
                    $fatal(1,"LMS reset did not discard in-flight hash");
                load_vector(ll);request_valid=1;tick();request_valid=0;
                while(!response_valid) tick();
                if(error || response_value!==vectors[ll][391:0]) $fatal(1,"LMS alignment reset replay");
                response_ready=1;tick();response_ready=0;tick();
            end
        end
        $display("SINGLE_HASH_TURNOVER_PASS cases=%0d UNROLL=%0d MASK=%04h",turnover_cases,UNROLL,MASK);
        for(i=0;i<16;i=i+1) if(latency_count[i])
            $display("SINGLE_HASH_LATENCY shape=%0d cases=%0d min=%0d max=%0d sum=%0d",i,
                latency_count[i],latency_min[i],latency_max[i],latency_sum[i]);
        $display("SINGLE_HASH_LANE_PASS cases=%0d UNROLL=%0d MASK=%04h",count,UNROLL,MASK);
        $finish;
    end
endmodule
