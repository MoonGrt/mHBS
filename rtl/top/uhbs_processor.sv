`timescale 1ns/1ps
`default_nettype none
// v4.2 generic image ports; compiled independently of initialization.
module uhbs_processor #(
 parameter integer LANES=2,UNROLL=2,parameter bit SWAP_PHYSICAL_LANES=0
)(
 input wire clk,rst_n,output wire [5:0] program_address,output wire [3:0] template_address,
 input wire [63:0] program_data,template_data,output wire [9:0] descriptor_addresses,
 input wire [127:0] descriptor_data,
 output wire out_valid,output wire [63:0] out_data,output wire [7:0] out_keep,
 output wire out_last,result_kind,output logic busy,done,keygen_done,error,
 output logic [15:0] error_code,output logic [31:0] boot_cycles,keygen_cycles,sign_cycles,
 output wire [31:0] hash_count,permutation_count
);
 typedef enum logic [2:0] {HEADER,PROFILE,CONTROL,JOB,RELEASE,REQUEST,RUN,HALTED} phase_t;
 phase_t phase;
 logic [4:0] load_index,entry;
 logic [63:0] image_header,profile_descriptor;
 logic [255:0] secret_seed,secret_prf,public_seed,randomizer,public_root;
 logic [6:0] message_length;
 logic operation,core_released,feeding_message;
 logic [3:0] message_word,last_message_word;
 wire [5:0] core_program_address;
 wire [9:0] core_descriptor_addresses;
 wire message_ready,core_job_ready,core_done,core_error;
 wire [15:0] core_error_code;
 wire [31:0] core_cycles;
 wire [6:0] last_byte=program_data[12:6]-7'd1;
 assign program_address=!core_released ? (phase==CONTROL ? 6'd52 : 6'd32+load_index)
     : feeding_message ? 6'd53+message_word : core_program_address;
 assign descriptor_addresses=!core_released ? {5'd0,(phase==HEADER ? 5'd0 : 5'd1)} : core_descriptor_addresses;
 assign result_kind=operation;
 wire core_rst_n=rst_n && core_released;
 uhbs_hbs #(.UNROLL(UNROLL),.LANES(LANES),.PROFILE_ENABLE(1),.SWAP_PHYSICAL_LANES(SWAP_PHYSICAL_LANES)) core (
  .clk,.rst_n(core_rst_n),.image_header,.profile_descriptor,.job_entry(entry),
  .program_address(core_program_address),.program_data,.template_address,.template_data,
  .descriptor_addresses(core_descriptor_addresses),.descriptor_data,
  .job_valid(phase==REQUEST),.job_ready(core_job_ready),.job_operation(operation),
  .job_message_length(message_length),.job_secret_seed(secret_seed),.job_secret_prf(secret_prf),
  .job_public_seed(public_seed),.job_randomizer(randomizer),.job_public_root(public_root),
  .message_valid(feeding_message),.message_ready,.message_data(program_data),
  .out_valid,.out_ready(1'b1),.out_data,.out_keep,.out_last,
  .busy(),.done(core_done),.error(core_error),.error_code(core_error_code),
  .hash_count,.permutation_count,.cycles(core_cycles)
 );
 // Overwrite every input before release; these data registers need no reset.
 always_ff @(posedge clk)if(rst_n && phase==JOB)begin
  case(load_index[4:2])
   0:secret_seed[load_index[1:0]*64 +:64]<=program_data;
   1:secret_prf[load_index[1:0]*64 +:64]<=program_data;
   2:public_seed[load_index[1:0]*64 +:64]<=program_data;
   3:randomizer[load_index[1:0]*64 +:64]<=program_data;
   4:public_root[load_index[1:0]*64 +:64]<=program_data;
   default:begin end
  endcase
 end
 always_ff @(posedge clk or negedge rst_n)begin
  if(!rst_n)begin
   phase<=HEADER;load_index<=0;core_released<=0;operation<=0;entry<=0;
   busy<=1;done<=0;keygen_done<=0;error<=0;error_code<=0;
   boot_cycles<=0;keygen_cycles<=0;sign_cycles<=0;
   image_header<=0;profile_descriptor<=0;message_length<=0;
   feeding_message<=0;message_word<=0;last_message_word<=0;
  end else begin
   keygen_done<=0;
   if(!core_released)boot_cycles<=boot_cycles+1;
   if(feeding_message && message_ready)begin
    message_word<=message_word+1'b1;if(message_word==last_message_word)feeding_message<=0;
   end
   if(core_released && core_error)begin
    error<=1;error_code<=core_error_code;busy<=0;feeding_message<=0;phase<=HALTED;
   end else case(phase)
    HEADER:begin image_header<=descriptor_data[63:0];phase<=PROFILE;end
    PROFILE:begin profile_descriptor<=descriptor_data[63:0];phase<=CONTROL;end
    CONTROL:begin operation<=program_data[0];entry<=program_data[5:1];message_length<=program_data[12:6];
     last_message_word<=last_byte[6:3];load_index<=0;phase<=JOB;end
    JOB:if(load_index==19)begin core_released<=1;phase<=RELEASE;end else load_index<=load_index+1'b1;
    RELEASE:phase<=REQUEST;
    REQUEST:if(core_job_ready)begin feeding_message<=operation;message_word<=0;phase<=RUN;end
    RUN:if(core_done)begin
     if(operation)sign_cycles<=core_cycles;else begin keygen_cycles<=core_cycles;keygen_done<=1;end
     done<=1;busy<=0;phase<=HALTED;
    end
    HALTED:begin end
    default:phase<=HALTED;
   endcase
  end
 end
endmodule
`default_nettype wire
