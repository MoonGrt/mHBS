#!/usr/bin/env python3
"""Generate the three small, fixed-job product wrappers from verified jobs."""
from pathlib import Path
import json

ROOT=Path(__file__).resolve().parents[1]
profiles=json.loads((ROOT/"manifests/experiments/unified_hbs_model_gate.json").read_text())["profiles"]
for name, p in profiles.items():
    top="uhbs_slh_dsa_top" if name=="slh" else f"uhbs_{name}_top"
    width=p["n"]*8
    params="\n".join(f"    parameter [{width-1}:0] {key.upper()} = {width}'h{bytes.fromhex(p[key])[::-1].hex()},"
                     for key in ("secret","prf","public","random"))
    text=f'''`timescale 1ns/1ps
`default_nettype none
// Generated fixed-job demonstration wrapper. Regenerate with generate_unified_tops.py.
// Algorithm control is supplied solely by the ABI 3 immutable image.
module {top} #(
    parameter integer UNROLL=2, LANES=2, MESSAGE_BYTES={p["message_bytes"]}, INITIAL_Q={p["initial_q"]},
{params}
    parameter [127:0] IDENTIFIER=128'h{bytes.fromhex(p["identifier"])[::-1].hex()},
    parameter bit PROFILE_ENABLE=0, SWAP_PHYSICAL_LANES=0
) (
    input wire clk, rst_n, start,
    output wire ready, busy, keygen_done, done,
    output wire [31:0] keygen_cycles, sign_cycles,
    input wire message_valid, output wire message_ready,
    input wire [63:0] message_data, input wire [7:0] message_keep, input wire message_last,
    output wire state_commit_valid, input wire state_commit_ready,
    output wire [10:0] state_next_q,
    output wire out_valid, input wire out_ready, output wire [63:0] out_data,
    output wire [7:0] out_keep, output wire out_last, output wire result_kind,
    output wire error, output wire [15:0] error_code,
    output wire [31:0] hash_count, permutation_count,
    output wire tree_cache_valid
);
    wire job_valid, job_ready, operation, core_done;
    wire [31:0] core_cycles;
    assign result_kind=operation;
    uhbs_job_sequence sequence_control (
        .clk,.rst_n,.start,.ready,.busy,.job_valid,.job_ready,.job_operation(operation),
        .core_done,.core_error(error),.core_cycles,.keygen_done,.done,.keygen_cycles,.sign_cycles
    );
    uhbs_hbs #(.N({p["n"]}),.STATEFUL(1'b{int(p["stateful"])}),.UNROLL(UNROLL),.LANES(LANES),
        .RECIPE_MASK(16'h{p["recipe_mask"]:04x}),
        .CHAIN_RECIPE_MASK(16'h{p["chain_recipe_mask"]:04x}),.MAX_MESSAGE_BYTES(MESSAGE_BYTES),
        .PROGRAM_TOKENS({p["tokens"]}),.PROGRAM_TEMPLATES({p["templates"]}),
        .PROFILE_ENABLE(PROFILE_ENABLE),.SWAP_PHYSICAL_LANES(SWAP_PHYSICAL_LANES),
        .TOKEN_INIT_FILE("rtl/microcode/uhbs_{name}_tokens.mem"),
        .TEMPLATE_INIT_FILE("rtl/microcode/uhbs_{name}_templates.mem"),
        .DESCRIPTOR_INIT_FILE("rtl/microcode/uhbs_{name}_descriptors.mem")
    ) core (
        .clk,.rst_n,.job_valid,.job_ready,.job_operation(operation),
        .job_message_length(7'(MESSAGE_BYTES)),.job_initial_q(11'(INITIAL_Q)),
        .job_secret_seed(SECRET),.job_secret_prf(PRF),.job_public_seed(PUBLIC),
        .job_randomizer(RANDOM),.job_identifier(IDENTIFIER),
        .message_valid,.message_ready,.message_data,.message_keep,.message_last,
        .state_commit_valid,.state_commit_ready,.state_next_q,
        .out_valid,.out_ready,.out_data,.out_keep,.out_last,
        .busy(),.done(core_done),.error,.error_code,.hash_count,.permutation_count,
        .cycles(core_cycles),.tree_cache_valid
    );
endmodule
`default_nettype wire
'''
    (ROOT/f"rtl/top/{top}.sv").write_text(text)
