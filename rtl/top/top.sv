`timescale 1ns / 1ps
`default_nettype none

// verilog_format: off
module top #(
    parameter integer UNROLL=2,PIPELINE=1,
    parameter [255:0] SECRET_SEED=256'h00000000000000000000000000000000d1d06dcbb9181a55aabce64467d6b81d,
    parameter [255:0] SECRET_PRF=256'h00000000000000000000000000000000ca423fc52136322bce5c73a684d95cb7,
    parameter [255:0] PUBLIC_SEED=256'h00000000000000000000000000000000f416dc35e41222ef87445111008541d5,
    parameter [255:0] RANDOMIZER=256'h00000000000000000000000000000000f416dc35e41222ef87445111008541d5,
    parameter [255:0] PUBLIC_ROOT=256'h000000000000000000000000000000003d774653892d5f3695b370c7cdab63ff,
    parameter [31:0] KEY_INDEX=0,
    parameter [127:0] IDENTIFIER=0,
    parameter [1:0] OPERATION=2'd1,
    parameter PROGRAM_INIT_FILE="tb/vectors/slh_128f/sign/program.mem",
    parameter TEMPLATE_INIT_FILE="tb/vectors/slh_128f/sign/template.mem",
    parameter DESCRIPTOR_INIT_FILE="tb/vectors/slh_128f/sign/descriptor.mem"
)(
`ifndef SYNTHESIS
    output logic [15:0] error_code,
    output logic [63:0] boot_cycles, keygen_cycles, sign_cycles,
    output wire [63:0] hash_count, permutation_count,
`endif
    input wire clk, rst,
    input wire message_valid, output wire message_ready,
    input wire [6:0] message_length, input wire [63:0] message_data,
    input wire verify_valid, output wire verify_ready,
    input wire [255:0] verify_data, output wire verify_pass,
    output logic busy, done, keygen_done,error,
    output wire out_valid, output wire [255:0] out_data, output wire [5:0] out_bytes,
    output wire [1:0] result_kind,
    input wire signature_read_enable, input wire [10:0] signature_read_address,
    output wire signature_read_valid, output wire [255:0] signature_read_data,
    output wire [5:0] signature_read_bytes,
    output wire [5:0] signature_node_bytes,
    output wire signature_valid,signature_error,
    output wire [10:0] signature_nodes, output wire [15:0] signature_length
);
// verilog_format: on
    wire [3:0] program_address;
    wire [3:0] template_address;
    wire [63:0] program_data, template_data;
    wire [9:0] descriptor_addresses;
    wire [127:0] descriptor_data;

    // Algorithm-independent construction images prevent ROM constant folding.
    // The selected profile's image is patched into INIT after core synthesis.
    (* rom_style = "distributed", DONT_TOUCH = "yes" *) logic [63:0] program_memory[0:15];
    (* rom_style = "distributed", DONT_TOUCH = "yes" *) logic [63:0] template_memory[0:15];
    (* rom_style = "distributed", DONT_TOUCH = "yes" *) logic [63:0] descriptor_memory[0:31];
    initial begin
        if (PROGRAM_INIT_FILE != "") $readmemh(PROGRAM_INIT_FILE, program_memory);
        if (TEMPLATE_INIT_FILE != "") $readmemh(TEMPLATE_INIT_FILE, template_memory);
        if (DESCRIPTOR_INIT_FILE != "") $readmemh(DESCRIPTOR_INIT_FILE, descriptor_memory);
    end
    assign program_data = program_memory[program_address];
    assign template_data = template_memory[template_address];
    assign descriptor_data = {
        descriptor_memory[descriptor_addresses[9:5]], descriptor_memory[descriptor_addresses[4:0]]
    };

    // COMMON_EXECUTION_BEGIN: equivalent execution region in common.sv.
    typedef enum logic [2:0] { HEADER, PROFILE, RELEASE, REQUEST, RUN, HALTED} phase_t;

    phase_t phase;
    logic [63:0] image_header, profile_descriptor;
    logic core_released;
    wire [9:0] core_descriptor_addresses;
    wire core_message_ready, core_job_ready, core_done, core_error;
`ifndef SYNTHESIS
    wire [15:0] core_error_code;
    wire [63:0] core_cycles;
`endif

    wire [3:0] entry = OPERATION ? image_header[44:41] : image_header[39:36];
    wire message_length_valid = OPERATION <= 2 &&
        (OPERATION ? (message_length >= 7'd1 && message_length <= 7'd87)
                       : message_length == 7'd0);
    wire core_rst = rst || !core_released;
    assign descriptor_addresses = !core_released
        ? {5'd0, (phase == HEADER ? 5'd0 : 5'd1)}
        : core_descriptor_addresses;
    assign result_kind = OPERATION;
    assign message_ready = phase == RUN && core_message_ready;

    // verilog_format: off
    executor #(.UNROLL(UNROLL),.PIPELINE(PIPELINE)) core (
`ifndef SYNTHESIS
        .error_code(core_error_code),
        .hash_count,.permutation_count,.cycles(core_cycles),
`endif
        .clk,.rst(core_rst),.image_header,.profile_descriptor,.job_entry(entry),
        .program_address,.program_data,.template_address,.template_data,
        .descriptor_addresses(core_descriptor_addresses),.descriptor_data,
        .job_valid(phase==REQUEST && message_length_valid),.job_ready(core_job_ready),
        .job_index(KEY_INDEX),.job_identifier(IDENTIFIER),
        .job_operation(OPERATION),.job_message_length(message_length),
        .job_secret_seed(SECRET_SEED),.job_secret_prf(SECRET_PRF),
        .job_public_seed(PUBLIC_SEED),.job_public_root(PUBLIC_ROOT),.job_randomizer(RANDOMIZER),
        .message_valid(message_valid && phase==RUN),.message_ready(core_message_ready),.message_data,
        .verify_valid(verify_valid && phase==RUN),.verify_ready,.verify_data,.verify_pass,
        .out_valid,.out_data,.out_bytes,
        .busy(),.done(core_done),.error(core_error)
    );
    // verilog_format: on

    // Functional control remains present in both simulation and synthesis.
    always_ff @(posedge clk) begin
        if (rst) begin
            phase <= HEADER;
            core_released <= 0;
            busy <= 1;
            done <= 0;
            keygen_done <= 0;
            error <= 0;
            image_header <= 0;
            profile_descriptor <= 0;
        end else begin
            keygen_done <= 0;
            if (core_released && core_error) begin
                error <= 1;
                busy  <= 0;
                phase <= HALTED;
            end else begin
                case (phase)
                    HEADER: begin
                        image_header <= descriptor_data[63:0];
                        phase <= PROFILE;
                    end
                    PROFILE: begin
                        profile_descriptor <= descriptor_data[63:0];
                        core_released <= 1;
                        phase <= RELEASE;
                    end
                    RELEASE: phase <= REQUEST;
                    REQUEST: begin
                        if (!message_length_valid) begin
                            error <= 1;
                            busy  <= 0;
                            phase <= HALTED;
                        end else if (core_job_ready) begin
                            phase <= RUN;
                        end
                    end
                    RUN: begin
                        if (core_done) begin
                            if (!OPERATION) keygen_done <= 1;
                            done  <= 1;
                            busy  <= 0;
                            phase <= HALTED;
                        end
                    end
                    HALTED: begin
                    end
                    default: phase <= HALTED;
                endcase
            end
        end
    end

`ifndef SYNTHESIS
    // Diagnostics observe functional control without driving it.
    always_ff @(posedge clk) begin
        if (rst) begin
            error_code <= 0;
            boot_cycles <= 0;
            keygen_cycles <= 0;
            sign_cycles <= 0;
        end else begin
            if (!core_released) boot_cycles <= boot_cycles + 1;
            if (core_released && core_error) begin
                error_code <= core_error_code;
            end else if (phase == REQUEST && !message_length_valid) begin
                error_code <= 16'h3002;
            end else if (phase == RUN && core_done) begin
                if (OPERATION == 1) sign_cycles <= core_cycles;
                else if (OPERATION == 0) keygen_cycles <= core_cycles;
            end
        end
    end
`endif
    // COMMON_EXECUTION_END

    // Opt in with -DMHBS_SIGNATURE_STORE; the external readback interface stays
    // stable when storage is omitted, with all responses and status tied low.
`ifdef MHBS_SIGNATURE_STORE
    localparam bit SIGNATURE_STORE_PRESENT = 1;
`else
    localparam bit SIGNATURE_STORE_PRESENT = 0;
`endif

    generate
        if (SIGNATURE_STORE_PRESENT && OPERATION == 1) begin : stored_signature
            // verilog_format: off
            signature storage (
                .clk,.rst,.finish(done),.abort(error),
                .write_valid(out_valid),.write_data(out_data),.write_bytes(out_bytes),
                .read_enable(signature_read_enable),.read_address(signature_read_address),
                .read_valid(signature_read_valid),.read_data(signature_read_data),.read_bytes(signature_read_bytes),
                .node_bytes(signature_node_bytes),.complete(signature_valid),
                .error(signature_error),.nodes(signature_nodes),.length(signature_length)
            );
            // verilog_format: on
        end else begin : no_signature_store
            assign signature_read_valid = 0;
            assign signature_read_bytes = 0;
            assign signature_read_data = 0;
            assign signature_node_bytes = 0;
            assign signature_valid = 0;
            assign signature_error = 0;
            assign signature_nodes = 0;
            assign signature_length = 0;
        end
    endgenerate
endmodule

`default_nettype wire
