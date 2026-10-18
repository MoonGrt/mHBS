#!/usr/bin/env python3
"""Freeze and synthesize the fixed K1U1 common; never starts placement or routing."""
from __future__ import annotations
import argparse
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import time
from zoneinfo import ZoneInfo
from report_atp import area,render

ROOT=Path(__file__).resolve().parents[1]
BASELINE={'lut':15698,'ff':4205}


def stamp():return datetime.now(ZoneInfo('Asia/Singapore')).isoformat(timespec='seconds')
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def write(path,data):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_name(path.name+f'.{os.getpid()}.tmp')
    temporary.write_text(json.dumps(data,indent=2,sort_keys=True)+'\n');temporary.replace(path)


def publish(run,state):
    archive=Path(state['archive_root']);archive.mkdir(parents=True,exist_ok=True)
    state['updated_at']=stamp();write(run/'status.json',state);write(archive/'status.json',state)
    for name in ('SOURCE.json','rtl.tar.gz','invocation.json'):
        if (run/name).exists():shutil.copy2(run/name,archive/name)
    dest=archive/'synthesis';dest.mkdir(exist_ok=True)
    for path in (run/'synthesis').iterdir():
        if path.is_file() and path.suffix in ('.rpt','.json','.log','.xdc'):shutil.copy2(path,dest/path.name)
    reports=archive/'reports';reports.mkdir(exist_ok=True)
    write(reports/'Synthesis.json',state);(reports/'Synthesis.md').write_text(render(state))
    write(archive/'ARTIFACTS.json',{'routed':False,'omitted_details':['sim','validation'],
        'sha256':{str(p.relative_to(archive)):sha(p) for p in archive.rglob('*') if p.is_file() and p.name!='ARTIFACTS.json'}})


def prepare(run,archive,backend):
    run.mkdir(parents=True,exist_ok=False);source=run/'source';source.mkdir();(run/'synthesis').mkdir()
    paths=(ROOT/'sources.txt').read_text().split()+['sources.txt','rtl/executor/instructions.svh',
        'scripts/synth.tcl','scripts/synthesize.py','scripts/report_atp.py']
    identity={}
    for name in sorted(paths):
        target=source/name;target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(ROOT/name,target);identity[name]=sha(target)
        if identity[name]!=sha(ROOT/name):raise ValueError('Source changed during freeze: '+name)
    write(run/'SOURCE.json',{'files':identity,'backend':backend,'source_root':str(source),
        'part':'xc7a200tffg1156-3','clock_period_ns':10.0,'LANES':1,'UNROLL':1,'PROFILE_ENABLE':0,
        'threads':2,'top':'common','signature_store_included':False,'routing_requested':False})
    with tarfile.open(run/'rtl.tar.gz','w:gz') as tar:
        for name in sorted(paths):tar.add(source/name,arcname=name,recursive=False)
    state=dict(status='prepared',hash_backend=backend,run_root=str(run),archive_root=str(archive),
        started_at=stamp(),started_epoch=time.time(),area_gate_applicable=False,area_gate_passed=None,area_gate_reason='standard XMSS/LMS feature extension; report increments, no source-import 1% gate')
    publish(run,state);return state


def worker(run):
    state=json.loads((run/'status.json').read_text());state.update(status='running',worker_pid=os.getpid())
    source=run/'source';out=run/'synthesis'
    command=[os.environ.get('VIVADO','vivado'),'-mode','batch','-nojournal','-notrace',
        '-log',str(out/'vivado.log'),'-source',str(source/'scripts/synth.tcl'),
        '-tclargs',str(source),str(out),state['hash_backend']]
    write(run/'invocation.json',{'command':command,'cwd':str(source)});publish(run,state)
    try:
        with (out/'driver.log').open('w') as stream:
            proc=subprocess.Popen(command,cwd=source,stdin=subprocess.DEVNULL,stdout=stream,stderr=subprocess.STDOUT)
            state['vivado_pid']=proc.pid;publish(run,state)
            while True:
                try:code=proc.wait(timeout=30);break
                except subprocess.TimeoutExpired:
                    state.update(elapsed_seconds=time.time()-state['started_epoch'],analysis_deferred=time.time()-state['started_epoch']>=600)
                    if state['analysis_deferred'] and not state.get('deferred_published'):
                        state['deferred_published']=True;publish(run,state)
        if code:raise RuntimeError('Vivado returned '+str(code)+'; see '+str(out/'driver.log'))
        identity=json.loads((run/'SOURCE.json').read_text())['files']
        if any(sha(source/name)!=value for name,value in identity.items()):raise ValueError('Frozen source changed')
        if 'MHBS_SYNTH_PASS' not in (out/'driver.log').read_text():raise ValueError('Missing synthesis pass marker')
        resources=area(out);state['resources']=resources;state['source_unchanged']=True
        state['relative_delta']={k:resources[k]/BASELINE[k]-1 for k in BASELINE}
        if state['area_gate_applicable']:
            delta={k:resources[k]/BASELINE[k]-1 for k in BASELINE}
            state.update(relative_delta=delta,area_gate_passed=all(abs(v)<=.01 for v in delta.values()))
            state['status']='passed' if state['area_gate_passed'] else 'area_gate_failed'
        else:state['status']='measured'
        state['analysis_deferred']=False
    except BaseException as error:state.update(status='failed',error=repr(error))
    state.update(finished_at=stamp(),elapsed_seconds=time.time()-state['started_epoch']);publish(run,state)
    print(json.dumps(state,indent=2));return 0 if state['status'] in ('passed','measured') else 1


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--hash',choices=['shake'],default=os.environ.get('HASH_BACKEND','shake'))
    p.add_argument('--out',type=Path);p.add_argument('--archive',type=Path);p.add_argument('--background',action='store_true')
    p.add_argument('--worker',action='store_true');p.add_argument('--status',action='store_true');args=p.parse_args()
    if args.hash != 'shake':p.error('This ABI4 source supports SHAKE only')
    if (args.worker or args.status) and args.out is None:p.error('--worker/--status require --out')
    if args.worker:return worker(args.out.resolve())
    if args.status:
        print((args.out/'status.json').read_text());return 0
    tag='common_synthesis_'+datetime.now(ZoneInfo('Asia/Singapore')).strftime('%Y%m%d_%H%M%S')+'_'+args.hash
    run=(args.out or ROOT/'build/synth'/tag).resolve();archive=(args.archive or ROOT/'docs/manifests/experiments'/tag).resolve()
    state=prepare(run,archive,args.hash)
    command=[sys.executable,str(run/'source/scripts/synthesize.py'),'--worker','--out',str(run)]
    if args.background:
        with (run/'runner.log').open('w') as stream:
            proc=subprocess.Popen(command,cwd=run/'source',stdin=subprocess.DEVNULL,stdout=stream,stderr=subprocess.STDOUT,start_new_session=True)
        print(json.dumps({'pid':proc.pid,'run':str(run),'report':str(archive/'reports/Synthesis.md')},indent=2));return 0
    return subprocess.call(command,cwd=run/'source')


if __name__=='__main__':raise SystemExit(main())
