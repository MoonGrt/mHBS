`timescale 1ns / 1ps
`default_nettype none
// One outstanding main-compatible template macro. Tree algorithms execute as
// ordinary bounded control instructions in the program ROM.
// verilog_format: off
module sequencer (
 input wire clk,rst,start, input wire [6:0] entry, output wire ready, output logic done,error,
 output wire [6:0] program_address, input wire [63:0] program_data,
 output wire [4:0] template_address, input wire [63:0] template_data,
 output wire command_valid, input wire command_ready, command_done, output wire [47:0] command,
 output wire command_keep_coordinates,
 output wire control_valid, output wire [63:0] control,
 input wire control_ready, control_done, control_condition
);
// verilog_format: on
    typedef enum logic [2:0] {IDLE,FETCH,LOAD,ISSUE,WAIT_MACRO,CONTROL,WAIT_CONTROL} state_t;
    state_t state;
    logic [6:0] pc, return_pc;
    logic return_valid;
    logic [63:0] token;
    logic [16:0] template_word;
    logic [10:0] coordinate,stride;
    logic [5:0] remaining;
    logic [1:0] sp;
    logic [6:0] loop_pc[0:1];
    logic [5:0] loop_remaining[0:1];
    logic [10:0] loop_bias[0:1],loop_delta[0:1];
    wire [1:0] kind=token[63:62];
    wire [5:0] back_count={1'b0,token[61:57]}+6'd1;
    wire [4:0] control_op=token[61:57];
    assign ready=state==IDLE;
    assign program_address=pc;
    assign template_address={token[29],token[61:58]};
    assign command_valid=state==ISSUE;
    assign command_keep_coordinates=token[28];
    // The token remains stable until WAIT_CONTROL retires the instruction.
    // Issue directly from LOAD; the executor does not need a second copy.
    assign control_valid=state==LOAD && kind==3 && control_op>=1 &&
        control_op<=15 && token[9:0]==0;
    assign control=token;
    assign command={1'b0,template_word[2:0],3'd0,template_word[7:3],
        3'd0,template_word[12:8],template_word[15],template_word[16],
        template_word[14:13],coordinate,13'd0};
    task automatic fault;
        begin error<=1;state<=IDLE;end
    endtask
    task automatic advance;
        begin
            if(pc==127) fault();
            else begin pc<=pc+1'b1;state<=FETCH;end
        end
    endtask
    integer i;
    always_ff @(posedge clk) begin
        if(rst) begin
            state<=IDLE;done<=0;error<=0;pc<=0;token<=0;template_word<=0;
            coordinate<=0;stride<=0;remaining<=0;sp<=0;return_pc<=0;return_valid<=0;
            for(i=0;i<2;i=i+1) begin
                loop_pc[i]<=0;loop_remaining[i]<=0;loop_bias[i]<=0;loop_delta[i]<=0;
            end
        end else begin
            done<=0;
            case(state)
                IDLE:if(start) begin
                    pc<=entry;sp<=0;loop_bias[0]<=0;loop_bias[1]<=0;
                    return_valid<=0;error<=0;state<=FETCH;
                end
                FETCH:begin token<=program_data;state<=LOAD;end
                LOAD:begin
                    if(kind==3) begin
                        if(control_op==0) begin
                            if(token[56:0]!=0 || return_valid || sp!=0) fault();
                            else begin done<=1;state<=IDLE;end
                        end else if(control_op>15 || token[9:0]!=0) fault();
                        else if(control_ready) state<=WAIT_CONTROL;
                    end else if(kind==2) begin
                        if(token[39:0]!=0 || back_count>pc) fault();
                        else if(sp!=0 && loop_pc[sp-1]==pc) begin
                            if(loop_remaining[sp-1]>1) begin
                                loop_remaining[sp-1]<=loop_remaining[sp-1]-1'b1;
                                loop_bias[sp-1]<=loop_bias[sp-1]+loop_delta[sp-1];
                                pc<=pc-back_count;state<=FETCH;
                            end else begin
                                loop_bias[sp-1]<=0;sp<=sp-1'b1;advance();
                            end
                        end else if(sp==2 || token[56:51]==0) fault();
                        else begin
                            loop_pc[sp]<=pc;loop_remaining[sp]<=token[56:51];
                            loop_bias[sp]<=token[50:40];loop_delta[sp]<=token[50:40];
                            sp<=sp+1'b1;pc<=pc-back_count;state<=FETCH;
                        end
                    end else if(token[27:0]!=0 || template_data[63:17]!=0 ||
                        template_data[2:0]==0 || template_data[2:0]==3 || template_data[2:0]>5) fault();
                    else begin
                        template_word<=template_data[16:0];
                        coordinate<=token[57:47]+loop_bias[0]+loop_bias[1];
                        stride<=token[40:30];remaining<=token[46:41];state<=ISSUE;
                    end
                end
                ISSUE:if(command_ready) state<=WAIT_MACRO;
                WAIT_MACRO:if(command_done) begin
                    if(remaining!=0) begin
                        remaining<=remaining-1'b1;coordinate<=coordinate+stride;state<=ISSUE;
                    end else advance();
                end
                WAIT_CONTROL:if(control_done) begin
                    if(control_op==7 && control_condition) begin pc<=token[20:14];state<=FETCH;end
                    else if(control_op==8) begin
                        if(return_valid || pc==127) fault();
                        else begin return_pc<=pc+1'b1;return_valid<=1;pc<=token[20:14];state<=FETCH;end
                    end else if(control_op==9) begin
                        if(!return_valid) fault();
                        else begin pc<=return_pc;return_valid<=0;state<=FETCH;end
                    end else advance();
                end
                default:fault();
            endcase
        end
    end
endmodule
`default_nettype wire
