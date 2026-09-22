`timescale 1ns/1ps
module tb_uhbs_recipe_lane;
    parameter integer PROFILE=0;
    localparam integer N=PROFILE==0 ? 16 : 32;
    logic clk=0,rst_n=0,request_valid=0;
    wire request_ready,response_valid,error;
    logic response_ready=0,request_chain,request_capture;
    logic [63:0] request_recipe,request_step_recipe;
    logic [4:0] request_steps,request_capture_after;
    logic [N*8-1:0] secret_seed,secret_prf,public_seed,root,randomizer,request_left,request_right;
    logic [127:0] identifier;
    logic [695:0] message_buffer;
    logic [6:0] message_length=87,request_a;
    logic [4:0] request_layer=0;
    logic [63:0] request_tree=0;
    logic [9:0] request_leaf=5;
    logic [31:0] request_b;
    wire [6:0] list_index0,list_index1;
    logic [N*8-1:0] list_data0,list_data1;
    wire [271:0] response_value;
    wire [N*8-1:0] response_capture;
    wire [31:0] hash_count,permutation_count;
    logic [767:0] vectors[0:5];
    integer i,j,cycles=0,length;
    logic [271:0] expected;
    uhbs_recipe_lane #(.N(N),.PROFILE_ENABLE(1)) dut(.*);
    always #5 clk=~clk;
    always @(posedge clk) begin cycles<=cycles+1; if(cycles>10000) $fatal(1,"recipe timeout"); end
    always_comb for(integer b=0;b<N;b=b+1) begin
        list_data0[b*8 +: 8]=list_index0+b;
        list_data1[b*8 +: 8]=list_index1+b;
    end
    task tick; begin @(posedge clk); #1; end endtask
    initial begin
        if(PROFILE==0) $readmemh("tb/vectors/uhbs_slh_lane.mem",vectors);
        else if(PROFILE==1) $readmemh("tb/vectors/uhbs_xmss_lane.mem",vectors);
        else $readmemh("tb/vectors/uhbs_lms_lane.mem",vectors);
        for(i=0;i<N;i=i+1) begin
            secret_seed[i*8 +: 8]=i; secret_prf[i*8 +: 8]=32+i;
            public_seed[i*8 +: 8]=64+i; randomizer[i*8 +: 8]=96+i;
            root[i*8 +: 8]=128+i; request_left[i*8 +: 8]=160+i; request_right[i*8 +: 8]=192+i;
        end
        for(i=0;i<16;i=i+1) identifier[i*8 +: 8]=i;
        for(i=0;i<87;i=i+1) message_buffer[i*8 +: 8]=i;
        repeat(3) tick(); rst_n=1; tick();
        for(j=0;j<6;j=j+1) begin
            $display("RECIPE_CASE profile=%0d case=%0d",PROFILE,j);
            request_recipe=vectors[j][767:704]; request_step_recipe=vectors[j][703:640];
            request_chain=vectors[j][639]; request_capture=request_chain;
            request_steps=vectors[j][638:634]; request_capture_after=vectors[j][633:629];
            request_a=vectors[j][628:622]; request_b=vectors[j][621:590];
            length=vectors[j][589:584]; expected=vectors[j][543:272];
            request_valid=1; tick(); request_valid=0;
            while(!response_valid) tick();
            if(error) $fatal(1,"recipe error profile=%0d case=%0d",PROFILE,j);
            for(i=0;i<length;i=i+1)
                if(response_value[i*8 +: 8]!==expected[i*8 +: 8]) $fatal(1,"recipe mismatch p=%0d c=%0d byte=%0d",PROFILE,j,i);
            if(request_chain && response_capture!==vectors[j][N*8-1:0]) $fatal(1,"capture mismatch p=%0d c=%0d",PROFILE,j);
            repeat(3) tick(); response_ready=1; tick(); response_ready=0; tick();
        end
        $display("UNIFIED_RECIPE_PASS profile=%0d cycles=%0d",PROFILE,cycles); $finish;
    end
endmodule
