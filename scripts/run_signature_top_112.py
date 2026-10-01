#!/usr/bin/env python3
"""Detached K2U2/128f Sign full-top synthesis and fixed 112 MHz routing.

start/resume/stop/status operate on a frozen run. Logs and checkpoints are in
manifests; the extracted workspace is rebuildable after deleting build.
"""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import tarfile
import time

ROOT = Path(__file__).resolve().parents[1]
DEFAULT = 'signature_top_112_20261002_v1'

def sha(p):
    h = hashlib.sha256()
    with Path(p).open('rb') as f:
        for block in iter(lambda: f.read(1048576), b''): h.update(block)
    return h.hexdigest()

def atomic(p, data):
    p = Path(p)
    tmp = p.with_suffix(p.suffix + '.tmp')
    tmp.write_text(data)
    tmp.replace(p)

def write(p, data):
    atomic(p, json.dumps(data, indent=2) + '\n')

def prepare(tag):
    from v42_external_flow import capture, PARAMS, BASE
    from v42_common_partition import partition
    out = ROOT / 'manifests/validation' / tag
    if (out / 'config.json').exists(): return out
    folder = capture(tag)
    out.mkdir(parents=True, exist_ok=True)
    for name in ('inputs.json', 'source_snapshot.tar.gz'):
        shutil.copy2(folder / name, out / name)
    ws = ROOT / 'build/signature_top' / tag
    ws.mkdir(parents=True, exist_ok=True)
    with tarfile.open(out / 'source_snapshot.tar.gz') as t: t.extractall(ws, filter='data')
    evidence = ROOT / 'manifests/validation/signature_store_compressed_20261002/simulation.json'
    sim = json.loads(evidence.read_text())
    inputs = json.loads((out / 'inputs.json').read_text())
    assert sim['passed'] and sim['rtl_sha256'] == inputs['rtl_sha256'], 'Current RTL needs simulation'
    shutil.copy2(evidence, out / 'simulation.json')
    synth = out / 'synthesis'
    synth.mkdir(exist_ok=True)
    common, shell = partition((ws / 'rtl/top/mhbs_top.sv').read_text(), stub=True)
    (synth / 'mhbs_common.sv').write_text(common)
    cfg = json.loads((BASE / 'vectors/slh_128f/sign/job.json').read_text())
    for k in PARAMS:
        value = int.from_bytes(bytes.fromhex(cfg[k]), 'little')
        shell = re.sub(r'(parameter \[255:0\] ' + k.upper() + r'=)[^,]+',
                       lambda m: m[1] + f"256'h{value:064x}", shell)
    for kind in ('program', 'template', 'descriptor'):
        shell = re.sub(r'(parameter ' + kind.upper() + r'_INIT_FILE=)"[^"]+"',
                       lambda m: m[1] + f'"experiments/v4.2/external_job_message/{kind}_construction.mem"', shell)
    (synth / 'slh_128f_sign_shell.sv').write_text(shell)
    tcl = (ws / 'experiments/v4.2/external_job_message/synth.tcl').read_text()
    tcl = re.sub(r'^set root .*$', 'set root {' + str(ws) + '}', tcl, count=1, flags=re.M)
    tcl = re.sub(r'^set out .*$', 'set out {' + str(synth) + '}', tcl, count=1, flags=re.M)
    tcl = re.sub(r'foreach name \{slh_128f_keygen[^\n]+\} \{', 'foreach name {slh_128f_sign} {', tcl, count=1)
    assert 'foreach name {slh_128f_sign} {' in tcl
    (out / 'synth.tcl').write_text(tcl)
    shutil.copy2(ws / 'experiments/v4.2/signature_top/route_112.tcl', out / 'route.tcl')
    shutil.copy2(__file__, out / 'driver.py')
    write(out / 'config.json', dict(tag=tag, workspace=str(ws), part='xc7a200tffg1156-3',
          threads=8, target_mhz=112, period_ns=8.928, profile='slh_128f_sign',
          setup_requirement='>0', hold_requirement='>=0', profile_enable=False,
          signature_store_enable=True, snapshot_sha256=sha(out / 'source_snapshot.tar.gz'),
          scripts_sha256={n:sha(out/n) for n in ('synth.tcl','route.tcl','driver.py')},
          tool_version=subprocess.check_output(['vivado','-version'],text=True).splitlines()[0]))
    return out

def worker(out):
    # Exclusive lock prevents duplicate schedulers across simultaneous resumes.
    lock = (out / 'run.lock').open('w')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    cfg = json.loads((out / 'config.json').read_text())
    state_path = out / 'status.json'
    state = json.loads(state_path.read_text()) if state_path.exists() else {'elapsed':{}}
    state.update(pid=os.getpid(), status='running', child_pid=None)
    stopping = False
    def stop(signum, frame):
        nonlocal stopping
        stopping = True
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    def publish():
        state['updated'] = time.strftime('%Y-%m-%d %H:%M:%S %z')
        write(state_path, state)
        atomic(out / 'STATUS.md', f"# K2U2 / 128f Sign / 112 MHz\n\n状态：{state['status']}\n\n阶段：{state.get('stage','prepare')}\n\nPID：{os.getpid()}；Vivado PID：{state.get('child_pid')}\n\n累计运行秒数：{state['elapsed']}\n\n{state.get('detail','')}\n\n综合报告：synthesis/slh_128f_sign/hierarchical.rpt\n\n布线报告：route/hierarchical.rpt\n")
    def run(stage, script, args):
        if stopping: raise InterruptedError('Stopped before starting Vivado')
        used = state['elapsed'].get(stage, 0)
        if used >= 7200: raise TimeoutError(stage + ' cumulative 2 hour limit')
        state['stage'] = stage
        with (out / (stage + '.log')).open('a') as log:
            cmd = ['vivado','-mode','batch','-nolog','-nojournal','-source',str(script),'-tclargs',*map(str,args)]
            print('START',stage,cmd,flush=True)
            proc = subprocess.Popen(cmd,cwd=cfg['workspace'],stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
            state['child_pid'] = proc.pid
            start = time.monotonic()
            while proc.poll() is None:
                state['elapsed'][stage] = used + time.monotonic()-start
                publish()
                if stopping or state['elapsed'][stage] >= 7200:
                    os.killpg(proc.pid, signal.SIGTERM)
                    try: proc.wait(timeout=15)
                    except subprocess.TimeoutExpired:
                        os.killpg(proc.pid, signal.SIGKILL); proc.wait()
                    state['elapsed'][stage] = used + time.monotonic()-start
                    if stopping: raise InterruptedError('Stopped by user')
                    raise TimeoutError(stage + ' cumulative 2 hour limit')
                time.sleep(2)
            state['elapsed'][stage] = used + time.monotonic()-start
            state['child_pid'] = None
            publish()
            if stopping: raise InterruptedError('Stopped by user')
            if proc.returncode: raise RuntimeError(f'{stage}: Vivado exit {proc.returncode}')
    try:
        publish()
        assert sha(out/'source_snapshot.tar.gz') == cfg['snapshot_sha256']
        for name,h in cfg['scripts_sha256'].items(): assert sha(out/name)==h, name
        ws = Path(cfg['workspace'])
        if not ws.exists():
            ws.mkdir(parents=True)
            with tarfile.open(out/'source_snapshot.tar.gz') as t: t.extractall(ws,filter='data')
        for name,h in json.loads((out/'inputs.json').read_text())['source_sha256'].items():
            assert sha(ws/name)==h, name
        sys.path.insert(0,str(ws/'scripts'))
        from v42_external_route import resources, audit_rom, audit_timing
        image = ws/'manifests/experiments/unified_hbs_v4.2/external_job_message/images/slh_128f'
        synth = out/'synthesis/slh_128f_sign'
        dcp = synth/'post_synth.dcp'
        if not (out/'synthesis_done.json').exists():
            run('synthesis',out/'synth.tcl',[cfg['tag']])
            assert 'EXTERNAL_COMMON_SYNTH_PASS' in (out/'synthesis.log').read_text()
            audit_rom(synth/'initialized_rom.tsv', image)
            write(out/'synthesis_done.json',dict(dcp_sha256=sha(dcp),resources=resources(synth/'utilization.rpt')))
        assert sha(dcp)==json.loads((out/'synthesis_done.json').read_text())['dcp_sha256']
        route = out/'route'; route.mkdir(exist_ok=True)
        resume = 'synthesis'
        for name,stage in [('post_route.dcp','route'),('post_place.dcp','place')]:
            p = route/name; h = route/(name+'.sha256')
            if p.exists() and h.exists() and sha(p)==h.read_text().strip():
                dcp=p;resume=stage;break
        run('route',out/'route.tcl',[dcp,route,resume])
        timing = json.loads((route/'timing.json').read_text())
        rom = audit_rom(route/'initialized_rom.tsv',image)
        failures=[]
        try: audit_timing(route)
        except (AssertionError,ValueError) as exc: failures.append(str(exc))
        if timing['wns_ns']<=0: failures.append('Setup must be > 0')
        if timing['whs_ns']<0: failures.append('Hold must be >= 0')
        if timing['period_ns']>8.9281: failures.append('Clock period changed')
        if timing['drc_errors']: failures.append('DRC errors')
        result=dict(passed=not failures,failures=failures,**timing,**resources(route/'utilization.rpt'),rom_audit=rom,
                    requested_frequency_mhz=112,validated_frequency_mhz=1000/timing['period_ns'] if not failures else None,
                    scope='Whole internal top including ROM and signature storage; external I/O not signed off')
        write(out/'result.json',result)
        state.update(status='passed' if result['passed'] else 'failed',stage='complete',detail=json.dumps(result,ensure_ascii=False))
        atomic(out/'REPORT.md', '# 完整顶层 112 MHz 验证\n\n```json\n'+json.dumps(result,indent=2,ensure_ascii=False)+'\n```\n\n综合分层：synthesis/slh_128f_sign/hierarchical.rpt\n\n布线分层：route/hierarchical.rpt\n')
        write(out/'FINISHED.json',dict(status=state['status']))
        write(out/'SHA256.json',{str(p.relative_to(out)):sha(p) for p in out.rglob('*') if p.is_file() and p.suffix in ('.rpt','.sv','.tcl','.json','.gz','.dcp') and p.name not in ('status.json','SHA256.json')})
    except InterruptedError as exc: state.update(status='stopped',detail=str(exc))
    except Exception as exc:
        state.update(status='error',detail=repr(exc));print(repr(exc),flush=True)
    finally:
        state['child_pid']=None
        publish()

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('action',choices=['start','resume','stop','status','worker'])
    p.add_argument('--tag',default=DEFAULT)
    p.add_argument('--run-dir',type=Path)
    a=p.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9_.-]+',a.tag): p.error('invalid tag')
    out=a.run_dir or ROOT/'manifests/validation'/a.tag
    if a.action=='worker': worker(out.resolve());return
    if a.action=='start': out=prepare(a.tag)
    if a.action=='status': print((out/'STATUS.md').read_text());return
    if a.action=='stop':
        state=json.loads((out/'status.json').read_text());pid=state['pid']
        cmd=Path(f'/proc/{pid}/cmdline')
        if cmd.exists() and str(out/'driver.py').encode() in cmd.read_bytes():
            os.kill(pid,signal.SIGTERM);print('Stop requested',pid)
        else: print('No live scheduler')
        return
    with (out/'run.lock').open('a') as lock:
        try: fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError: print('Already running:',out/'STATUS.md');return
    if (out/'FINISHED.json').exists(): print('Already completed:',out/'result.json');return
    with (out/'driver.log').open('a') as log:
        proc=subprocess.Popen([sys.executable,str(out/'driver.py'),'worker','--run-dir',str(out)],
                              stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
    print(json.dumps(dict(pid=proc.pid,status=str(out/'STATUS.md'),log=str(out/'driver.log'))))

if __name__=='__main__': main()
