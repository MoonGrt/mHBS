#!/usr/bin/env python3
"""Freeze isolated i/c control candidates; validate and route at 100 MHz."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import time

ROOT = Path(__file__).resolve().parents[1]
BASELINE = 'ablation_route_20261023_190751'
BACKENDS = ('shake', 'sha2')


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def read(p, default=None):
    return json.loads(Path(p).read_text()) if Path(p).is_file() else default


def write(p, value):
    p = Path(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + f'.{os.getpid()}.tmp')
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    tmp.replace(p)


def now():
    return datetime.now().astimezone().isoformat(timespec='seconds')


def freeze(run, label, design, staging):
    meta = read(run / 'SOURCE.json')
    source = run / 'candidates' / label / 'source'
    if source.exists():
        raise ValueError('Never overwrite frozen candidates')
    # One immutable complete package supports independent simulator and Vivado jobs.
    old = ROOT / 'build/c_idea_migration/20261023_191653/baseline_source'
    shutil.copytree(old, source, ignore=shutil.ignore_patterns('build', '__pycache__'))
    for name in ('executor.sv', 'sequencer.sv'):
        shutil.copyfile(staging / f'rtl/{design}/executor' / name,
                        source / f'rtl/{design}/executor' / name)
    (source / 'sources.txt').write_text((source / f'rtl/{design}/sources.txt').read_text())
    shutil.copyfile(ROOT / 'scripts/validate_idea_migration.py', source / 'scripts/validate_idea_migration.py')
    names = (source / 'sources.txt').read_text().splitlines()
    names += [str(p.relative_to(source)) for p in (source / f'rtl/{design}').rglob('*.svh')]
    names += ['sources.txt', 'scripts/audit_debug.tcl']
    checks = {name: sha(source / name) for name in sorted(set(names)) if name and not name.startswith('#')}
    record = dict(label=label, design=design, source=str(source), sha256=checks,
                  created_at=now(), backends=BACKENDS,
                  production_unchanged=True, inherited_baseline=BASELINE)
    archive = Path(meta['archive']) / 'candidates' / label
    write(archive / 'SOURCE.json', record)
    if (staging / 'AUDIT.json').exists():
        shutil.copyfile(staging / 'AUDIT.json', archive / 'AUDIT.json')
    with tarfile.open(archive / 'frozen_rtl.tar.gz', 'w:gz') as tar:
        for name in checks:
            tar.add(source / name, arcname=name)
    write(run / 'queue' / (label + '.json'), record)


def launch():
    stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    run = ROOT / 'build/ic_timing_remaining' / stamp
    archive = ROOT / 'docs/manifests/experiments' / f'ic_timing_remaining_{stamp}'
    run.mkdir(parents=True, exist_ok=False)
    (archive / 'reports').mkdir(parents=True, exist_ok=False)
    for name in ('run_ic_timing.py', 'route_ablation_common.tcl', 'run_ablation_route.py', 'validate_idea_migration.py'):
        (run / 'control').mkdir(exist_ok=True)
        (archive / 'control').mkdir(exist_ok=True)
        shutil.copyfile(ROOT / 'scripts' / name, run / 'control' / name)
        shutil.copyfile(ROOT / 'scripts' / name, archive / 'control' / name)
    production = {str(p.relative_to(ROOT)): sha(p) for d in ('i', 'c', 't')
                  for p in (ROOT / f'rtl/{d}').rglob('*') if p.is_file()}
    meta = dict(stamp=stamp, root=str(ROOT), run=str(run), archive=str(archive), started_at=now(),
                baseline=BASELINE, production_sha256=production, frequency_mhz=100,
                configuration='P1U1', part='xc7a200tffg1156-3', refresh_seconds=60,
                note='i remains explicit HASH software chain/tree; c retains CHAIN/software tree. t unchanged.',
                adoption='Manual measured selection after byte/count/ROM/handshake checks; no automatic RTL overwrite.')
    write(run / 'SOURCE.json', meta)
    write(archive / 'SOURCE.json', meta)
    freeze(run, 'c_control_pipeline', 'c', ROOT / 'build/ic_timing_staging/c')
    report = archive / 'reports' / f'IC_Timing_Remaining_{stamp}.md'
    with (archive.parent / 'INDEX.md').open('a') as log:
        log.write(f'| {stamp} | i/c 时序与 i Remaining 优化 | [报告]({archive.name}/reports/{report.name}) | [证据]({archive.name}/ARTIFACTS.json) |\n')
    with (run / 'controller.log').open('w') as log:
        process = subprocess.Popen([sys.executable, str(run / 'control/run_ic_timing.py'), '--run', str(run)],
                                   cwd=ROOT, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                                   start_new_session=True)
    write(run / 'LAUNCH.json', dict(pid=process.pid, run=str(run), report=str(report)))
    print(json.dumps(read(run / 'LAUNCH.json'), indent=2))


def execute(run, record, backend, kind):
    label, design = record['label'], record['design']
    out = run / kind / label / backend
    out.mkdir(parents=True, exist_ok=True)
    source = Path(record['source'])
    if kind == 'routes':
        command = [shutil.which('vivado'), '-mode', 'batch', '-nolog', '-nojournal', '-notrace',
                   '-source', str(run / 'control/route_ablation_common.tcl'), '-tclargs',
                   str(source), design, backend, str(out), '100', '2']
    else:
        command = [sys.executable, str(run / 'control/validate_idea_migration.py'), '--source',
                   str(source), '--design', design, '--backend', backend, '--output', str(out)]
    state = dict(status='running', started_at=now(), started_epoch=time.time(), command=command)
    write(out / 'PROCESS.json', state)
    assert all(sha(source / n) == h for n, h in record['sha256'].items())
    with (out / ('vivado.log' if kind == 'routes' else 'validator.log')).open('w') as log:
        proc = subprocess.Popen(command, cwd=out if kind == 'routes' else source,
                                stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                                start_new_session=True)
        state['pid'] = proc.pid
        write(out / 'PROCESS.json', state)
        code = proc.wait()
    intact = all(sha(source / n) == h for n, h in record['sha256'].items())
    state.update(status='complete' if code == 0 and intact else 'error', returncode=code,
                 source_unchanged=intact, finished_at=now(), seconds=time.time() - state['started_epoch'])
    write(out / 'PROCESS.json', state)
    return state


def publish(run, complete=False):
    meta = read(run / 'SOURCE.json')
    archive = Path(meta['archive'])
    spec = importlib.util.spec_from_file_location('resources', run / 'control/run_ablation_route.py')
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    state = dict(updated_at=now(), complete=complete, routes={}, validation={}, profiles={},
                 adoption=read(run / 'DECISION.json', {'status': 'pending_measurements'}))
    lines = ['# i/c 时序与 i Remaining 优化', '', f'更新：{now()}；完成：{complete}。P1U1 common，100 MHz。', '',
             '保持 i 软件逐次 HASH、c 硬件 CHAIN＋软件树的消融粒度；t 不变。', '',
             '基线为 ablation_route_20261023_190751 同源、同器件、同工具流程。基线 i/c 均未闭合100 MHz。', '',
             '| 候选 | 后端 | 状态 | 综合等效Slice | 布线等效Slice | WNS ns | WHS ns | 100MHz达标 |',
             '|---|---|---|---:|---:|---:|---:|---|']
    for item in sorted((run / 'queue').glob('*.json')):
        rec = read(item)
        for backend in BACKENDS:
            key = rec['label'] + '/' + backend
            for kind in ('routes', 'validation'):
                out = run / kind / key
                proc = read(out / 'PROCESS.json', {'status': 'pending'})
                if kind == 'validation':
                    summary = read(out / 'SUMMARY.json')
                    state[kind][key] = dict(process=proc, summary=summary)
                    if summary:
                        dest = archive / 'validation_summary' / (key + '.json')
                        write(dest, summary)
                    continue
                result = read(out / 'result.json')
                stage = read(out / 'stage.json', {}).get('stage', proc['status'])
                synth, route = [helper.resources(out / p / 'utilization.rpt') for p in ('synth', 'route')]
                deferred = bool(proc['status'] == 'running' and time.time() - proc.get('started_epoch', time.time()) > 600 and stage == 'synthesis')
                state[kind][key] = dict(process=proc, result=result, stage=stage, synth=synth, route=route, analysis_deferred=deferred)
                number = lambda x: f'{x:.3f}' if x is not None else '—'
                lines.append('| ' + ' | '.join([rec['label'], backend, stage,
                    number(synth['equivalent_slice'] if synth else None), number(route['equivalent_slice'] if route else None),
                    number(result.get('wns_ns') if result else None), number(result.get('whs_ns') if result else None),
                    ('是' if result['accepted_frequency'] else '否') if result else '待完成']) + ' |')
                for p in out.rglob('*'):
                    if p.is_file() and p.suffix in ('.rpt', '.log', '.json', '.txt', '.xdc'):
                        dest = archive / 'jobs' / key / p.relative_to(out)
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        if not dest.exists() or sha(p) != sha(dest):
                            shutil.copyfile(p, dest)
    lines += ['', '## 验证', '', '| 候选／后端 | 状态 | 通过操作 |', '|---|---|---:|']
    for key, row in state['validation'].items():
        summary = row['summary'] or {}
        label = ('通过' if summary.get('passed') else '失败') if summary.get('complete') else row['process']['status']
        lines.append(f'| {key} | {label} | {summary.get("case_counts", {}).get("passed", 0)} |')
    for p in sorted((run / 'profiles').glob('**/result.json')):
        key = str(p.relative_to(run / 'profiles'))
        state['profiles'][key] = read(p)
        write(archive / 'profile_summary' / key, read(p))
    lines += ['', '## i Remaining（相同33字节KAT）', '',
              '| 后端 | 基线 | SLotH |', '|---|---:|---:|', '| SHAKE | 3,291,179 | 2,036,877 |', '| SHA2 | 3,709,883 | 1,784,934 |', '',
              'Hash区间计入真实轮计算与SHA2 feed-forward，内部交接空拍归入Remaining；本核无MMIO Transfer。SLotH的Hash区间另含部分装载／链控制，其边界并不完全等同纯轮计算。', '',
              '100MHz未闭合点的同频ATP只是理论比较，不能宣称硬件达到100MHz。统计60秒刷新，任务完成后退出。', '',
              '取舍：' + json.dumps(state['adoption'], ensure_ascii=False), '']
    report = archive / 'reports' / f'IC_Timing_Remaining_{meta["stamp"]}'
    write(report.with_suffix('.json'), state)
    report.with_suffix('.md').write_text('\n'.join(lines))
    write(run / 'STATE.json', state)
    write(archive / 'ARTIFACTS.json', dict(complete=complete, sha256={
        str(p.relative_to(archive)): sha(p) for p in archive.rglob('*')
        if p.is_file() and p.name != 'ARTIFACTS.json' and not p.name.endswith('.tmp')}))


def runner(run):
    submitted = set()
    jobs = []
    with ThreadPoolExecutor(max_workers=12) as pool:
        while True:
            for p in sorted((run / 'queue').glob('*.json')):
                rec = read(p)
                if rec['label'] in submitted:
                    continue
                for backend in BACKENDS:
                    for kind in ('routes', 'validation'):
                        jobs.append(pool.submit(execute, run, rec, backend, kind))
                submitted.add(rec['label'])
            done = (run / 'QUEUE_CLOSED').exists() and all(j.done() for j in jobs)
            publish(run, done)
            if done:
                for j in jobs:
                    j.result()
                return
            time.sleep(60)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--launch', action='store_true')
    p.add_argument('--run', type=Path)
    p.add_argument('--add', metavar='LABEL')
    p.add_argument('--design', choices=('i', 'c'))
    p.add_argument('--staging', type=Path)
    args = p.parse_args()
    if args.launch:
        launch()
    elif args.add:
        freeze(args.run.resolve(), args.add, args.design, args.staging.resolve())
    else:
        runner(args.run.resolve())
