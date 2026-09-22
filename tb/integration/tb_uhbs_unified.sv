`timescale 1ns/1ps
module tb_uhbs_unified;
    parameter integer PROFILE=0, SWAP=0, BACKPRESSURE=0, LANES=2, UNROLL=2;
    localparam integer KG_BYTES=PROFILE==0 ? 96 : PROFILE==1 ? 196 : 140;
    localparam integer SG_BYTES=PROFILE==0 ? 17088 : PROFILE==1 ? 2500 : 2508;
    localparam integer MSG_BYTES=PROFILE==0 ? 1 : PROFILE==1 ? 21 : 20;
    logic clk=0, rst_n=0, start=0;
    wire ready,busy,keygen_done,done,error;
    wire [15:0] error_code;
    wire [31:0] keygen_cycles,sign_cycles,hash_count,permutation_count;
    logic message_valid=0,message_last=0;
    wire message_ready;
    logic [63:0] message_data=0;
    logic [7:0] message_keep=0;
    wire state_commit_valid; logic state_commit_ready=0;
    wire [10:0] state_next_q;
    wire out_valid,out_last,result_kind,tree_cache_valid;
    logic out_ready=1;
    wire [63:0] out_data; wire [7:0] out_keep;
    logic [7:0] expected_kg[0:KG_BYTES-1], expected_sg[0:SG_BYTES-1], msg[0:MSG_BYTES-1];
    integer kg_index=0,sg_index=0,cycles=0,commit_wait=0;
    integer index,byte_index,valid_bytes;
    logic committed=0;
    logic [15:0] lfsr=16'h1;
    wire [5:0] core_state;
    integer residency[0:63];
    logic stalled=0;
    logic [73:0] stalled_word;
    generate if(PROFILE==0) begin: g_slh
        uhbs_slh_dsa_top #(.PROFILE_ENABLE(1),.SWAP_PHYSICAL_LANES(SWAP),.LANES(LANES),.UNROLL(UNROLL)) dut(.*);
        assign core_state=dut.core.state;
    end else if(PROFILE==1) begin: g_xmss
        uhbs_xmss_top #(.PROFILE_ENABLE(1),.SWAP_PHYSICAL_LANES(SWAP),.LANES(LANES),.UNROLL(UNROLL)) dut(.*);
        assign core_state=dut.core.state;
    end else begin: g_lms
        uhbs_lms_top #(.PROFILE_ENABLE(1),.SWAP_PHYSICAL_LANES(SWAP),.LANES(LANES),.UNROLL(UNROLL)) dut(.*);
        assign core_state=dut.core.state;
    end endgenerate
    always #5 clk=~clk;
    always @(negedge clk) begin
        if(rst_n) begin
            lfsr<={lfsr[14:0],lfsr[15]^lfsr[13]^lfsr[12]^lfsr[10]};
            out_ready<=!BACKPRESSURE || lfsr[2:0]!=0;
            if(state_commit_valid) begin
                commit_wait<=commit_wait+1;
                state_commit_ready<=!BACKPRESSURE || commit_wait>=9;
            end else state_commit_ready<=0;
        end
    end
    always @(posedge clk) if(rst_n) begin
        cycles<=cycles+1;
        if(core_state!=0) residency[core_state]=residency[core_state]+1;
        if(stalled && (!out_valid || {out_data,out_keep,out_last,result_kind}!==stalled_word))
            $fatal(1,"output changed under backpressure");
        stalled<=out_valid && !out_ready;
        stalled_word<={out_data,out_keep,out_last,result_kind};
        if(error) $fatal(1,"UNIFIED_ERROR profile=%0d code=%h cycle=%0d kg=%0d sg=%0d",PROFILE,error_code,cycles,kg_index,sg_index);
        if(cycles>60000000) $fatal(1,"timeout profile=%0d",PROFILE);
        if(state_commit_valid && state_commit_ready) begin
            if(state_next_q!=6) $fatal(1,"incorrect durable next q");
            committed<=1;
        end
        if(out_valid && result_kind && PROFILE!=0 && !committed)
            $fatal(1,"signature before durable commit");
        if(out_valid && out_ready) begin
            for(integer b=0;b<8;b=b+1) if(out_keep[b]) begin
                if(!result_kind) begin
                    if(kg_index>=KG_BYTES || out_data[b*8 +: 8]!==expected_kg[kg_index])
                        $fatal(1,"KG mismatch profile=%0d byte=%0d got=%h expected=%h",PROFILE,kg_index,out_data[b*8 +: 8],expected_kg[kg_index]);
                    kg_index=kg_index+1;
                end else begin
                    if(sg_index>=SG_BYTES || out_data[b*8 +: 8]!==expected_sg[sg_index])
                        $fatal(1,"SG mismatch profile=%0d byte=%0d got=%h expected=%h",PROFILE,sg_index,out_data[b*8 +: 8],expected_sg[sg_index]);
                    sg_index=sg_index+1;
                end
            end
            if(out_last !== (result_kind ? sg_index==SG_BYTES : kg_index==KG_BYTES)) $fatal(1,"out_last");
        end
        if(keygen_done) begin
            if(kg_index!=KG_BYTES) $fatal(1,"keygen length");
            if(hash_count!=(PROFILE==0 ? 4495 : PROFILE==1 ? 3430396 : 1100799)) $fatal(1,"keygen hash count");
            if(permutation_count!=(PROFILE==0 ? 4527 : PROFILE==1 ? 3430396 : 1116159)) $fatal(1,"keygen permutation count");
            $display("UNIFIED_KEYGEN profile=%0d cycles=%0d hashes=%0d permutations=%0d",PROFILE,keygen_cycles,hash_count,permutation_count);
            for(integer s=0;s<64;s=s+1) begin
                if(residency[s]) $display("RESIDENCY keygen state=%0d cycles=%0d",s,residency[s]);
                residency[s]=0;
            end
        end
    end
    task tick; begin @(posedge clk); #1; end endtask
    initial begin
        for(integer s=0;s<64;s=s+1) residency[s]=0;
        if(PROFILE==0) begin
            $readmemh("tb/vectors/uhbs_slh_keygen.mem",expected_kg);
            $readmemh("tb/vectors/uhbs_slh_sign.mem",expected_sg);
            $readmemh("tb/vectors/uhbs_slh_message.mem",msg);
        end else if(PROFILE==1) begin
            $readmemh("tb/vectors/uhbs_xmss_keygen.mem",expected_kg);
            $readmemh("tb/vectors/uhbs_xmss_sign.mem",expected_sg);
            $readmemh("tb/vectors/uhbs_xmss_message.mem",msg);
        end else begin
            $readmemh("tb/vectors/uhbs_lms_keygen.mem",expected_kg);
            $readmemh("tb/vectors/uhbs_lms_sign.mem",expected_sg);
            $readmemh("tb/vectors/uhbs_lms_message.mem",msg);
        end
        repeat(4) tick(); rst_n=1; tick(); start=1; tick(); start=0;
        for(index=0;index<MSG_BYTES;index=index+8) begin
            while(!message_ready) tick();
            if(BACKPRESSURE) repeat(index%3+1) tick();
            valid_bytes=MSG_BYTES-index>=8 ? 8 : MSG_BYTES-index;
            message_data=0;
            for(byte_index=0;byte_index<valid_bytes;byte_index=byte_index+1)
                message_data[byte_index*8 +: 8]=msg[index+byte_index];
            message_keep=8'hff>>(8-valid_bytes); message_last=index+valid_bytes==MSG_BYTES;
            message_valid=1; tick(); message_valid=0;
        end
        while(!done) tick();
        if(sg_index!=SG_BYTES) $fatal(1,"signature length");
        if(hash_count!=(PROFILE==0 ? 104937 : PROFILE==1 ? 1554 : 548)) $fatal(1,"hash count %0d",hash_count);
        if(permutation_count!=(PROFILE==0 ? 105641 : PROFILE==1 ? 1555 : 548)) $fatal(1,"permutation count %0d",permutation_count);
        $display("UNIFIED_PASS profile=%0d keygen_cycles=%0d sign_cycles=%0d hash=%0d permutations=%0d swap=%0d backpressure=%0d",PROFILE,keygen_cycles,sign_cycles,hash_count,permutation_count,SWAP,BACKPRESSURE);
        for(integer s=0;s<64;s=s+1)
            if(residency[s]) $display("RESIDENCY sign state=%0d cycles=%0d",s,residency[s]);
        $finish;
    end
endmodule
