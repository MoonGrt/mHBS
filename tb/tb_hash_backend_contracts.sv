`timescale 1ns / 1ps
`default_nettype none
// Job admission only: message_valid remains low, so no tree/hash executes.
module tb_hash_backend_contracts;
    logic clk=0, rst=1;
    always #5 clk=~clk;
`ifdef MHBS_SHA2
    localparam [63:0] BACKEND_BIT=64'h20;
`else
    localparam [63:0] BACKEND_BIT=64'h00;
`endif
    logic [63:0] profile=0;
    logic [31:0] job_index=0;
    logic [6:0] message_length=1;
    wire [7:0] program_address;wire [4:0] template_address;
    wire [9:0] descriptor_addresses;
    wire [127:0] descriptor_data;
    function automatic [63:0] descriptor(input [4:0] address);
        descriptor=address==0 ? 64'ha808080000000000 : address==1 ? profile : 0;
    endfunction
    assign descriptor_data={descriptor(descriptor_addresses[9:5]),descriptor(descriptor_addresses[4:0])};
    wire message_ready, busy, done, error, out_valid;
`ifndef SYNTHESIS
    wire [15:0] error_code;
    wire [63:0] hash_count, permutation_count;
`endif
    // verilog_format: off
    common #(.PIPELINE(1),.UNROLL(1)) dut (
        .clk,.rst,.program_address,.template_address,.descriptor_addresses,.descriptor_data,
        .program_data(64'hc000000000000000),.template_data(64'd0),
        .job_secret_seed(256'd0),.job_secret_prf(256'd0),.job_public_seed(256'd0),
        .job_randomizer(256'd0),.job_public_root(256'd0),.job_identifier(128'd0),
        .job_index,.job_operation(2'd1),.message_length,
        .message_valid(1'b0),.message_data(64'd0),.message_ready,
        .verify_valid(1'b0),.verify_data(256'd0),.verify_ready(),.verify_pass(),
        .out_valid,.out_data(),.out_bytes(),.result_kind(),.busy,.done,.keygen_done(),.error
`ifndef SYNTHESIS
        ,.error_code,.boot_cycles(),.keygen_cycles(),.sign_cycles(),.hash_count,.permutation_count
`endif
    );
    // verilog_format: on
    integer cases=0, accepted_cases=0, rejected_cases=0, recipe_cases=0;
    task automatic tick;
        @(posedge clk); #1;
    endtask
    task automatic admission(input [63:0] code,input [31:0] q,
        input [6:0] length,input bit expected);
        begin
            rst=1; profile=code; job_index=q; message_length=length;
            repeat(3) tick();
            rst=0;
            repeat(14) tick();
            if(error!==!expected || message_ready!==expected || done || out_valid)
                $fatal(1,"Admission mismatch profile=%h q=%0d length=%0d expected=%b error=%b ready=%b",
                    code,q,length,expected,error,message_ready);
`ifndef SYNTHESIS
            if(hash_count!=0 || permutation_count!=0)
                $fatal(1,"Admission test unexpectedly executed a hash");
`endif
            repeat(3) begin
                tick();
                if(error!==!expected || message_ready!==expected || done || out_valid)
                    $fatal(1,"Admission state did not remain stable");
            end
            cases=cases+1;
            if(expected) accepted_cases=accepted_cases+1;
            else rejected_cases=rejected_cases+1;
        end
    endtask

`ifdef MHBS_SHA2
    logic recipe_rst=1, request_valid=0, response_ready=0, request_capture=0;
    logic [63:0] request_recipe=0;
    wire request_ready, response_valid, recipe_error;
    wire [391:0] response_value;
    wire [255:0] response_capture;
    logic [255:0] secret_seed=0, public_seed=0, left=0, right=0, fixed_expected;
    // verilog_format: off
    recipe #(.N(32),.DIGEST_BYTES(49),.INDEX_BITS(8),.PIPELINE(1),.UNROLL(1),
        .RECIPE_MASK(16'h7fff)) scalar (
        .clk,.rst(recipe_rst),.error(recipe_error),.node_bytes(6'd16),.identifier(128'd0),
        .batch_mode(1'b0),.batch_request_valid(1'b0),.batch_request_ready(),
        .batch_request_tag(1'd0),.batch_steps(5'd0),.batch_capture_after(5'd0),.batch_capture_enable(1'b0),
        .batch_leaf(20'd0),.batch_a(8'd0),.batch_b(32'd0),.batch_family(2'd0),.batch_no_seed(1'b0),
        .batch_start(4'd0),.batch_initial_value(256'd0),.batch_fixed_shape(4'd0),.batch_pair(1'b0),
        .batch_right(256'd0),.batch_seed_domain(8'd0),.batch_step_domain(8'd0),
        .batch_response_valid(),.batch_response_ready(1'b0),.batch_response_tag(),
        .batch_response_digest(),.batch_response_capture(),.batch_read_tag(1'd0),
        .batch_read_digest(),.batch_read_capture(),
        .request_valid,.request_ready,.request_recipe,.request_step_recipe(64'd0),
        .request_chain(1'b0),.request_steps(5'd0),.request_capture_after(5'd1),.request_capture,
        .secret_seed,.secret_prf(256'd0),.public_seed,.root(256'd0),.randomizer(256'd0),
        .message_buffer(696'd0),.message_length(7'd1),.request_layer(5'd3),
        .request_tree(64'h0123456789abcdef),.request_leaf(20'd513),.request_a(8'd67),
        .request_b(32'h12345678),.request_left(left),.request_right(right),
        .list_index0(),.list_index1(),.list_next_index0(),.list_data0(256'd0),.list_data1(256'd0),
        .response_valid,.response_ready,.response_value,.response_capture
`ifndef SYNTHESIS
        ,.batch_hashes(),.batch_permutations(),.hash_count(),.permutation_count()
`endif
    );
    // verilog_format: on
    task automatic scalar_case(input [3:0] selected_shape,input bit expected_error);
        integer timeout;
        reg [391:0] held_value;
        begin
            recipe_rst=1; request_valid=0; response_ready=0;
            request_capture=!expected_error;
            request_recipe=(64'(selected_shape)<<56)|(64'h83<<48)|(64'd2<<40)|(64'd16<<32)|(64'd63<<24);
            repeat(3) tick();
            recipe_rst=0; tick();
            if(!request_ready) $fatal(1,"Recipe did not accept after reset");
            request_valid=1; tick(); request_valid=0;
            timeout=0;
            while(!response_valid) begin
                tick(); timeout=timeout+1;
                if(timeout>(expected_error ? 8 : 1000)) $fatal(1,"Recipe error/response handshake hung");
            end
            if(recipe_error!==expected_error) $fatal(1,"Unexpected recipe error status");
            if(!expected_error && (response_value[255:0]!==fixed_expected ||
                response_value[391:256]!==0 || response_capture!==fixed_expected))
                $fatal(1,"Fixed recipe capture mismatch value=%h capture=%h expected=%h",
                    response_value,response_capture,fixed_expected);
            held_value=response_value;
            repeat(4) begin
                tick();
                if(!response_valid || request_ready || recipe_error!==expected_error || response_value!==held_value)
                    $fatal(1,"Recipe response was not retained under backpressure");
            end
            response_ready=1; tick(); response_ready=0; tick();
            if(response_valid || !request_ready) $fatal(1,"Recipe did not release consumed response");
            recipe_cases=recipe_cases+1;
        end
    endtask
`endif

    initial begin
        // h20 never appears below: its encodings are checked statically by the
        // Python runner and its widths are elaborated in the universal core.
        admission(BACKEND_BIT|0,0,1,1);
        admission(BACKEND_BIT|4,0,87,1);
        admission(BACKEND_BIT|64'h18,0,1,1);
        admission(BACKEND_BIT|64'h18,1,1,1);
        admission(BACKEND_BIT|64'h18,1023,1,1);
        admission(BACKEND_BIT|64'h18,1024,1,0);
        admission(BACKEND_BIT|64'h1b,1023,1,1);
        admission(BACKEND_BIT|64'h1b,1024,1,0);
        admission(BACKEND_BIT|64'h19,1024,1,1);
        admission(BACKEND_BIT|64'h19,32768,1,1);
        admission(BACKEND_BIT|64'h19,65535,1,1);
        admission(BACKEND_BIT|64'h19,65536,1,0);
        admission(BACKEND_BIT|64'h1c,1024,1,1);
        admission(BACKEND_BIT|64'h1c,32767,1,1);
        admission(BACKEND_BIT|64'h1c,32768,1,0);
        for(integer bit_index=6;bit_index<64;bit_index=bit_index+1)
            admission(BACKEND_BIT|(64'd1<<bit_index),0,1,0);
        admission((BACKEND_BIT^64'h20)|0,0,1,0);
        admission((BACKEND_BIT^64'h20)|4,0,1,0);
        admission((BACKEND_BIT^64'h20)|64'h18,0,1,0);
        admission((BACKEND_BIT^64'h20)|64'h1b,0,1,0);
`ifdef MHBS_SHA2
        admission(BACKEND_BIT|1,0,1,0);
        admission(BACKEND_BIT|2,0,1,0);
        admission(BACKEND_BIT|5,0,1,0);
        admission(BACKEND_BIT|6,0,1,0);
`else
        admission(BACKEND_BIT|1,0,1,1);
        admission(BACKEND_BIT|2,0,1,1);
        admission(BACKEND_BIT|5,0,1,1);
        admission(BACKEND_BIT|6,0,1,1);
`endif
        admission(BACKEND_BIT|64'h10,0,1,0);
        admission(BACKEND_BIT|64'h11,0,1,0);
        admission(BACKEND_BIT,0,0,0);
        admission(BACKEND_BIT,0,88,0);
        admission(BACKEND_BIT,0,127,0);
        rst=1; repeat(3) tick();
`ifdef MHBS_SHA2
        if(!$value$plusargs("FIXED_EXPECTED=%h",fixed_expected)) $fatal(1,"FIXED_EXPECTED required");
        for(integer k=0;k<32;k=k+1) begin
            secret_seed[k*8+:8]=8'(k+1); public_seed[k*8+:8]=8'(k+65);
            left[k*8+:8]=8'(k+161); right[k*8+:8]=8'(k+193);
        end
        scalar_case(4'd0,1);
        scalar_case(4'd2,0);
        scalar_case(4'd15,1);
        scalar_case(4'd2,0);
`endif
        $display("HASH_BACKEND_CONTRACTS_PASS backend_bit=%h admissions=%0d accepted=%0d rejected=%0d recipes=%0d h20_jobs=0",
            BACKEND_BIT,cases,accepted_cases,rejected_cases,recipe_cases);
        $finish;
    end
endmodule
`default_nettype wire
