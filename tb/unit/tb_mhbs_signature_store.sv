`timescale 1ns/1ps
module tb_mhbs_signature_store;
    logic clk=0,rst=1,finish=0,abort=0,write_valid=0,read_enable=0;
    logic [255:0] write_data=0;
    logic [5:0] write_bytes=16;
    logic [10:0] read_address=0;
    wire read_valid,complete,error;
    wire [255:0] read_data;
    wire [5:0] node_bytes,read_bytes;
    wire [10:0] nodes;
    wire [15:0] length;
    mhbs_signature_store dut(.*);
    always #5 clk=~clk;
    task tick;begin @(posedge clk);#1;end endtask
    task reset_store;begin
        rst=1;tick();rst=0;finish=0;abort=0;write_valid=0;read_enable=0;
        if(complete || error || read_valid || nodes || length)$fatal(1,"reset metadata");
    end endtask
    function automatic [255:0] pattern(input integer index);
        // All address bits participate: bank aliases must not share patterns.
        for(integer b=0;b<8;b=b+1)pattern[b*32+:32]=32'(index*65537+b*16777219);
    endfunction
    initial begin
        // Includes odd node counts and the largest six-profile signature.
        for(integer bytes_per_node=16;bytes_per_node<=32;bytes_per_node+=8)begin
            reset_store();write_bytes=6'(bytes_per_node);
            for(integer n=0;n<1558;n=n+1)begin
                write_valid=1;write_data=pattern(n);read_enable=1;
                tick();if(read_valid || complete)$fatal(1,"read before completion");
            end
            write_valid=0;finish=1;tick();
            if(!complete || error || nodes!=1558 || length!=1558*bytes_per_node || node_bytes!=bytes_per_node)
                $fatal(1,"full store metadata");
            for(integer n=1557;n>=0;n=n-1)begin
                read_address=11'(n);tick();
                if(!read_valid || read_data!==pattern(n) || read_bytes!=bytes_per_node)$fatal(1,"readback %0d",n);
            end
            // Jump between all three banks on consecutive requests.
            for(integer n=0;n<1558;n=n+1)begin
                read_address=11'((n*613)%1558);tick();
                if(!read_valid || read_data!==pattern(int'(read_address)))$fatal(1,"bank switch");
            end
            read_address=1558;tick();if(read_valid)$fatal(1,"bounds");
            read_address=0;write_valid=1;write_data='1;tick();
            if(!read_valid || read_data!==pattern(0) || nodes!=1558)$fatal(1,"write after finish");
            read_enable=0;tick();if(read_valid)$fatal(1,"read enable");
            // A reset must invalidate even a pending read; RAM need not clear.
            read_enable=1;reset_store();read_enable=1;finish=1;tick();
            if(read_valid || complete)$fatal(1,"stale signature after reset");
        end
        reset_store();write_valid=1;write_bytes=32;
        repeat(1558)tick();tick();
        if(!error || nodes!=1558 || length!=49856)$fatal(1,"overflow must not wrap");
        finish=1;tick();if(complete)$fatal(1,"overflow completion");
        reset_store();write_valid=1;write_bytes=16;tick();write_bytes=24;tick();
        if(!error || nodes!=1)$fatal(1,"mixed widths");
        reset_store();write_valid=1;write_bytes=0;tick();
        if(!error || nodes)$fatal(1,"invalid width");
        reset_store();write_valid=1;write_bytes=16;tick();abort=1;tick();
        finish=1;read_enable=1;tick();
        if(!error || complete || read_valid || nodes!=1)$fatal(1,"abort");
        reset_store();write_valid=1;write_data=pattern(99);tick();
        reset_store();write_valid=1;write_bytes=24;write_data=pattern(7);tick();
        write_valid=0;finish=1;read_enable=1;read_address=0;tick();
        if(!read_valid || read_data!==pattern(7) || length!=24)$fatal(1,"restart");
        reset_store();
        for(integer n=0;n<148;n++)begin
            write_valid=1;write_data=pattern(n);write_bytes=n==0||n==1||n==137 ? 4 : 32;tick();
        end
        write_valid=0;finish=1;tick();
        if(error||!complete||nodes!=148||length!=4652)$fatal(1,"mixed metadata");
        for(integer n=147;n>=0;n--)begin
            read_enable=1;read_address=n;tick();
            if(!read_valid||read_data!==pattern(n)||read_bytes!=(n==0||n==1||n==137 ? 4 : 32))$fatal(1,"mixed bytes");
        end
        $display("SIGNATURE_STORE_UNIT_PASS");$finish;
    end
endmodule
