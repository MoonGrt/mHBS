`timescale 1ns/1ps
// Check the final word in each boot scan, after the validation pipeline fills.
module tb_mhbs_boot_drain;
    tb_mhbs_autonomous bench();
    integer bad;
    initial begin
        if (!$value$plusargs("BAD=%d",bad)) $fatal(1,"BAD required");
        #1;
        case (bad)
            15: bench.dut.program_rom.memory[63]=1;
            16: bench.dut.template_rom.memory[63]=1;
            17: bench.dut.descriptor_rom.memory[127]=64'hf000000000000000;
            default: $fatal(1,"unknown drain test");
        endcase
        @(negedge bench.rst);
        wait(bench.error);
        #1;
        if (bench.error_code !== (bad==15 ? 16'h4105 : bad==16 ? 16'h4106 : 16'h4107))
            $fatal(1,"wrong rejection code %h",bench.error_code);
    end
endmodule
