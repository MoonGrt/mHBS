`timescale 1ns/1ps
// Small image-driven programs: observe accepted macro commands independently
// of the executor's internal state encoding.
module tb_mhbs_microcode_probe;
    tb_mhbs_autonomous base();
    always @(posedge base.clk)
        if(!base.rst && base.dut.processor.core.sequencer.lane0_valid
                && base.dut.processor.core.sequencer.lane0_ready)
            $display("MACRO_TRACE phase=%0d command=%012h",base.result_kind,
                base.dut.processor.core.sequencer.lane0_command);
endmodule
