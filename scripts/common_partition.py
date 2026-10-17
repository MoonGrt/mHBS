"""Generic Job/ROM synthesis boundary for hbs_micro64, including boot control.

Instruction memory is external and has exactly one clock of read latency.
The same extracted source is used for simulation and common-core synthesis.
"""
import re

JOBS = {'SECRET_SEED': 'job_secret_seed', 'SECRET_PRF': 'job_secret_prf',
        'PUBLIC_SEED': 'job_public_seed', 'RANDOMIZER': 'job_randomizer',
        'PUBLIC_ROOT': 'job_public_root', 'OPERATION': 'job_operation'}
PORTS = '''
 input wire clk,rst,
 output wire [8:0] program_address,input wire [63:0] program_data,
 output wire [4:0] descriptor_address,input wire [63:0] descriptor_data,
 input wire [255:0] job_secret_seed,job_secret_prf,job_public_seed,job_randomizer,job_public_root,
 input wire [1:0] job_operation,input wire [6:0] message_length,
 input wire verify_valid,output wire verify_ready,
 input wire [255:0] verify_data,output wire verify_pass,
 input wire [63:0] message_data,input wire message_valid,output wire message_ready,
 output wire out_valid,output wire [255:0] out_data,output wire [5:0] out_bytes,
 output wire [1:0] result_kind,output logic busy,done,keygen_done,error,
 output logic [15:0] error_code,output logic [31:0] boot_cycles,keygen_cycles,sign_cycles,
 output wire [31:0] hash_count,permutation_count
'''


def partition(source):
    if '    // COMMON_MICRO_BEGIN:' not in source:
        from pathlib import Path
        return (Path(__file__).resolve().parents[1]/'rtl/top/common.sv').read_text(), source
    begin = '    // COMMON_MICRO_BEGIN:'
    end = '    // COMMON_MICRO_END'
    if source.count(begin) != 1 or source.count(end) != 1:
        raise ValueError('micro common boundary missing or ambiguous')
    start, stop = source.index(begin), source.index(end) + len(end)
    body = source[source.index('\n', start)+1:source.index(end)]
    body = re.sub(r'\b('+'|'.join(JOBS)+r')\b', lambda m: JOBS[m[0]], body)
    common = ('`timescale 1ns/1ps\n`default_nettype none\n'
              'module common #(parameter integer LANES=1,UNROLL=1,'
              'parameter bit SWAP_PHYSICAL_LANES=0,PROFILE_ENABLE=1) (' + PORTS + ');\n'
              + body + 'endmodule\n`default_nettype wire\n')
    instance = ('    common #(.LANES(LANES),.UNROLL(UNROLL),'
                '.SWAP_PHYSICAL_LANES(SWAP_PHYSICAL_LANES),.PROFILE_ENABLE(PROFILE_ENABLE)) common (\n')
    instance += ','.join('.'+v+'('+k+')' for k,v in JOBS.items())+',\n'
    instance += ' .clk,.rst,.program_address,.program_data,.descriptor_address,.descriptor_data,\n'
    instance += ' .message_length,.message_data,.message_valid,.message_ready,\n'
    instance += ' .verify_valid,.verify_ready,.verify_data,.verify_pass,\n'
    instance += ' .busy,.done,.keygen_done,.error,.error_code,.boot_cycles,.keygen_cycles,.sign_cycles,\n'
    instance += ' .hash_count,.permutation_count,.out_valid,.out_data,.out_bytes,.result_kind\n    );'
    return common, source[:start]+instance+source[stop:]
