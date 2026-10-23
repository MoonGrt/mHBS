#!/usr/bin/env python3
"""Validate a frozen C1 candidate and publish a bounded, 60-second report."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import threading
import time
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
EXPERIMENTS = ROOT / 'docs/manifests/experiments'
BASE = EXPERIMENTS / 'macro_atp_restart_20261021_164834'


def now():
    return datetime.now(ZoneInfo('Asia/Singapore')).isoformat(timespec='seconds')


def read_area(folder):
    utilization = folder / 'utilization.rpt'
    if not utilization.exists():
        return None
    content = utilization.read_text()
    def field(label):
        match = re.search(r'\|\s*' + label + r'\s*\|\s*([\d,.]+)', content)
        return float(match[1].replace(',', '')) if match else 0
    lut, ff, bram, dsp = [field(label) for label in
                           (r'Slice LUTs\*?', 'Slice Registers', 'Block RAM Tile', 'DSPs')]
    timing = (folder / 'timing.rpt').read_text() if (folder / 'timing.rpt').exists() else ''
    match = re.search(r'WNS\(ns\).*?\n\s*-+.*?\n\s*([-\d.]+)', timing, re.S)
    return dict(lut=lut, ff=ff, bram=bram, dsp=dsp,
                equivalent_slice=lut/4+ff/8+232.4*bram+102.4*dsp,
                synthesis_wns_ns=float(match[1]) if match else None,
                completed=(folder/'debug_audit.json').exists())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run', type=Path)
    args = parser.parse_args()
    run = args.run.resolve()
    source = run / 'stages/combined/source'
    archive = EXPERIMENTS / ('c_atp_optimization_' + run.name)
    reports = archive / 'reports'
    reports.mkdir(parents=True, exist_ok=True)
    baseline = json.loads((BASE/'evidence/image-chain/VALIDATION_SUMMARY.json').read_text())
    old_results = json.loads((BASE/'reports/Macro_ATP_Restart.json').read_text())['results']
    old = {(r['backend'], r['profile']): r for r in old_results if r['architecture']=='image-chain'}
    state = dict(started_at=now(), complete=False, passed=False, design='c',
                 frequency_mhz_assumed=100, routed=False, source=str(source),
                 scope='K1U1 common; excludes ROM and signature cache', tests={}, area={})
    lock = threading.Lock()
    def publish():
        with lock:
            state['updated_at'] = now()
            for stage in ('control_only', 'combined'):
                state['area'][stage] = {backend: read_area(run/'stages'/stage/'synth'/backend)
                                        for backend in ('shake', 'sha2')}
            data = json.loads(json.dumps(state))
        summary = reports/'C_ATP_Optimization.json'
        temporary = summary.with_suffix('.tmp')
        temporary.write_text(json.dumps(data, indent=2)+'\n')
        temporary.replace(summary)
        lines = ['# C1 面积与 ATP 优化', '', f'更新：{data["updated_at"]}；完成：{data["complete"]}；通过：{data["passed"]}。', '',
                 '保留硬件 CHAIN、程序 TREE、layout4 ROM 和单物理 Hash 通道。common 不含 ROM/签名缓存。100MHz 是综合诊断约束及 ATP 假定，未布线。', '',
                 '| 后端 | 基线面积 | 候选面积 | 面积变化 |', '|---|---:|---:|---:|']
        for backend in ('shake', 'sha2'):
            area = data['area']['combined'][backend]
            before = old[backend, 'slh_128f']['new_area']['equivalent_slice']
            after = area['equivalent_slice'] if area and area['completed'] else None
            lines.append(f'| {backend} | {before:,.3f} | '+(f'{after:,.3f} | {(after/before-1)*100:.3f}% |' if after else '待完成 | — |'))
        lines += ['', '| 后端 | Sign | 基线周期 | 候选周期 | 周期变化 | 基线ATP | 候选ATP | ATP变化 |',
                  '|---|---|---:|---:|---:|---:|---:|---:|']
        for backend in ('shake', 'sha2'):
            for profile in ('slh_128f', 'xmss_h10', 'lms_h10'):
                before = old[backend, profile]
                result = data['tests'].get(f'{backend}/{profile}/sign', {})
                area = data['area']['combined'][backend]
                if result.get('status')=='passed' and area and area['completed']:
                    cycles=result['cycles'];atp=area['equivalent_slice']*cycles/100000
                    row=f'{cycles:,} | {(cycles/before["cycles"]-1)*100:.3f}% | {before["atp"]:,.3f} | {atp:,.3f} | {(atp/before["atp"]-1)*100:.3f}%'
                else:
                    row=f'待完成 | — | {before["atp"]:,.3f} | — | —'
                lines.append(f'| {backend} | {profile} | {before["cycles"]:,} | {row} |')
        counts = {status:sum(v['status']==status for v in data['tests'].values()) for status in ('passed','failed','running')}
        lines += ['', f'整核状态：`{json.dumps(counts)}`；包含输出/签名缓存逐字节检查、64位统计和基线原像/结果指纹核对。', '',
                  'h16/h15/h20 仅 Verify，不启动完整 Keygen/Sign。验证明细日志保留运行目录。报告最多每60秒更新一次，结束后退出。', '',
                  f'运行目录：`{run}`；冻结源：`stages/combined/source/SOURCE.json`。']
        (reports/'C_ATP_Optimization.md').write_text('\n'.join(lines)+'\n')

    def group(backend):
        profiles = ('slh_128f','xmss_h10','lms_h10')
        cases = [(p, 'sign') for p in profiles] + [(p, 'verify') for p in profiles] + [(p, 'keygen') for p in profiles]
        slh = ('slh_128s','slh_192f','slh_192s','slh_256f','slh_256s') if backend=='shake' else ('slh_128s',)
        cases += [(p, op) for p in slh for op in ('keygen','sign','verify')]
        cases += [(p, 'verify') for p in ('xmss_h16','lms_h15','xmss_h20','lms_h20')]
        for profile, operation in cases:
            key=f'{backend}/{profile}/{operation}'
            folder=run/'validation'/backend;folder.mkdir(parents=True,exist_ok=True)
            log=folder/f'{profile}_{operation}.log'
            with lock:state['tests'][key]=dict(status='running',started_at=now())
            started=time.monotonic()
            env=dict(os.environ,MHBS_DESIGN='c',HASH_BACKEND=backend,SIM_HASH_TRACE='1',SIM_FAST_OPT_SLOW='-O1')
            with log.open('w') as handle:
                process=subprocess.run(['bash','scripts/simulate_fast.sh',profile,operation,'1','1'],cwd=source,env=env,stdout=handle,stderr=subprocess.STDOUT)
            text=log.read_text()
            try:
                if process.returncode:raise AssertionError(f'RTL/compile failure: {text[-800:]}')
                match=re.search(r'STATEFUL_PASS P1U1 op=\d cycles=(\d+) total=(\d+) hashes=(\d+) permutations=(\d+)',text)
                if not match:raise AssertionError('missing byte-exact PASS')
                cycles,total,hashes,blocks=map(int,match.groups())
                trace=json.loads(re.search(r'HASH_TRACE_METRICS (\{[^\n]+)',text)[1])
                macro=json.loads(re.search(r'MACRO_METRICS (\{[^\n]+)',text)[1])
                previous=baseline['tests'][key]
                if (hashes,blocks)!=(previous['hashes'],previous['permutations']):raise AssertionError('Hash workload changed')
                if trace!=previous['primitive_trace']:raise AssertionError('primitive fingerprint changed')
                if macro!=previous['macro_metrics']:raise AssertionError('program/control/macro workload changed')
                result=dict(status='passed',cycles=cycles,total_cycles=total,hashes=hashes,permutations=blocks,primitive_trace=trace,macro_metrics=macro,baseline_workload_equal=True)
            except Exception as error:
                result=dict(status='failed',error=str(error))
            result.update(seconds=time.monotonic()-started,log=str(log),log_sha256=hashlib.sha256(log.read_bytes()).hexdigest())
            with lock:state['tests'][key]=result
            print(key,result['status'],result.get('cycles'),flush=True)
            if result['status']=='failed':break

    publish()
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures=[pool.submit(group,b) for b in ('shake','sha2')]
        while not all(f.done() for f in futures):
            time.sleep(60);publish()
        for future in futures:future.result()
    state['complete']=True
    state['passed']=len(state['tests'])==44 and all(v['status']=='passed' for v in state['tests'].values())
    state['finished_at']=now();publish()
    # Archive evidence without verbose simulation logs or implementation DCPs.
    for stage in ('control_only','combined'):
        target=archive/'stages'/stage;target.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(run/'stages'/stage/'frozen_rtl.tar.gz',target/'frozen_rtl.tar.gz')
        shutil.copyfile(run/'stages'/stage/'source/SOURCE.json',target/'SOURCE.json')
        for backend in ('shake','sha2'):
            src=run/'stages'/stage/'synth'/backend
            if src.exists():shutil.copytree(src,target/'synth'/backend,ignore=shutil.ignore_patterns('*.dcp','*.jou'),dirs_exist_ok=True)
    print(json.dumps(dict(complete=True,passed=state['passed'],report=str(reports/'C_ATP_Optimization.md'))),flush=True)
    return 0 if state['passed'] else 1


if __name__=='__main__':
    raise SystemExit(main())
