#!/usr/bin/env python3
"""Generate the seven small, fixed-job product wrappers from verified jobs."""
from pathlib import Path
import json

ROOT=Path(__file__).resolve().parents[1]
profiles=json.loads((ROOT/"manifests/experiments/unified_hbs_v4/model_gate.json").read_text())["profiles"]
for name, p in profiles.items():
    top=f"uhbs_{name}_top"
    width=p["n"]*8
    params="\n".join(f"    parameter [{width-1}:0] {key.upper()} = {width}'h{bytes.fromhex(p[key])[::-1].hex()},"
                     for key in ("secret","prf","public","random"))
    text=f'''`timescale 1ns/1ps
`default_nettype none
// Generated fixed-job demonstration wrapper. Regenerate with generate_unified_tops.py.
// Algorithm control is supplied solely by the ABI 4 immutable image.
module {top} #(
    parameter integer UNROLL=2, LANES={p["lanes"]}, MESSAGE_BYTES={p["message_bytes"]}, INITIAL_Q={p["initial_q"]},
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
    uhbs_hbs #(.N({p["n"]}),.STATEFUL(1'b{int(p["stateful"])}),
        .OMEGA({p["omega"]}),.CHAIN_COUNT({p["chains"]}),.DIGEST_BYTES({p["m"]}),
        .FORS_A({p["a"]}),.FORS_K({p["k"]}),.TREE_BITS({p["h"]-p["hp"] if not p["stateful"] else 0}),.HP({p["hp"]}),.UNROLL(UNROLL),.LANES(LANES),
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

# Keep old top names as exact static products; their ports and fixed jobs stay compatible.
for old,new in (("uhbs_slh_dsa_top","slh_128f"),("uhbs_xmss_top","xmss_omega4"),("uhbs_lms_top","lms_omega4")):
    text=(ROOT/f"rtl/top/uhbs_{new}_top.sv").read_text().replace(f"module uhbs_{new}_top",f"module {old}")
    (ROOT/f"rtl/top/{old}.sv").write_text(text)
manifest=ROOT/"manifests/unified_sources.txt"
sources=manifest.read_text().splitlines()
for name in profiles:
    path=f"rtl/top/uhbs_{name}_top.sv"
    if path not in sources:sources.append(path)
manifest.write_text("\n".join(sources)+"\n")

keys={"KG_BYTES":"keygen_bytes","SG_BYTES":"sign_bytes","MSG_BYTES":"message_bytes","KG_HASHES":"keygen_hashes","KG_PERMUTATIONS":"keygen_permutations","SG_HASHES":"sign_hashes","SG_PERMUTATIONS":"sign_permutations"}
boundary_path=ROOT/"manifests/experiments/unified_hbs_v4/boundary_counts.json"
boundaries=json.loads(boundary_path.read_text()) if boundary_path.exists() else {}
lines=["// Generated from independently verified ABI 4 profiles."]
for key,field in keys.items():
    expression=""
    for i,(name,p) in enumerate(profiles.items()):
        value=str(p[field])
        if key.startswith("SG_") and key!="SG_BYTES" and name in boundaries:
            value=f"(Q==0 ? {boundaries[name]['0'][field]} : Q==1023 ? {boundaries[name]['1023'][field]} : {value})"
        expression+=f"PROFILE=={i} ? {value} : "
    lines.append(f"localparam integer {key} = {expression}0;")
(ROOT/"tb/vectors/uhbs_profile_constants.svh").write_text("\n".join(lines)+"\n")
