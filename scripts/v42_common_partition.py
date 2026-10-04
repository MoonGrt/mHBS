"""Extract the top's execution region for OOC synthesis without changing its scope.

Production RTL keeps boot/control and mhbs_hbs in mhbs_top. The generated module
is a build artifact: its generic Job/ROM ports prevent algorithm specialization,
while the node output and boot/core connections remain inside the optimizer.
"""
import re

JOBS = {'SECRET_SEED':'job_secret_seed', 'SECRET_PRF':'job_secret_prf',
        'PUBLIC_SEED':'job_public_seed', 'RANDOMIZER':'job_randomizer',
        'PUBLIC_ROOT':'job_public_root', 'KEY_INDEX':'job_index', 'IDENTIFIER':'job_identifier', 'OPERATION':'job_operation'}
PORTS = '''
 input wire clk,rst,
 output wire [3:0] program_address,output wire [3:0] template_address,
 input wire [63:0] program_data,template_data,
 output wire [9:0] descriptor_addresses,input wire [127:0] descriptor_data,
 input wire [255:0] job_secret_seed,job_secret_prf,job_public_seed,job_randomizer,job_public_root,
 input wire [31:0] job_index,input wire [127:0] job_identifier,
 input wire [1:0] job_operation,input wire [6:0] message_length,
 input wire verify_valid,output wire verify_ready,
 input wire [255:0] verify_data,output wire verify_pass,
 input wire [63:0] message_data,input wire message_valid,output wire message_ready,
 output wire out_valid,output wire [255:0] out_data,output wire [5:0] out_bytes,
 output wire [1:0] result_kind,output logic busy,done,keygen_done,error,
 output logic [15:0] error_code,output logic [31:0] boot_cycles,keygen_cycles,sign_cycles,
 output wire [31:0] hash_count,permutation_count
'''

def partition(source, *, stub=False):
    begin='    // COMMON_EXECUTION_BEGIN:'
    end='    // COMMON_EXECUTION_END'
    assert source.count(begin)==source.count(end)==1
    start=source.index(begin);stop=source.index(end)+len(end)
    body=source[source.index('\n',start)+1:source.index(end)]
    body=re.sub(r'\b('+'|'.join(JOBS)+r')\b',lambda m:JOBS[m[0]],body)
    common='`timescale 1ns/1ps\n`default_nettype none\nmodule mhbs_common #(parameter integer LANES=2,UNROLL=2,PIPELINE=1,parameter bit SWAP_PHYSICAL_LANES=0,PROFILE_ENABLE=1)('+PORTS+');\n'+body+'endmodule\n`default_nettype wire\n'
    params='' if stub else ' #(.LANES(LANES),.UNROLL(UNROLL),.PIPELINE(PIPELINE),.SWAP_PHYSICAL_LANES(SWAP_PHYSICAL_LANES),.PROFILE_ENABLE(PROFILE_ENABLE))'
    instance='    (* DONT_TOUCH="yes" *) mhbs_common'+params+' common (\n'
    instance+=','.join('.'+v+'('+k+')' for k,v in JOBS.items())+',\n'
    instance+=' .clk,.rst,.message_length,.message_data,.message_valid,.message_ready,\n'
    instance+=' .verify_valid,.verify_ready,.verify_data,.verify_pass,\n'
    instance+=' .program_address,.program_data,.template_address,.template_data,.descriptor_addresses,.descriptor_data,\n'
    instance+=' .busy,.done,.keygen_done,.error,.error_code,.boot_cycles,.keygen_cycles,.sign_cycles,\n'
    instance+=' .hash_count,.permutation_count,.out_valid,.out_data,.out_bytes,.result_kind\n    );'
    return common,source[:start]+instance+source[stop:]
