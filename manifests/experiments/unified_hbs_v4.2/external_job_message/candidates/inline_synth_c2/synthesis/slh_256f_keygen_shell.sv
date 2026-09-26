`timescale 1ns/1ps
`default_nettype none
module uhbs_top #(
    parameter integer LANES=2,UNROLL=2,
    parameter bit SWAP_PHYSICAL_LANES=0,
    parameter [255:0] SECRET_SEED=256'h0b4aa1346ff6f7f48301823c2594d44555f9a25b176721a082227130abd55d79,
    parameter [255:0] SECRET_PRF=256'ha327db7afb31277f93a9c7eb2f31358cc3f0ec984b8f1aa32901b14c85c748ad,
    parameter [255:0] PUBLIC_SEED=256'ha30998feb9594a23d122c76ea0367151ede46dbbe9c52d130c3751f97fdbf9cc,
    parameter [255:0] RANDOMIZER=256'ha30998feb9594a23d122c76ea0367151ede46dbbe9c52d130c3751f97fdbf9cc,
    parameter [255:0] PUBLIC_ROOT=256'h0000000000000000000000000000000000000000000000000000000000000000,
    parameter bit OPERATION=1'b0,
    parameter PROGRAM_INIT_FILE="experiments/v4.2/external_job_message/program_construction.mem",
    parameter TEMPLATE_INIT_FILE="experiments/v4.2/external_job_message/template_construction.mem",
    parameter DESCRIPTOR_INIT_FILE="experiments/v4.2/external_job_message/descriptor_construction.mem"
)(
    input wire clk,rst,
    input wire [6:0] message_length,
    input wire [63:0] message_data,input wire message_valid,output wire message_ready,
    output logic busy,done,keygen_done,error,output logic [15:0] error_code,
    output logic [31:0] boot_cycles,keygen_cycles,sign_cycles,
    output wire [31:0] hash_count,permutation_count,
    output wire out_valid,output wire [63:0] out_data,output wire [7:0] out_keep,
    output wire out_last,result_kind
);
    (* ASYNC_REG="TRUE" *) logic [1:0] reset_sync;
    always_ff @(posedge clk or posedge rst) begin
        if(rst) reset_sync<=2'b11; else reset_sync<={reset_sync[0],1'b0};
    end
    wire rst_n=~reset_sync[1];
    wire [4:0] program_address;
    wire [3:0] template_address;
    wire [63:0] program_data,template_data;
    (* KEEP="TRUE", DONT_TOUCH="TRUE" *) wire [9:0] descriptor_addresses;
    wire [127:0] descriptor_data;
    // Inferred arrays, no explicit ROM module or vendor memory primitive.
    // Hardware synthesis uses algorithm-independent construction images;
    // real images are applied to INIT only after the common netlist is frozen.
    (* rom_style="distributed", DONT_TOUCH="yes" *) logic [63:0] program_memory[0:31];
    (* rom_style="distributed", DONT_TOUCH="yes" *) logic [63:0] template_memory[0:15];
    (* rom_style="distributed", DONT_TOUCH="yes" *) logic [63:0] descriptor_memory[0:31];
    initial begin
        if(PROGRAM_INIT_FILE!="") $readmemh(PROGRAM_INIT_FILE,program_memory);
        if(TEMPLATE_INIT_FILE!="") $readmemh(TEMPLATE_INIT_FILE,template_memory);
        if(DESCRIPTOR_INIT_FILE!="") $readmemh(DESCRIPTOR_INIT_FILE,descriptor_memory);
    end
    assign program_data=program_memory[program_address];
    assign template_data=template_memory[template_address];
    (* KEEP="TRUE", DONT_TOUCH="TRUE" *) wire [63:0] descriptor_word0=descriptor_memory[descriptor_addresses[4:0]];
    (* KEEP="TRUE", DONT_TOUCH="TRUE" *) wire [63:0] descriptor_word1=descriptor_memory[descriptor_addresses[9:5]];
    assign descriptor_data={descriptor_word1,descriptor_word0};
    typedef enum logic [2:0] {HEADER,PROFILE,RELEASE,REQUEST,RUN,HALTED} phase_t;
    phase_t phase;
    logic [63:0] image_header,profile_descriptor;
    logic core_released;
    wire [9:0] core_descriptor_addresses;
    wire core_message_ready,core_job_ready,core_done,core_error;
    wire [15:0] core_error_code;
    wire [31:0] core_cycles;
    wire [4:0] entry=OPERATION ? image_header[45:41] : image_header[40:36];
    wire message_length_valid=OPERATION ? (message_length>=7'd1 && message_length<=7'd87)
                                        : (message_length==7'd0);
    wire core_rst_n=rst_n && core_released;
    assign descriptor_addresses=!core_released ? {5'd0,(phase==HEADER ? 5'd0 : 5'd1)}
                                               : core_descriptor_addresses;
    assign result_kind=OPERATION;
    assign message_ready=(phase==RUN) && core_message_ready;
    (* DONT_TOUCH="yes" *) uhbs_hbs core (
        .clk,.rst_n(core_rst_n),.image_header,.profile_descriptor,.job_entry(entry),
        .program_address,.program_data,.template_address,.template_data,
        .descriptor_addresses(core_descriptor_addresses),.descriptor_data,
        .job_valid(phase==REQUEST && message_length_valid),.job_ready(core_job_ready),
        .job_operation(OPERATION),.job_message_length(message_length),
        .job_secret_seed(SECRET_SEED),.job_secret_prf(SECRET_PRF),
        .job_public_seed(PUBLIC_SEED),.job_randomizer(RANDOMIZER),.job_public_root(PUBLIC_ROOT),
        .message_valid(message_valid && phase==RUN),.message_ready(core_message_ready),.message_data,
        .out_valid,.out_ready(1'b1),.out_data,.out_keep,.out_last,
        .busy(),.done(core_done),.error(core_error),.error_code(core_error_code),
        .hash_count,.permutation_count,.cycles(core_cycles)
    );
    always_ff @(posedge clk or negedge rst_n) begin
        if(!rst_n) begin
            phase<=HEADER;core_released<=0;
            busy<=1;done<=0;keygen_done<=0;error<=0;error_code<=0;
            boot_cycles<=0;keygen_cycles<=0;sign_cycles<=0;
            image_header<=0;profile_descriptor<=0;
        end else begin
            keygen_done<=0;
            if(!core_released) boot_cycles<=boot_cycles+1;
            if(core_released && core_error) begin
                error<=1;error_code<=core_error_code;busy<=0;phase<=HALTED;
            end else case(phase)
                HEADER:begin image_header<=descriptor_data[63:0];phase<=PROFILE;end
                PROFILE:begin profile_descriptor<=descriptor_data[63:0];core_released<=1;phase<=RELEASE;end
                RELEASE:phase<=REQUEST;
                REQUEST:begin
                    if(!message_length_valid) begin
                        error<=1;error_code<=16'h3002;busy<=0;phase<=HALTED;
                    end else if(core_job_ready) phase<=RUN;
                end
                RUN:if(core_done) begin
                    if(OPERATION) sign_cycles<=core_cycles;
                    else begin keygen_cycles<=core_cycles;keygen_done<=1;end
                    done<=1;busy<=0;phase<=HALTED;
                end
                HALTED:begin end
                default:phase<=HALTED;
            endcase
        end
    end
endmodule
`default_nettype wire
