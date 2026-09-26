`timescale 1ns/1ps
`default_nettype none
// Fixed demonstration lifecycle: one start, Keygen, one message, one Sign.
module uhbs_job_sequence (
    input wire clk, rst, start,
    output wire ready, busy,
    output wire job_valid, input wire job_ready, output wire job_operation,
    input wire core_done, core_error, input wire [31:0] core_cycles,
    output logic keygen_done, done,
    output logic [31:0] keygen_cycles, sign_cycles
);
    typedef enum logic [2:0] {IDLE, KEYGEN_REQUEST, KEYGEN_WAIT, SIGN_REQUEST, SIGN_WAIT} state_t;
    state_t state;
    assign ready=state==IDLE;
    assign busy=state!=IDLE;
    assign job_valid=state==KEYGEN_REQUEST || state==SIGN_REQUEST;
    assign job_operation=state==SIGN_REQUEST || state==SIGN_WAIT;
    always_ff @(posedge clk) begin
        if(rst) begin state<=IDLE; keygen_done<=0; done<=0; keygen_cycles<=0; sign_cycles<=0; end
        else begin
            keygen_done<=0; done<=0;
            if(core_error && (state==KEYGEN_WAIT || state==SIGN_WAIT)) state<=IDLE;
            else case(state)
                IDLE: if(start) state<=KEYGEN_REQUEST;
                KEYGEN_REQUEST: if(job_ready) state<=KEYGEN_WAIT;
                KEYGEN_WAIT: if(core_done) begin keygen_done<=1; keygen_cycles<=core_cycles; state<=SIGN_REQUEST; end
                SIGN_REQUEST: if(job_ready) state<=SIGN_WAIT;
                SIGN_WAIT: if(core_done) begin sign_cycles<=core_cycles; done<=1; state<=IDLE; end
                default: state<=IDLE;
            endcase
        end
    end
endmodule
`default_nettype wire
