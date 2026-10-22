`timescale 1ns/1ps
`default_nettype none
`include "rtl/executor/instructions.svh"
// Bounded program-control tests: every test owns zero cryptographic Hashes.
module tb_chain_controls;
    logic clk=0,rst=1;
    always #5 clk=~clk;
    logic [63:0] pm[0:255],tm[0:31],dm[0:31];
    wire [7:0] program_address;
    wire [4:0] template_address;
    wire [9:0] descriptor_addresses;
    wire [127:0] descriptor_data={dm[descriptor_addresses[9:5]],dm[descriptor_addresses[4:0]]};
    wire done,error,busy,out_valid;
    wire [255:0] out_data;
    wire [5:0] out_bytes;
    localparam [255:0] PUBLIC_ROOT=256'hffeeddccbbaa998877665544332211000102030405060708090a0b0c0d0e0f10;
`ifdef MHBS_SHA2
    localparam [63:0] BACKEND=64'h20;
`else
    localparam [63:0] BACKEND=0;
`endif
    // verilog_format: off
    common #(.UNROLL(1),.PIPELINE(1)) dut(
        .clk,.rst,.program_address,.template_address,.program_data(pm[program_address]),
        .template_data(tm[template_address]),.descriptor_addresses,.descriptor_data,
        .job_secret_seed(256'd0),.job_secret_prf(256'd0),.job_public_seed(256'd0),
        .job_randomizer(256'd0),.job_public_root(PUBLIC_ROOT),.job_index(32'd0),.job_identifier(128'd0),
        .job_operation(2'd0),.message_length(7'd0),.verify_valid(1'b0),.verify_ready(),.verify_data(256'd0),
        .verify_pass(),.message_data(64'd0),.message_valid(1'b0),.message_ready(),
        .out_valid,.out_data,.out_bytes,.result_kind(),.busy,.done,.keygen_done(),.error
`ifndef SYNTHESIS
        ,.error_code(),.boot_cycles(),.keygen_cycles(),.sign_cycles(),.hash_count(),.permutation_count()
`endif
    );
    // verilog_format: on
    function automatic [63:0] ctl(input [4:0] op,dst,src,aux,input [20:0] imm,
        input [7:0] target,input [3:0] cond);
        ctl=64'hc000000000000000 | (64'(op)<<57) | (64'(dst)<<52) |
            (64'(src)<<47) | (64'(aux)<<42) | (64'(imm)<<21) | (64'(target)<<13) | (64'(cond)<<9);
    endfunction
    task automatic tick;
        @(posedge clk);#1;
    endtask
    integer outputs=0,hash_requests=0,cases=0,rejections=0,commands=0;
    always @(posedge clk) begin
        if(rst) begin outputs=0;hash_requests=0;commands=0;end
        else begin
            if(dut.core.state==6 && dut.core.lane_ready) hash_requests++;
            if(dut.core.cmd_valid && dut.core.state==3) commands++;
            if(out_valid) begin
                if(out_bytes!=16 || out_data[127:0]!==PUBLIC_ROOT[127:0])
                    $fatal(1,"Control output mismatch");
                outputs++;
            end
        end
    end
    task automatic initialize;
        begin
            rst=1;repeat(3)tick();
            for(integer i=0;i<256;i++)pm[i]=64'hc000000000000000;
            for(integer i=0;i<32;i++)begin tm[i]=0;dm[i]=0;end
            dm[0]=64'ha808080000000000;
            dm[1]=BACKEND;
        end
    endtask
    task automatic run_case(input string label,input bit reject,input integer expected_outputs);
        integer clocks;
        begin
            // Hold reset while the mutable ROM settles before admitting the Job.
            repeat(2)tick();rst=0;clocks=0;
            while(!done && !error && clocks<4000)begin tick();clocks++;end
            if(clocks==4000 || error!==reject || done===reject) begin
                $display("CONTROL_BOOT header=%h profile=%h lengthvalid=%b expected_magic=%h validprofile=%b",dut.image_header,dut.profile_descriptor,dut.message_length_valid,`CHAIN_HEADER_MAGIC,dut.core.valid_profile);
                $fatal(1,"Control case %s status clocks=%0d error=%b done=%b pc=%0d state=%0d",
                    label,clocks,error,done,program_address,dut.core.state);
            end
            repeat(8)tick();
            if(hash_requests!=0 || outputs!=expected_outputs)
                $fatal(1,"Control case %s gained Hash/output ownership",label);
            if(reject) begin
                rejections++;
                repeat(12)begin tick();if(!error || busy || done || out_valid)$fatal(1,"Fault did not remain quiescent");end
            end
            cases++;
            $display("CHAIN_CONTROL_CASE %s passed=1 rejected=%0d",label,reject);
        end
    endtask
    initial begin
        initialize();
        pm[0]=ctl(`CTRL_CALL,0,0,0,0,6,0);
        pm[1]=ctl(`CTRL_OUTPUT,0,`WIDE_LEFT,0,0,0,0);
        pm[6]=ctl(`CTRL_WMOV,`WIDE_NODE,`WIDE_V3,0,0,0,0);
        pm[7]=ctl(`CTRL_STORE,`CTX_ZERO,`WIDE_NODE,0,107,0,0);
        pm[8]=ctl(`CTRL_LOAD,`WIDE_LEFT,`CTX_ZERO,0,107,0,0);
        pm[9]=ctl(`CTRL_RET,0,0,0,0,0,0);
        run_case("call_ret_ram107",0,1);
        initialize();
        pm[0]=ctl(`CTRL_SET,`CTX_A,0,0,7,0,0);
        pm[1]=ctl(`CTRL_INC,`CTX_A,0,0,0,0,0);
        pm[2]=ctl(`CTRL_SHR,`CTX_A,0,0,1,0,0);
        pm[3]=ctl(`CTRL_XOR1,`CTX_A,0,0,0,0,0);
        pm[4]=ctl(`CTRL_SHL,`CTX_A,0,0,1,0,0);
        pm[5]=ctl(`CTRL_MOV,`CTX_B,`CTX_A,0,0,0,0);
        pm[6]=ctl(`CTRL_ADD,`CTX_B,`CTX_B,`CTX_ONE,0,0,0);
        pm[7]=ctl(`CTRL_BR,`CTX_B,`CTX_ZERO,1,11,10,`COND_EQ);
        pm[8]=ctl(`CTRL_RET,0,0,0,0,0,0); // Reject unless branch skips it.
        run_case("narrow_alu_branch",0,0);
        if(dut.core.task_a!=10 || dut.core.task_b!=11)$fatal(1,"Narrow ALU values");
        initialize();pm[0]=ctl(`CTRL_SET,`CTX_Q,0,0,1,0,0);run_case("readonly_context",1,0);
        initialize();pm[0]=ctl(`CTRL_SET,`CTX_HEIGHT,0,0,21,0,0);run_case("height21",1,0);
        if(dut.core.tree_height!=0)$fatal(1,"Invalid height partially committed");
        initialize();pm[0]=ctl(`CTRL_SET,`CTX_MODE,0,0,3,0,0);run_case("mode3",1,0);
        initialize();pm[0]=ctl(`CTRL_SET,`CTX_A,0,0,255,0,0);
        pm[1]=ctl(`CTRL_INC,`CTX_A,0,0,0,0,0);run_case("increment_overflow",1,0);
        if(dut.core.task_a!=255)$fatal(1,"Overflow partially committed");
        initialize();pm[0]=ctl(`CTRL_SET,`CTX_B,0,0,21'h100000,0,0);
        pm[1]=ctl(`CTRL_SHL,`CTX_B,0,0,20,0,0);run_case("high_shift_overflow",1,0);
        if(dut.core.task_b!=21'h100000)$fatal(1,"Shift overflow partially committed");
        initialize();pm[0]=ctl(`CTRL_SHR,`CTX_B,0,0,0,0,0);run_case("zero_shift",1,0);
        initialize();pm[0]=ctl(`CTRL_STORE,`CTX_ZERO,`WIDE_NODE,0,108,0,0);run_case("reserved_ram108_store",1,0);
        initialize();pm[0]=ctl(`CTRL_LOAD,`WIDE_NODE,`CTX_ZERO,0,128,0,0);run_case("ram128_load",1,0);
        initialize();pm[0]=ctl(`CTRL_WMOV,`WIDE_ZERO,`WIDE_V3,0,0,0,0);run_case("readonly_wide_zero",1,0);
        initialize();pm[0]=ctl(`CTRL_INPUT,`WIDE_NODE,0,0,0,0,0);run_case("input_without_verify",1,0);
        initialize();pm[0]=ctl(`CTRL_RET,0,0,0,0,0,0);run_case("ret_without_call",1,0);
        initialize();pm[0]=ctl(`CTRL_CALL,0,0,0,0,200,0);
        pm[1]=ctl(`CTRL_OUTPUT,0,`WIDE_LEFT,0,0,0,0);
        pm[200]=ctl(`CTRL_CALL,0,0,0,0,240,0);
        pm[201]=ctl(`CTRL_RET,0,0,0,0,0,0);
        pm[240]=ctl(`CTRL_WMOV,`WIDE_LEFT,`WIDE_V3,0,0,0,0);
        pm[241]=ctl(`CTRL_RET,0,0,0,0,0,0);
        run_case("nested_call_high_pc",0,1);
        initialize();pm[0]=ctl(`CTRL_CALL,0,0,0,0,4,0);
        pm[4]=ctl(`CTRL_CALL,0,0,0,0,8,0);
        pm[8]=ctl(`CTRL_CALL,0,0,0,0,12,0);run_case("call_depth3_overflow",1,0);
        initialize();pm[0]=ctl(`CTRL_SET,`CTX_DIGIT,0,0,1,0,0);run_case("readonly_digit",1,0);
        initialize();pm[0]=ctl(`CTRL_SET,`CTX_LT_COUNT,0,0,67,0,0);
        pm[1]=ctl(`CTRL_SET,`CTX_LT_CURSOR,0,0,66,0,0);
        pm[2]=ctl(`CTRL_SET,`CTX_LT_LEVEL,0,0,7,0,0);run_case("ltree_narrow_context",0,0);
        if(dut.core.lt_count!=67 || dut.core.lt_cursor!=66 || dut.core.lt_level!=7)$fatal(1,"L-tree contexts");
        initialize();pm[0]=ctl(`CTRL_SET,`CTX_LT_COUNT,0,0,256,0,0);run_case("ltree_count_overflow",1,0);
        initialize();pm[0]=ctl(`CTRL_SET,`CTX_LT_LEVEL,0,0,16,0,0);run_case("ltree_level_overflow",1,0);
        initialize();pm[0]=ctl(`CTRL_MOV,`CTX_A,5'd29,0,0,0,0);run_case("reserved_context",1,0);
        initialize();for(integer i=0;i<256;i++)pm[i]=ctl(`CTRL_INC,`CTX_B,0,0,0,0,0);
        run_case("pc_overflow",1,0);
        initialize();pm[0]=0;tm[0]=2;run_case("chain_template",1,0);
        initialize();pm[0]=0;tm[0]=3;run_case("tree_template",1,0);
        initialize();dm[0]=64'ha600000000000000;run_case("layout4_header",1,0);
        initialize();dm[0]=64'h00000600018042c0;run_case("legacy_header",1,0);
        initialize();dm[1]=BACKEND^64'h20;run_case("backend_mismatch",1,0);
        initialize();pm[0]=64'he000000000000000;run_case("unknown_control",1,0);
        initialize();pm[0]=ctl(`CTRL_SET,`CTX_A,0,0,3,0,0)|1;run_case("reserved_control_bits",1,0);
        // RUN and both LOOP levels remain independent of the CALL stack.
        initialize();tm[0]=64'd4|(64'd2<<3);dm[2]=(64'd2<<56)|(64'd1<<40);
        pm[0]=(64'd1<<62)|(64'd2<<41);
        run_case("run_three_templates",0,0);
        if(commands!=3)$fatal(1,"RUN repetition count");
        initialize();pm[0]=ctl(`CTRL_INC,`CTX_A,0,0,0,0,0);
        pm[1]=(64'd2<<62)|(64'd2<<51);
        run_case("counted_loop",0,0);
        if(dut.core.task_a!=3)$fatal(1,"LOOP repetition count");
        initialize();pm[0]=ctl(`CTRL_INC,`CTX_A,0,0,0,0,0);
        pm[1]=(64'd2<<62)|(64'd1<<51);
        pm[2]=(64'd2<<62)|(64'd1<<57)|(64'd1<<51);
        run_case("nested_counted_loop",0,0);
        if(dut.core.task_a!=4)$fatal(1,"Nested LOOP repetition count");
        initialize();pm[0]=ctl(`CTRL_INC,`CTX_A,0,0,0,0,0);
        pm[1]=(64'd2<<62)|(64'd1<<51);
        pm[2]=(64'd2<<62)|(64'd1<<57)|(64'd1<<51);
        pm[3]=(64'd2<<62)|(64'd2<<57)|(64'd1<<51);
        run_case("loop_depth3_overflow",1,0);
        $display("CHAIN_CONTROLS_PASS cases=%0d accepted=%0d rejected=%0d hash_requests=0",cases,cases-rejections,rejections);
        $finish;
    end
endmodule
`default_nettype wire
