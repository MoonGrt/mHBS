`timescale 1ns/1ps
module tb_mhbs_value_store;
    parameter bit SINGLE_READ=0;
    parameter integer DEPTH=136;
    logic clk=0, write0=0, write1=0;
    logic [7:0] address0=0,address1=0,read0=0,read1=1;
    logic [255:0] data0=0,data1=0;
    wire [255:0] value0,value1;
    mhbs_value_store #(.WIDTH(256),.DEPTH(DEPTH),.ADDRESS_BITS(8),.SINGLE_READ(SINGLE_READ)) dut(.*);
    always #5 clk=~clk;
    task tick;begin @(posedge clk);#1;end endtask
    function automatic [255:0] sample(input integer i);
        sample={8{32'hc5a00000+i}};
    endfunction
    integer i;
    initial begin
        for(i=0;i<DEPTH;i=i+2)begin
            write0=1;write1=1;address0=i;address1=i+1;data0=sample(i);data1=sample(i+1);tick();
        end
        write0=0;write1=0;
        // Include both bank orders and the crossing from address 127 to 128.
        for(i=0;i<DEPTH-1;i=i+1)begin
            read0=i;read1=i+1;#1;
            if(value0!==sample(i) || value1!==(SINGLE_READ ? 256'd0 : sample(i+1)))$fatal(1,"store address %0d",i);
            read0=i+1;read1=i;#1;
            if(value0!==sample(i+1) || value1!==(SINGLE_READ ? 256'd0 : sample(i)))$fatal(1,"store reverse %0d",i);
        end
        // The final odd L-tree endpoint survives in-place promotion.
        address0=66;data0=sample(132);write0=1;tick();write0=0;read0=66;read1=67;#1;
        if(value0!==sample(132))$fatal(1,"odd promotion");
        $display("VALUE_STORE_PASS depth=%0d",DEPTH);$finish;
    end
endmodule
