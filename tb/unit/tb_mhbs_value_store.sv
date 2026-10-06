`timescale 1ns/1ps
module tb_mhbs_value_store;
    parameter integer DEPTH=136;
    logic clk=0, write_enable=0;
    logic [7:0] write_address=0,read0=0,read1=1;
    logic [255:0] write_data=0;
    wire [255:0] value0,value1;
    mhbs_value_store #(.WIDTH(256),.DEPTH(DEPTH),.ADDRESS_BITS(8)) dut(.*);
    always #5 clk=~clk;
    task tick;begin @(posedge clk);#1;end endtask
    function automatic [255:0] sample(input integer i);
        sample={8{32'hc5a00000+i}};
    endfunction
    integer i;
    initial begin
        for(i=0;i<DEPTH;i=i+1)begin
            write_enable=1;write_address=i;write_data=sample(i);tick();
        end
        write_enable=0;
        // Include both bank orders and the crossing from address 127 to 128.
        for(i=0;i<DEPTH-1;i=i+1)begin
            read0=i;read1=i+1;#1;
            if(value0!==sample(i) || value1!==sample(i+1))$fatal(1,"store address %0d",i);
            read0=i+1;read1=i;#1;
            if(value0!==sample(i+1) || value1!==sample(i))$fatal(1,"store reverse %0d",i);
        end
        // The final odd L-tree endpoint survives in-place promotion.
        write_address=66;write_data=sample(132);write_enable=1;tick();write_enable=0;read0=66;read1=67;#1;
        if(value0!==sample(132))$fatal(1,"odd promotion");
        $display("VALUE_STORE_PASS depth=%0d",DEPTH);$finish;
    end
endmodule
