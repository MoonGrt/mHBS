`timescale 1ns/1ps
module tb_hash_backend_contracts;
    `include "rtl/executor/instructions.svh"
    logic clk=0,rst=1,job_valid=0;
    logic [1:0] job_operation=0;
    logic [6:0] job_message_length=0;
    logic [63:0] image_header=64'h4842535018000000;
    logic [63:0] profile_identity=0;
    logic [31:0] job_index=0;
    logic [127:0] job_identifier=0;
    logic [63:0] profile_descriptor=64'h2342220621160310;
    wire job_ready,message_ready,verify_ready,verify_pass,busy,done,error,out_valid;
    wire [15:0] error_code;
    wire [63:0] hash_count,permutation_count,cycles;
    wire [255:0] out_data;
    wire [5:0] out_bytes;
    logic message_valid=0,verify_valid=0;
    logic [63:0] message_data=0;
    logic [255:0] verify_data=0;
    logic [255:0] job_secret_seed,job_secret_prf,job_public_seed,job_randomizer,job_public_root;
    wire [8:0] program_address;
    logic [63:0] program_data;
    wire [4:0] descriptor_address;
    logic [63:0] program_memory[0:511],descriptor_memory[0:31];
    wire [63:0] descriptor_data=descriptor_memory[descriptor_address];
    integer clocks=0,outputs=0,traces=0,p=0;
    logic [255:0] observed_output[0:15];
    logic check_outputs=0,check_tree_trace=0;
    logic check_target_window=0;
    integer target_checks=0;
    logic check_digit_snapshot=0;
    logic [3:0] expected_digits[0:66];
    integer expected_checks=0;
    executor #(.PROFILE_ENABLE(1)) dut (
        .clk,.rst,.image_header,.profile_descriptor,.profile_identity,.job_index,.job_identifier,
        .program_address,.program_data,.job_entry(9'd0),.descriptor_address,.descriptor_data,
        .job_valid,.job_ready,.job_operation,.job_message_length,
        .job_secret_seed,.job_secret_prf,.job_public_seed,.job_randomizer,.job_public_root,
        .message_valid,.message_ready,.message_data,.verify_valid,.verify_ready,.verify_data,.verify_pass,
        .out_valid,.out_data,.out_bytes,.busy,.done,.error,.error_code,.hash_count,.permutation_count,.cycles
    );
    always #5 clk=~clk;
    always @(posedge clk) if(!rst && (dut.illegal || dut.lane_fault) && dut.node_memory_write)
        $fatal(1,"fault instruction modified node memory");
    // The inactive SLH digest storage is the XMSS macro's private KEY scratch.
    // Its architectural valid bit remains clear; the key survives the MASK
    // response and the same-edge F request until that F response is consumed.
    logic stateful_key_live=0;
    logic [255:0] stateful_key_snapshot=0;
    integer stateful_key_lifetimes=0;
    always @(posedge clk) begin : stateful_digest_ownership
        if(rst || dut.job_accept)begin stateful_key_live=0;stateful_key_snapshot=0;end
        if(!rst && dut.family_stateful) begin
            if(dut.hmsg_valid || dut.hmsg_digest[391:256]!==0)
                $fatal(1,"stateful Job exposed an SLH H_msg digest");
            if(dut.execute && dut.opcode==OP_PARSE)
                $fatal(1,"stateful Job retired SLH PARSE");
            if(dut.macro_request && dut.physical_ready
                && (dut.physical_recipe[59:56]<5 || dut.physical_recipe[59:56]==12))
                $fatal(1,"stateful macro issued an SLH Hash recipe");
            if(stateful_key_live && !dut.lane_fault
                && dut.hmsg_digest[255:0]!==stateful_key_snapshot)
                $fatal(1,"XMSS KEY scratch changed before F consumed it");
            if(dut.chain_issue && dut.family_xmss && dut.physical_recipe[59:56]==6
                && (!stateful_key_live || dut.hmsg_digest[255:0]!==stateful_key_snapshot))
                $fatal(1,"XMSS F request did not own its saved KEY");
            if(dut.chain_response && dut.family_xmss && dut.chain_hash_kind==2) begin
                stateful_key_snapshot=dut.physical_value[255:0];stateful_key_live=1;
                stateful_key_lifetimes=stateful_key_lifetimes+1;
                #1;
                if(dut.hmsg_digest[255:0]!==stateful_key_snapshot)
                    $fatal(1,"XMSS KEY response did not enter scratch");
            end else if(dut.lane_fault || dut.chain_complete) begin
                stateful_key_live=0;#1;
                if(dut.hmsg_digest!==0)$fatal(1,"stateful fault/retirement retained KEY scratch");
            end else if(dut.chain_response && dut.family_xmss && dut.chain_hash_kind==1)
                stateful_key_live=0;
        end
        if(rst)begin #1;if(dut.hmsg_digest!==0)$fatal(1,"reset retained KEY scratch");end
    end
    always @(posedge clk) begin
        program_data<=program_memory[program_address];
        clocks=clocks+1;
        if(clocks>12000000) $fatal(1,"typed processor timeout");
        if(!rst) begin
            if(out_valid) begin
                if(outputs<16) observed_output[outputs]=out_data;
                if(check_outputs) begin
                    case(outputs)
                        0:if(out_data!==256'h23911c442f79bd98edc093dfde60b102) $fatal(1,"seed lane0 %h",out_data);
                        1:if(out_data!==256'h60ebf3b226a1afc637ab58779479737c) $fatal(1,"seed lane1 %h",out_data);
                        2:if(out_data!==256'h01fb02127eb78244a7c5a5d53d7a2553) $fatal(1,"single step %h",out_data);
                        default:$fatal(1,"unexpected output");
                    endcase
                    if(out_bytes!=16) $fatal(1,"node bytes");
                end
                outputs=outputs+1;
            end
            for(integer lane=0;lane<2;lane=lane+1) if(dut.trace_hash_valid[lane]) begin
                if(check_tree_trace && traces==1 && dut.trace_tree!==64'h603fc83be20079b9)
                    $fatal(1,"64-bit request snapshot %h",dut.trace_tree);
                traces=traces+1;
            end
        end
    end
    // Compare all payload/checksum digits after V2 has been overwritten.
    // Expected values use byte order and a software checksum, independently
    // of the processor's snapshot representation and checksum topology.
    always @(posedge clk) begin : digit_snapshot_monitor
        integer sample;
        if(check_digit_snapshot && !rst && dut.phase==3 && dut.ir_valid
            && dut.opcode==OP_DIGIT_LOAD && !dut.illegal) begin
            sample=dut.ctx_chain;
            #1;
            if(dut.ctx_digit[0]!==expected_digits[sample])
                $fatal(1,"digit snapshot chain=%0d actual=%0d expected=%0d",sample,dut.ctx_digit[0],expected_digits[sample]);
            expected_checks=expected_checks+1;
        end
    end
    // Independent byte/bit reference for all allowed FORS widths, including
    // the final group when a 14-bit implementation window needs padding.
    always @(posedge clk) begin : target_window_monitor
        integer reference_value,bit_address,byte_value;
        if(check_target_window && !rst && dut.phase==3 && dut.ir_valid
            && dut.opcode==OP_TARGET && dut.d==0 && !dut.illegal) begin
            if(integer'(dut.ctx_fors_offset)!=integer'(dut.ctx_group)*integer'(dut.fors_a))
                $fatal(1,"FORS offset invariant before TARGET");
            reference_value=0;
            for(integer bit_number=0;bit_number<dut.fors_a;bit_number=bit_number+1) begin
                bit_address=dut.ctx_group*dut.fors_a+bit_number;
                byte_value=integer'(dut.hmsg_digest[(bit_address/8)*8+:8]);
                reference_value=(reference_value<<1)|((byte_value>>(7-bit_address%8))&1);
            end
            #1;
            if(integer'(dut.ctx_target)!=reference_value)
                $fatal(1,"FORS target window a=%0d group=%0d actual=%0d expected=%0d",dut.fors_a,dut.ctx_group,dut.ctx_target,reference_value);
            target_checks=target_checks+1;
        end
    end
    // The dedicated FORS offset shadows GROUP*a without a multiplier in the
    // target path. Explicit metadata updates may overlap an outstanding Hash.
    always @(posedge clk) begin : fors_offset_monitor
        integer next_group,reference_offset;
        if(!rst && dut.phase==3 && dut.ir_valid && !dut.illegal
            && (dut.opcode==OP_GROUP_INIT || dut.opcode==OP_GROUP_NEXT)) begin
            next_group=dut.opcode==OP_GROUP_INIT ? 0 : integer'(dut.ctx_group)+1;
            reference_offset=next_group*integer'(dut.fors_a);
            #1;
            if(integer'(dut.ctx_group)!=next_group || integer'(dut.ctx_fors_offset)!=reference_offset)
                $fatal(1,"FORS offset group=%0d actual=%0d expected=%0d",dut.ctx_group,dut.ctx_fors_offset,reference_offset);
        end
    end
    function automatic [63:0] ins(input [7:0] op,d,a,b,input [31:0] imm);
        ins={op,d,a,b,imm};
    endfunction
    task automatic emit(input [7:0] op,d=0,a=0,b=0,input [31:0] imm=0);
        begin program_memory[p]=ins(op,d,a,b,imm);p=p+1;end
    endtask
    task tick;begin @(posedge clk);#1;end endtask
    task reset_program;
        begin
            rst=1;job_valid=0;message_valid=0;verify_valid=0;check_outputs=0;check_tree_trace=0;
            check_digit_snapshot=0;check_target_window=0;
            job_operation=0;job_message_length=0;image_header=64'h4842535018000000;
            profile_descriptor=64'h2342220621160310;profile_identity=0;job_index=0;job_identifier=0;
            repeat(2)tick();
            for(integer j=0;j<512;j=j+1) program_memory[j]=0;
            p=0;outputs=0;traces=0;
        end
    endtask
    task launch;
        begin rst=0;tick();job_valid=1;tick();job_valid=0;end
    endtask
    task finish_job;
        begin
            while(!done && !error) tick();
            if(error) $fatal(1,"unexpected typed fault %h opcode=%0d",error_code,dut.opcode);
        end
    endtask
    task expect_fault;
        begin
            while(!error && !done)tick();
            if(!error || error_code!=16'h3006 || outputs || verify_pass)
                $fatal(1,"expected atomic typed fault code=%h outputs=%0d",error_code,outputs);
            repeat(3)tick();
            if(done || out_valid) $fatal(1,"fault did not halt");
        end
    endtask
    task send_message;
        begin message_valid=1;while(!message_ready)tick();tick();message_valid=0;end
    endtask
    // hashlib.shake_256 reference values for the complete 49-byte result.
    // message[byte]=(byte*11+sample*17+3)&255; n=16+8*(sample/10),
    // recipe=3+(sample%10)/5, lengths={87,1,7,8,9}[sample%5].
    function automatic [391:0] expected_message_hash(input integer sample);
        case(sample)
            0:expected_message_hash=392'h34c9517de33027195a04643c5a9c7d1ca6f4377aeb593645222a1525b3f1a42358bd192070014207cb315131b1a94b8828;
            1:expected_message_hash=392'h734d6a362cfd90e6a0be7b485ab18faa9557382d10a6caaccca206f4e7fe11b6fa259bb6136b1aa6593d284730c0981a11;
            2:expected_message_hash=392'h8c1b9f9126efcb93fb2162256dfbb307b0a8a8ba9b2dc48a6e40d66cbc22575c4add330874a6627e84d752bff1518dc4c3;
            3:expected_message_hash=392'h70d959e8632ae98799cde8423586c6a94366dad49d5744d13c8cb12bebae44cb882707a21c7fdc2352d081429c125507fa;
            4:expected_message_hash=392'hea8d804f17e9178196b8dc45da653f66055f07213d270c55cc0016b95df8826df674d5e6ed3de0d20648d645d0cb46f554;
            5:expected_message_hash=392'h44b8b68c9fbf61d7a5b0759d26923d77d0f7163d4429313eaef7fa72a8f11cffc90b1880f200ea8ef0686c767f65b80e3a;
            6:expected_message_hash=392'h2842ab705ef89c123edc0701d59a63352f51731bf17d356ee594b34ae2a78b47635a0cb36cbb93803b83cb787c9ed392d0;
            7:expected_message_hash=392'h4396af323853d00037b312489a3af989a4b335a8e201ea71bad2d0a3e414865a1a6408324cfefed3f403e29f1daa68348a;
            8:expected_message_hash=392'h2f0982170c86eba8f379a16b6ced5f2e08832bbc4a7ec06c1442d7156e3d3efb4e40ac89e4984457acef9f4ecf3fbd19ce;
            9:expected_message_hash=392'h0c71e1a943d81bccc7200c71386ef61d8df9161c2ca19741b6ec051a16f03bcdf29eca3617fc8f6bb511597f3699ddfd35;
            10:expected_message_hash=392'hc3d7aee6506a68ad47b0f877265f43ad265622c2b495710eedc99c533274269382eb3b7693b51f83baae7f13a93229fae8;
            11:expected_message_hash=392'hd5fbe0c6ba8ffb28ac3a454812528564022e05a2dc4f86a16c9996656ff6e6d7b72ad42fcbc3f2a085731cca27b5b25183;
            12:expected_message_hash=392'h3a39655dd3fa74699cc54774921ecd487b475358b09edc6cb81ba63a14e58b72b661a1578dbf88ee5fa1778a4ebf43751e;
            13:expected_message_hash=392'hf09445487aef9e66f06f403430953f7852e2e087fbaab16efac854b3847b8f9759d3636366be702bd3e1eef36a0807ccd2;
            14:expected_message_hash=392'h018b33cde2207665e34f8b356a135d6be3604a755bc6292bcd8b498b0da83ddba0c17286f6c4af5ac34e13ef43f0cab16a;
            15:expected_message_hash=392'h13361f7f9a483267be47021cd23ddee56cd087b9dccf03a1bece26e87683c9b62e70d0401278c863b5433b18b2c54179be;
            16:expected_message_hash=392'hde49719d485c10128f750e990a04eeec1aa58df0ab860e6387fd162cbdf26b456fe34f2275c9c49963388bdd6e0617a23b;
            17:expected_message_hash=392'hbf605b37e2f7f68164ccd23fdb8a43ac0152e88706a040c01dadc4896c65b49147b2e935825b3684c3f57ef7f3e7016d5a;
            18:expected_message_hash=392'he33bfc42e2ac10f2cee58bce77e0a34da967e6762ab87cfeb0b8218b5eb127ec2fe70d2077b5663192ed4ed3fb12262145;
            19:expected_message_hash=392'hb5c9c354328b4d0d32f3558078bd3a739f94deb1d9cea1a52e383580cd0a309ea1096afa42c2d5e82cd0295459f904d9d3;
            20:expected_message_hash=392'heba9ab0ed9dcf669dd6e6b197522e6359c231ebfbfd1ebb6edac814bfb69b845f23cb49ef899f615cd8676cc38ae2e96e3;
            21:expected_message_hash=392'h4198e828c0ce4bdd002de95016ff5efefd41a05c41e6051a7e61a3f09ad3ee10e4580f86b31b929d91399aacb247e7ac89;
            22:expected_message_hash=392'ha6f4170dbe1a17dd86d8219e926c102195b2ab38f791dffb8fe7fc9fac83ecbddb43e3c2c2abff10be2af33d0789ed91b3;
            23:expected_message_hash=392'ha1a426af8fbf3e0c635ee113713417d7cdd5abdffc22119b8291cbeadd7629de2db59bfaa3103f288298a6079cea91e6bf;
            24:expected_message_hash=392'hf5c0471668a6c537043306f28c1f62e7700a8f13d3fa86479835fe8aa7f8d1e34b0243533da29b5e670da92b806725e729;
            25:expected_message_hash=392'hf59f8d7b5dd138c21e263bd026cd896f4e17fc5138c765952916e4e6148c735ae31d454004a48e32a6a961afffd1df36e4;
            26:expected_message_hash=392'hcd2c97e09f64f92363a5f8a81ba7ebf11fbbc1f89ed7a0b713c4a060e48b3722c4c69698494ca882adbad8fd32b4397cde;
            27:expected_message_hash=392'hb842499ed8b12a2b78b79c1fcdf2c9f323fa9605a140b1ea198feeaedce55f37970d2e507f052143054485ac6be4a8a6a5;
            28:expected_message_hash=392'h0dff2c9e3c1d535a6c3de8f8ee996bc1b92676f55e25eaf2740bcf78c27a5caebb57f21234554f437c49a2c68a632179c2;
            29:expected_message_hash=392'h3699f249262809afe0a15b401b876f1bc7b255e0f70982e995abc7698b27b65d786560d4f8a725490098e590a66139e567;
            default:expected_message_hash=0;
        endcase
    endfunction
    task send_pattern_message(input integer sample,length);
        begin
            for(integer offset=0;offset<length;offset=offset+8) begin
                // Deliberately dirty bytes outside the final partial word.
                message_data=64'ha5a5a5a5a5a5a5a5;
                for(integer byte_index=0;byte_index<8;byte_index=byte_index+1)
                    if(offset+byte_index<length)
                        message_data[byte_index*8+:8]=8'((offset+byte_index)*11+sample*17+3);
                repeat(offset%3)tick();send_message();
            end
            // Further input traffic must not write the dedicated RAM after
            // collection, including while a Hash waits for explicit WAIT.
            message_data=64'h5a5a5a5a5a5a5a5a;message_valid=1;
        end
    endtask
    // These checks observe instruction output, so they also run with SYNTHESIS
    // defined, where the node[] debug views deliberately have no RAM ports.
    function automatic [255:0] expected_node(input integer bytes,input [255:0] value);
        case(bytes)
            16:expected_node={128'd0,value[127:0]};
            24:expected_node={64'd0,value[191:0]};
            default:expected_node=value;
        endcase
    endfunction
    // Independent hashlib.shake_256 oracle: seed/public bytes are j/j+64.
    // Prefix uses leaf CURSOR=5; suffix uses LEAF=0 and PRF-seed bytes j+32.
    function automatic [255:0] expected_chain(input integer bytes,slot,digit,input bit suffix);
        integer key;
        begin
            key=((bytes-16)/8)*64+slot*32+integer'(suffix)*16+digit;
            case(key)
                0:expected_chain=256'h000000000000000000000000000000001f164f63a9680387b7f739c83cf17ee3;
                1:expected_chain=256'h00000000000000000000000000000000e77ee55e0cdf15d0540916fbeda48bf6;
                2:expected_chain=256'h00000000000000000000000000000000e2c7b081ca8be53242cf2ae14ef20bb2;
                3:expected_chain=256'h0000000000000000000000000000000010ceb0c19e22bc1c7ce428e8e5909453;
                4:expected_chain=256'h000000000000000000000000000000007449d2d3f72b28013d9208a7299d3f8c;
                5:expected_chain=256'h0000000000000000000000000000000090bd7ced1885e9e4acab5bf992bd84e2;
                6:expected_chain=256'h00000000000000000000000000000000c4e8c2273b8e5bf80c1cbbf1b203c542;
                7:expected_chain=256'h0000000000000000000000000000000080754f6fbcfada41469c85f69ec09d6c;
                8:expected_chain=256'h00000000000000000000000000000000826c6697612f2717c5371ab23f459ea3;
                9:expected_chain=256'h00000000000000000000000000000000b1a25a73e66e12409d586813ed3f905b;
                10:expected_chain=256'h000000000000000000000000000000006de37e0427f9d4ff9d76990b9f5e5d7c;
                11:expected_chain=256'h00000000000000000000000000000000d6e2087cb2625c295a9bad0b2748bbf8;
                12:expected_chain=256'h000000000000000000000000000000000bf622751ae9ccfd13a4cb912026f264;
                13:expected_chain=256'h00000000000000000000000000000000f62983ed8379d95344a7c775f46e686d;
                14:expected_chain=256'h00000000000000000000000000000000319904f4c99c98c5405f4e1aedf37438;
                15:expected_chain=256'h00000000000000000000000000000000c6777f21bc0fb5610775aa511f7808aa;
                16:expected_chain=256'h0000000000000000000000000000000024eb8d802e4a1fdb150dd2ec5a206db8;
                17:expected_chain=256'h00000000000000000000000000000000b8f96048b3abde47d5e36ff53658023d;
                18:expected_chain=256'h00000000000000000000000000000000fadc485a8ce44fe27f8e6e45c69e5988;
                19:expected_chain=256'h000000000000000000000000000000009cae0c53d19f9d35a198dc7bedb25263;
                20:expected_chain=256'h000000000000000000000000000000005d26b98ad48ec471ad4c4ade33fb7309;
                21:expected_chain=256'h00000000000000000000000000000000690bb08785f8238044eb727e09233af7;
                22:expected_chain=256'h00000000000000000000000000000000801e1ed5bce963f7c19ae76f9980fb8e;
                23:expected_chain=256'h00000000000000000000000000000000a2262f27aa0c2dddf38d70cdd843d777;
                24:expected_chain=256'h0000000000000000000000000000000041052a0301b8f6708a0e4bdf81809e26;
                25:expected_chain=256'h000000000000000000000000000000001b996339b640a1e326fab14a0d87558c;
                26:expected_chain=256'h000000000000000000000000000000004f1605006f9dbb5092ce403e78186e95;
                27:expected_chain=256'h000000000000000000000000000000006acae524f342e6c19d4f412686a1af08;
                28:expected_chain=256'h00000000000000000000000000000000586df6002de5ba7f6fca09d1b053bfef;
                29:expected_chain=256'h000000000000000000000000000000000378c850f0d55e55b0eb72156849f814;
                30:expected_chain=256'h00000000000000000000000000000000f8bd66755b3a966c54eed8ff36009cac;
                31:expected_chain=256'h000000000000000000000000000000002f2e2d2c2b2a29282726252423222120;
                32:expected_chain=256'h00000000000000000000000000000000c1edddcc823ccbdb1ba59bab2ddab570;
                33:expected_chain=256'h000000000000000000000000000000005e9b61f93d5484ef669e99aa24da5b52;
                34:expected_chain=256'h00000000000000000000000000000000b6c89c53994845964d17f619daf326ef;
                35:expected_chain=256'h0000000000000000000000000000000083fa938e5bc818b7113c5174e340e765;
                36:expected_chain=256'h0000000000000000000000000000000009ddfad6415fe5aed7741aa0fd8d30b2;
                37:expected_chain=256'h00000000000000000000000000000000764a4547feac009490b66b9d44aeb70c;
                38:expected_chain=256'h00000000000000000000000000000000f0ca4728d0a6f8da9a03f01f3ac8bf5c;
                39:expected_chain=256'h00000000000000000000000000000000558cf2020af07b17127d80245d6550df;
                40:expected_chain=256'h00000000000000000000000000000000bcb0182383229fbc7fe7e0ef0efab462;
                41:expected_chain=256'h00000000000000000000000000000000b5347222680a55a06c05f1aed41dd65b;
                42:expected_chain=256'h00000000000000000000000000000000a19c1009f1d362629cde51cf89e286cf;
                43:expected_chain=256'h00000000000000000000000000000000d66c774534485a030969e5abe3947460;
                44:expected_chain=256'h00000000000000000000000000000000ded7905e753e8aff2c90113a71d2a616;
                45:expected_chain=256'h00000000000000000000000000000000a63845f085ff3b1293e83b3f55c1523b;
                46:expected_chain=256'h00000000000000000000000000000000fcb725300b35f075156e85ee506fc6e3;
                47:expected_chain=256'h000000000000000000000000000000008f7de55479b1235c0243c0a78fdcd7ce;
                48:expected_chain=256'h00000000000000000000000000000000e22934e2f065834b1c7ea6e22558e29a;
                49:expected_chain=256'h00000000000000000000000000000000fbcb69438e7d537ed539238966c13bb2;
                50:expected_chain=256'h00000000000000000000000000000000a8acac9ad2ba2d9bb34c3d7b19c38e0a;
                51:expected_chain=256'h000000000000000000000000000000001762444c4f012c393ee37baf078df132;
                52:expected_chain=256'h0000000000000000000000000000000025c04b959542ed7ef800e22551e630ec;
                53:expected_chain=256'h000000000000000000000000000000002d91cbdd2483a63c920b2916430bb2b0;
                54:expected_chain=256'h00000000000000000000000000000000061d6f393a71737c47cb9f432e167551;
                55:expected_chain=256'h00000000000000000000000000000000be8321888f99873c075a2a1fb7a28488;
                56:expected_chain=256'h0000000000000000000000000000000007f3b66d6b0c7292fe9d13a167383184;
                57:expected_chain=256'h000000000000000000000000000000008778232ef9b0a9c3fcb3609e0990dca2;
                58:expected_chain=256'h00000000000000000000000000000000e1c54e0b0db1346f330ae1729a4c99e8;
                59:expected_chain=256'h00000000000000000000000000000000fda46450934bdaac63fd28c5beb2a8af;
                60:expected_chain=256'h000000000000000000000000000000008e8c48b89a4b6540cf77ec9215b4a2df;
                61:expected_chain=256'h00000000000000000000000000000000a17a3ccb6a7b2e63647f22e5b486c7ac;
                62:expected_chain=256'h00000000000000000000000000000000fa251ae1390d24b8f2c896f34e902ca0;
                63:expected_chain=256'h000000000000000000000000000000002f2e2d2c2b2a29282726252423222120;
                64:expected_chain=256'h00000000000000005ef035c7c5b2e5a8fc1bbfb70252d9591b0da16df85c571e;
                65:expected_chain=256'h0000000000000000335190549d6e8e2dafd2d6427ba8cb5acc6f6b46c197b129;
                66:expected_chain=256'h00000000000000004e94dae1d1e0688cfa39bb5222621f8c5890808a2bcf7f76;
                67:expected_chain=256'h00000000000000009a297f646c60f064520d805ee06963910061e9935b09b460;
                68:expected_chain=256'h0000000000000000d3689710af712fab8b00f5e3966261d3c0f12a23e8faa7ca;
                69:expected_chain=256'h0000000000000000f3076814738eacae3298e3127790eed5ac0f0121a9e55de3;
                70:expected_chain=256'h000000000000000087984959cf1eb0eb05b03f6184f4b42f1a8666fcd80cb927;
                71:expected_chain=256'h0000000000000000c3da239cc062b33e75fc198e1d12347c2deaa5e826467750;
                72:expected_chain=256'h0000000000000000027b1b4a5ad26956a102bdd13f695bffcf15fc0a53d55358;
                73:expected_chain=256'h0000000000000000d47b0fef8865a4637caa5bf0c1b886e784a350b04f5fdf33;
                74:expected_chain=256'h000000000000000040973f6b1a220aba452cfa6c001846de561e2bd53bc3c865;
                75:expected_chain=256'h0000000000000000245f861dc77bd0488f0efb560fe4b932633c0804df907cd0;
                76:expected_chain=256'h00000000000000008782e0ecd324a1c53f267011bfe324bcb5aec988ba68138d;
                77:expected_chain=256'h0000000000000000865edf465dfe958a1053e7a48f4c979d04841936a01521cc;
                78:expected_chain=256'h0000000000000000aa47813ee61bc4a713edf27a5517ec0ce49b88566da0da4d;
                79:expected_chain=256'h00000000000000002291a2d6683ab097dfaf7ddf27eaa3a2087c5e87a6d04bb6;
                80:expected_chain=256'h00000000000000000517c87fec57288387021b97c2705ad1924314a90ea0e261;
                81:expected_chain=256'h00000000000000009643eb3d55d9b127d2abf2ccf5432908662418d9a46c943e;
                82:expected_chain=256'h0000000000000000b1c29e9804b6b959285905bf08b1c1ae3ed70c63d70324c1;
                83:expected_chain=256'h0000000000000000a17cb1a64ff4877d5636d803e272c35d39a55968951df287;
                84:expected_chain=256'h0000000000000000877a75796a54012ee3ef6dfc30c52f73d0cd85241426a1cb;
                85:expected_chain=256'h00000000000000004d7074374a624c154e53b527466694769491710817e6c08f;
                86:expected_chain=256'h0000000000000000b13dc84fe1b3b65a2bef36328d0c781ddffa1c06bf941817;
                87:expected_chain=256'h0000000000000000e6764dfda9eda48d0387c49e8a768287bf0e9c1b07d364a0;
                88:expected_chain=256'h0000000000000000f648caaa48c93bc6ac3f02622844df9a8c9b5dee2e3a0917;
                89:expected_chain=256'h0000000000000000f477523ecbff718e26675d08034b5c902c5634527f7aeb69;
                90:expected_chain=256'h0000000000000000f19b04daf6cb3bfa520aff3b976a7ba0f40eb96785619a44;
                91:expected_chain=256'h00000000000000008e05c810e707cc91039462fbb7ffc84587ff1b510808eccd;
                92:expected_chain=256'h00000000000000009ce47bd55171a5070d46fab95903e759444670065870e668;
                93:expected_chain=256'h000000000000000066dd9caff7b0b4fd353870a2c9ccd4de8d5dd9aec31fb2f6;
                94:expected_chain=256'h0000000000000000202cb1cbc22e3e2f0e05a1fb643dcfebedf0a686d8f950c6;
                95:expected_chain=256'h000000000000000037363534333231302f2e2d2c2b2a29282726252423222120;
                96:expected_chain=256'h00000000000000000f62320b616dc34fec0c9e003a2d0cfc865c60772bd13aa4;
                97:expected_chain=256'h00000000000000000887f9a3c0530d07a6330357c64a65d994a619928174c512;
                98:expected_chain=256'h0000000000000000db6b6be326ff0f35c278863ffb39cb02fea3f85c2092ceea;
                99:expected_chain=256'h000000000000000076093b693b9c837cb469fd741e93e099a262ee579d169ef4;
                100:expected_chain=256'h0000000000000000b050da5c31e59366f0c61afdeb8de4cadbb8eb61ad75e341;
                101:expected_chain=256'h0000000000000000697a396426d0a916949435ab7cdca18a3c8c17f259674ff4;
                102:expected_chain=256'h0000000000000000b54b0f5429951e194f5308ea01464b9fffd7f62d60fa115c;
                103:expected_chain=256'h00000000000000008eebbe31a24f3f9428932717062b8c4ce037e6e0a533b781;
                104:expected_chain=256'h000000000000000069ef6d1acdfe8f6fe08945f8f5bd7107d72be6d957d55c16;
                105:expected_chain=256'h000000000000000000c906c03627b0870ea257840db374049e095c230962b769;
                106:expected_chain=256'h00000000000000002d0ff763e17d812aef2e4c5f724e6137e2906d8f66545ee0;
                107:expected_chain=256'h00000000000000009107a9b2ff6462493e0d73e2d9129bb8998b5df17f087cc7;
                108:expected_chain=256'h00000000000000009fbb6ae7a79d17da36e960e8d2319238705f0c9acaa23960;
                109:expected_chain=256'h00000000000000007c29bbfedb5015c2058548dc8e61f4f16d27cec42e93a965;
                110:expected_chain=256'h0000000000000000648df0252ce56eec3d84ba0a9241fa2fdf87a75627bda29c;
                111:expected_chain=256'h00000000000000006edd68a0d5865229d9a743f441577198d21c02b24cb77b68;
                112:expected_chain=256'h00000000000000000614b4d5dfb982af41590357f1e3060fd55b8a1a896c4246;
                113:expected_chain=256'h0000000000000000dd1d29778b9743df7178d6b815cb245901ac0ebc8b147b5c;
                114:expected_chain=256'h0000000000000000552d51dbd79ad6882728195dc3ee35aff0f3ffdf37359983;
                115:expected_chain=256'h00000000000000003e1bca2883473a3122c56a874f2668001a4527a17abec6d5;
                116:expected_chain=256'h0000000000000000d8f4435783647080ec50f0254b37de17129845ddb989a8a0;
                117:expected_chain=256'h00000000000000009a7367d63ea5c94f616a026bd6b1ff3ebe789bcadc1bb848;
                118:expected_chain=256'h0000000000000000434f1897203a159c88fb9183a3e8872224b06553ae2eaa72;
                119:expected_chain=256'h00000000000000009bf105b6e44c2a748db46c462239c0fc41ce7e9fb2722c0f;
                120:expected_chain=256'h0000000000000000ad8ef395a8d1fb179e7683238b15cb9b5bfa9889af804e43;
                121:expected_chain=256'h000000000000000097aa1ea33c0a68dfd23aaccbbd704e60ce875b92b0657bd1;
                122:expected_chain=256'h0000000000000000c694f6b6a70a5c1b95ab0c377660f53d1ddc010d2e64c368;
                123:expected_chain=256'h000000000000000082666ed88b71db90d24904a1709f6e472e6488161b00dae9;
                124:expected_chain=256'h00000000000000000fd1220751eacc26fdddcf9a7a5ac73660a3c13424ebb3eb;
                125:expected_chain=256'h0000000000000000ee36a5ceb82d8df16469311d50dd61bdb406d1f7066a5513;
                126:expected_chain=256'h00000000000000003f9142dd825021b80d6823762550c769f83243126614a5cc;
                127:expected_chain=256'h000000000000000037363534333231302f2e2d2c2b2a29282726252423222120;
                128:expected_chain=256'h2487e755ba06126564e0c6c80baef6ae3d1d5e12b5cb829867e11be7109f7ea8;
                129:expected_chain=256'hd24eaa60b826ddd02b7f21f32b09422d9a90d100dd493cafe46e397f69bac3f7;
                130:expected_chain=256'h2857c676ddd7f7d3016d5057c26d64d6c1c0e9a0552046f88ae65ca0802c3897;
                131:expected_chain=256'h9d1824c559d645957a33cc9880e8ea255c6c3f1340f3fd0a39854503bbe5c1ed;
                132:expected_chain=256'h359f039fcb5e1dcd0cf207178392fb4e2e83d01818c86c62461aec9d5e283280;
                133:expected_chain=256'hf6fef39144f1f01fb988c577737fc43eac751e77e3dcb1382502836de9fe2329;
                134:expected_chain=256'h94b64d45ea6c7d161e8a290076b6af4e2f048fb7a1f8df972c945d0b1464c7d0;
                135:expected_chain=256'h9a3cd2f85ec80d3a499ebe9d000e31ad856452975b8f773e43bbcc1cbf53394f;
                136:expected_chain=256'h9c61f567874f6e98eba0264414169cc946d1c926d47f8bea592f690fe2f70482;
                137:expected_chain=256'h47e576f572958bee4d686eb9333dba8186f91811344038297fc440f40705f924;
                138:expected_chain=256'h658007339681ec9e5f274d75fccd5c7fa2f93e3bea328a92a1f9392e75b051ed;
                139:expected_chain=256'h866a6cf773b4f59d864d9d16801608b27c1c3fea3816786930f35474560d5918;
                140:expected_chain=256'h970484996854400d8d52056543842b0beb9f5e5c3282c1a962383b0f2477f58b;
                141:expected_chain=256'h4c38aae8443afbb1576aa4b802646a151164952a7e0ab78f6e0aa9fc29b39f90;
                142:expected_chain=256'h1c3e02592a97a4a0aa4850bb87f912aa4a73f43804629c87bac5fd40cdbf1c7e;
                143:expected_chain=256'ha8595f9ea4363b9972fbb55d4d37a3321345e4d971251b958fb45cdedba1eadf;
                144:expected_chain=256'h6abd7f65eee48a3922b8d17312827405f13153f89d6ed0b4a073cc5e8c392d1d;
                145:expected_chain=256'h4222fbe6930bed3672ba525c7942c96351f107519b01a39d5552a1f1b52481b2;
                146:expected_chain=256'h69712f0d2a0c847d4a5b83fcf7c5483694e4d62d5c60c9e5cf1f1299edc39dfc;
                147:expected_chain=256'h831f94aeb153ea91669a98675c01176f8c905267d6affd4f91e0e05d5b619b0d;
                148:expected_chain=256'h9994d0518958e343d38a5d48646226c2663d7a089d7a0991338ad75e99d7c51f;
                149:expected_chain=256'hff1eb2b8265e217a276f556f8ee8ee764b77c50476509edbc4ba6a7881ca4e50;
                150:expected_chain=256'h9b58d57c98f82473c00d89eeef1150f5f9f5d00e2ae7d7b774bd816edc6b021e;
                151:expected_chain=256'hcc674f26c1b5e327e4ef71ed2958e9bbd136403702497578199253f94bccca41;
                152:expected_chain=256'h46c56048f6462d7012d5e0ab1f203ab0c609c9f697378b1c7adb1991bda621b3;
                153:expected_chain=256'h48d7768b4b03479bdfaef8a1c6c37cf6828495519671e95c36a8e0a135edfe14;
                154:expected_chain=256'h63dee5bfb5db4eefe39ff23e9eddf95cefc684017d75031336fba45bf8cca181;
                155:expected_chain=256'hc26904a2d7799d8ad3eab6744b6bb48033329d374225ad8f87358f2eb186d576;
                156:expected_chain=256'hffc15ee1bd63c5c08d51250171db83e50fb24343564802909db1df3253ff0e7e;
                157:expected_chain=256'he4a29048611564dd9f460fd8432983e882d0eae3c45a0fc0c4a10707fb355c38;
                158:expected_chain=256'hdd2a53b84a86607898398a875bb870350a2492838db096745faf7c5d1e9ff641;
                159:expected_chain=256'h3f3e3d3c3b3a393837363534333231302f2e2d2c2b2a29282726252423222120;
                160:expected_chain=256'h95cf9f160224dc30d9c234117045cff8cc46ab46a5827b7decd0cd31c4c6f52d;
                161:expected_chain=256'h8a19e42c201f53efaa21121697e715a628066386a9720b9039e1a3d06af05866;
                162:expected_chain=256'hb42726b9c410f262eb8134dd583606575e4f65e7530c456ec5db48717c1e6c79;
                163:expected_chain=256'h91a94e64d7aab911a4d4c4831dd51113df1fe0a514e0a470c46bea49f0e05d76;
                164:expected_chain=256'h2cb90f0f8f248f8654415797eeabd0b79288396b6a75f3c610211902b5323291;
                165:expected_chain=256'h01dbf0cf9f46db8a039ce5c3f8c0ca66dda545f0b67090a6c041f5478b6cd17a;
                166:expected_chain=256'h9e7773b8dafc5369cd6a413aa750fed2b6715054679bad05fde75c8c761be5df;
                167:expected_chain=256'hc94ad6926c57324b45f2bdb3744ec12d39003001a4832e3273dcebe068ae3798;
                168:expected_chain=256'h2839ce367aa42f838da3119627b4b0aad6264e68fd419932288d5087bffd67da;
                169:expected_chain=256'hf5488779c9a99e4118ba29e7db672981ba0472b66bf7f573b72645fc649087f0;
                170:expected_chain=256'ha8e0edae5681ef54ad5ccfa5c6d638f2cf98c04e9f01a4b418a6737c03bb6b6d;
                171:expected_chain=256'hd4ef403624045f0118894729aa8f957801fb45c846c7c62c68c05d64d4bd08df;
                172:expected_chain=256'ha0d90dd5340b82925d6facdfd54539860318a68d370c082c751db77c7b3669fb;
                173:expected_chain=256'h4edac243b57462b8bc9e2bbbc16e17f1b2184dc23e73070d49c098c2d833fa80;
                174:expected_chain=256'ha329e03a9e6069df10c455ff95ea1822bbec5723e3361fb6a50ec7e5b10b74dc;
                175:expected_chain=256'h21c54ddb265f60e3d507932bc318a18d825e8f42f38502247e97e7af02d0a442;
                176:expected_chain=256'h00b3db60f94cd9fc03f39a1ed4095a61c97696e8a71dbae7daf357879ca7cea0;
                177:expected_chain=256'h97d3b95223b860615b6f600a538c60313dd1e86bf43f57098b4b6b9ed231daa3;
                178:expected_chain=256'h20b130adc0269b08946824390a41afea8ac44693bc323220c4388cdbcec1eeb1;
                179:expected_chain=256'h99af35e2401f98cd9f355de25025576a814d6151e356da4599805113510ddcd8;
                180:expected_chain=256'h2849c1e71204e20c2a62161504b383aeae207d2d3daf28b70d06d592b8008fb7;
                181:expected_chain=256'h927b4735d81319f785e14242cd44c6b9c7ce7991256ea5405e3de6ddecad4b78;
                182:expected_chain=256'h6698b35957bd154c798e0a9eaa987ec8d6ab8d56d019e2714495d5ce503d6663;
                183:expected_chain=256'h8a4ecf0c6f2a2ce245dba7195e0bdd24e8f9b8e51c85dacd2733c363d016075e;
                184:expected_chain=256'h8eb6e91c2f2b42ace6dfa3d348cd6f4bb11218897ccac5024295b6b7900f4046;
                185:expected_chain=256'he9d93ba9026ccfffb42a9588f66ef5cc2f214f9a1c48af77a8aa45acb5ebb4a8;
                186:expected_chain=256'hdd4fff6419d10496192583629dfaaa90a5db6d019830e3fffc09ded366a8f651;
                187:expected_chain=256'h42b6a44cef29b88204cd8ed9e7ae17215eefb3ec66cc48362efb8eb6d4e99f49;
                188:expected_chain=256'h041e55e3585a71f94f556a6ef68e82767c2e7a8fe72a412dc07aae3140d8dbba;
                189:expected_chain=256'hf00621f7d7271e6774905ed150eda2a7fbc1d6e54af4f7c143cd68f3bca6dadc;
                190:expected_chain=256'h020d2b89daaf39fa4a52d63417729a718ae82b07205a727c219ed2da931103cc;
                191:expected_chain=256'h3f3e3d3c3b3a393837363534333231302f2e2d2c2b2a29282726252423222120;
                default:expected_chain=0;
            endcase
        end
    endfunction
    task storage_cases;
        begin
            for(integer bytes=16;bytes<=32;bytes=bytes+8) begin
                reset_program();profile_descriptor[7:0]=8'(bytes);
                profile_descriptor[39:32]=14;profile_descriptor[31:24]=17;
                emit(OP_NMOV,0,13);emit(OP_NMOV,4,11);emit(OP_NMOV,5,12);
                emit(OP_NMOV,7,0);emit(OP_NMOV,8,4);emit(OP_NMOV,9,5);emit(OP_NMOV,10,7);
                emit(OP_STORE,0,0,IDX_IMMEDIATE,0);emit(OP_STORE,0,4,IDX_IMMEDIATE,63);
                emit(OP_STORE,0,5,IDX_IMMEDIATE,64);emit(OP_STORE,0,10,IDX_IMMEDIATE,67);
                emit(OP_HEIGHT,1);emit(OP_STORE,1,8,IDX_LEVEL);emit(OP_STORE,2,9,IDX_LEVEL);
                repeat(14)emit(OP_LEVEL_NEXT);
                emit(OP_STORE,1,10,IDX_LEVEL);emit(OP_STORE,2,5,IDX_LEVEL);
                emit(OP_LOAD,0,0,IDX_IMMEDIATE,0);emit(OP_EMIT,0,0);
                emit(OP_LOAD,4,0,IDX_IMMEDIATE,63);emit(OP_EMIT,0,4);
                emit(OP_LOAD,5,0,IDX_IMMEDIATE,64);emit(OP_EMIT,0,5);
                emit(OP_LOAD,7,0,IDX_IMMEDIATE,67);emit(OP_EMIT,0,7);
                emit(OP_LOAD,8,1,IDX_LEVEL);emit(OP_EMIT,0,8);
                emit(OP_LOAD,9,2,IDX_LEVEL);emit(OP_EMIT,0,9);emit(OP_LEVEL_INIT);
                emit(OP_LOAD,10,1,IDX_LEVEL);emit(OP_EMIT,0,10);
                emit(OP_LOAD,1,2,IDX_LEVEL);emit(OP_EMIT,0,1);
                emit(OP_NMOV,0,5);emit(OP_NMOV,5,4);emit(OP_NMOV,4,0);
                emit(OP_EMIT,0,4);emit(OP_EMIT,0,5);emit(OP_EMIT,0,0);emit(OP_END);
                launch();finish_job();
                if(outputs!=11) $fatal(1,"storage output count");
                for(integer sample=0;sample<11;sample=sample+1) begin
                    case(sample)
                        0,3,4:if(observed_output[sample]!==expected_node(bytes,job_public_seed))
                            $fatal(1,"LIST/STACK/node alias n=%0d output=%0d",bytes,sample);
                        1,6,9:if(observed_output[sample]!==expected_node(bytes,job_secret_seed))
                            $fatal(1,"STACK/NMOV source differs from destination n=%0d output=%0d",bytes,sample);
                        default:if(observed_output[sample]!==expected_node(bytes,job_secret_prf))
                            $fatal(1,"AUTH/NMOV alias n=%0d output=%0d",bytes,sample);
                    endcase
                end
                // A new Job zeros every writable node but retains initialized
                // LIST/STACK/AUTH data. This must not clear the shared RAM.
                for(integer j=0;j<512;j=j+1)program_memory[j]=0;
                p=0;outputs=0;
                emit(OP_EMIT,0,0);emit(OP_EMIT,0,1);emit(OP_EMIT,0,4);emit(OP_EMIT,0,5);
                emit(OP_EMIT,0,7);emit(OP_EMIT,0,8);emit(OP_EMIT,0,9);emit(OP_EMIT,0,10);
                emit(OP_LOAD,0,0,IDX_IMMEDIATE,0);emit(OP_EMIT,0,0);
                emit(OP_LOAD,4,1,IDX_LEVEL);emit(OP_EMIT,0,4);
                emit(OP_LOAD,5,2,IDX_LEVEL);emit(OP_EMIT,0,5);emit(OP_END);
                launch();finish_job();
                if(outputs!=11) $fatal(1,"new Job storage output count");
                for(integer sample=0;sample<8;sample=sample+1)
                    if(observed_output[sample]!==0) $fatal(1,"new Job exposed stale node=%0d",sample);
                if(observed_output[8]!==expected_node(bytes,job_public_seed)
                    || observed_output[9]!==expected_node(bytes,job_secret_seed)
                    || observed_output[10]!==expected_node(bytes,job_secret_prf))
                    $fatal(1,"new Job cleared LIST/STACK/AUTH");
            end
            // Reserved/out-of-bounds memory instructions may not alias a
            // neighboring physical partition, including while cancelling.
            reset_program();emit(OP_NMOV,0,13);emit(OP_STORE,0,0,IDX_IMMEDIATE,68);
            launch();expect_fault();
            if(dut.node_memory_write) $fatal(1,"faulting memory write stayed enabled");
            reset_program();emit(OP_NMOV,4,12);emit(OP_LOAD,4,0,IDX_IMMEDIATE,68);
            launch();expect_fault();
            if(dut.scratch_valid[4]!==1 || dut.node_memory[116]!==expected_node(16,job_secret_prf))
                $fatal(1,"faulting LOAD changed destination");
        end
    endtask
    task chain_program(input integer bytes,slot,digit,mode);
        begin
            reset_program();profile_descriptor[7:0]=8'(bytes);
            profile_descriptor[63:56]=8'(bytes*2+3);
            descriptor_memory[7]=64'h0105010001000000|({56'd0,8'(bytes)}<<32);
            descriptor_memory[8]=64'h0200010001000000|({56'd0,8'(bytes)}<<32);
            for(integer j=0;j<32;j=j+1)job_randomizer[j*8+:8]={4'(digit),4'(digit)};
            emit(OP_NMOV,4,12);emit(OP_NMOV,5,12);
            emit(OP_NMOV,7,11);emit(OP_NMOV,8,13);
            emit(OP_NMOV,2,14);emit(OP_DIGITS);
            emit(OP_MASK,0,0,0,3);emit(OP_STEP_NEXT,1);emit(OP_STEP_NEXT,2);emit(OP_STEP_NEXT,2);
            emit(OP_HEIGHT);repeat(5)emit(OP_CURSOR_NEXT,0,0,0,1);
            emit(OP_MASK,0,0,0,slot==0 ? 1 : 2);emit(OP_DIGIT_LOAD);
            emit(OP_ADRS,0);
            emit(OP_CHAIN,8'(mode),digit[0] ? 8'(slot+1) : 8'd0,mode==3 ? 8'd1 : 8'd0);
            emit(OP_EMIT,0,8'(4+slot));emit(OP_EMIT,0,8'(7+slot));
            emit(OP_EMIT,0,8'(5-slot));emit(OP_EMIT,0,8'(8-slot));emit(OP_END);
        end
    endtask
    task chain_cases;
        integer cases,budget;
        logic [255:0] endpoint,capture;
        begin
            cases=0;
            for(integer bytes=16;bytes<=32;bytes=bytes+8)
                for(integer slot=0;slot<2;slot=slot+1)
                    for(integer digit=0;digit<16;digit=digit+1)
                        for(integer mode=0;mode<4;mode=mode+1) begin
                            chain_program(bytes,slot,digit,mode);launch();finish_job();
                            endpoint=expected_chain(bytes,slot,mode==2 ? digit : 15,0);
                            if(mode==3)endpoint=expected_chain(bytes,slot,digit,1);
                            capture=mode==1 || mode==2 ? expected_chain(bytes,slot,digit,0)
                                : expected_node(bytes,slot==0 ? job_secret_seed : job_public_seed);
                            budget=mode==0 || mode==1 ? 16 : mode==2 ? 1+digit : 15-digit;
                            if(outputs!=4 || observed_output[0]!==endpoint || observed_output[1]!==capture)
                                $fatal(1,"CHAIN oracle n=%0d slot=%0d digit=%0d mode=%0d endpoint=%h expected=%h cap=%h expected=%h",
                                    bytes,slot,digit,mode,observed_output[0],endpoint,observed_output[1],capture);
                            if(observed_output[2]!==expected_node(bytes,job_secret_prf)
                                || observed_output[3]!==expected_node(bytes,slot==0 ? job_public_seed : job_secret_seed))
                                $fatal(1,"CHAIN touched inactive slot");
                            if(dut.ctx_step[slot]!=(mode==2 ? digit : 15) || dut.ctx_step[1-slot]!=(slot==0 ? 2 : 1)
                                || dut.ctx_chain!=0 || dut.ctx_cursor!=5 || dut.ctx_layer!=0 || dut.ctx_tree!=0
                                || dut.addr_leaf[0]!=5 || dut.addr_leaf[1]!=5 || dut.addr_a[0]!=0 || dut.addr_a[1]!=1
                                || dut.addr_b[0]!=1 || dut.addr_b[1]!=2)
                                $fatal(1,"CHAIN changed unrelated context or failed terminal STEP");
                            if(hash_count!=budget || permutation_count!=budget || traces!=budget
                                || dut.macro_count!=1 || dut.macro_hashes!=budget || dut.macro_busy_cycles<3)
                                $fatal(1,"CHAIN counts expected=%0d hashes=%0d traces=%0d macros=%0d work=%0d",
                                    budget,hash_count,traces,dut.macro_count,dut.macro_hashes);
                            cases=cases+1;
                        end
            // FULL has no digit dependency; CAP/STEP/L commit only on success.
            reset_program();descriptor_memory[7]=64'h0105011001000000;descriptor_memory[8]=64'h0200011001000000;
            emit(OP_MASK,0,0,0,1);emit(OP_CHAIN);emit(OP_END);launch();finish_job();
            if(hash_count!=16 || dut.ctx_step[0]!=15) $fatal(1,"FULL requires no digit");
            for(integer bad=0;bad<7;bad=bad+1) begin
                chain_program(16,0,3,1);
                case(bad)
                    0:descriptor_memory[7][55:48]=0;
                    1:descriptor_memory[8][47:40]=2;
                    2:descriptor_memory[8][29:24]=0;
                    3:descriptor_memory[7][0]=1;
                    4:descriptor_memory[8][37:32]=24;
                    5:descriptor_memory[8][55:48]=1;
                    6:descriptor_memory[8][31]=1;
                endcase
                launch();expect_fault();
                if(hash_count || traces || dut.macro_count || dut.ctx_step[0]!=1 || dut.chain_shadow_valid
                    || dut.node_memory[116]!==expected_node(16,job_secret_prf)
                    || dut.node_memory[119]!==expected_node(16,job_secret_seed))
                    $fatal(1,"bad CHAIN recipe launched Hash or modified architectural state bad=%0d",bad);
            end
            // Instruction permissions and bounds are checked before a macro
            // can start, including the full-width odd final-slot addition.
            for(integer mask=0;mask<=3;mask=mask+3) begin
                reset_program();emit(OP_NMOV,4,12);emit(OP_MASK,0,0,0,8'(mask));emit(OP_CHAIN);
                launch();expect_fault();
                if(hash_count || dut.macro_count || dut.node_memory[116]!==expected_node(16,job_secret_prf))
                    $fatal(1,"bad CHAIN mask changed state");
            end
            reset_program();emit(OP_MASK,0,0,0,1);emit(OP_CHAIN,0,2);launch();expect_fault();
            reset_program();emit(OP_MASK,0,0,0,1);emit(OP_CHAIN,0,0,0,1);launch();expect_fault();
            reset_program();profile_descriptor[63:56]=67;
            repeat(33)emit(OP_CHAIN_NEXT,0,0,0,2);
            emit(OP_MASK,0,0,0,2);emit(OP_CHAIN);launch();expect_fault();
            if(dut.ctx_chain!=66 || hash_count || dut.macro_count) $fatal(1,"odd CHAIN slot aliased valid chain");
            reset_program();profile_descriptor[39:32]=10;profile_descriptor[31:24]=32;
            emit(OP_HEIGHT,1);emit(OP_CURSOR_NEXT,0,0,0,2);emit(OP_BR,COND_CURSOR_MORE,0,0,1);
            emit(OP_MASK,0,0,0,1);emit(OP_CHAIN);launch();expect_fault();
            if(dut.ctx_cursor!=1024 || hash_count || dut.macro_count) $fatal(1,"CHAIN narrowed invalid cursor");
            reset_program();emit(OP_NMOV,2,13);emit(OP_DIGITS);emit(OP_MASK,0,0,0,1);
            emit(OP_CHAIN,1);launch();expect_fault();
            reset_program();image_header=64'h4842535010000000;emit(OP_MASK,0,0,0,1);emit(OP_CHAIN);
            launch();expect_fault();
            // Force a lane failure after digit3 has already reached private
            // shadow, and before the endpoint; no partial result may escape.
            chain_program(16,0,3,1);launch();
            while(!(dut.chain_active && dut.chain_shadow_valid && dut.physical_valid
                && dut.chain_hash_stage && dut.group_b_value>=7))tick();
            force dut.physical_error=1'b1;tick();release dut.physical_error;
            if(!error || error_code!=16'h3007 || dut.chain_shadow_valid || dut.ctx_step[0]!=1
                || dut.node_memory[116]!==expected_node(16,job_secret_prf)
                || dut.node_memory[119]!==expected_node(16,job_secret_seed))
                $fatal(1,"late CHAIN fault committed partial node/capture/STEP");
            repeat(3)tick();if(done || outputs) $fatal(1,"late CHAIN fault did not halt");
            // Reset interrupts a captured chain; replay uses a new shadow and
            // retained RAM cannot expose the abandoned private capture.
            chain_program(16,1,4,1);launch();
            while(!dut.chain_shadow_valid)tick();rst=1;repeat(2)tick();
            if(dut.chain_shadow_valid || dut.scratch_valid!=0) $fatal(1,"CHAIN reset retained valid state");
            launch();finish_job();
            if(observed_output[0]!==expected_chain(16,1,15,0)
                || observed_output[1]!==expected_chain(16,1,4,0) || hash_count!=16)
                $fatal(1,"CHAIN reset replay");
            $display("MICRO_CHAIN_MACRO_PASS cases=%0d all_n both_slots digit0_15 four_modes zero_suffix private_capture atomic_recipe late_fault reset_replay",cases);
        end
    endtask
    // Independent hashlib oracle: standard byte preimages, not the project VM.
    function automatic [255:0] expected_stateful_chain(input integer family,slot,pos,suffix);
        integer item;
        begin
            item=family*64+slot*32+pos+(suffix ? 16 : 0);
            case(item)
                0:expected_stateful_chain=256'h2329b502ab2970aed34007cc69a493090162e53ae521dd910bb90928827db9c4;
                1:expected_stateful_chain=256'he10510544dcbb742f953cb2ab9d37753e8270ee70534036945d9bef203ddb8aa;
                2:expected_stateful_chain=256'h7174b682a16fa3bd6cf269fe7c94a19f432439d786a5da39304fe09db3eef10e;
                3:expected_stateful_chain=256'h6f90e768be83fa7a845691b2887522d4c0541a24be7b8bcb0afa6af60898fcb4;
                4:expected_stateful_chain=256'h63eef657b2e6e9c817cc8194944cd8799b0810f9ff118e043f37106ad94384ed;
                5:expected_stateful_chain=256'hbc9cb904a3722ba6fab19857bea2ac99a6e9e4af693df6c52705a7d7245efd4c;
                6:expected_stateful_chain=256'ha703b54deb82255115be607a9244d61b86296649fd2aa8cb7166e45b660671c4;
                7:expected_stateful_chain=256'h8469faf64f8a241e47e740bda31df6cb2c090a3c9d9a8fec62f4edf547655f1c;
                8:expected_stateful_chain=256'hce796364c35affd869c27e472b9ef24ae48cd6d5a56431eb5ab5a6688b65d719;
                9:expected_stateful_chain=256'h21201149172d731b742110e63914601e089158ffb5a795e4fd23720c8df35e4d;
                10:expected_stateful_chain=256'hafb04084d6e96fcfaaa97901826c69c2406f1e6eef9a900c0c2080df385411fb;
                11:expected_stateful_chain=256'h5543fa29d6aba409c2a857e55ceb4fc51538b1b891e0d6ca07309605b5336d09;
                12:expected_stateful_chain=256'hbadd8550d372362848e5cdd32e96f1ed3d7aae2e391e5aaf946f0de34945dab7;
                13:expected_stateful_chain=256'h75866c70a034f234c87a9c6d3551c2c9edbde61a01b463a2bf89348f3efbbe60;
                14:expected_stateful_chain=256'h88c3ea1199e74193f362a2067e9955afd84e738d2eca9696206d3ba99ba6dd82;
                15:expected_stateful_chain=256'hfad70562f103acda3f90c3f9fc8362639400f5f5a3afbc0c1804281aa262717e;
                16:expected_stateful_chain=256'he34694d05aea228bf3b1ba1912df7ac8cdb8238397d7cc1a0f7bf4ca4b6dd8a8;
                17:expected_stateful_chain=256'h829b5cac40e6b1f864ac5b10bec8794c4efdb1485aaf766d85016acdc8c161b4;
                18:expected_stateful_chain=256'h311180cfa10755c0afc40a8c20312c145f2fc39979a702eb594c94f7c33e6462;
                19:expected_stateful_chain=256'h97b35ee4ce67b9f89c7b2fe7b881887d5d1492211b0859a91c16fdd981d4485c;
                20:expected_stateful_chain=256'h60068f86c2d72b4fd1759e851535b6b93b6c1cd96ed4ec641fa7aa07e4572a8f;
                21:expected_stateful_chain=256'hc5c51ed51f805ffe99c3f089c31324c2748b0b874925c5406b8c5dd47884e882;
                22:expected_stateful_chain=256'h44cfa200dfb5bb9fca7c20a552f255f722ad48719852b0d01a016ad72a6b7e54;
                23:expected_stateful_chain=256'hf3f4687a8558c367c7931fea242ee143933e7175fea05256cbf07615ca9d4a9b;
                24:expected_stateful_chain=256'hf8ed249eadc57289a2b341f6a5901002a79502c61ec402c2d9da7b35ade2c40d;
                25:expected_stateful_chain=256'hb012d7a62674d061e7daf048fe16e1d719175aba3c2c3b42643650fb49ab9611;
                26:expected_stateful_chain=256'hb23d69c166fd21fce4dcaa10bfcd437944cc9cc72addd46506d0239a41f07c34;
                27:expected_stateful_chain=256'h54dee7c7823d52c060c67e45cc8c8e385899987d19f77cc93f5fce8ae0313447;
                28:expected_stateful_chain=256'ha0e73e7fb7d7d63ac012586093181608dc2355b7ed58a70ae904d984cc483e5e;
                29:expected_stateful_chain=256'hf6f267dbaef8aa96312440f7dad3cdb01c5d56675af59d28934512d721c8841a;
                30:expected_stateful_chain=256'h2a31482edc6b63b6bf595b84e2cd150eb680a7e5955e2e915abce95a0d201b7e;
                31:expected_stateful_chain=256'h3f3e3d3c3b3a393837363534333231302f2e2d2c2b2a29282726252423222120;
                32:expected_stateful_chain=256'h6fc2f8f728d128015296478e6be5ea82a373a38030403c82bc82268796601e90;
                33:expected_stateful_chain=256'h9b6f66bf1f05ee1214b3cb1dee772625ecbfedfebb2e5df64309d1de1a9935dc;
                34:expected_stateful_chain=256'h710a7c90dd52fd8d6fa07ca63136938792aaa4a451430fd7691b9f0f7dd3f40d;
                35:expected_stateful_chain=256'h5b7be51b742db53064f543bcafa82cb881f7f409d907a2bc3b9c8d602551a5a4;
                36:expected_stateful_chain=256'hb8b0b8cf5269b1f08e732581bfdcc68eb7b11696141ecce7a73a20ef74f4753f;
                37:expected_stateful_chain=256'h3b4f3e14abb05a2a16d7e753f74dd2b26944d17e373ec6db1a1d3b68dc3408d0;
                38:expected_stateful_chain=256'h5c03e50eacfd98703bf312832b437b88655f4d1850855271c0f3be92525afafb;
                39:expected_stateful_chain=256'h1c6a47152cde10e488d2f9e2257eaf49491919dfcffc4e9fa6c7a9b3b21ee690;
                40:expected_stateful_chain=256'h31b879c14bc964b9868e20005eb11f03a65d05d7b8d163f0b40aae84ddab6d59;
                41:expected_stateful_chain=256'h97f89137f912dae97e735751ed4369995a12e6b7e3bdae19520698022a3a985d;
                42:expected_stateful_chain=256'h6734e8560e1bd78ce1133104aceff770a9a5b25c90544ea6caef1bae6d616f6e;
                43:expected_stateful_chain=256'h4cf6a2d7315b967a10a0cb42e9383d6596f6540be58871b19c63035150e0648c;
                44:expected_stateful_chain=256'h5c79fd85e5edbe077ae8f7343961af4ec504180f5e61a7eaa3741c3046424965;
                45:expected_stateful_chain=256'hb11f0ed9f1d9a9a835ee8b80d70e9b59bb9fe9fe95153eaa0322e0f6bace7d7d;
                46:expected_stateful_chain=256'hebc743146599323e733f3d7da0e23a37e4296f1653fa082eb9ecf8453377ecd3;
                47:expected_stateful_chain=256'h74aeb37983c2bbbe05d505596b68ded73b3537ec76a37a14fb3f9f3beed2c404;
                48:expected_stateful_chain=256'h53ab3d1bb37f6d518ca0055c7df3d6511d802d026b818d65c263acbb297554c7;
                49:expected_stateful_chain=256'h595734eb6c2cd60534198c13478ab9c6b68f03384197fa01b7c94f0737523f70;
                50:expected_stateful_chain=256'he4fee5df87c1a3599f3cc18eaf2dfff67acba610e15ab950d4e3b7ef5ebf4746;
                51:expected_stateful_chain=256'hf9252338667a40463062457b9d55b67c1b21671b3ecd43c52c8d7f236edc0353;
                52:expected_stateful_chain=256'hbdd54947077d6aff7b5e996fe125fe25724686e12369d6ff5f5058b7356df974;
                53:expected_stateful_chain=256'h46d946641b3d88d78f3c75d79a6069c3423a559423909a441fa805e6dab0dece;
                54:expected_stateful_chain=256'h27f43c87d5eebfb667983adb59c925ed906333674cf6f701b969a2bf941fb7fd;
                55:expected_stateful_chain=256'h204208901019bf2be57c20b8fc0b0c174a3bf3a81d7e7886a8703787233d05ba;
                56:expected_stateful_chain=256'h5373b1f2097d622c234f2c2b8bf44b20bc6f2a71c4c09e98d409ce8a2d8a2e2a;
                57:expected_stateful_chain=256'h9a0e2897ce6c37f810ddecb0a25d817c8115d67e7da2f146a9a0bc161d572887;
                58:expected_stateful_chain=256'h050443a7550dd3aad68a08d35469e548a82432a74e2f72a5ee3e0d5376b4a62e;
                59:expected_stateful_chain=256'h5584072101741ea2a61df3d2c5c7cf6bbcc1bceee04220d1f3b4e85c140f6f5f;
                60:expected_stateful_chain=256'h39a3f81daab39f8edd98ce6404acc2fdbcec7b27bb3e7d2bd5c01dd4b67d790f;
                61:expected_stateful_chain=256'hdf8f52235c461433b80e3db3e3897c52e044ec18003619b99550dee9bc13b65b;
                62:expected_stateful_chain=256'ha426f30c039bac7a3d33efecd2938a3f3362d9803cb62bd07d5ea063ae5d3b0c;
                63:expected_stateful_chain=256'h3f3e3d3c3b3a393837363534333231302f2e2d2c2b2a29282726252423222120;
                64:expected_stateful_chain=256'h944eb357e0fda01b9c9d7854b8839812e76be25c26733d0f5cb89848cab99fbd;
                65:expected_stateful_chain=256'hf29c8c34647096bdd45e9a68c03cbafc3ba84b5ad76c0c9b2e7d1885ee8a463e;
                66:expected_stateful_chain=256'h34f6aad63a41108f7aacfc2f4af7d99d304b06a9a56c492a1c32619283cec917;
                67:expected_stateful_chain=256'h91c274a38387f69275ba6bb339979e5f8faf2a04021dd1aad22e3de60c814c21;
                68:expected_stateful_chain=256'he3ac24c6ad061881e3a72c10d2c94ba202bf09bb5d8d62e7d55f043b5108389d;
                69:expected_stateful_chain=256'hb9f7637fe2673e123e8e259058166e08118c2adc80c82c30847f568c59ce52cc;
                70:expected_stateful_chain=256'h0b303814f3b4b7db37ef6b39d8f94580c263474a01b46c9282bb6ca8b64c457e;
                71:expected_stateful_chain=256'h4dfa3dde1dfa511dc9096f2a23a961988820f3f8092b1643e045f06b39387204;
                72:expected_stateful_chain=256'hdb2e28b447080834d0bef018863e74ee1bc4a164bb3a4c639fea5fc1a60aa0a3;
                73:expected_stateful_chain=256'hbf786f05abf54a324670a8a691ca2c374718f95f0d5532c1a59a00d3c64eaaa5;
                74:expected_stateful_chain=256'hc1d819976f357a23b6b5ce011794b172d0e05db5abb8a1deb115c5458be52efd;
                75:expected_stateful_chain=256'h40cc45a0b5cb259180e355df10cfd5ec322e1e3a5fec1ce0fe41d9bfe6e8c2d2;
                76:expected_stateful_chain=256'h6d39c4bb70f88dd79a6ceccd264bb43e6dfbab670d0038a1195887548640e636;
                77:expected_stateful_chain=256'h2ae8ed7f059965a5bab2cd234378c634cb7e5cafed1f56544f3e5ab999148d64;
                78:expected_stateful_chain=256'hcb8c48b0668c378282c05eb7d20e972ba35c99c367b006d37356634d8624a228;
                79:expected_stateful_chain=256'h5a52e87895d682f44f655135e73213c1b2cedd51f8eb9f4ac703f1479b425854;
                80:expected_stateful_chain=256'h13ffbb26d963690655499a6bef017b51b69dde2041dd9152571586b7d7e54c9c;
                81:expected_stateful_chain=256'hc6f3f1e6515baefe33371053f9ab428cfe02f72d34dd8a9cca83fb6701398944;
                82:expected_stateful_chain=256'hce59711c90ce8af670e171f9205cfc2a1da42ffa6c3b668b44c26b637472161c;
                83:expected_stateful_chain=256'he774a81b5545cd59ceee5fa3b0f019ea08191206f7f7e1740f1cccf66eae016a;
                84:expected_stateful_chain=256'h28648e1608cd6e3bc6e89b54c2b61c705e9c6b4e6cef60dfedc7030475941307;
                85:expected_stateful_chain=256'hfc6aa4bff7716c64cb648a13d936b5fa2d1f71a65f77769fbe070cd4218321f2;
                86:expected_stateful_chain=256'h1f6067ed2581c47a85bf0cb00fb65e391255b6dd0ac44a8274f95037bccb658f;
                87:expected_stateful_chain=256'hf41da7e64ac344b437b2e0f98118e32fd37c3f6fce437c10c0a39c5691ffe42f;
                88:expected_stateful_chain=256'h51731af3e544a95d48c8951aa54df9ca22f3753c2721e3c2ec647e59add7a1d5;
                89:expected_stateful_chain=256'ha6e3ec0978e1f1009d5bf4a292cd8271f7ece63bfe6d6000a2635ebfd67a9fe2;
                90:expected_stateful_chain=256'h7dc8cf1b7d85e6a88365c221f79e025725483b165957cc66f2b72ba1d8af0cce;
                91:expected_stateful_chain=256'hce543e4197eef74759fc4897ac25953aec0fc9e78547e27b4a1764eac41eee27;
                92:expected_stateful_chain=256'h0bc222cbe180e844a8b029f14d9d86914eed45b7f4c150e88076d9e828f364d0;
                93:expected_stateful_chain=256'h9b3c94ef05668d9db43cdaf03f2cd716bf7387c64d25c79f75442b95d7eeefd3;
                94:expected_stateful_chain=256'h0fdde1d63058b80f5d11eb7c31f9b89d08b4ce34a1c7ea83bef269504c0d7a22;
                95:expected_stateful_chain=256'h3f3e3d3c3b3a393837363534333231302f2e2d2c2b2a29282726252423222120;
                96:expected_stateful_chain=256'hcb5c142ed289a80ff708493a22e3b4dedb6e32330c6d3b3c678aa20b3610a92c;
                97:expected_stateful_chain=256'hc1fc2e2efee610b87a71942696dcb4a93139dca66409ea8600cd7cff04f491ca;
                98:expected_stateful_chain=256'hc4a8e5cc3a97512ad1ce3c884008fae1ffcf7bdedb7059698ff648746e74e37a;
                99:expected_stateful_chain=256'h56b51e71074d9ab1834b7ec012a67081a9e91c289e3fd2d508877fafa560a82d;
                100:expected_stateful_chain=256'h39134e6630ad386924886029f96e62df8fe80bb5268c5088e2414777ea334d43;
                101:expected_stateful_chain=256'ha387f4b7701aeb56e53608714dd3f7f862e907e91a132617845b86c43f5d0aa0;
                102:expected_stateful_chain=256'hc22316616983b6018dd0933b8d9eef4dd1dcd8427161eba5640d59c3b40dee8f;
                103:expected_stateful_chain=256'h755b0ee8f98a3ca1957fc35a2d15d910a4bf5396db55ae44bdc901a2a188c2b3;
                104:expected_stateful_chain=256'h2c48cc401f55cc78ac63d5424674c5bb97810ceae2a9758c40ab257eeeb0142e;
                105:expected_stateful_chain=256'h991bde4dd480a6d3243166a2d99f184df0f99ffea5f6016688bbd57a972615d8;
                106:expected_stateful_chain=256'h843d9f8181c0bd85fd150f1f4b4bc0d4a07b25bc0c89617e9e7c10087f821764;
                107:expected_stateful_chain=256'hc100a8b81ce7f2f910619c0fe0b570476a9286a58d07bb5146a0108e444359f5;
                108:expected_stateful_chain=256'he73f191c65b8dfff405cec36897e6a9cae188d23b337134d10bf8c4cd5fc723a;
                109:expected_stateful_chain=256'h81ffc1d53f2a3354cfd131338ea70b8dd2c30460c1ae64dccb241fa0661710eb;
                110:expected_stateful_chain=256'h7aac46a8be26b7575d94b7017c467b2897ef167fac19ffba9e42d2dbca9df915;
                111:expected_stateful_chain=256'hd101306f98e5cfb166cf9537f80178be16e0ecea585c8aa0a04ca7b33a22c843;
                112:expected_stateful_chain=256'hffaab788f022e559e47b82d3f8ba9ece9867b0e765b80151d8a6812da0a9369e;
                113:expected_stateful_chain=256'h56eea7a3c75e3283559d3700d89c3e25a57b932a3bdcde797389f2a821a84eb6;
                114:expected_stateful_chain=256'h85e76d93519c6a28fce616de28482977b9325ca76af7510b16bf8ad4b1226106;
                115:expected_stateful_chain=256'h69fb9a70c1bb79cec61b309c7b182da746ad006b6931a2ed5a62ed49a8ffa56d;
                116:expected_stateful_chain=256'h07a620aa334150164573299496968b50dd56956cc1507c5203d4d1260282af9d;
                117:expected_stateful_chain=256'h1e6bf077944e83198c501d59b69b57a31b3f885a06d8d61c617da190544c8d6a;
                118:expected_stateful_chain=256'he5e7cc71689effb5f049a3ac24b5b8552c87486d8bfefe158955e96ed4b03fe7;
                119:expected_stateful_chain=256'hf9c48398365edbf4bfbbcbaab57eac1d3218686b5d70045fd030a26aa8f4f63f;
                120:expected_stateful_chain=256'h495bc749616f8b18a234708ccb97a3600544fee304e952e2739609f40f30958d;
                121:expected_stateful_chain=256'hd7cbda3ba9330719a80db504832b4dabdc8040eba0989c8ea66ec57793cac72f;
                122:expected_stateful_chain=256'h8af4f662c5e7647e29e6ef4c93ea2794ff3de60d328cdb589453e1a948518292;
                123:expected_stateful_chain=256'h613d27240d5df4af9914deecb84ab84873619cc853edcc582365f3dca5bf2c21;
                124:expected_stateful_chain=256'h44351cb398bbd329068d160e9d2f8b7573291915b4e02af6f3e3fc32ea4ebb64;
                125:expected_stateful_chain=256'h3e9665f099f31a3aaddda3e556de52ff56a5b127d356469a5e9861d3f7ecca60;
                126:expected_stateful_chain=256'h98ec3634e27ff35718d53a899d71cef6d1a1f4aa153131f4d9c9941cb4a39e78;
                127:expected_stateful_chain=256'h3f3e3d3c3b3a393837363534333231302f2e2d2c2b2a29282726252423222120;
                default:expected_stateful_chain=0;
            endcase
        end
    endfunction
    task stateful_chain_program(input integer family,slot,digit,mode);
        begin
            chain_program(32,slot,digit,mode);
            profile_identity=family==0 ? 64'd8 : 64'd11;
            profile_descriptor=64'h430a200000010a20;
            for(integer j=0;j<16;j=j+1)job_identifier[j*8+:8]=8'(160+j);
            if(family==0) begin
                descriptor_memory[4]=64'h0502012001000000;
                descriptor_memory[5]=64'h0503012001000000;
                descriptor_memory[7]=64'h0500012001000000;
                descriptor_memory[8]=64'h0600012001000000;
            end else begin
                descriptor_memory[7]=64'h0900012001000000;
                descriptor_memory[8]=64'h0a00012001000000;
            end
        end
    endtask
    task stateful_chain_cases;
        integer cases,budget;
        logic [255:0] endpoint,capture;
        begin
            cases=0;
            for(integer family=0;family<2;family=family+1)
                for(integer slot=0;slot<2;slot=slot+1)
                    for(integer digit=0;digit<16;digit=digit+1)
                        for(integer mode=0;mode<4;mode=mode+1) begin
                            stateful_chain_program(family,slot,digit,mode);launch();finish_job();
                            endpoint=expected_stateful_chain(family,slot,mode==2 ? digit : 15,0);
                            if(mode==3)endpoint=expected_stateful_chain(family,slot,digit,1);
                            capture=mode==1 || mode==2 ? expected_stateful_chain(family,slot,digit,0)
                                : (slot==0 ? job_secret_seed : job_public_seed);
                            budget=mode==0 || mode==1 ? (family==0 ? 46 : 16)
                                : mode==2 ? 1+digit*(family==0 ? 3 : 1) : (15-digit)*(family==0 ? 3 : 1);
                            if(outputs!=4 || observed_output[0]!==endpoint || observed_output[1]!==capture)
                                $fatal(1,"stateful CHAIN oracle family=%0d slot=%0d digit=%0d mode=%0d got=%h expected=%h cap=%h expected=%h",
                                    family,slot,digit,mode,observed_output[0],endpoint,observed_output[1],capture);
                            if(observed_output[2]!==job_secret_prf || observed_output[3]!==(slot==0 ? job_public_seed : job_secret_seed)
                                || dut.node[2]!==job_randomizer || dut.node[6]!==0 || dut.hmsg_digest!==0 || dut.hmsg_valid)
                                $fatal(1,"stateful CHAIN touched inactive/retained architectural state");
                            if(dut.ctx_step[slot]!=(mode==2 ? digit : 15) || dut.ctx_step[1-slot]!=(slot==0 ? 2 : 1)
                                || dut.ctx_chain!=0 || dut.ctx_cursor!=5 || dut.ctx_layer!=0 || dut.ctx_tree!=0)
                                $fatal(1,"stateful CHAIN terminal/context");
                            if(hash_count!=budget || permutation_count!=budget || traces!=budget
                                || dut.macro_count!=1 || dut.macro_hashes!=budget)
                                $fatal(1,"stateful CHAIN budget family=%0d digit=%0d mode=%0d expected=%0d actual=%0d macro=%0d",
                                    family,digit,mode,budget,hash_count,dut.macro_hashes);
                            cases=cases+1;
                        end
            for(integer bad=0;bad<4;bad=bad+1) begin
                stateful_chain_program(0,0,3,1);
                case(bad)
                    0:descriptor_memory[4][55:48]=3;
                    1:descriptor_memory[4][47:40]=2;
                    2:descriptor_memory[5][29:24]=0;
                    3:descriptor_memory[5][0]=1;
                endcase
                launch();expect_fault();
                if(hash_count || traces || dut.macro_count || dut.ctx_step[0]!=1
                    || dut.node_memory[116]!==job_secret_prf || dut.node_memory[119]!==job_secret_seed)
                    $fatal(1,"stateful CHAIN preflight not atomic");
            end
            // A private digit capture precedes a forced failing F; no CAP,
            // endpoint or STEP commit is allowed, and invalid H_msg stays zero.
            stateful_chain_program(0,0,3,1);launch();
            while(!(dut.chain_active && dut.chain_shadow_valid && dut.physical_valid
                && dut.chain_hash_stage && dut.group_b_value>=7))tick();
            force dut.physical_error=1'b1;tick();release dut.physical_error;
            if(!error || error_code!=16'h3007 || dut.chain_shadow_valid || dut.ctx_step[0]!=1
                || dut.node_memory[116]!==job_secret_prf || dut.node_memory[119]!==job_secret_seed
                || dut.hmsg_digest!==0 || dut.node[2]!==job_randomizer || dut.node[6]!==0)
                $fatal(1,"stateful CHAIN late fault committed private state");
            stateful_chain_program(0,1,4,1);launch();
            while(!dut.chain_shadow_valid)tick();rst=1;repeat(2)tick();
            if(dut.chain_shadow_valid || dut.scratch_valid!=0 || dut.hmsg_digest!==0)
                $fatal(1,"stateful CHAIN reset retained private state");
            launch();finish_job();
            if(observed_output[0]!==expected_stateful_chain(0,1,15,0)
                || observed_output[1]!==expected_stateful_chain(0,1,4,0) || hash_count!=46)
                $fatal(1,"stateful CHAIN reset replay");
            if(stateful_key_lifetimes<1440)$fatal(1,"missing XMSS KEY ownership lifetimes");
            $display("MICRO_STATEFUL_KEY_OWNERSHIP_PASS lifetimes=%0d valid0 stable_through_MASK_F fault_reset_retirement_clear",stateful_key_lifetimes);
            $display("MICRO_STATEFUL_CHAIN_PASS cases=%0d both_families both_slots digit0_15 four_modes key_mask_f_capture_atomic preflight late_fault reset_replay",cases);
        end
    endtask
    // Zero-Hash instruction tests exercise widths and logical RAM partitions
    // directly, independently of a million-leaf traversal or a Hash oracle.
    task stateful_boundary_cases;
        integer cases,height,index_value;
        logic [31:0] expected_node_number;
        begin
            cases=0;
            for(integer profile=8;profile<=13;profile=profile+1) begin
                height=profile==8 || profile==11 ? 10 : profile==9 ? 16 : profile==12 ? 15 : 20;
                for(integer sample=0;sample<9;sample=sample+1) begin
                    case(sample)
                        0:index_value=0;1:index_value=1;2:index_value=(1<<height)-1;
                        3:index_value=1023;4:index_value=1024;
                        5:index_value=32767;6:index_value=32768;
                        7:index_value=65535;default:index_value=65536;
                    endcase
                    if(index_value<(1<<height)) begin
                        reset_program();profile_identity=64'(profile);
                        profile_descriptor={8'd67,8'(height),8'd32,16'd0,8'd1,8'(height),8'd32};
                        job_operation=1;job_index=32'(index_value);
                        emit(OP_HEIGHT);emit(OP_TARGET,1);emit(OP_NODE_BEGIN,2);
                        if(profile>=11)emit(OP_ADRS,5);
                        emit(OP_NODE_PARENT);emit(OP_ADRS,5);emit(OP_END);
                        launch();finish_job();
                        expected_node_number=profile>=11 ? (32'd1<<(height-1))+32'(index_value>>1) : 32'(index_value>>1);
                        if(dut.accepted_index!==32'(index_value) || dut.ctx_leaf!==20'(index_value)
                            || dut.ctx_target!==20'(index_value) || dut.ctx_index!==20'(index_value>>1)
                            || dut.ctx_height!==5'(height) || dut.ctx_level!==5'd1
                            || dut.addr_b[0]!==expected_node_number || hash_count || traces)
                            $fatal(1,"stateful index/parent width profile=%0d q=%0d",profile,index_value);
                        cases=cases+1;
                    end
                end
                reset_program();profile_identity=64'(profile);
                profile_descriptor={8'd67,8'(height),8'd32,16'd0,8'd1,8'(height),8'd32};
                job_operation=1;job_index=32'd1<<height;emit(OP_END);launch();
                while(!error && !done)tick();
                if(!error || error_code!=16'h3008 || hash_count || traces || outputs || dut.scratch_valid)
                    $fatal(1,"stateful out-of-range q accepted profile=%0d",profile);
                cases=cases+1;
            end
            for(integer family=0;family<2;family=family+1) begin
                reset_program();profile_identity=family==0 ? 10 : 13;profile_descriptor=64'h4314200000011420;
                emit(OP_HEIGHT);emit(OP_NMOV,4,11);emit(OP_NMOV,5,13);
                emit(OP_STORE,1,4,IDX_LEVEL);repeat(20)emit(OP_LEVEL_NEXT);
                emit(OP_STORE,1,5,IDX_LEVEL);emit(OP_LOAD,0,1,IDX_LEVEL);emit(OP_EMIT,0,0);
                emit(OP_LEVEL_INIT);repeat(19)emit(OP_LEVEL_NEXT);
                emit(OP_STORE,2,4,IDX_LEVEL);emit(OP_LOAD,0,2,IDX_LEVEL);emit(OP_EMIT,0,0);
                emit(OP_LEVEL_INIT);emit(OP_LOAD,0,1,IDX_LEVEL);emit(OP_EMIT,0,0);emit(OP_END);
                launch();finish_job();
                if(outputs!=3 || observed_output[0]!==job_public_seed
                    || observed_output[1]!==job_secret_seed || observed_output[2]!==job_secret_seed
                    || dut.node_memory[88]!==job_public_seed || dut.node_memory[108]!==job_secret_seed
                    || hash_count || traces)$fatal(1,"stateful STACK20/AUTH19 overlap family=%0d",family);
                cases=cases+1;
                reset_program();profile_identity=family==0 ? 10 : 13;profile_descriptor=64'h4314200000011420;
                emit(OP_HEIGHT);repeat(20)emit(OP_LEVEL_NEXT);emit(OP_STORE,2,11,IDX_LEVEL);emit(OP_END);
                launch();expect_fault();if(hash_count || traces)$fatal(1,"AUTH20 started Hash");cases=cases+1;
                reset_program();profile_identity=family==0 ? 10 : 13;profile_descriptor=64'h4314200000011420;
                emit(OP_HEIGHT);repeat(21)emit(OP_LEVEL_NEXT);emit(OP_END);
                launch();expect_fault();if(dut.ctx_level!=20)$fatal(1,"level21 not atomic");cases=cases+1;
            end
            // Existing SLH ABI3 images retain their original logical limits;
            // the added stateful RAM ranges and selectors grant no permission.
            for(integer bad=0;bad<7;bad=bad+1) begin
                reset_program();
                case(bad)
                    0:begin profile_descriptor[39:32]=14;emit(OP_HEIGHT,1);repeat(16)emit(OP_LEVEL_NEXT);end
                    1:emit(OP_ADRS,9);
                    2:emit(OP_REDUCE_INIT,2);
                    3:emit(OP_REDUCE_NEXT,2);
                    4:emit(OP_XMSS_MASK);
                    5:emit(OP_BR,COND_LTREE_PAIR,0,0,0);
                    6:emit(OP_BR,COND_LTREE_MORE,0,0,0);
                endcase
                emit(OP_END);launch();expect_fault();if(hash_count || traces)$fatal(1,"SLH extension violation started Hash");cases=cases+1;
            end
            // TREE remains absent from ABI3, even in a valid stateful Job.
            for(integer family=0;family<3;family=family+1) begin
                reset_program();
                if(family!=0)begin profile_identity=family==1 ? 8 : 11;profile_descriptor=64'h430a200000010a20;end
                emit(8'd37);emit(OP_END);launch();expect_fault();cases=cases+1;
            end
            // The final cursor value 2^20 must be representable and stop the
            // bounded loop, while a further update is an atomic fault. This
            // executes metadata only: no h20 leaf or tree Hash is evaluated.
            for(integer overflow=0;overflow<2;overflow=overflow+1) begin
                reset_program();profile_identity=10;profile_descriptor=64'h4314200000011420;
                emit(OP_HEIGHT);emit(OP_CURSOR_INIT);emit(OP_CURSOR_NEXT,0,0,0,2);
                emit(OP_BR,COND_CURSOR_MORE,0,0,2);
                if(overflow)emit(OP_CURSOR_NEXT,0,0,0,1);
                emit(OP_END);launch();
                if(overflow)expect_fault();else finish_job();
                if(dut.ctx_cursor!==21'h100000 || hash_count || traces)
                    $fatal(1,"stateful cursor21 terminal/overflow");
                cases=cases+1;
            end
            $display("MICRO_STATEFUL_BOUNDARY_PASS cases=%0d q_width20 parent_width21 heights10_15_16_20 STACK21 AUTH20 family_permissions illegal_TREE",cases);
        end
    endtask
    initial begin
        for(integer j=0;j<32;j=j+1) descriptor_memory[j]=0;
        descriptor_memory[2]=64'h0105011001000000;
        descriptor_memory[3]=64'h0200011001000000;
        descriptor_memory[4]=64'h0400013102000000;
        descriptor_memory[5]=64'h0202021001000000;
        for(integer j=0;j<32;j=j+1) begin
            job_secret_seed[j*8+:8]=8'(j);job_secret_prf[j*8+:8]=8'(j+32);
            job_public_seed[j*8+:8]=8'(j+64);job_randomizer[j*8+:8]=8'(j+96);
            job_public_root[j*8+:8]=8'(j+128);
        end
        if($test$plusargs("STATEFUL_ONLY")) begin stateful_chain_cases();stateful_boundary_cases();$finish;end
        if($test$plusargs("BOUNDARY_ONLY")) begin stateful_boundary_cases();$finish;end
        storage_cases();
        if($test$plusargs("STORAGE_ONLY")) begin
            $display("MICRO_STORAGE_PASS all_n fixed_partitions independent_rw node_zero_job retained_spaces atomic_faults");
            $finish;
        end
        chain_cases();
        if($test$plusargs("CHAIN_ONLY")) $finish;
        for(integer j=0;j<32;j=j+1)job_randomizer[j*8+:8]=8'(j+96);
        // Snapshot every request field; long metadata work cannot relaunch a
        // completed lane. A taken branch discards its invalid prefetched word.
        reset_program();
        emit(OP_HEIGHT);emit(OP_MASK,0,0,0,1);emit(OP_ADRS,0);
        emit(OP_HASH,2);emit(OP_GROUP_NEXT);emit(OP_GROUP_INIT);repeat(48)emit(OP_GROUP_INIT);emit(OP_WAIT);emit(OP_EMIT,0,4);
        emit(OP_MASK,0,0,0,2);emit(OP_ADRS,0);emit(OP_HASH,2);repeat(48)emit(OP_GROUP_INIT);
        emit(OP_CHAIN_NEXT,0,0,0,2);emit(OP_LAYER_INIT,1);emit(OP_ADRS,0);
        emit(OP_JMP,0,0,0,p+2);emit(0);emit(OP_WAIT);
        emit(OP_EMIT,0,5);emit(OP_NMOV,8,5);
        emit(OP_CHAIN_INIT);emit(OP_LAYER_INIT);emit(OP_MASK,0,0,0,1);emit(OP_ADRS,0);
        emit(OP_HASH,3);emit(OP_STEP_NEXT);emit(OP_WAIT);emit(OP_EMIT,0,4);
        emit(OP_NMOV,2,13);emit(OP_DIGITS);repeat(16)emit(OP_CHAIN_NEXT,0,0,0,2);
        emit(OP_MASK,1);emit(OP_DIGIT_LOAD);emit(OP_CHAIN_NEXT,0,0,0,2);
        emit(OP_MASK,1);emit(OP_DIGIT_LOAD);emit(OP_END);
        check_outputs=1;launch();finish_job();
        if(outputs!=3 || traces!=3 || hash_count!=3 || permutation_count!=3)
            $fatal(1,"counts outputs=%0d traces=%0d hashes=%0d perms=%0d",outputs,traces,hash_count,permutation_count);
        if(dut.node[5]!==dut.node[8] || dut.ctx_step[0]!=1 || dut.ctx_step[1]!=0)
            $fatal(1,"inactive lane changed");
        if(dut.ctx_digit[0]!=8 || dut.ctx_digit[1]!=2 || dut.ctx_mask!=1)
            $fatal(1,"odd chain/checksum digits");

        // All supported n values, checksum extremes, and both nibble orders.
        // The source object changes before the first digit is consumed.
        for(integer profile_n=16;profile_n<=32;profile_n=profile_n+8) begin
            for(integer pattern=0;pattern<3;pattern=pattern+1) begin : snapshot_cases
                integer checksum;
                reset_program();
                profile_descriptor[7:0]=8'(profile_n);
                profile_descriptor[63:56]=8'(profile_n*2+3);
                for(integer byte_index=0;byte_index<32;byte_index=byte_index+1)
                    job_public_seed[byte_index*8+:8]=pattern==0 ? 8'h00 : pattern==1 ? 8'hff : 8'(byte_index*13+7);
                checksum=0;
                for(integer digit_index=0;digit_index<profile_n*2;digit_index=digit_index+1) begin
                    expected_digits[digit_index]=job_public_seed[(digit_index/2)*8+(digit_index%2==0?4:0)+:4];
                    checksum=checksum+15-integer'(expected_digits[digit_index]);
                end
                expected_digits[profile_n*2]=4'(checksum>>8);
                expected_digits[profile_n*2+1]=4'(checksum>>4);
                expected_digits[profile_n*2+2]=4'(checksum);
                emit(OP_NMOV,2,13);emit(OP_DIGITS);emit(OP_NMOV,2,11);emit(OP_MASK,0,0,0,1);
                for(integer digit_index=0;digit_index<profile_n*2+3;digit_index=digit_index+1) begin
                    emit(OP_DIGIT_LOAD);emit(OP_CHAIN_NEXT,0,0,0,1);
                end
                emit(OP_END);expected_checks=0;check_digit_snapshot=1;launch();finish_job();check_digit_snapshot=0;
                if(expected_checks!=profile_n*2+3) $fatal(1,"missing snapshot digit checks");
            end
        end
        // Restore Job data used by the remaining independent tests.
        for(integer byte_index=0;byte_index<32;byte_index=byte_index+1)
            job_public_seed[byte_index*8+:8]=8'(byte_index+64);

        // Main/tail LIST entries keep exact object addressing. STACK/AUTH use
        // only the typed level field; their maximum reachable level is 14.
        reset_program();profile_descriptor[39:32]=14;profile_descriptor[31:24]=17;
        emit(OP_STORE,0,13,IDX_IMMEDIATE,63);emit(OP_STORE,0,12,IDX_IMMEDIATE,64);
        emit(OP_STORE,0,11,IDX_IMMEDIATE,67);
        emit(OP_LOAD,0,0,IDX_IMMEDIATE,63);emit(OP_LOAD,1,0,IDX_IMMEDIATE,64);
        emit(OP_LOAD,2,0,IDX_IMMEDIATE,67);emit(OP_HEIGHT,1);
        repeat(14)emit(OP_LEVEL_NEXT);
        emit(OP_STORE,1,13,IDX_LEVEL);emit(OP_STORE,2,12,IDX_LEVEL);
        emit(OP_LOAD,3,1,IDX_LEVEL);emit(OP_LOAD,4,2,IDX_LEVEL);emit(OP_END);
        launch();finish_job();
        if(dut.node[0]!=={128'd0,job_public_seed[127:0]} || dut.node[1]!=={128'd0,job_secret_prf[127:0]}
            || dut.node[2]!=={128'd0,job_secret_seed[127:0]} || dut.node[3]!==dut.node[0] || dut.node[4]!==dut.node[1])
            $fatal(1,"typed node store boundary");

        // CPU-only opaque objects support back-to-back copies, then return
        // to logical zero on a new Job without requiring a physical RAM clear.
        reset_program();
        emit(OP_NMOV,1,13);emit(OP_NMOV,7,12);emit(OP_NMOV,8,11);
        emit(OP_NMOV,9,14);emit(OP_NMOV,10,13);emit(OP_NMOV,9,7);emit(OP_NMOV,7,9);emit(OP_END);
        launch();finish_job();
        if(dut.node[1]!=={128'd0,job_public_seed[127:0]} || dut.node[7]!=={128'd0,job_secret_prf[127:0]}
            || dut.node[8]!=={128'd0,job_secret_seed[127:0]} || dut.node[9]!==dut.node[7] || dut.node[10]!==dut.node[1])
            $fatal(1,"opaque object copy dependency");
        // Re-enter the same core after END, changing only the program ROM.
        for(integer j=0;j<512;j=j+1)program_memory[j]=0;
        p=0;emit(OP_NMOV,0,1);emit(OP_NMOV,2,7);emit(OP_NMOV,4,8);emit(OP_NMOV,5,9);emit(OP_NMOV,6,10);emit(OP_END);
        launch();finish_job();
        if(dut.node[0]!=0 || dut.node[2]!=0 || dut.node[4]!=0 || dut.node[5]!=0 || dut.node[6]!=0)
            $fatal(1,"new Job exposed stale opaque object");

        // Each constructor ignores fields outside its own address type.
        reset_program();emit(OP_HEIGHT,1);emit(OP_GROUP_NEXT);emit(OP_ADRS,3);emit(OP_END);
        launch();finish_job();
        if(dut.addr_b[0]!=64 || dut.addr_b[1]!=64) $fatal(1,"FORS target lane address");
        reset_program();emit(OP_HEIGHT,1);emit(OP_GROUP_NEXT);emit(OP_NODE_BEGIN,3,1,0,15);
        emit(OP_ADRS,5);emit(OP_END);launch();finish_job();
        if(dut.addr_b[0]!=15 || dut.addr_b[1]!=15 || dut.addr_leaf[0]!=0) $fatal(1,"HT address leaked FORS base");
        reset_program();emit(OP_HEIGHT,2,0,0,3);emit(OP_GROUP_NEXT);emit(OP_REDUCE_INIT,1);
        emit(OP_REDUCE_NEXT,1);emit(OP_REDUCE_NEXT);emit(OP_ADRS,8);emit(OP_END);launch();finish_job();
        if(dut.addr_b[0]!=1 || dut.addr_b[1]!=1 || dut.ctx_fors_base!=32) $fatal(1,"HT reduction leaked FORS base");

        // The independent H_msg scratch retains all 49 bytes across another
        // Hash, including the upper half of a full 64-bit TREE address.
        reset_program();profile_descriptor=64'h4344310923110420;
        descriptor_memory[2]=64'h0105012001000000;
        emit(OP_NMOV,0,14);emit(OP_MASK,0,0,0,1);emit(OP_HASH,4);emit(OP_WAIT);emit(OP_PARSE);
        emit(OP_ADRS,1);emit(OP_HASH,2);emit(OP_TREE_NEXT);emit(OP_WAIT);
        emit(OP_PARSE);emit(OP_TARGET);emit(OP_END);
        check_tree_trace=1;launch();finish_job();
        if(dut.ctx_tree!==64'h603fc83be20079b9 || dut.ctx_leaf!=5 || dut.ctx_target!=268
            || dut.hmsg_digest!==392'h55b97900e23bc83f60c3942b3723e120cf813f0efce8b88cf2bc5770b4fbdaca71003f81682fc4d0ec932a93a09ecf2a86)
            $fatal(1,"digest retention tree=%h leaf=%h target=%h",dut.ctx_tree,dut.ctx_leaf,dut.ctx_target);
        if(hash_count!=2 || permutation_count!=2 || traces!=2) $fatal(1,"64-bit Hash count");
        descriptor_memory[2]=64'h0105011001000000;

        // Exercise each bounded FORS digit width and every valid group.
        for(integer address_bits=1;address_bits<=14;address_bits=address_bits+1) begin : fors_windows
            integer groups;
            groups=320/address_bits;if(groups>35)groups=35;
            reset_program();profile_descriptor=64'h4344310923110420;
            profile_descriptor[39:32]=8'(address_bits);profile_descriptor[31:24]=8'(groups);
            emit(OP_NMOV,0,14);emit(OP_MASK,0,0,0,1);emit(OP_HASH,4);emit(OP_WAIT);
            for(integer group_number=0;group_number<groups;group_number=group_number+1) begin
                emit(OP_TARGET);emit(OP_GROUP_NEXT);
            end
            emit(OP_GROUP_INIT);emit(OP_TARGET);emit(OP_END);
            target_checks=0;check_target_window=1;launch();finish_job();check_target_window=0;
            if(target_checks!=groups+1 || dut.ctx_fors_offset!=0) $fatal(1,"missing target window/reset checks");
        end

        // Every update is bounded, including terminal cursor 2^14 and the
        // odd final WOTS pair (chain 34 -> terminal 36, never wrap to zero).
        reset_program();profile_descriptor[39:32]=14;profile_descriptor[31:24]=17;
        emit(OP_HEIGHT,1);emit(OP_CURSOR_NEXT,0,0,0,2);emit(OP_BR,COND_CURSOR_MORE,0,0,1);
        emit(OP_CURSOR_NEXT,0,0,0,1);emit(OP_END);launch();expect_fault();
        if(dut.ctx_cursor!=16384) $fatal(1,"cursor overflow changed state");
        reset_program();repeat(18)emit(OP_CHAIN_NEXT,0,0,0,2);emit(OP_CHAIN_NEXT,0,0,0,1);launch();expect_fault();
        if(dut.ctx_chain!=36) $fatal(1,"chain overflow changed state");
        reset_program();profile_descriptor[39:32]=14;profile_descriptor[31:24]=17;
        emit(OP_HEIGHT,1);repeat(16)emit(OP_GROUP_NEXT);
        emit(OP_NODE_BEGIN,3,1,0,16383);repeat(14)emit(OP_NODE_PARENT);
        emit(OP_NODE_PARENT);launch();expect_fault();
        if(dut.ctx_level!=14 || dut.ctx_index!=0 || dut.ctx_fors_base!=16)
            $fatal(1,"parent overflow changed context");

        // The terminal GROUP value is legal, but a further increment faults
        // atomically and preserves both the group and its shadow offset.
        reset_program();repeat(33)emit(OP_GROUP_NEXT);emit(OP_GROUP_NEXT);launch();expect_fault();
        if(dut.ctx_group!=33 || dut.ctx_fors_offset!=198)
            $fatal(1,"group overflow changed group/offset");

        // Illegal operands and operations cannot modify nodes or consume a
        // result. Old images fail before their first instruction.
        reset_program();emit(OP_LAYER_INIT,1,1);launch();expect_fault();
        if(dut.ctx_layer!=0) $fatal(1,"reserved field changed state");
        reset_program();image_header=64'h4842535008000000;emit(OP_EMIT,0,13);launch();expect_fault();
        reset_program();emit(OP_WAIT);launch();expect_fault();
        reset_program();emit(OP_MASK,0,0,0,1);emit(OP_ADRS);emit(OP_HASH,2);emit(OP_NMOV,0,4);launch();expect_fault();
        if(dut.node[0]!=0 || traces) $fatal(1,"node mutation before WAIT");
        reset_program();emit(OP_HEIGHT,2,0,0,1);emit(OP_MASK,0,0,0,1);emit(OP_ADRS);emit(OP_HASH,2);
        repeat(48)emit(OP_GROUP_INIT);emit(OP_WAIT,0,0,0,1);launch();expect_fault();
        if(dut.node[4]!=0 || dut.node[5]!=0 || traces) $fatal(1,"malformed WAIT published result");
        // A paired logical mask is not a request to serialize in hardware.
        // The bad ISSUE leaves the prior result and all Hash counts intact.
        reset_program();emit(OP_NMOV,4,13);emit(OP_MASK,0,0,0,3);emit(OP_ADRS);emit(OP_HASH,2);
        launch();expect_fault();
        if(dut.node[4]!=={128'd0,job_public_seed[127:0]} || dut.node[5]!=0
            || traces || hash_count || permutation_count || dut.group_valid)
            $fatal(1,"paired ISSUE changed result or launched a physical Hash");
        reset_program();emit(OP_LOAD,4,1,IDX_IMMEDIATE,0);launch();expect_fault();
        reset_program();emit(OP_MASK,0,0,0,2);emit(OP_HASH,5);launch();expect_fault();
        reset_program();emit(OP_DIGIT_LOAD);launch();expect_fault();

        // A broader profile chain_count cannot expose uninitialized WOTS
        // digits beyond the payload plus three checksum nibbles. One invalid
        // lane prevents the valid lane from changing on the same instruction.
        reset_program();profile_descriptor[63:56]=67;
        emit(OP_NMOV,2,13);emit(OP_DIGITS);emit(OP_MASK,0,0,0,1);emit(OP_DIGIT_LOAD);
        repeat(17)emit(OP_CHAIN_NEXT,0,0,0,2);emit(OP_MASK,0,0,0,3);emit(OP_DIGIT_LOAD);
        launch();expect_fault();
        if(dut.ctx_digit[0]!=4 || dut.ctx_digit[1]!=0) $fatal(1,"out-of-range digit changed valid lane");

        // One physical RAM survives consecutive Jobs and resets. Both message
        // recipes use independent full-width hashlib results after 87 -> 1
        // byte and word-boundary transitions, with dirty unused input bytes.
        for(integer profile_n=16;profile_n<=32;profile_n=profile_n+8) begin
            reset_program();profile_descriptor[7:0]=8'(profile_n);
            emit(OP_MASK,0,0,0,1);emit(OP_NMOV,0,14);
            emit(OP_HASH,6);emit(OP_WAIT);emit(OP_END);
            for(integer shape=3;shape<=4;shape=shape+1) begin
                for(integer length_case=0;length_case<5;length_case=length_case+1) begin : message_cases
                    integer length,sample;
                    case(length_case)0:length=87;1:length=1;2:length=7;3:length=8;default:length=9;endcase
                    sample=((profile_n-16)/8)*10+(shape-3)*5+length_case;
                    descriptor_memory[6]=shape==3 ? 64'h0300011001000000 : 64'h0400013102000000;
                    job_operation=1;job_message_length=7'(length);launch();
                    send_pattern_message(sample,length);finish_job();message_valid=0;
                    if(dut.physical_value!==expected_message_hash(sample) || hash_count!=1
                        || permutation_count!=((shape==3 ? 2 : 3)*profile_n+length)/136+1)
                        $fatal(1,"message RAM hash n=%0d shape=%0d length=%0d",profile_n,shape,length);
                end
            end
        end
        // Interrupt absorption after overwriting only the short message's
        // words. A replay must not depend on either partial state or old RAM.
        job_message_length=9;launch();send_pattern_message(28,9);repeat(8)tick();
        rst=1;message_valid=0;repeat(2)tick();rst=0;tick();
        launch();send_pattern_message(29,9);finish_job();message_valid=0;message_data=0;
        if(dut.physical_value!==expected_message_hash(29) || hash_count!=1 || permutation_count!=1)
            $fatal(1,"message RAM reset replay");

        // Verify consumes one node only when supplied; END uses only a fresh
        // fixed root comparison. A failed multi-lane increment changes none.
        reset_program();job_operation=2;job_message_length=1;
        emit(OP_INPUT,2);emit(OP_ROOT_COMPARE);emit(OP_END);launch();send_message();
        while(!verify_ready)tick();repeat(17)tick();
        if(done || error || !verify_ready) $fatal(1,"verify input stall");
        verify_data=job_public_root;verify_valid=1;tick();verify_valid=0;finish_job();
        if(!verify_pass || out_valid || hash_count) $fatal(1,"fixed root comparison");
        reset_program();job_operation=2;job_message_length=1;
        emit(OP_INPUT,2);emit(OP_DIGITS);emit(OP_MASK,0,0,0,3);emit(OP_DIGIT_LOAD);
        emit(OP_STEP_INIT,0,1);emit(OP_STEP_NEXT);launch();send_message();
        while(!verify_ready)tick();verify_data=256'h000000000000000000000000000000f0;verify_valid=1;tick();verify_valid=0;
        expect_fault();if(dut.ctx_step[0]!=15 || dut.ctx_step[1]!=0) $fatal(1,"atomic step overflow");
        reset_program();job_operation=2;job_message_length=1;
        emit(OP_END);launch();send_message();expect_fault();
        reset_program();job_operation=2;job_message_length=1;
        emit(OP_ROOT_COMPARE);emit(OP_NMOV,2,15);emit(OP_END);launch();send_message();expect_fault();
        $display("MICRO_PROCESSOR_PASS K1U1 onehot_issue typed_permissions snapshots64 overlap branch_flush atomic_wait inactive_lane digest_retention checksum snapshot_digits_all_n target_widths1_14 group_offset_atomic cursor14 chain_terminal parent14 atomic_step faults verify_stall message_ram_long_short_all_n both_recipes reset_replay");
        stateful_chain_cases();
        stateful_boundary_cases();
        $finish;
    end
endmodule
