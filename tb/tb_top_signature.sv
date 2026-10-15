`timescale 1ns / 1ps
`default_nettype none

// Compare the production top's output stream and optional signature cache.
module tb_top_signature;
    logic clk = 0;
    always #5 clk = ~clk;
    logic rst = 1;
    logic message_valid = 0;
    wire message_ready;
    logic [6:0] message_length = 1;
    logic [63:0] message_data;
    wire verify_ready, verify_pass;
    wire busy, done, keygen_done, error;
    wire out_valid;
    wire [255:0] out_data;
    wire [5:0] out_bytes;
    wire [1:0] result_kind;
    logic signature_read_enable = 0;
    logic [10:0] signature_read_address = 0;
    wire signature_read_valid;
    wire [255:0] signature_read_data;
    wire [5:0] signature_read_bytes, signature_node_bytes;
    wire signature_valid, signature_error;
    wire [10:0] signature_nodes;
    wire [15:0] signature_length;
`ifndef SYNTHESIS
    wire [15:0] error_code;
    wire [63:0] boot_cycles, keygen_cycles, sign_cycles, hash_count, permutation_count;
`endif
    top #(.PIPELINE(4), .UNROLL(1)) dut (
        .verify_valid(1'b0), .verify_data(256'd0), .*
    );
    logic [7:0] expected[0:65535], message[0:86];
    logic [63:0] metadata[0:4];
    integer cursor = 0;
    integer observed_cycles = 0;
    longint unsigned observed_hashes = 0, observed_permutations = 0;
    logic message_sent = 0;

    task automatic tick;
        @(posedge clk);
        #1;
    endtask

    always @(negedge clk) begin
        message_valid = !rst && !message_sent;
        message_data = {56'd0, message[0]};
    end

    always @(posedge clk) begin
        if (rst) begin
            cursor = 0;
            observed_cycles = 0;
            observed_hashes = 0;
            observed_permutations = 0;
            message_sent = 0;
        end else begin
            observed_cycles++;
            if (observed_cycles > 2_000_000) $fatal(1, "top timeout");
            if (message_valid && message_ready) message_sent = 1;
            if (out_valid) begin
                for (integer byte_index = 0; byte_index < out_bytes; byte_index++) begin
                    if (cursor >= metadata[0] || out_data[byte_index*8+:8] !== expected[cursor])
                        $fatal(1, "top output byte %0d", cursor);
                    cursor++;
                end
            end
`ifdef MHBS_SHA2
            if (dut.core.lane.hash_complete_event) observed_hashes++;
            if (dut.core.lane.compression_complete_event) observed_permutations++;
`else
            if (dut.core.lane.permutation_complete) begin
                observed_permutations++;
                if (dut.core.lane.running_last) observed_hashes++;
            end
            if (dut.core.lane.batch_perm_done) begin
                observed_hashes++;
                observed_permutations++;
            end
`endif
        end
    end

    initial begin
`ifdef MHBS_SHA2
        $readmemh("tb/vectors/sha2/slh_128f/sign/expected.mem", expected);
        $readmemh("tb/vectors/sha2/slh_128f/sign/message.mem", message);
        $readmemh("tb/vectors/sha2/slh_128f/sign/meta.mem", metadata);
`else
        $readmemh("tb/vectors/slh_128f/sign/expected.mem", expected);
        $readmemh("tb/vectors/slh_128f/sign/message.mem", message);
        $readmemh("tb/vectors/slh_128f/sign/meta.mem", metadata);
`endif
        repeat (5) tick();
        rst = 0;
        while (!done && !error) tick();
        if (error || cursor != metadata[0] || result_kind != 1) $fatal(1, "top result");
        if (observed_hashes != metadata[1] || observed_permutations != metadata[2])
            $fatal(1, "top functional event counts");
`ifndef SYNTHESIS
        if (hash_count != observed_hashes || permutation_count != observed_permutations)
            $fatal(1, "top diagnostics differ from functional observation");
`endif
`ifdef MHBS_SIGNATURE_STORE
        if (!signature_valid || signature_error || signature_length != metadata[0])
            $fatal(1, "top signature metadata");
        cursor = 0;
        for (integer node = 0; node < signature_nodes; node++) begin
            signature_read_enable = 1;
            signature_read_address = 11'(node);
            tick();
            if (!signature_read_valid) $fatal(1, "top signature read");
            for (integer byte_index = 0; byte_index < signature_read_bytes; byte_index++) begin
                if (signature_read_data[byte_index*8+:8] !== expected[cursor])
                    $fatal(1, "top signature cache byte %0d", cursor);
                cursor++;
            end
        end
        if (cursor != metadata[0]) $fatal(1, "top cache length");
`else
        signature_read_enable = 1;
        repeat (3) tick();
        if (signature_read_valid || signature_read_data || signature_read_bytes || signature_node_bytes ||
            signature_valid || signature_error || signature_nodes || signature_length)
            $fatal(1, "disabled signature interface");
`endif
        $display("TOP_SIGNATURE_PASS bytes=%0d hashes=%0d permutations=%0d", metadata[0],
                 observed_hashes, observed_permutations);
        $finish;
    end
endmodule

`default_nettype wire
