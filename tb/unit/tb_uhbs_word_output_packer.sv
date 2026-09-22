`timescale 1ns/1ps
module tb_uhbs_word_output_packer;
    logic clk=0,rst_n=0,clear=0,in_valid=0,out_ready=0,in_last=0;
    logic [63:0] in_data=0;
    logic [3:0] in_bytes=0;
    wire in_ready,out_valid,out_last,idle;
    wire [63:0] out_data; wire [7:0] out_keep;
    integer sent=0,received=0,cycle=0,j,chunk;
    logic [15:0] lfsr=16'h1;
    uhbs_word_output_packer dut(.*);
    always #5 clk=~clk;
    always @(negedge clk) begin
        lfsr<={lfsr[14:0],lfsr[15]^lfsr[13]^lfsr[12]^lfsr[10]};
        out_ready<=lfsr[2:0]!=0;
    end
    always @(posedge clk) if(rst_n) begin
        cycle<=cycle+1;
        if(cycle>2000) $fatal(1,"packer timeout");
        if(out_valid && out_ready) begin
            for(integer b=0;b<8;b=b+1) if(out_keep[b]) begin
                if(out_data[b*8 +: 8]!==8'(received)) $fatal(1,"packer byte %0d",received);
                received=received+1;
            end
            if(out_last!==(received==257)) $fatal(1,"packer last");
        end
    end
    task tick; begin @(posedge clk); #1; end endtask
    initial begin
        repeat(3) tick(); rst_n=1;
        while(sent<257) begin
            chunk=(sent%8)+1; if(sent+chunk>257) chunk=257-sent;
            in_data=0; for(j=0;j<chunk;j=j+1) in_data[j*8 +: 8]=sent+j;
            in_bytes=chunk; in_last=sent+chunk==257; in_valid=1;
            do begin @(posedge clk); end while(!in_ready);
            #1; sent=sent+chunk; in_valid=0;
        end
        while(received<257) tick(); tick();
        if(!idle) $fatal(1,"packer not drained");
        $display("WORD_PACKER_PASS cycles=%0d",cycle); $finish;
    end
endmodule
