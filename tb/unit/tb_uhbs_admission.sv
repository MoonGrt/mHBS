`timescale 1ns/1ps
module tb_uhbs_admission;
    logic clk=0,rst_n=0,job_valid=0,job_operation=0;
    logic [6:0] job_message_length=1;
    logic [10:0] job_initial_q=5;
    wire job_ready,error,out_valid,busy,done;
    wire [15:0] error_code;
    logic [63:0] header;
    logic [63:0] tree_descriptor;
    integer timeout;
    logic message_valid=0, message_last=0;
    logic [7:0] message_keep=0;
    uhbs_hbs #(.N(32),.STATEFUL(1),.PROGRAM_TOKENS(10),.PROGRAM_TEMPLATES(8),
        .TOKEN_INIT_FILE("rtl/microcode/uhbs_xmss_tokens.mem"),
        .TEMPLATE_INIT_FILE("rtl/microcode/uhbs_xmss_templates.mem"),
        .DESCRIPTOR_INIT_FILE("rtl/microcode/uhbs_xmss_descriptors.mem")) dut (
        .clk,.rst_n,.job_valid,.job_ready,.job_operation,.job_message_length,.job_initial_q,
        .job_secret_seed(256'd0),.job_secret_prf(256'd0),.job_public_seed(256'd0),
        .job_randomizer(256'd0),.job_identifier(128'd0),
        .message_valid,.message_ready(),.message_data(64'd0),.message_keep,.message_last,
        .state_commit_valid(),.state_commit_ready(1'b0),.state_next_q(),
        .out_valid,.out_ready(1'b1),.out_data(),.out_keep(),.out_last(),
        .busy,.done,.error,.error_code,.hash_count(),.permutation_count(),.cycles(),.tree_cache_valid()
    );
    always #5 clk=~clk;
    always @(posedge clk) if(rst_n && (out_valid || done)) $fatal(1,"invalid job produced output/completion");
    task tick; begin @(posedge clk); #1; end endtask
    task reject(input [15:0] expected);
        begin
            rst_n=0; repeat(2) tick(); rst_n=1; tick();
            job_valid=1; tick(); job_valid=0;
            if(!error || error_code!==expected) $fatal(1,"admission code %h expected %h",error_code,expected);
            repeat(3) tick();
        end
    endtask
    task reject_message(input [7:0] keep, input last);
        begin
            rst_n=0; repeat(2) tick(); rst_n=1; tick();
            dut.tree_cache_valid=1; dut.cache_q=0;
            job_operation=1; job_message_length=1;
            job_valid=1; tick(); job_valid=0;
            message_valid=1; message_keep=keep; message_last=last;
            tick(); message_valid=0;
            if(!error || error_code!=16'h3002) $fatal(1,"malformed message was accepted");
        end
    endtask
    initial begin
        tick(); header=dut.descriptors[0]; tree_descriptor=dut.descriptors[20];
        job_operation=1; reject(16'h3003);
        job_message_length=0; reject(16'h3002);
        job_message_length=88; reject(16'h3002);
        job_operation=0; job_initial_q=1024; reject(16'h3004);
        job_initial_q=5; dut.descriptors[0]=0; reject(16'h3001);
        dut.descriptors[0]=header;
        rst_n=0; repeat(2) tick(); rst_n=1; tick();
        job_initial_q=1023; job_valid=1; tick(); job_valid=0;
        if(error || dut.active_q!=1023) $fatal(1,"last valid index rejected");
        job_initial_q=5;
        // Model the state left after a committed signature subsequently fails:
        // the cache/guard validity is cleared, but q+1 remains burned.
        rst_n=0; repeat(2) tick(); rst_n=1; tick();
        dut.index_started=1;
        dut.g_guard.guard.current_q=6;
        dut.g_guard.guard.initialized=0;
        job_valid=1; tick(); job_valid=0;
        if(error || dut.active_q!=6) $fatal(1,"failure recovery rolled back committed q");
        rst_n=0; repeat(2) tick(); rst_n=1; tick();
        dut.index_started=1;
        dut.g_guard.guard.current_q=1024;
        dut.g_guard.guard.initialized=0;
        job_valid=1; tick(); job_valid=0;
        if(!error || error_code!=16'h3004) $fatal(1,"failure recovery bypassed exhaustion");
        rst_n=0; repeat(2) tick(); rst_n=1; tick();
        dut.descriptors[20]=0;
        job_valid=1; tick(); job_valid=0;
        timeout=0;
        while(!error && timeout<100) begin tick(); timeout=timeout+1; end
        if(!error || error_code!=16'h3006) $fatal(1,"invalid macro was not rejected");
        repeat(3) tick();
        if(!dut.seq_ready) $fatal(1,"failed macro left sequencer busy");
        dut.descriptors[20]=tree_descriptor;
        job_valid=1; tick(); job_valid=0;
        repeat(30) tick();
        if(error || dut.state==3) $fatal(1,"error recovery cannot relaunch image");
        reject_message(8'h00,1);
        reject_message(8'h05,1);
        reject_message(8'h03,1);
        reject_message(8'h01,0);
        $display("UNIFIED_ADMISSION_PASS"); $finish;
    end
endmodule
