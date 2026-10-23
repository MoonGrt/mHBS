`timescale 1ns / 1ps
`default_nettype none
// One outstanding hash/transform/output template. Chain and tree algorithms
// execute as bounded software routines in the program ROM.
// verilog_format: off
module sequencer (
 input wire clk,rst,start, input wire [6:0] entry, output wire ready, output logic done,error,
 output wire [7:0] program_address, input wire [63:0] program_data,
 output wire [4:0] template_address, input wire [63:0] template_data,
 output wire command_valid, input wire command_ready,command_done, output wire [47:0] command,
 output wire command_keep_coordinates,
 output wire control_valid, output wire [63:0] control,
 input wire control_ready,control_done,control_condition
);
// verilog_format: on
    typedef enum logic [2:0] {IDLE,FETCH,LOAD,ISSUE,WAIT_MACRO,WAIT_CONTROL} state_t;
    state_t state;
    logic [7:0] pc, return_pc[0:1];
    logic [1:0] return_depth;
    logic [63:0] token;
    logic [16:0] template_word;
    logic [10:0] coordinate,stride;
    logic [5:0] remaining;
    logic [1:0] sp;
    logic [7:0] loop_pc[0:1];
    logic [5:0] loop_remaining[0:1];
    logic [10:0] loop_bias[0:1],loop_delta[0:1];
    wire [1:0] kind=token[63:62];
    wire [5:0] back_count={1'b0,token[61:57]}+6'd1;
    wire [4:0] control_op=token[61:57];
    assign ready=state==IDLE;
    // Read the likely successor while the current token executes. No
    // context/ALU result feeds the ROM address: branch prediction is static.
    // A misprediction redirects through FETCH before executing another token.
    wire predict_branch=control[12:9]==0 || control[12:9]==2;
    wire loop_back=kind==2 && !(sp!=0 && loop_pc[sp-1]==pc && loop_remaining[sp-1]<=1);
    wire [7:0] lookahead_address=
        kind==3 && (control_op==8 || control_op==7 && predict_branch) ? token[20:13] :
        kind==3 && control_op==9 ? return_pc[!return_depth[0]] :
        loop_back ? pc-back_count : pc+8'd1;
    assign program_address=state==FETCH ? pc : lookahead_address;
    assign template_address={token[29],token[61:58]};
    assign command_valid=state==ISSUE;
    assign command_keep_coordinates=token[28];
    // The token remains stable until WAIT_CONTROL retires the instruction.
    // Issue directly from LOAD; the executor does not need a second copy.
    assign control_valid=state==LOAD && kind==3 && control_op>=1 &&
        control_op<=15 && token[8:0]==0;
    assign control=token;
    assign command={1'b0,template_word[2:0],3'd0,template_word[7:3],
        3'd0,template_word[12:8],template_word[15],template_word[16],
        template_word[14:13],coordinate,13'd0};
    task automatic fault;
        begin error<=1;state<=IDLE;end
    endtask
    task automatic advance;
        begin
            if(pc==8'd255) fault();
            else begin pc<=pc+1'b1;token<=program_data;state<=LOAD;end
        end
    endtask
    // Pure software controls retire on their execution edge. Storage and I/O
    // retain WAIT_CONTROL until the executor reports their actual completion.
    task automatic retire_control;
        begin
            if(control_op==7) begin
                if(!control_condition && pc==8'd255) fault();
                else begin
                    pc<=control_condition ? token[20:13] : pc+8'd1;
                    if(control_condition==predict_branch) begin token<=program_data;state<=LOAD;end
                    else state<=FETCH;
                end
            end
            else if(control_op==8) begin
                if(return_depth==2 || pc==8'd255) fault();
                else begin
                    return_pc[return_depth[0]]<=pc+1'b1;return_depth<=return_depth+1'b1;
                    pc<=token[20:13];token<=program_data;state<=LOAD;
                end
            end else if(control_op==9) begin
                if(return_depth==0) fault();
                else begin
                    pc<=return_pc[!return_depth[0]];return_depth<=return_depth-1'b1;token<=program_data;state<=LOAD;
                end
            end else advance();
        end
    endtask
    integer i;
    always_ff @(posedge clk) begin
        if(rst) begin
            state<=IDLE;done<=0;error<=0;pc<=0;token<=0;template_word<=0;
            coordinate<=0;stride<=0;remaining<=0;sp<=0;return_depth<=0;
            for(i=0;i<2;i=i+1) begin
                return_pc[i]<=0;loop_pc[i]<=0;loop_remaining[i]<=0;loop_bias[i]<=0;loop_delta[i]<=0;
            end
        end else begin
            done<=0;
            case(state)
                IDLE:if(start) begin
                    pc<={1'b0,entry};sp<=0;loop_bias[0]<=0;loop_bias[1]<=0;
                    return_depth<=0;error<=0;state<=FETCH;
                end
                FETCH:begin token<=program_data;state<=LOAD;end
                LOAD:begin
                    if(kind==3) begin
                        if(control_op==0) begin
                            if(token[56:0]!=0 || return_depth!=0 || sp!=0) fault();
                            else begin done<=1;state<=IDLE;end
                        end else if(control_op>15 || token[8:0]!=0) fault();
                        else if(control_ready) begin
                            if(control_done) retire_control();else state<=WAIT_CONTROL;
                        end
                    end else if(kind==2) begin
                        if(token[39:0]!=0 || back_count>pc) fault();
                        else if(sp!=0 && loop_pc[sp-1]==pc) begin
                            if(loop_remaining[sp-1]>1) begin
                                loop_remaining[sp-1]<=loop_remaining[sp-1]-1'b1;
                                loop_bias[sp-1]<=loop_bias[sp-1]+loop_delta[sp-1];
                                pc<=pc-back_count;token<=program_data;state<=LOAD;
                            end else begin
                                loop_bias[sp-1]<=0;sp<=sp-1'b1;advance();
                            end
                        end else if(sp==2 || token[56:51]==0) fault();
                        else begin
                            loop_pc[sp]<=pc;loop_remaining[sp]<=token[56:51];
                            loop_bias[sp]<=token[50:40];loop_delta[sp]<=token[50:40];
                            sp<=sp+1'b1;pc<=pc-back_count;token<=program_data;state<=LOAD;
                        end
                    end else if(token[27:0]!=0 || template_data[63:17]!=0 ||
                        !(template_data[2:0]==1 || template_data[2:0]==4 || template_data[2:0]==5)) fault();
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
                WAIT_CONTROL:if(control_done) retire_control();
                default:fault();
            endcase
        end
    end
endmodule
`default_nettype wire
