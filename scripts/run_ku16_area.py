#!/usr/bin/env python3
"""Four U batches of four independent six-thread Vivado area syntheses.

K2 uses the current production controller with only its elaboration guard
relaxed for U1/U3/U4. K1/K3/K4 use the archived generic K controller, linked
to current datapath sources. These points are synthesis experiments only.
"""
import hashlib
import json
import re
import shutil
import subprocess
import tarfile
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

from resynth_ku_area import ROOT, atomic_json, digest, parse_resources, write_tcl
from v42_common_partition import partition

OUT = ROOT / 'manifests/experiments/ku_sixteen_area_20261006_v1'
ARCHIVE = ROOT / 'manifests/experiments/ku_sign_latest/experiment_source.tar.gz'
THREADS = 6
LOCK = threading.Lock()


def hybrid_hbs(current, generic):
    header = current[:current.index(');') + 2]
    assert header.count('module mhbs_hbs #') == 1
    wrapper = header + '''
    generate if (LANES==2) begin: current_k2
        mhbs_hbs_current_k2 #(.UNROLL(UNROLL),.LANES(LANES),
            .PROFILE_ENABLE(PROFILE_ENABLE),.SWAP_PHYSICAL_LANES(SWAP_PHYSICAL_LANES)) body (.*);
    end else begin: generic_k
        mhbs_hbs_generic #(.UNROLL(UNROLL),.LANES(LANES),
            .PROFILE_ENABLE(PROFILE_ENABLE),.SWAP_PHYSICAL_LANES(SWAP_PHYSICAL_LANES)) body (.*);
    end endgenerate
endmodule
`default_nettype wire
'''
    k2 = current.replace('module mhbs_hbs #', 'module mhbs_hbs_current_k2 #', 1)
    guard = 'initial if(LANES!=2 || UNROLL!=2) $error("Production core requires K2U2");'
    assert k2.count(guard) == 1
    k2 = k2.replace(guard, 'initial if(LANES!=2 || UNROLL<1 || UNROLL>4 || (24 % UNROLL)!=0) '
                    '$error("Experimental K2 U1-U4 sweep");')
    generic = generic.replace('module mhbs_hbs #', 'module mhbs_hbs_generic #', 1)
    guard = 'initial if((LANES!=1 && LANES!=2 && LANES!=4) || (UNROLL<1 || UNROLL>4))'
    assert generic.count(guard) == 1
    generic = generic.replace(guard,
        'initial if((LANES<1 || LANES>4) || (UNROLL<1 || UNROLL>4 || (24 % UNROLL)!=0))')
    generic = generic.replace('generate if(LANES==4) begin: endpoint_four_way',
                              'generate if(LANES>=3) begin: endpoint_four_way', 1)
    marker = '// Four independent residue banks allow four adjacent endpoint writes on the'
    assert generic.count(marker) == 1
    generic = generic[:generic.index(marker)] + '''
// Experimental three/four-bank endpoint store. Address modulo and division
// map adjacent writes to distinct physical banks for K3 and K4.
module mhbs_ku_store #(
    parameter integer WIDTH=256, DEPTH=68, ADDRESS_BITS=7, LANES=4
) (
    input wire clk,
    input wire [LANES-1:0] write_enable,
    input wire [ADDRESS_BITS-1:0] write_address [0:LANES-1],
    input wire [WIDTH-1:0] write_data [0:LANES-1],
    input wire [ADDRESS_BITS-1:0] read0,read1,
    output wire [WIDTH-1:0] value0,value1
);
    localparam integer BANK_DEPTH=(DEPTH+LANES-1)/LANES;
    localparam integer ROW_BITS=$clog2(BANK_DEPTH);
    wire [WIDTH-1:0] bank_value0 [0:LANES-1], bank_value1 [0:LANES-1];
    for(genvar bank=0;bank<LANES;bank=bank+1) begin: banks
        (* ram_style="distributed" *) logic [WIDTH-1:0] words [0:BANK_DEPTH-1];
        always_ff @(posedge clk)
            if(write_enable[bank]) words[write_address[bank]/LANES]<=write_data[bank];
        assign bank_value0[bank]=words[read0/LANES];
        assign bank_value1[bank]=words[read1/LANES];
    end
    assign value0=bank_value0[read0%LANES];
    assign value1=bank_value1[read1%LANES];
endmodule
`default_nettype wire
'''
    return wrapper + '\n' + k2 + '\n' + generic


def prepare():
    OUT.mkdir(parents=True, exist_ok=True)
    snapshot = OUT / 'snapshot'
    sources = (ROOT / 'manifests/v42_sources.txt').read_text().splitlines()
    sources.append('manifests/v42_sources.txt')
    if not snapshot.exists():
        snapshot.mkdir()
        for name in sources:
            dst = snapshot / name
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / name, dst)
        with tarfile.open(ARCHIVE) as archive:
            old = archive.extractfile('rtl/top/mhbs_hbs.sv').read().decode()
        current = (snapshot / 'rtl/top/mhbs_hbs.sv').read_text()
        (snapshot / 'rtl/top/mhbs_hbs.sv').write_text(hybrid_hbs(current, old))
        common, _ = partition((snapshot / 'rtl/top/mhbs_top.sv').read_text(), stub=True)
        (snapshot / 'mhbs_common.sv').write_text(common)
    hashes = {p:digest(snapshot/p) for p in sources}
    hashes['mhbs_common.sv'] = digest(snapshot/'mhbs_common.sv')
    config = OUT/'config.json'
    if config.exists():
        assert json.loads(config.read_text())['source_sha256'] == hashes
    else:
        atomic_json(config, dict(schema='mhbs.ku16_area.v1', created_at=datetime.now(timezone.utc).isoformat(),
                                 git_head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
                                 current_source_sha256={p:digest(ROOT/p) for p in sources},
                                 old_generic_sha256=digest(ARCHIVE), source_sha256=hashes,
                                 device='xc7a200tffg1156-3', period_ns=10,
                                 profile_enable=0, max_threads_per_vivado=THREADS,
                                 max_parallel_vivado=4, batch_order=[1,2,3,4],
                                 frequencies_for_later_report_mhz={'1':150,'2':110,'3':67,'4':48},
                                 k2_controller='current RTL, elaboration guard relaxed for U1-U4',
                                 other_k_controller='archived generic K controller with current datapath; K3 bank mapping added',
                                 functional_status='synthesis only; K1/K3/K4 current-source compatibility not verified',
                                 vivado=subprocess.check_output(['vivado','-version'],text=True).splitlines()[0]))
    return snapshot, hashes


def run_point(snapshot, hashes, k, u, state):
    label = f'K{k}U{u}'
    d = OUT/label
    d.mkdir(exist_ok=True)
    result = d/'result.json'
    if result.exists():
        obj = json.loads(result.read_text())
        if obj['source_sha256'] == hashes and digest(d/'core_utilization.rpt') == obj['evidence_sha256']['core_utilization.rpt']:
            with LOCK:
                state['points'][label]='complete'
                atomic_json(OUT/'status.json',state)
            return
    tcl = write_tcl(snapshot,d,k,u)
    tcl.write_text(tcl.read_text().replace('set_param general.maxThreads 8',
                                           f'set_param general.maxThreads {THREADS}',1))
    with LOCK:
        state['points'][label]='running'
        atomic_json(OUT/'status.json',state)
    with (d/'vivado.log').open('w') as log:
        proc = subprocess.run(['vivado','-mode','batch','-nolog','-nojournal','-source',str(tcl)],
                              cwd=d,stdout=log,stderr=subprocess.STDOUT)
    if proc.returncode or 'KU_CURRENT_CORE_SYNTH_PASS' not in (d/'vivado.log').read_text():
        with LOCK:
            state['points'][label]='failed'
            atomic_json(OUT/'status.json',state)
        return
    report_names=['core_utilization.rpt','core_hierarchical.rpt','core_timing.rpt','clock.xdc','synth.tcl','vivado.log']
    atomic_json(result,dict(point=label,k=k,u=u,source_sha256=hashes,
                            area=parse_resources(d/'core_utilization.rpt'),
                            evidence_sha256={name:digest(d/name) for name in report_names}))
    with LOCK:
        state['points'][label]='complete'
        atomic_json(OUT/'status.json',state)


def main():
    snapshot, hashes = prepare()
    path = OUT/'status.json'
    state=json.loads(path.read_text()) if path.exists() else {'points':{}}
    state['status']='running'
    for u in (1,2,3,4):
        state['batch_u']=u
        atomic_json(path,state)
        with ThreadPoolExecutor(max_workers=4) as pool:
            futures=[pool.submit(run_point,snapshot,hashes,k,u,state) for k in (1,2,3,4)]
            for future in as_completed(futures):
                future.result()
    state['status']='complete' if all(x=='complete' for x in state['points'].values()) else 'complete_with_failures'
    state['batch_u']=None
    atomic_json(path,state)
    atomic_json(OUT/'results.json',dict(schema='mhbs.ku16_area.v1',
        config_sha256=digest(OUT/'config.json'),
        points={label:json.loads((OUT/label/'result.json').read_text()) for label,s in state['points'].items() if s=='complete'},
        failed_points=[label for label,s in state['points'].items() if s!='complete']))


if __name__=='__main__':
    main()
