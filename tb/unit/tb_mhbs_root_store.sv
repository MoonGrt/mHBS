`timescale 1ns/1ps
module tb_mhbs_root_store;
    parameter bit SINGLE_READ=0;
    logic clk=0,write=0;
    logic [5:0] address=0,read0=0,read1=1;
    logic [255:0] data=0;
    wire [255:0] value0,value1;
    mhbs_root_store #(.SINGLE_READ(SINGLE_READ)) dut(.*);
    always #5 clk=~clk;
    function automatic [255:0] sample(input integer i);
        sample={8{32'h5a720000+i}};
    endfunction
    initial begin
        for(integer i=0;i<64;i=i+1) begin
            write=1;address=i;data=sample(i);@(posedge clk);#1;
        end
        write=0;
        for(integer i=0;i<63;i=i+1) begin
            read0=i;read1=i+1;#1;
            if(value0!==sample(i) || value1!==(SINGLE_READ ? 256'd0 : sample(i+1))) $fatal(1,"roots adjacent %0d",i);
            read0=i+1;read1=i;#1;
            if(value0!==sample(i+1) || value1!==(SINGLE_READ ? 256'd0 : sample(i))) $fatal(1,"roots reverse %0d",i);
        end
        $display("ROOT_STORE_PASS");$finish;
    end
endmodule
