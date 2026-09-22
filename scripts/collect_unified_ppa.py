#!/usr/bin/env python3
"""Capture immutable build inputs and compare synthesized/routed Sign ATP."""
from pathlib import Path
import argparse
import hashlib
import json
import re
import subprocess

ROOT=Path(__file__).resolve().parents[1]
LIMITS={"slh":57360.476,"xmss":1506.437,"lms":579.399}


def capture(tag, family, unroll, lanes):
    sources=(ROOT/"manifests/unified_sources.txt").read_text().splitlines()
    sources += [f"rtl/microcode/uhbs_{family}_{kind}.mem" for kind in ("tokens","templates","descriptors")]
    sources += ["model/unified_hbs.py","manifests/experiments/unified_hbs_model_gate.json",
                "tb/integration/tb_uhbs_unified.sv", "tests/test_unified_hbs.py",
                "tests/test_unified_rtl_contract.py", "experiments/synth_unified_hbs.tcl",
                "experiments/route_unified_hbs.tcl", "manifests/unified_sources.txt"]
    hashes={p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in sources}
    data=dict(family=family,unroll=unroll,lanes=lanes,part="xc7a200tffg1156-3",period_ns=10.0,
              tool="Vivado 2025.2",stage="post_synth",source_sha256=hashes,
              git_head=subprocess.check_output(["git","rev-parse","HEAD"],cwd=ROOT,text=True).strip(),
              source_set_sha256=hashlib.sha256(json.dumps(hashes,sort_keys=True).encode()).hexdigest(),
              cache_policy="selected_authentication_path" if family!="slh" else "transient_tree",
              comparison="NON_STRICT_FIXED_JOB_PROFILE_AND_CACHE")
    out=ROOT/"build/vivado"/tag
    out.mkdir(parents=True,exist_ok=True)
    (out/"inputs.json").write_text(json.dumps(data,indent=2)+"\n")


def collect(tag, family, cycles, route, period, keygen_cycles=None):
    out=ROOT/"build/vivado"/tag
    util=(out/"utilization.rpt").read_text()
    timing=(out/"timing_summary.rpt").read_text()
    def amount(label):
        m=re.search(r"\|\s*"+re.escape(label).replace(r"\*",r"\*?")+r"\s*\|\s*([\d,.]+)\s*\|",util)
        if not m: raise ValueError("missing utilization row: "+label)
        return float(m[1].replace(",",""))
    lut,ff,bram,dsp=(amount(s) for s in ("Slice LUTs*","Slice Registers","Block RAM Tile","DSPs"))
    m=re.search(r"WNS\(ns\).*?\n\s*[- ]+\n\s*([-\d.]+)\s+([-\d.]+)",timing)
    if not m: raise ValueError("missing timing summary")
    wns,tns=map(float,m.groups())
    row=re.search(r"WNS\(ns\).*?\n\s*[- ]+\n([^\n]+)",timing)[1].split()
    has_hold="WHS(ns)" in timing
    whs,ths=map(float,row[4:6]) if has_hold else (None,None)
    pulse_index=8 if has_hold else 4
    wpws,tpws=map(float,row[pulse_index:pulse_index+2])
    clock=re.search(r"^clk\s+\{[^}]+\}\s+([\d.]+)",timing,re.M)
    if not clock or abs(float(clock[1])-period)>0.0001:
        raise ValueError("requested period disagrees with reported clock")
    inputs=json.loads((out/"inputs.json").read_text())
    matches=all(hashlib.sha256((ROOT/p).read_bytes()).hexdigest()==h
                for p,h in inputs["source_sha256"].items() if not p.startswith("experiments/"))
    area=lut/4+ff/8+bram*232.4+dsp*102.4
    atp=area*cycles*period/1e6
    data=dict(family=family,stage="post_route" if route else "post_synth",lut=int(lut),ff=int(ff),
              bram36_equivalent=bram,dsp=int(dsp),equivalent_slice=area,
              keygen_cycles=keygen_cycles,sign_cycles=cycles,period_ns=period,frequency_mhz=1000/period,
              source_set_sha256=inputs["source_set_sha256"],source_matches_worktree=matches,
              unroll=inputs["unroll"],lanes=inputs.get("lanes",2),
              wns_ns=wns,tns_ns=tns,sign_ms=cycles*period/1e6,sign_atp=atp,
              whs_ns=whs,ths_ns=ths,wpws_ns=wpws,tpws_ns=tpws,
              target=LIMITS[family],ratio=atp/LIMITS[family],
              numerical_target_pass=atp<LIMITS[family],timing_pass=wns>=0 and tns==0,
              final_pass=bool(route and matches and wns>=0 and tns==0
                              and has_hold and whs>=0 and ths==0
                              and wpws>=0 and tpws==0 and atp<LIMITS[family]),
              comparison="NON_STRICT_FIXED_JOB_PROFILE_AND_CACHE")
    if route:
        flow=json.loads((out/"route_inputs.json").read_text())
        flow_matches=flow["script_sha256"]==hashlib.sha256((ROOT/"experiments/route_unified_hbs.tcl").read_bytes()).hexdigest()
        data["route_flow_matches_worktree"]=flow_matches
        data["timing_scope"]=flow["timing_scope"]
        data["final_pass"] &= flow_matches
        status=(out/"route_status.rpt").read_text()
        counts={}
        for label in ("nets with routing errors", "routable nets", "fully routed nets"):
            match=re.search(re.escape(label)+r"[^\d\n]*?(\d+)",status,re.I)
            if not match: raise ValueError("missing route-status count: "+label)
            counts[label]=int(match[1])
        data["route_counts"]=counts
        data["final_pass"] &= counts["nets with routing errors"]==0 and counts["routable nets"]==counts["fully routed nets"]
        data["timing_pass"]=bool(wns>=0 and tns==0 and has_hold and whs>=0 and ths==0 and wpws>=0 and tpws==0)
        checks=(out/"check_timing.rpt").read_text()
        coverage={}
        for name in ("no_clock","constant_clock","pulse_width_clock",
                     "unconstrained_internal_endpoints","multiple_clock",
                     "generated_clocks","loops","latch_loops"):
            match=re.search(r"checking\s+"+name+r"\s+\((\d+)\)",checks)
            if not match: raise ValueError("missing timing coverage check: "+name)
            coverage[name]=int(match[1])
        data["timing_coverage"]=coverage
        data["final_pass"] &= not any(coverage.values())
        final_clock=json.loads((out/"final_clock.json").read_text())
        clock_matches=final_clock["script_sha256"]==hashlib.sha256((ROOT/"experiments/finalize_unified_clock.tcl").read_bytes()).hexdigest()
        data["final_clock"]=final_clock
        data["finalization_flow_matches_worktree"]=clock_matches
        data["final_pass"] &= clock_matches
    (out/"ppa.json").write_text(json.dumps(data,indent=2)+"\n")
    print(json.dumps(data,indent=2))


if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("tag");p.add_argument("family",choices=LIMITS)
    p.add_argument("--capture",action="store_true");p.add_argument("--unroll",type=int,default=2)
    p.add_argument("--lanes",type=int,default=2)
    p.add_argument("--cycles",type=int);p.add_argument("--route",action="store_true")
    p.add_argument("--keygen-cycles",type=int)
    p.add_argument("--period",type=float,default=10.0)
    a=p.parse_args()
    if a.capture: capture(a.tag,a.family,a.unroll,a.lanes)
    else:
        if a.cycles is None: p.error("--cycles required for collection")
        collect(a.tag,a.family,a.cycles,a.route,a.period,a.keygen_cycles)
