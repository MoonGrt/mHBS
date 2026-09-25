`timescale 1ns/1ps
module tb_uhbs_autonomous;
    parameter integer LANES=2,UNROLL=2,SWAP=0;
    logic clk=0,rst=1;
    wire busy,done,keygen_done,error,out_valid,out_last,result_kind;
    wire [15:0] error_code;
    wire [31:0] boot_cycles,keygen_cycles,sign_cycles,hash_count,permutation_count;
    wire [63:0] out_data;wire [7:0] out_keep;
    uhbs_top #(.LANES(LANES),.UNROLL(UNROLL),.SWAP_PHYSICAL_LANES(SWAP),
        .PROGRAM_INIT_FILE(""),.TEMPLATE_INIT_FILE(""),.DESCRIPTOR_INIT_FILE("")) dut(.*);
    always #5 clk=~clk;
    string directory;
    reg [31:0] metadata[0:9];
    reg [7:0] expected_kg[0:255],expected_sg[0:65535];
    integer kg_index=0,sg_index=0,total_cycles=0,replays=1,interrupt_run=0,bad=0,fault=0;
    integer residency[0:63];
    task tick;begin @(posedge clk);#1;end endtask
    always @(posedge clk) begin
        if(rst) begin kg_index=0;sg_index=0;total_cycles=0;for(integer i=0;i<64;i=i+1)residency[i]=0;end
        else begin
            total_cycles=total_cycles+1;
            if(total_cycles>200000000) $fatal(1,"timeout");
            if(dut.processor.core.state!=0) residency[dut.processor.core.state]=residency[dut.processor.core.state]+1;
            if(error && bad==0 && fault==0) $fatal(1,"AUTONOMOUS_ERROR code=%h cycle=%0d kg=%0d sg=%0d",error_code,total_cycles,kg_index,sg_index);
            if(out_valid) begin
                if(bad!=0) $fatal(1,"invalid image produced output");
                for(integer i=0;i<8;i=i+1) if(out_keep[i]) begin
                    if(result_kind) begin
                        if(sg_index>=metadata[1] || out_data[i*8 +:8]!==expected_sg[sg_index])
                            $fatal(1,"SG byte=%0d got=%h expected=%h state=%0d",sg_index,out_data[i*8 +:8],expected_sg[sg_index],dut.processor.core.state);
                        sg_index=sg_index+1;
                    end else begin
                        if(kg_index>=metadata[0] || out_data[i*8 +:8]!==expected_kg[kg_index])
                            $fatal(1,"KG byte=%0d got=%h expected=%h",kg_index,out_data[i*8 +:8],expected_kg[kg_index]);
                        kg_index=kg_index+1;
                    end
                end
                if(out_last!==(result_kind ? sg_index==metadata[1] : kg_index==metadata[0])) $fatal(1,"out_last");
            end
            if(keygen_done) begin
                if(kg_index!=metadata[0] || hash_count!=metadata[2] || permutation_count!=metadata[3])
                    $fatal(1,"keygen length/counts bytes=%0d hash=%0d perm=%0d expected %0d/%0d",kg_index,hash_count,permutation_count,metadata[2],metadata[3]);
                $display("AUTONOMOUS_KEYGEN cycles=%0d hashes=%0d permutations=%0d",keygen_cycles,hash_count,permutation_count);
                for(integer i=0;i<64;i=i+1) begin
                    if(residency[i]) $display("RESIDENCY keygen state=%0d cycles=%0d",i,residency[i]);
                    residency[i]=0;
                end
            end
        end
    end
    initial begin
        if(!$value$plusargs("IMAGE=%s",directory)) $fatal(1,"IMAGE required");
        if($value$plusargs("REPLAYS=%d",replays)) begin end
        if($value$plusargs("INTERRUPT=%d",interrupt_run)) begin end
        if($value$plusargs("BAD=%d",bad)) begin end
        if($value$plusargs("FAULT=%d",fault)) begin end
        $readmemh({directory,"/program.mem"},dut.program_rom.memory);
        $readmemh({directory,"/template.mem"},dut.template_rom.memory);
        $readmemh({directory,"/descriptor.mem"},dut.descriptor_rom.memory);
        $readmemh({directory,"/metadata.mem"},metadata);
        $readmemh({directory,"/keygen.mem"},expected_kg,0,metadata[0]-1);
        $readmemh({directory,"/sign.mem"},expected_sg,0,metadata[1]-1);
        case(bad)
            1:dut.descriptor_rom.memory[0][59:56]=3;
            2:dut.descriptor_rom.memory[1][55:48]=17;
            3:dut.program_rom.memory[41][10:0]=1024;
            4:dut.program_rom.memory[41][17:11]=0;
            5:dut.program_rom.memory[50]=1;
            6:dut.descriptor_rom.memory[0][46:38]=44;
            7:dut.program_rom.memory[41][17:11]=88;
            8:dut.program_rom.memory[41][30:24]=65;
            9:dut.template_rom.memory[63]=1;
            10:dut.descriptor_rom.memory[16][59:52]=128;
            11:dut.descriptor_rom.memory[16][27:20]=134;
            12:dut.descriptor_rom.memory[20][43:40]=0;
            13:dut.descriptor_rom.memory[50][59:52]=127;
            14:dut.descriptor_rom.memory[2][59:56]=1;
            22:begin end // Unmodified legacy XMSS/LMS image must be rejected.
            23:dut.descriptor_rom.memory[1][58:56]=2;
            24:dut.program_rom.memory[41][10:0]=5;
            25:dut.descriptor_rom.memory[2][59:56]=5;
            26:dut.descriptor_rom.memory[20][31]=1;
            27:dut.descriptor_rom.memory[17][27:20]=68;
            28:dut.descriptor_rom.memory[64][59:56]=5;
            29:dut.program_rom.memory[40]=1;
            30:dut.template_rom.memory[0][78]=1;
            default:begin end
        endcase
        repeat(4) tick();rst=0;
        if(bad) begin
            while(!error) tick();
            repeat(40)tick();
            if(done || out_valid || busy) $fatal(1,"error did not halt");
            $display("AUTONOMOUS_REJECT_PASS bad=%0d code=%h",bad,error_code);$finish;
        end
        if(interrupt_run) begin
            repeat(1000) tick();rst=1;repeat(4)tick();rst=0;
        end
        if(fault) begin
            while(!keygen_done) tick();
            if(fault>=1) begin
                while(!result_kind || !dut.processor.core.busy) tick();
                if(fault==3) while(sg_index<40) tick();
                force dut.processor.core.seq_error=1;
            end
            while(!error) tick();
            repeat(40) begin
                tick();
                if(out_valid || busy || done) $fatal(1,"failed run did not halt");
            end
            if(fault<=2 && sg_index!=0) $fatal(1,"pre-execution failure produced signature");
            $display("AUTONOMOUS_FAULT_PASS fault=%0d q=%0d sign_prefix=%0d",fault,metadata[6],sg_index);
            $finish;
        end
        for(integer run=0;run<replays;run=run+1) begin
            while(!done) tick();
            if(sg_index!=metadata[1] || hash_count!=metadata[4] || permutation_count!=metadata[5])
                $fatal(1,"signature length/counts bytes=%0d hash=%0d perm=%0d expected=%0d/%0d",sg_index,hash_count,permutation_count,metadata[4],metadata[5]);
            $display("AUTONOMOUS_PASS image=%s boot_cycles=%0d keygen_cycles=%0d sign_cycles=%0d hash=%0d permutations=%0d lanes=%0d unroll=%0d swap=%0d run=%0d",directory,boot_cycles,keygen_cycles,sign_cycles,hash_count,permutation_count,LANES,UNROLL,SWAP,run);
            for(integer i=0;i<64;i=i+1) if(residency[i]) $display("RESIDENCY sign state=%0d cycles=%0d",i,residency[i]);
            repeat(100) begin tick();if(!done || busy || out_valid) $fatal(1,"completion did not halt");end
            if(run+1<replays) begin rst=1;repeat(4)tick();rst=0;end
        end
        $finish;
    end
endmodule
