`timescale 1ns/1ps
module tb_mhbs_v42_recipe_lane;
    parameter integer PROFILE=0;
    parameter [15:0] MASK=16'h101e;
    parameter integer CASES=7;
    localparam integer N=PROFILE==0 ? 16 : PROFILE==1 ? 24 : 32;
    localparam integer M=PROFILE==0 ? 34 : PROFILE==1 ? 42 : 49;
    localparam integer IB=7;
    wire [5:0] node_bytes=N;
    logic clk=0,rst=1,request_valid=0;
    wire request_ready,response_valid,error;
    logic response_ready=0,request_chain,request_capture;
    logic [63:0] request_recipe,request_step_recipe;
    logic [4:0] request_steps,request_capture_after;
    logic [255:0] secret_seed,secret_prf,public_seed,root,randomizer,request_left,request_right;
    logic [127:0] identifier;
    logic [695:0] message_buffer;
    logic [6:0] message_length=87;
    logic [7:0] request_a;
    logic [4:0] request_layer=0;
    logic [63:0] request_tree=0;
    logic [9:0] request_leaf=5;
    logic [31:0] request_b;
    wire [7:0] list_index0,list_index1;
    logic [255:0] list_data0,list_data1;
    wire [391:0] response_value;
    wire [255:0] response_capture;
    wire [31:0] hash_count,permutation_count;
    logic [1023:0] vectors[0:CASES-1];
    integer i,j,cycles=0,length;
    logic [M*8-1:0] expected;
    mhbs_recipe_lane #(.N(32),.DIGEST_BYTES(49),.INDEX_BITS(8),.RECIPE_MASK(MASK),.PROFILE_ENABLE(1)) dut(.batch_mode(1'b0),.batch_request_valid(1'b0),.batch_request_tag(2'd0),
     .batch_steps(5'd0),.batch_capture_after(5'd0),.batch_capture_enable(1'b0),
     .batch_leaf(10'd0),.batch_a(7'd0),.batch_b(32'd0),.batch_seed_domain(8'd0),.batch_step_domain(8'd0),
     .batch_response_ready(1'b0),.batch_request_ready(),.batch_response_valid(),.batch_response_tag(),
     .batch_response_digest(),.batch_response_capture(),.batch_hashes(),.batch_permutations(),.*);
    always #5 clk=~clk;
    always @(posedge clk) begin cycles<=cycles+1; if(cycles>10000) $fatal(1,"recipe timeout"); end
    always_comb for(integer b=0;b<N;b=b+1) begin
        list_data0[b*8 +: 8]=list_index0+b;
        list_data1[b*8 +: 8]=list_index1+b;
    end
    task tick; begin @(posedge clk); #1; end endtask
    string vector_path;
    initial begin
        if(PROFILE<0 || PROFILE>2) $fatal(1,"unsupported SLH profile");
        if($value$plusargs("VECTORS=%s",vector_path)) $readmemh(vector_path,vectors);
        else case(PROFILE)
            0: $readmemh("tb/vectors/mhbs_slh_128f_lane.mem",vectors);
            1: $readmemh("tb/vectors/mhbs_slh_192f_lane.mem",vectors);
            2: $readmemh("tb/vectors/mhbs_slh_256f_lane.mem",vectors);
        endcase
        for(i=0;i<N;i=i+1) begin
            secret_seed[i*8 +: 8]=i; secret_prf[i*8 +: 8]=32+i;
            public_seed[i*8 +: 8]=64+i; randomizer[i*8 +: 8]=96+i;
            root[i*8 +: 8]=128+i; request_left[i*8 +: 8]=160+i; request_right[i*8 +: 8]=192+i;
        end
        for(i=0;i<16;i=i+1) identifier[i*8 +: 8]=i;
        for(i=0;i<87;i=i+1) message_buffer[i*8 +: 8]=i;
        repeat(3) tick(); rst=0; tick();
        for(j=0;j<CASES;j=j+1) begin
            $display("RECIPE_CASE profile=%0d case=%0d",PROFILE,j);
            request_recipe=vectors[j][1023:960]; request_step_recipe=vectors[j][959:896];
            request_chain=vectors[j][895]; request_capture=request_chain;
            request_steps=vectors[j][894:890]; request_capture_after=vectors[j][889:885];
            request_a=vectors[j][884:877]; request_b=vectors[j][876:845];
            length=vectors[j][844:839]; expected=vectors[j][256 +: M*8];
            request_valid=1; tick(); request_valid=0;
            while(!response_valid) tick();
            if(error) $fatal(1,"recipe error profile=%0d case=%0d",PROFILE,j);
            for(i=0;i<length;i=i+1)
                if(response_value[i*8 +: 8]!==expected[i*8 +: 8]) $fatal(1,"recipe mismatch p=%0d c=%0d byte=%0d",PROFILE,j,i);
            if(request_chain && response_capture[N*8-1:0]!==vectors[j][N*8-1:0]) $fatal(1,"capture mismatch p=%0d c=%0d",PROFILE,j);
            repeat(3) tick(); response_ready=1; tick(); response_ready=0; tick();
        end
        $display("UNIFIED_RECIPE_PASS profile=%0d cycles=%0d",PROFILE,cycles); $finish;
    end
endmodule
