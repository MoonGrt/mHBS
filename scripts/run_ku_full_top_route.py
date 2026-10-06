#!/usr/bin/env python3
"""Batch full-top 128f Sign synth/route for the frozen sixteen-point K/U source.

Four K points run concurrently in each U batch; each Vivado has six threads.
The signature store and actual 128f ROM images are part of the top-level netlist.
"""
from legacy_lane_guard import require_legacy_lanes
require_legacy_lanes()
import hashlib
import json
import math
import os
import re
import signal
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

from resynth_ku_area import ROOT, atomic_json, digest, parse_resources
from v42_common_partition import partition

SOURCE = ROOT/'manifests/experiments/ku_sixteen_area_20261006_v1'
SNAPSHOT = SOURCE/'snapshot'
OUT = ROOT/'manifests/experiments/ku_full_top_route_20261006_v1'
FREQ = {1:150.0,2:110.0,3:67.0,4:48.0}
PART = 'xc7a200tffg1156-3'
THREADS = 6
LOCK = threading.Lock()
STOP = threading.Event()
CHILDREN = set()


def stop(signum, frame):
    STOP.set()
    with LOCK:
        children = list(CHILDREN)
    for pid in children:
        try: os.killpg(pid, signal.SIGTERM)
        except ProcessLookupError: pass


def process(stage, script, folder, timeout=7200):
    with (folder/f'{stage}.log').open('a') as log:
        proc = subprocess.Popen(['vivado','-mode','batch','-nolog','-nojournal','-source',str(script)],
                                cwd=ROOT,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,
                                start_new_session=True)
        with LOCK: CHILDREN.add(proc.pid)
        start=time.monotonic()
        try:
            while proc.poll() is None:
                if STOP.is_set() or time.monotonic()-start >= timeout:
                    try: os.killpg(proc.pid, signal.SIGTERM)
                    except ProcessLookupError: pass
                    try: proc.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        try: os.killpg(proc.pid, signal.SIGKILL)
                        except ProcessLookupError: pass
                        proc.wait()
                    raise RuntimeError('stopped' if STOP.is_set() else f'{stage} timeout')
                time.sleep(2)
            if proc.returncode: raise RuntimeError(f'{stage} Vivado exit {proc.returncode}')
        finally:
            with LOCK: CHILDREN.discard(proc.pid)


def write_synth(d,k,u):
    sources=(SNAPSHOT/'manifests/v42_sources.txt').read_text().splitlines()
    (d/'clock.xdc').write_text('create_clock -name clk -period 10.0 [get_ports clk]\n')
    _,shell=partition((SNAPSHOT/'rtl/top/mhbs_top.sv').read_text(),stub=True)
    job=json.loads((ROOT/'manifests/experiments/unified_hbs_v4.2/external_job_message/vectors/slh_128f/sign/job.json').read_text())
    for name in ('SECRET_SEED','SECRET_PRF','PUBLIC_SEED','RANDOMIZER','PUBLIC_ROOT'):
        value=int.from_bytes(bytes.fromhex(job[name.lower()]),'little')
        shell=re.sub(r'(parameter \[255:0\] '+name+r'=)[^,]+',
                     lambda m:m[1]+f"256'h{value:064x}",shell)
    for kind in ('PROGRAM','TEMPLATE','DESCRIPTOR'):
        shell=re.sub(r'(parameter '+kind+r'_INIT_FILE=)"[^"]+"',
                     lambda m:m[1]+f'"experiments/v4.2/external_job_message/{kind.lower()}_construction.mem"',shell)
    (d/'shell.sv').write_text(shell)
    lines=[f'set_param general.maxThreads {THREADS}',f'create_project -in_memory -part {PART}']
    lines += [f'read_verilog -sv {{{SNAPSHOT/p}}}' for p in sources if p!='rtl/top/mhbs_top.sv']
    lines += [f'read_verilog -sv {{{SNAPSHOT/"mhbs_common.sv"}}}',
              f'read_xdc {{{d/"clock.xdc"}}}',
              f'synth_design -top mhbs_common -part {PART} -mode out_of_context '
              f'-flatten_hierarchy rebuilt -max_dsp 0 -generic LANES={k} '
              f'-generic UNROLL={u} -generic PROFILE_ENABLE=0',
              f'write_edif -force {{{d/"mhbs_common.edf"}}}',
              f'write_verilog -force -mode synth_stub {{{d/"common_stub.v"}}}',
              'close_project',
              f'create_project -in_memory -part {PART}',
              f'read_verilog -sv {{{SNAPSHOT/"rtl/memory/mhbs_signature_store.sv"}}}',
              f'read_verilog {{{d/"common_stub.v"}}}',
              f'read_verilog -sv {{{d/"shell.sv"}}}',
              f'synth_design -top mhbs_top -part {PART} -mode out_of_context -flatten_hierarchy none',
              f'write_edif -force {{{d/"mhbs_top.edf"}}}',
              'close_project',
              f'read_edif {{{d/"mhbs_common.edf"}}}',
              f'read_edif {{{d/"mhbs_top.edf"}}}',
              f'link_design -top mhbs_top -part {PART} -mode out_of_context',
              'if {[llength [get_cells -hier -filter {IS_BLACKBOX == 1}]]} {error "Unresolved blackbox"}',
              'set_property DONT_TOUCH true [get_cells common]',
              'create_clock -name clk -period 10.0 [get_ports clk]',
              f'source {{{ROOT/"experiments/v4.2/external_job_message/rom_mapping.tcl"}}}',
              f'export_rom_mapping {{{d/"rom_mapping.tsv"}}}',
              f'exec python3 {{{ROOT/"scripts/v42_external_rom.py"}}} {{{d}}} slh_128f',
              f'source {{{d/"init.tcl"}}}',
              f'export_rom_mapping {{{d/"initialized_rom.tsv"}}}',
              f'exec python3 {{{ROOT/"scripts/v42_external_rom.py"}}} {{{d}}} slh_128f --audit',
              f'report_utilization -file {{{d/"synth_utilization.rpt"}}}',
              f'report_utilization -hierarchical -file {{{d/"synth_hierarchical.rpt"}}}',
              f'write_checkpoint -force {{{d/"post_synth.dcp"}}}',
              'puts "KU_FULL_TOP_SYNTH_PASS"','exit']
    path=d/'synth.tcl';path.write_text('\n'.join(lines)+'\n');return path


def write_route(d,k,u):
    period=1000/FREQ[u]
    lines=[f'set_param general.maxThreads {THREADS}',
           f'open_checkpoint {{{d/"post_synth.dcp"}}}',
           f'create_clock -name clk -period {period:.9f} [get_ports clk]',
           'set_property HD.CLK_SRC BUFGCTRL_X0Y0 [get_ports clk]',
           'set inputs [get_ports -filter {DIRECTION == IN && NAME != clk}]',
           'set_input_delay -clock clk -max 0 $inputs',
           'set_input_delay -clock clk -min 0 $inputs',
           'set_output_delay -clock clk -max 0 [all_outputs]',
           'set_output_delay -clock clk -min 0 [all_outputs]',
           'set_false_path -from $inputs',
           'set_false_path -to [all_outputs]',
           'opt_design','place_design -directive Explore',
           'phys_opt_design -directive AggressiveExplore',
           f'write_checkpoint -force {{{d/"post_place.dcp"}}}',
           'route_design -directive Explore',
           f'write_checkpoint -force {{{d/"post_route_initial.dcp"}}}',
           'set initial_wns [get_property SLACK [get_timing_paths -delay_type max -max_paths 1]]',
           'if {$initial_wns eq ""} {error "No internal setup path"}',
           'set delay [expr {'+f'{period:.9f}'+' - $initial_wns}]',
           'set final_period [expr {ceil(($delay + 0.050)*1000.0)/1000.0}]',
           'if {$final_period < 1.0} {set final_period 1.0}',
           'create_clock -name clk -period $final_period [get_ports clk]',
           f'report_utilization -file {{{d/"route_utilization.rpt"}}}',
           f'report_utilization -hierarchical -file {{{d/"route_hierarchical.rpt"}}}',
           f'report_timing_summary -delay_type min_max -report_unconstrained -max_paths 10 -file {{{d/"timing_summary.rpt"}}}',
           f'report_timing -delay_type max -max_paths 10 -file {{{d/"setup_paths.rpt"}}}',
           f'report_timing -delay_type min -max_paths 10 -file {{{d/"hold_paths.rpt"}}}',
           f'report_route_status -file {{{d/"route_status.rpt"}}}',
           f'report_drc -file {{{d/"drc.rpt"}}}',
           f'check_timing -verbose -file {{{d/"check_timing.rpt"}}}',
           f'write_xdc -force {{{d/"final_constraints.xdc"}}}',
           f'write_checkpoint -force {{{d/"post_route.dcp"}}}',
           'set final_wns [get_property SLACK [get_timing_paths -delay_type max -max_paths 1]]',
           'set final_whs [get_property SLACK [get_timing_paths -delay_type min -max_paths 1]]',
           'set drc_errors [llength [get_drc_violations -quiet -filter {SEVERITY == Error}]]',
           f'set f [open {{{d/"timing.json"}}} w]',
           f'puts $f "{{\\"target_period_ns\\":{period:.9f},\\"initial_wns_ns\\":$initial_wns,\\"final_period_ns\\":$final_period,\\"final_wns_ns\\":$final_wns,\\"final_whs_ns\\":$final_whs,\\"drc_errors\\":$drc_errors}}"',
           'close $f','puts "KU_FULL_TOP_ROUTE_PASS"','exit']
    path=d/'route.tcl';path.write_text('\n'.join(lines)+'\n');return path


def route_ok(d,timing):
    checks=(d/'check_timing.rpt').read_text()
    status=(d/'route_status.rpt').read_text()
    summary=(d/'timing_summary.rpt').read_text()
    if timing['final_wns_ns'] <= 0 or timing['final_whs_ns'] < 0 or timing['drc_errors']:
        return False
    if 'All user specified timing constraints are met.' not in summary:
        return False
    counts={}
    for name in ('routable nets','fully routed nets','nets with routing errors'):
        m=re.search(r'# of\s+'+name+r'\.*\s*:\s*(\d+)',status,re.I)
        if not m: return False
        counts[name]=int(m[1])
    if counts['routable nets'] != counts['fully routed nets'] or counts['nets with routing errors']:
        return False
    for name in ('no_clock','unconstrained_internal_endpoints'):
        m=re.search(r'checking\s+'+name+r'\s*\((\d+)\)',checks,re.I)
        if not m or int(m[1]): return False
    return True


def point(k,u,state):
    label=f'K{k}U{u}';d=OUT/label;d.mkdir(exist_ok=True)
    result_path=d/'result.json'
    if result_path.exists():
        with LOCK:
            state['points'][label]='complete'
            atomic_json(OUT/'status.json',state)
        return
    def publish(status):
        with LOCK:
            state['points'][label]=status
            atomic_json(OUT/'status.json',state)
    try:
        if STOP.is_set(): raise RuntimeError('stopped')
        synth=write_synth(d,k,u)
        route=write_route(d,k,u)
        synth_meta=d/'synth_result.json'
        if not synth_meta.exists() or not (d/'post_synth.dcp').exists():
            publish('synthesizing')
            process('synth',synth,d)
            if 'KU_FULL_TOP_SYNTH_PASS' not in (d/'synth.log').read_text():
                raise RuntimeError('synthesis pass marker missing')
            atomic_json(synth_meta,dict(area=parse_resources(d/'synth_utilization.rpt'),
                                        dcp_sha256=digest(d/'post_synth.dcp')))
        meta=json.loads(synth_meta.read_text())
        if meta['dcp_sha256']!=digest(d/'post_synth.dcp'):
            raise RuntimeError('synthesis DCP hash mismatch')
        publish('routing')
        process('route',route,d)
        if 'KU_FULL_TOP_ROUTE_PASS' not in (d/'route.log').read_text():
            raise RuntimeError('route pass marker missing')
        timing=json.loads((d/'timing.json').read_text())
        area=parse_resources(d/'route_utilization.rpt')
        passed=route_ok(d,timing)
        evidence={name:digest(d/name) for name in ('synth.tcl','route.tcl','synth_utilization.rpt',
                  'synth_hierarchical.rpt','route_utilization.rpt','route_hierarchical.rpt',
                  'timing_summary.rpt','route_status.rpt','check_timing.rpt','drc.rpt',
                  'post_synth.dcp','post_route.dcp')}
        atomic_json(result_path,dict(point=label,k=k,u=u,target_frequency_mhz=FREQ[u],
                                     full_top=True,signature_store_enabled=True,
                                     area_synth=meta['area'],area_route=area,timing=timing,
                                     final_frequency_mhz=1000/timing['final_period_ns'] if passed else None,
                                     timing_passed=passed,io_timing_qualified=False,
                                     source_sha256=digest(SOURCE/'config.json'),
                                     evidence_sha256=evidence))
        publish('complete')
    except Exception as exc:
        (d/'failure.txt').write_text(repr(exc)+'\n')
        publish('stopped' if STOP.is_set() else 'failed')


def main():
    signal.signal(signal.SIGTERM,stop)
    signal.signal(signal.SIGINT,stop)
    OUT.mkdir(parents=True,exist_ok=True)
    config=OUT/'config.json'
    if not config.exists():
        atomic_json(config,dict(schema='mhbs.ku_full_top_route.v1',
                                created_at=datetime.now(timezone.utc).isoformat(),
                                source_config_sha256=digest(SOURCE/'config.json'),
                                device=PART,threads_per_vivado=THREADS,max_parallel_vivado=4,
                                profile='slh_128f_sign',batch_order=[1,2,3,4],
                                target_frequency_mhz_by_u=FREQ,
                                scope='monolithic full top including signature store and ROM; external I/O excluded'))
    else:
        assert json.loads(config.read_text())['source_config_sha256']==digest(SOURCE/'config.json')
    status_path=OUT/'status.json'
    state=json.loads(status_path.read_text()) if status_path.exists() else {'points':{}}
    state['status']='running'
    for u in (1,2,3,4):
        if STOP.is_set(): break
        state['batch_u']=u
        atomic_json(status_path,state)
        with ThreadPoolExecutor(max_workers=4) as pool:
            futures=[pool.submit(point,k,u,state) for k in (1,2,3,4)]
            for future in as_completed(futures): future.result()
    state['status']='stopped' if STOP.is_set() else ('complete' if all(
        state['points'].get(f'K{k}U{u}')=='complete' for u in (1,2,3,4) for k in (1,2,3,4)) else 'complete_with_failures')
    state['batch_u']=None
    atomic_json(status_path,state)
    atomic_json(OUT/'results.json',dict(schema='mhbs.ku_full_top_route.v1',
        points={f'K{k}U{u}':json.loads((OUT/f'K{k}U{u}'/'result.json').read_text())
                for u in (1,2,3,4) for k in (1,2,3,4) if (OUT/f'K{k}U{u}'/'result.json').exists()},
        statuses=state['points']))
    if not STOP.is_set():
        try:
            subprocess.run([sys.executable,'scripts/report_ku_sign_atp.py'],cwd=ROOT,check=True)
            subprocess.run([sys.executable,'scripts/verify_ku_archive.py'],cwd=ROOT,check=True)
        except Exception as exc:
            state['report_error']=repr(exc)
            atomic_json(status_path,state)


if __name__=='__main__': main()
