`timescale 1ns/1ps
`default_nettype none

module tb_micro_hbs_randomized_f_p2_slice;
    logic clk = 1'b0;
    logic rst_n = 1'b0;
    logic program_we = 1'b0;
    logic [8:0] program_addr = '0;
    logic [63:0] program_wdata = '0;
    logic job_valid = 1'b0;
    wire job_ready;
    logic [8:0] job_entry = '0;
    logic [255:0] job_pub_seed = '0;
    logic [255:0] job_address_template = '0;
    logic [255:0] job_node0 = '0;
    logic [255:0] job_node1 = '0;
    logic [7:0] job_chain_bound = '0;
    wire busy, done, error;
    wire [15:0] error_code;
    wire [255:0] result_node0, result_node1;
    wire step_valid;
    wire [31:0] step_index;
    wire [1:0] step_lane_mask;
    wire [255:0] step_node0, step_node1;
    wire [31:0] accepted_job_commands;
    wire [31:0] host_control_writes_during_busy;
    wire [31:0] issued_hash_requests;
    wire [31:0] retired_instructions;
    wire [31:0] completed_steps;
    wire [31:0] lane0_internal_hash_calls;
    wire [31:0] lane1_internal_hash_calls;
    wire [31:0] lane0_active_cycles, lane0_idle_cycles;
    wire [31:0] lane1_active_cycles, lane1_idle_cycles;

    logic [31:0] observed_indices [0:2];
    logic [1:0] observed_masks [0:2];
    logic [255:0] observed_node0 [0:2];
    logic [255:0] observed_node1 [0:2];
    integer observed_steps = 0;
    integer watchdog;
    integer i;
    integer p2_lane_active_cycles;
    integer tail_lane0_active_cycles;
    integer tail_lane1_active_cycles;
    integer tail_lane0_idle_cycles;
    integer tail_lane1_idle_cycles;

    always #5 clk = ~clk;

    micro_hbs_randomized_f_p2_slice #(.UNROLL(2)) dut (.*);

    always @(posedge clk) begin
        #1;
        if (step_valid) begin
            observed_indices[observed_steps] = step_index;
            observed_masks[observed_steps] = step_lane_mask;
            observed_node0[observed_steps] = step_node0;
            observed_node1[observed_steps] = step_node1;
            observed_steps = observed_steps + 1;
        end
    end

    function automatic [63:0] enc;
        input [7:0] opcode;
        input [7:0] flags;
        input [7:0] rd;
        input [7:0] rs;
        input [31:0] imm;
        enc = {opcode, flags, rd, rs, imm};
    endfunction

    task automatic write_program;
        input [8:0] address;
        input [63:0] word;
        begin
            @(negedge clk);
            program_addr = address;
            program_wdata = word;
            program_we = 1'b1;
            @(negedge clk);
            program_we = 1'b0;
        end
    endtask

    task automatic load_chain_program;
        input [1:0] mask;
        begin
            // Dynamic public bound initializes R0.  HASH_LAYOUT binds R0 to
            // ADRS word 6 without an algorithm-specific instruction.
            write_program(0, enc(8'h04, 8'h01, 1, 0, 32'd3));
            write_program(1, enc(8'h03, {6'b0, mask}, 0, 0, 32'h0300));
            write_program(2, enc(8'h05, 0, 0, 0, 0));
            write_program(3, enc(8'h0d, 0, 0, 0, 0));
        end
    endtask

    task automatic launch_and_mutate_raw_bus;
        begin
            @(negedge clk);
            while (!job_ready) @(negedge clk);
            job_entry = 0;
            job_valid = 1'b1;
            @(negedge clk);
            job_valid = 1'b0;
            if (!busy)
                $fatal(1, "Job did not enter BUSY after acceptance");

            // These are data-bus changes only: program_we and job_valid stay
            // low, so there is no busy-time host write/task/hash transaction.
            job_entry = '1;
            job_pub_seed = '1;
            job_address_template = '1;
            job_node0 = '1;
            job_node1 = '1;
            job_chain_bound = 8'd15;
            program_addr = '1;
            program_wdata = '1;
            if (program_we || job_valid)
                $fatal(1, "unexpected busy-time command input");
        end
    endtask

    task automatic wait_success;
        begin
            watchdog = 0;
            while (!done && !error) begin
                @(posedge clk);
                #1;
                watchdog = watchdog + 1;
                if (!done && !error && job_ready)
                    $fatal(1, "Job interface exposed during BUSY");
                if (watchdog > 700)
                    $fatal(1, "randomized-F P2 Job timeout");
            end
            if (error)
                $fatal(1, "unexpected randomized-F P2 error %h", error_code);
        end
    endtask

    task automatic wait_failure;
        input [15:0] expected_code;
        begin
            watchdog = 0;
            while (!done && !error) begin
                @(posedge clk);
                #1;
                watchdog = watchdog + 1;
                if (watchdog > 80)
                    $fatal(1, "invalid Job did not fail closed");
            end
            if (!error || done || error_code != expected_code)
                $fatal(1, "failure mismatch done=%0d error=%0d code=%h expected=%h",
                       done, error, error_code, expected_code);
        end
    endtask

    task automatic check_lane0_trace;
        begin
            if (observed_steps != 3)
                $fatal(1, "step trace length %0d", observed_steps);
            if (observed_indices[0] != 0 || observed_indices[1] != 1
                || observed_indices[2] != 2)
                $fatal(1, "step index trace mismatch %0d,%0d,%0d",
                       observed_indices[0], observed_indices[1],
                       observed_indices[2]);
            if (observed_node0[0]
                !== 256'h27109a4f7d4b20deedd61a8b4b17f04c5592be71d03645f41bf200ce8be40927)
                $fatal(1, "lane0 oracle mismatch at step 0");
            if (observed_node0[1]
                !== 256'hc1e3ce21bce194c097a8238f8cf0aa945cfc85008c42a8226a779ed42acd928c)
                $fatal(1, "lane0 oracle mismatch at step 1");
            if (observed_node0[2]
                !== 256'h3d8f3507289a0eef556841c6b7ffc6567b41c9b7cc1a1ac8deddc08808bf51aa)
                $fatal(1, "lane0 oracle mismatch at step 2");
        end
    endtask

    task automatic apply_reset;
        begin
            rst_n = 1'b0;
            repeat (3) @(posedge clk);
            rst_n = 1'b1;
            @(posedge clk);
        end
    endtask

    initial begin : kat
        reg [255:0] raw_pub_seed;
        reg [255:0] raw_address;
        reg [255:0] raw_node0;
        reg [255:0] raw_node1;

        raw_pub_seed = '0;
        raw_address = '0;
        raw_node0 = '0;
        raw_node1 = '0;
        for (i = 0; i < 32; i = i + 1) begin
            raw_pub_seed[8*i +: 8] = 8'h20 + i[7:0];
            raw_node0[8*i +: 8] = i[7:0];
            raw_node1[8*i +: 8] = 8'h80 + i[7:0];
        end
        // ADRS words [0,0,0,0,5,2,step,0], serialized big-endian.
        raw_address[8*19 +: 8] = 8'h05;
        raw_address[8*23 +: 8] = 8'h02;

        apply_reset();
        load_chain_program(2'b11);

        job_pub_seed = raw_pub_seed;
        job_address_template = raw_address;
        job_node0 = raw_node0;
        job_node1 = raw_node1;
        job_chain_bound = 3;
        observed_steps = 0;
        launch_and_mutate_raw_bus();
        wait_success();
        check_lane0_trace();
        if (observed_masks[0] != 2'b11 || observed_masks[1] != 2'b11
            || observed_masks[2] != 2'b11)
            $fatal(1, "P2 step mask trace mismatch");
        if (observed_node1[0]
            !== 256'he18162ee733802b7425b1fc61b251d3d453958701e00f73d5c10c7fb68bec112)
            $fatal(1, "lane1 chain-address+1 oracle mismatch at step 0");
        if (observed_node1[1]
            !== 256'h2c7588e6c65ffc896e30e781f4e7751b516b9dc6d8f980c4178e8aad3af01e73)
            $fatal(1, "lane1 chain-address+1 oracle mismatch at step 1");
        if (observed_node1[2]
            !== 256'h4c686978afcddf5637ce31f5d40f62ab0a403fa71c1d51bd666a6772c0d5b414)
            $fatal(1, "lane1 chain-address+1 oracle mismatch at step 2");
        if (result_node0 !== observed_node0[2]
            || result_node1 !== observed_node1[2])
            $fatal(1, "P2 final feedback result mismatch");
        if (accepted_job_commands != 1 || issued_hash_requests != 3
            || completed_steps != 3 || retired_instructions != 8)
            $fatal(1, "P2 autonomy counters jobs=%0d req=%0d steps=%0d retired=%0d",
                   accepted_job_commands, issued_hash_requests,
                   completed_steps, retired_instructions);
        if (lane0_internal_hash_calls != 9 || lane1_internal_hash_calls != 9)
            $fatal(1, "P2 internal SHAKE calls %0d/%0d",
                   lane0_internal_hash_calls, lane1_internal_hash_calls);
        if (lane0_active_cycles != lane1_active_cycles
            || lane0_idle_cycles != lane1_idle_cycles)
            $fatal(1, "P2 lane utilization is asymmetric");
        if (host_control_writes_during_busy != 0)
            $fatal(1, "unexpected busy-time host program write");
        p2_lane_active_cycles = lane0_active_cycles;

        // Same Job program with static mask 01: lane1 must remain entirely
        // idle and its raw node must pass through unchanged.
        load_chain_program(2'b01);
        job_pub_seed = raw_pub_seed;
        job_address_template = raw_address;
        job_node0 = raw_node0;
        job_node1 = raw_node1;
        job_chain_bound = 3;
        observed_steps = 0;
        launch_and_mutate_raw_bus();
        wait_success();
        check_lane0_trace();
        if (observed_masks[0] != 2'b01 || observed_masks[1] != 2'b01
            || observed_masks[2] != 2'b01)
            $fatal(1, "tail step mask trace mismatch");
        if (observed_node1[0] !== raw_node1
            || observed_node1[1] !== raw_node1
            || observed_node1[2] !== raw_node1)
            $fatal(1, "disabled lane1 changed during tail steps");
        if (result_node0 !== observed_node0[2] || result_node1 !== raw_node1)
            $fatal(1, "tail final feedback/pass-through mismatch");
        if (accepted_job_commands != 2 || issued_hash_requests != 6
            || completed_steps != 3 || retired_instructions != 16)
            $fatal(1, "tail autonomy counters mismatch");
        if (lane0_internal_hash_calls != 9 || lane1_internal_hash_calls != 0)
            $fatal(1, "tail internal SHAKE calls %0d/%0d",
                   lane0_internal_hash_calls, lane1_internal_hash_calls);
        if (lane0_active_cycles == 0 || lane1_active_cycles != 0
            || lane1_idle_cycles <= lane0_idle_cycles)
            $fatal(1, "tail lane utilization mismatch active=%0d/%0d idle=%0d/%0d",
                   lane0_active_cycles, lane1_active_cycles,
                   lane0_idle_cycles, lane1_idle_cycles);
        if ((lane0_active_cycles + lane0_idle_cycles)
            != (lane1_active_cycles + lane1_idle_cycles))
            $fatal(1, "lane accounting windows differ");
        if (host_control_writes_during_busy != 0)
            $fatal(1, "busy-time program write counter changed");
        tail_lane0_active_cycles = lane0_active_cycles;
        tail_lane1_active_cycles = lane1_active_cycles;
        tail_lane0_idle_cycles = lane0_idle_cycles;
        tail_lane1_idle_cycles = lane1_idle_cycles;

        // Bound zero and values above the RFC 8391 w=16 maximum (15) are
        // rejected by the generic dynamic-bound interface before any hash.
        job_pub_seed = raw_pub_seed;
        job_address_template = raw_address;
        job_node0 = raw_node0;
        job_node1 = raw_node1;
        job_chain_bound = 16;
        launch_and_mutate_raw_bus();
        wait_failure(16'h0402);
        if (issued_hash_requests != 6)
            $fatal(1, "invalid bound issued a hash request");

        // Reset clears the sequencer's sticky fault.  A nonzero but illegal
        // lane mask reaches the generic layout capability and fails closed.
        apply_reset();
        load_chain_program(2'b10);
        job_pub_seed = raw_pub_seed;
        job_address_template = raw_address;
        job_node0 = raw_node0;
        job_node1 = raw_node1;
        job_chain_bound = 1;
        launch_and_mutate_raw_bus();
        wait_failure(16'h0401);
        if (accepted_job_commands != 1 || issued_hash_requests != 1
            || completed_steps != 0)
            $fatal(1, "invalid-mask fail-closed counters mismatch");

        $display("PASS randomized-F P2/U2 raw Job: distinct chain 2/3 + tail oracles, 9/9 and 9/0 SHAKE, P2 active/lane=%0d, tail active=%0d/%0d idle=%0d/%0d, invalid bound/mask fail closed",
                 p2_lane_active_cycles,
                 tail_lane0_active_cycles, tail_lane1_active_cycles,
                 tail_lane0_idle_cycles, tail_lane1_idle_cycles);
        $finish;
    end
endmodule

`default_nettype wire
