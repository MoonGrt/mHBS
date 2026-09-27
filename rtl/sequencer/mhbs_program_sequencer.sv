`timescale 1ns/1ps
`default_nettype none
// slh64_v4.2: offline-validated image, one outstanding macro.
module mhbs_program_sequencer (
 input wire clk,rst,start,input wire [4:0] entry,output wire ready,output logic done,
 output wire [4:0] program_address,input wire [63:0] program_data,
 output wire [3:0] template_address,input wire [63:0] template_data,
 output wire command_valid,input wire command_ready,command_done,output wire [47:0] command
);
 typedef enum logic [2:0] {IDLE,FETCH,LOAD,ISSUE,WAIT_MACRO} state_t;
 state_t state;
 logic [4:0] pc;
 logic [63:0] token;
 logic [15:0] template_word;
 logic [10:0] coordinate,stride;
 logic [5:0] remaining;
 logic [1:0] sp;
 logic [4:0] loop_pc[0:1];
 logic [5:0] loop_remaining[0:1];
 logic [10:0] loop_bias[0:1],loop_delta[0:1];
 wire [1:0] kind=token[63:62];
 wire [5:0] back_count={1'b0,token[61:57]}+6'd1;
 assign program_address=pc;
 assign template_address=token[61:58];
 assign ready=state==IDLE;
 assign command_valid=state==ISSUE;
 assign command={1'b0,template_word[2:0],3'd0,template_word[7:3],3'd0,template_word[12:8],
                 template_word[15],1'b0,template_word[14:13],coordinate,13'd0};
 integer i;
 always_ff @(posedge clk) begin
  if(rst) begin
   state<=IDLE;done<=0;pc<=0;token<=0;template_word<=0;coordinate<=0;stride<=0;remaining<=0;sp<=0;
   for(i=0;i<2;i=i+1)begin loop_pc[i]<=0;loop_remaining[i]<=0;loop_bias[i]<=0;loop_delta[i]<=0;end
  end else begin
   done<=0;
   case(state)
    IDLE:if(start)begin pc<=entry;sp<=0;loop_bias[0]<=0;loop_bias[1]<=0;state<=FETCH;end
    FETCH:begin token<=program_data;state<=LOAD;end
    LOAD:begin
     if(kind==3)begin done<=1;state<=IDLE;end
     else if(kind==2)begin
      if(sp!=0 && loop_pc[sp-1]==pc)begin
       if(loop_remaining[sp-1]>1)begin
        loop_remaining[sp-1]<=loop_remaining[sp-1]-1'b1;
        loop_bias[sp-1]<=loop_bias[sp-1]+loop_delta[sp-1];pc<=pc-back_count;
       end else begin loop_bias[sp-1]<=0;sp<=sp-1'b1;pc<=pc+1'b1;end
      end else begin
       loop_pc[sp]<=pc;loop_remaining[sp]<=token[56:51];loop_bias[sp]<=token[50:40];
       loop_delta[sp]<=token[50:40];sp<=sp+1'b1;pc<=pc-back_count;
      end
      state<=FETCH;
     end else begin
      template_word<=template_data[15:0];coordinate<=token[57:47]+loop_bias[0]+loop_bias[1];
      stride<=token[40:30];remaining<=token[46:41];state<=ISSUE;
     end
    end
    ISSUE:if(command_ready)state<=WAIT_MACRO;
    WAIT_MACRO:if(command_done)begin
     if(remaining!=0)begin remaining<=remaining-1'b1;coordinate<=coordinate+stride;state<=ISSUE;end
     else begin pc<=pc+1'b1;state<=FETCH;end
    end
    default:state<=IDLE;
   endcase
  end
 end
endmodule
`default_nettype wire
