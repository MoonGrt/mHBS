`timescale 1ns/1ps
module tb_mhbs_recipe_padding;
    parameter integer PIPELINE=1;
    parameter bit SHARED_STATE=1;
    logic clk=0,rst=1,request_valid=0,response_ready=0;
    logic [5:0] node_bytes;
    wire request_ready,response_valid,error;
    logic [63:0] request_recipe;
    logic [6:0] message_length;
    logic [255:0] secret_prf,public_seed,root,randomizer;
    logic [695:0] message_buffer;
    wire [391:0] response_value;
    wire [31:0] hash_count,permutation_count;
    logic [447:0] vectors[0:9];
    integer i,j,cycles=0,old_hashes,old_permutations;
    string vector_file;
    mhbs_recipe_lane #(.PIPELINE(PIPELINE),.SHARED_STATE(SHARED_STATE),.N(32),.DIGEST_BYTES(49),.RECIPE_MASK(16'h101e),.PROFILE_ENABLE(1)) dut (.batch_mode(1'b0),.batch_request_valid(1'b0),
        .clk,.rst,.node_bytes,.request_valid,.request_ready,.request_recipe,
        .request_step_recipe(64'd0),.request_chain(1'b0),.request_steps(5'd0),
        .request_capture_after(5'd0),.request_capture(1'b0),.secret_seed(256'd0),
        .secret_prf,.public_seed,.root,.randomizer,.identifier(128'd0),
        .message_buffer,.message_length,.request_layer(5'd0),.request_tree(64'd0),
        .request_leaf(10'd0),.request_a(7'd0),.request_b(32'd0),
        .request_left(256'd0),.request_right(256'd0),.list_index0(),.list_index1(),
        .list_data0(256'd0),.list_data1(256'd0),.response_valid,.response_ready,
        .response_value,.response_capture(),.error,.hash_count,.permutation_count
    );
    always #5 clk=~clk;
    always @(posedge clk) begin
        cycles<=cycles+1;
        if(cycles>3000) $fatal(1,"padding timeout");
    end
    task tick; begin @(posedge clk);#1;end endtask
    initial begin
        if(!$value$plusargs("VECTORS=%s",vector_file)) $fatal(1,"missing vectors");
        $readmemh(vector_file,vectors);
        for(i=0;i<32;i=i+1) begin
            secret_prf[i*8+:8]=32+i;public_seed[i*8+:8]=64+i;
            randomizer[i*8+:8]=96+i;root[i*8+:8]=128+i;
        end
        for(i=0;i<87;i=i+1) message_buffer[i*8+:8]=i;
        repeat(3) tick();rst=0;tick();
        for(j=0;j<10;j=j+1) begin
            node_bytes=vectors[j][447:442];message_length=vectors[j][437:431];
            request_recipe=64'h1000000002000000;
            request_recipe[59:56]=vectors[j][441:438];
            old_hashes=hash_count;old_permutations=permutation_count;
            request_valid=1;tick();request_valid=0;
            while(!response_valid) tick();
            if(error || response_value!==vectors[j][391:0]) $fatal(1,"padding bytes case=%0d",j);
            if(hash_count-old_hashes!=1 || permutation_count-old_permutations!=vectors[j][430:423])
                $fatal(1,"padding counts case=%0d",j);
            repeat(2) tick();response_ready=1;tick();response_ready=0;tick();
        end
        $display("RECIPE_PADDING_PASS 135/136/137 bytes, alternating node sizes and recipes");
        $finish;
    end
endmodule
