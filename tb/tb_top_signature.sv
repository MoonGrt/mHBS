`timescale 1ns/1ps
`default_nettype none
// Public default wrapper versus the extracted generic Job/ROM boundary.
module tb_top_signature;
    logic clk=0,rst=1;
    always #5 clk=~clk;
    reg [255:0] job[0:7];
    reg [31:0] metadata[0:5];
    reg [7:0] expected[0:65535],message[0:86];
    logic [63:0] instruction_memory[0:511],config_memory[0:31];
    wire [8:0] program_address;
    logic [63:0] program_data;
    wire [4:0] descriptor_address;
    wire [63:0] descriptor_data=config_memory[descriptor_address];
    always @(posedge clk) program_data<=instruction_memory[program_address];

    logic message_valid=0,verify_valid=0;
    logic [63:0] message_data=0;
    logic [255:0] verify_data=0;
    wire [6:0] message_length=job[6][6:0];
    wire [255:0] job_secret_seed=job[0],job_secret_prf=job[1],job_public_seed=job[2],
        job_randomizer=job[3],job_public_root=job[4];
    wire [1:0] job_operation=job[5][1:0];
    wire message_ready,verify_ready,verify_pass,busy,done,keygen_done,error,out_valid;
    wire [15:0] error_code;
    wire [31:0] boot_cycles,keygen_cycles,sign_cycles,hash_count,permutation_count;
    wire [255:0] out_data;
    wire [5:0] out_bytes;
    wire [1:0] result_kind;
    logic signature_read_enable=0;
    logic [10:0] signature_read_address=0;
    wire signature_read_valid,signature_valid,signature_error;
    wire [255:0] signature_read_data;
    wire [5:0] signature_node_bytes;
    wire [10:0] signature_nodes;
    wire [15:0] signature_length;
    // Deliberately leave every parameter at its public default.
    top dut(.*);

    wire common_message_ready,common_verify_ready,common_verify_pass;
    wire common_busy,common_done,common_keygen_done,common_error,common_out_valid;
    wire [15:0] common_error_code;
    wire [31:0] common_boot_cycles,common_keygen_cycles,common_sign_cycles;
    wire [31:0] common_hash_count,common_permutation_count;
    wire [255:0] common_out_data;
    wire [5:0] common_out_bytes;
    wire [1:0] common_result_kind;
    common #(.PROFILE_ENABLE(1)) common (
        .clk,.rst,.program_address,.program_data,.descriptor_address,.descriptor_data,
        .job_secret_seed,.job_secret_prf,.job_public_seed,.job_randomizer,.job_public_root,
        .job_operation,.message_length,.message_valid,.message_data,.verify_valid,.verify_data,
        .message_ready(common_message_ready),.verify_ready(common_verify_ready),
        .verify_pass(common_verify_pass),.busy(common_busy),.done(common_done),
        .keygen_done(common_keygen_done),.error(common_error),.error_code(common_error_code),
        .boot_cycles(common_boot_cycles),.keygen_cycles(common_keygen_cycles),
        .sign_cycles(common_sign_cycles),.hash_count(common_hash_count),
        .permutation_count(common_permutation_count),.out_valid(common_out_valid),
        .out_data(common_out_data),.out_bytes(common_out_bytes),.result_kind(common_result_kind)
    );

    integer sent=0,cursor=0,cycles=0,waits=0,stall=0,completion_cycles=0;
    integer partial_nodes=0,partial_bytes=0,fault_hashes=0,abort_mode=0;
    logic allow_abort_error=0;
    string vector_dir;
    task tick; begin @(posedge clk);#2;end endtask
    always @(negedge clk) begin
        if(rst)begin message_valid=0;message_data=0;end
        else if(!(message_valid && !message_ready))begin
            message_valid=sent<int'(message_length) && (!stall || (cycles>17 && cycles%3==0));
            // Deliberately poison unused tail bytes; hash input length masks them.
            message_data=64'ha5a5a5a5a5a5a5a5;
            for(integer i=0;i<8;i=i+1)
                if(sent+i<int'(message_length))message_data[8*i+:8]=message[sent+i];
        end
    end
    always @(posedge clk)begin
        if(rst)begin sent=0;cursor=0;cycles=0;waits=0;end
        else begin
            cycles=cycles+1;
            if(message_valid && message_ready)sent=sent+8;
            if(message_ready && !message_valid)waits=waits+1;
            if(cycles>20000000)$fatal(1,"public wrapper timeout");
            if(out_valid)begin
                if(out_bytes!=16 || result_kind!=1)$fatal(1,"public output shape");
                for(integer i=0;i<16;i=i+1)begin
                    if(cursor>=metadata[0] || out_data[8*i+:8]!==expected[cursor])
                        $fatal(1,"public output byte %0d",cursor);
                    cursor=cursor+1;
                end
            end
        end
        #1;
        if(!rst)begin
            if({message_ready,verify_ready,verify_pass,busy,done,keygen_done,error,error_code,
                boot_cycles,keygen_cycles,sign_cycles,hash_count,permutation_count,
                out_valid,out_data,out_bytes,result_kind} !==
               {common_message_ready,common_verify_ready,common_verify_pass,common_busy,
                common_done,common_keygen_done,common_error,common_error_code,
                common_boot_cycles,common_keygen_cycles,common_sign_cycles,common_hash_count,
                common_permutation_count,common_out_valid,common_out_data,common_out_bytes,
                common_result_kind})
                $fatal(1,"public/common cycle mismatch at %0d",cycles);
            if(error && !allow_abort_error)$fatal(1,"public wrapper error %h",error_code);
        end
    end
    initial begin
        if(!$value$plusargs("VECTOR=%s",vector_dir))$fatal(1,"VECTOR required");
        if($value$plusargs("STALL=%d",stall))begin end
        abort_mode=$test$plusargs("TREE_ABORT");
        $readmemh({vector_dir,"/job.mem"},job);
        $readmemh({vector_dir,"/metadata.mem"},metadata);
        $readmemh({vector_dir,"/expected.mem"},expected,0,metadata[0]-1);
        $readmemh({vector_dir,"/message.mem"},message,0,int'(job[6])-1);
        $readmemh("tb/vectors/slh_128f/program.mem",instruction_memory);
        $readmemh("tb/vectors/slh_128f/descriptor.mem",config_memory);
        #1;
        if(job[5]!=1 || job[7]!=16 || metadata[0]!=17088 ||
           dut.SECRET_SEED!==job[0] || dut.SECRET_PRF!==job[1] ||
           dut.PUBLIC_SEED!==job[2] || dut.RANDOMIZER!==job[3] ||
           dut.PUBLIC_ROOT!==job[4] || dut.OPERATION!==job[5][1:0])
            $fatal(1,"vector does not exercise actual public default Job");
        repeat(4)tick();rst=0;
        if(abort_mode) begin
            // Abort a later tree after the public cache has accepted real
            // signature nodes. Both public and extracted boundaries see the
            // same physical-lane error and must halt on the same cycle.
            while(!(dut.common.core.tree_active && cursor>16 && dut.common.core.physical_valid)) tick();
            @(negedge clk);allow_abort_error=1;
            partial_nodes=signature_nodes;partial_bytes=cursor;fault_hashes=hash_count;
            if(partial_nodes==0 || partial_bytes<32 || signature_valid)
                $fatal(1,"TREE abort did not contain a partial public signature");
            force dut.common.core.physical_error=1'b1;
            force common.core.physical_error=1'b1;
            tick();
            release dut.common.core.physical_error;
            release common.core.physical_error;
            while(!error)tick();repeat(3)tick();
            if(error_code!=16'h3007 || done || busy || signature_valid || !signature_error
                || message_ready || verify_ready || out_valid)
                $fatal(1,"TREE fault did not abort public wrapper/cache");
            @(negedge clk);signature_read_enable=1;signature_read_address=0;
            repeat(8) begin
                tick();
                if(signature_read_valid || signature_valid || done || out_valid
                    || dut.common.core.lanes[0].lane.request_valid || common.core.lanes[0].lane.request_valid)
                    $fatal(1,"aborted TREE signature readable or execution continued");
            end
            // Reset discards partial validity. The very same public top and
            // image replay the entire signature and its cache readback below.
            @(negedge clk);rst=1;signature_read_enable=0;
            repeat(4)tick();
            if(signature_valid || signature_read_valid || signature_error || signature_nodes)
                $fatal(1,"TREE abort reset retained public cache validity");
            allow_abort_error=0;rst=0;
        end
        while(!done)tick();completion_cycles=cycles;
        if(cursor!=metadata[0] || hash_count!=metadata[1] || permutation_count!=metadata[2] ||
           boot_cycles!=2 || keygen_cycles!=0 || sign_cycles==0 || keygen_done || verify_pass)
            $fatal(1,"public completion/counts");
        if(!signature_valid || signature_error || signature_length!=metadata[0] ||
           signature_nodes!=metadata[0]/16 || signature_node_bytes!=16)
            $fatal(1,"direct public signature cache metadata");
        // Read every node, crossing the physical cache bank boundary at1024.
        for(integer index=0;index<signature_nodes;index=index+1)begin
            @(negedge clk);signature_read_enable=1;signature_read_address=11'(index);
            tick();
            if(!signature_read_valid)$fatal(1,"public signature synchronous read");
            for(integer b=0;b<32;b=b+1)
                if(signature_read_data[8*b+:8] !== (b<16 ? expected[index*16+b] : 8'd0))
                    $fatal(1,"public cache index=%0d byte=%0d",index,b);
        end
        @(negedge clk);signature_read_address=signature_nodes;tick();
        if(signature_read_valid)$fatal(1,"public cache out-of-range read");
        @(negedge clk);signature_read_enable=0;tick();
        repeat(30)begin
            tick();if(!done || busy || out_valid || message_ready || verify_ready || error)
                $fatal(1,"public completion halt");
        end
        $display("MICRO_TOP_EQUIVALENCE_PASS cycles=%0d signature_nodes=%0d bytes=%0d hashes=%0d permutations=%0d boot=%0d sign=%0d waits=%0d stall=%0d",completion_cycles,signature_nodes,cursor,hash_count,permutation_count,boot_cycles,sign_cycles,waits,stall);
        if(abort_mode)
            $display("MICRO_TOP_TREE_ABORT_PASS partial_nodes=%0d partial_bytes=%0d code=3007 aborted_hashes=%0d replay_cycles=%0d replay_nodes=%0d replay_bytes=%0d replay_hashes=%0d replay_permutations=%0d",partial_nodes,partial_bytes,fault_hashes,completion_cycles,signature_nodes,cursor,hash_count,permutation_count);
        $finish;
    end
endmodule
`default_nettype wire
