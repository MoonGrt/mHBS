`timescale 1ns / 1ps
`default_nettype none
module tb_sha256 #(
    parameter integer PIPELINE=1, UNROLL=1,
    localparam integer TAG_BITS=PIPELINE>1 ? $clog2(PIPELINE) : 1
);
    logic clk=0, rst=1;
    always #5 clk=~clk;
    logic input_valid=0, output_ready=0;
    wire input_ready, output_valid;
    logic [255:0] input_cv=0;
    logic [511:0] input_block=0;
    logic [TAG_BITS-1:0] input_tag=0;
    wire [255:0] output_cv;
    wire [TAG_BITS-1:0] output_tag;
    // verilog_format: off
    sha256 #(.PIPELINE(PIPELINE),.UNROLL(UNROLL),.TAG_BITS(TAG_BITS)) dut (
        .clk,.rst,.input_valid,.input_ready,.input_cv,.input_block,.input_tag,
        .output_valid,.output_ready,.output_cv,.output_tag
    );
    // verilog_format: on
    logic [1023:0] vectors[0:511];
    logic [255:0] expected_cv[0:511];
    logic [TAG_BITS-1:0] expected_tag[0:511];
    integer count, sent=0, received=0, cycles=0, stalls=0, simultaneous=0;
    logic accepted=0, replay=0;
    logic [31:0] random_state=32'h793a46c5;
    logic held=0;
    logic [255:0] held_cv;
    logic [TAG_BITS-1:0] held_tag;
    string vector_file;

    always @(negedge clk) begin
        random_state = {random_state[30:0], random_state[31] ^ random_state[21] ^
            random_state[1] ^ random_state[0]};
        if (rst) begin
            input_valid=0;
            output_ready=0;
        end else begin
            // Preserve every offered request until its acceptance edge.
            if (!input_valid || accepted) begin
                // Deliberately pair the second input with the first output.
                // An always-pending input otherwise refills P1 one cycle before
                // its registered output appears, so random stalls cannot cover it.
                input_valid = sent < count && ((sent == 1 && received == 0) ?
                    output_valid : (random_state[0] || random_state[7]));
                if (sent < count) begin
                    input_cv=vectors[sent][1023:768];
                    input_block=vectors[sent][767:256];
                    input_tag=TAG_BITS'((sent*5) ^ (sent >> 1));
                end
            end
            // Include long output stalls as well as isolated bubbles.
            output_ready = cycles % 71 < 58 && (random_state[3] || random_state[9]);
        end
    end

    always @(posedge clk) begin
        if (rst) begin
            sent=0; received=0; cycles=0; stalls=0; simultaneous=0;
            accepted=0; held=0;
        end else begin
            cycles=cycles+1;
            accepted=input_valid && input_ready;
            if (held && (!output_valid || output_cv !== held_cv || output_tag !== held_tag))
                $fatal(1, "SHA256 response changed under backpressure");
            if (output_valid && !output_ready && input_ready)
                $fatal(1, "SHA256 accepted input while globally stalled");
            held=output_valid && !output_ready;
            held_cv=output_cv; held_tag=output_tag;
            if (held) stalls=stalls+1;
            if (accepted) begin
                if (sent >= count) $fatal(1, "Unexpected SHA256 input acceptance");
                expected_cv[sent]=vectors[sent][255:0];
                expected_tag[sent]=input_tag;
                sent=sent+1;
            end
            if (output_valid && output_ready) begin
                if (received >= sent) $fatal(1, "Unsolicited SHA256 response");
                if (output_cv !== expected_cv[received] || output_tag !== expected_tag[received]) begin
                    $display("item=%0d actual=%h expected=%h tag=%0d expected_tag=%0d",
                        received,output_cv,expected_cv[received],output_tag,expected_tag[received]);
                    $fatal(1, "SHA256 compression mismatch");
                end
                received=received+1;
                if (accepted) simultaneous=simultaneous+1;
            end
            if (cycles > 200000) $fatal(1, "SHA256 test timeout");
        end
    end

    initial begin
        if (!$value$plusargs("VECTOR=%s",vector_file) || !$value$plusargs("COUNT=%d",count))
            $fatal(1, "Require VECTOR and COUNT");
        if (count < 8 || count > 512) $fatal(1, "Invalid SHA256 vector count");
        $readmemh(vector_file,vectors);
        repeat (4) @(posedge clk);
        @(negedge clk); #1 rst=0;
        wait (sent >= 7);
        @(negedge clk); #1 rst=1;
        repeat (3) @(posedge clk);
        @(negedge clk); #1 rst=0; replay=1;
        wait (replay && received == count);
        repeat (4) @(posedge clk);
        if (sent != count || stalls == 0 || simultaneous == 0)
            $fatal(1, "Missing SHA256 handshake coverage sent=%0d stalls=%0d simultaneous=%0d",
                sent,stalls,simultaneous);
        $display("SHA256_PASS P=%0d U=%0d vectors=%0d cycles=%0d stalls=%0d simultaneous=%0d reset_replay=1",
            PIPELINE,UNROLL,count,cycles,stalls,simultaneous);
        $finish;
    end
endmodule
`default_nettype wire
