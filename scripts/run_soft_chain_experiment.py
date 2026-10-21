#!/usr/bin/env python3
"""Freeze and reproduce the C1-to-software-CHAIN ablation, without routing.

All complete-tree fixtures are reused from the certified C1 run. Only the three
ROM files are replaced; external inputs, expected bytes and work counts must
retain their certified identities. No high-tree Keygen or Sign is generated.
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile
import threading
import time
from datetime import datetime
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
LOW = {'shake': ('slh_128f', 'slh_192f', 'slh_256f', 'slh_128s', 'slh_192s', 'slh_256s', 'xmss_h10', 'lms_h10'),
       'sha2': ('slh_128f', 'slh_128s', 'xmss_h10', 'lms_h10')}
HIGH = ('xmss_h16', 'xmss_h20', 'lms_h15', 'lms_h20')
ROMS = {'program.mem', 'template.mem', 'descriptor.mem'}
BASELINE = 'macro_atp_acceptance_20261021_161437'
BASELINE_AREA = 'restart_chain_control_20261021_161243'


def now():
    return datetime.now(ZoneInfo('Asia/Singapore')).isoformat(timespec='seconds')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.tmp')
    temp.write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n')
    temp.replace(path)


def hashes(folder):
    return {p.name: digest(p) for p in folder.glob('*.mem')}


def launch(args):
    source_root = args.root.resolve()
    stamp = datetime.now(ZoneInfo('Asia/Singapore')).strftime('%Y%m%d_%H%M%S')
    run = source_root / 'build/soft_chain' / stamp
    archive = source_root / 'docs/manifests/experiments' / ('soft_chain_' + stamp)
    src = run / 'source'
    run.mkdir(parents=True)
    archive.mkdir(parents=True)
    identity = {}
    for folder in ('rtl', 'model', 'scripts', 'tb'):
        for path in (source_root / folder).rglob('*'):
            if (not path.is_file() or '__pycache__' in path.parts or
                    path.suffix not in ('.sv', '.svh', '.py', '.sh', '.cpp', '.c', '.tcl', '.xdc', '.mem', '.json')):
                continue
            name = path.relative_to(source_root)
            target = src / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
            identity[str(name)] = digest(target)
    shutil.copy2(source_root / 'sources.txt', src / 'sources.txt')
    identity['sources.txt'] = digest(src / 'sources.txt')
    baseline = source_root / 'docs/manifests/experiments' / BASELINE
    baseline_area = source_root / 'docs/manifests/experiments' / BASELINE_AREA
    for name in ('SOURCE.json', 'VALIDATION_SUMMARY.json', 'SIGN_INDEX_VALIDATION.json', 'EMPTY_MESSAGE_VALIDATION.json'):
        shutil.copy2(baseline / name, archive / ('C1_' + name))
    shutil.copy2(baseline_area / 'SYNTHESIS_SUMMARY.json', archive / 'C1_SYNTHESIS_SUMMARY.json')
    meta = dict(schema='mhbs.soft_chain.v1', created_at=now(), root=str(source_root), source=str(src),
                run=str(run), archive=str(archive), sha256=identity,
                branch=subprocess.check_output(['git', 'branch', '--show-current'], cwd=source_root, text=True).strip(),
                head=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=source_root, text=True).strip(),
                baseline=BASELINE, high_complete_trees=False, route=False, clock_mhz_assumed=100,
                max_vivado_threads=2, synthesize=args.synthesize)
    write(run / 'SOURCE.json', meta)
    write(archive / 'SOURCE.json', meta)
    with tarfile.open(archive / 'frozen_rtl.tar.gz', 'w:gz') as tar:
        for name in sorted(identity):
            if name.startswith('rtl/') or name == 'sources.txt':
                tar.add(src / name, arcname=name)
    with (run / 'runner.log').open('w') as log:
        process = subprocess.Popen([sys.executable, str(src / 'scripts/run_soft_chain_experiment.py'),
                                    '--run', str(run)], cwd=src, stdin=subprocess.DEVNULL,
                                   stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    launch_record = dict(pid=process.pid, run=str(run), report=str(archive / 'reports/Soft_Chain.md'))
    write(run / 'LAUNCH.json', launch_record)
    with (source_root / 'docs/manifests/experiments/INDEX.md').open('a') as index:
        index.write(f'\n| {stamp} | image-soft-chain software CHAIN | [报告](soft_chain_{stamp}/reports/Soft_Chain.md) | 后台运行；56项整核；100MHz共同核综合；不布线 |\n')
    print(json.dumps(launch_record, indent=2))


def execute(args):
    run = args.run.resolve()
    meta = json.loads((run / 'SOURCE.json').read_text())
    src, archive = Path(meta['source']), Path(meta['archive'])
    baseline_meta = json.loads((archive / 'C1_SOURCE.json').read_text())
    baseline = json.loads((archive / 'C1_VALIDATION_SUMMARY.json').read_text())
    area_baseline = json.loads((archive / 'C1_SYNTHESIS_SUMMARY.json').read_text())
    if not baseline['complete'] or not baseline['passed']:
        raise AssertionError('C1 reference is not certified')
    sys.path.insert(0, str(src))
    from model.mHBS import compile_image
    from model.profiles import profile_names
    lock = threading.RLock()
    state = dict(started_at=now(), complete=False, passed=False, images={}, tests={}, checks={}, synthesis={})
    cases = []

    def publish():
        with lock:
            state['updated_at'] = now()
            state['counts'] = {s: sum(r['status'] == s for r in state['tests'].values())
                               for s in ('pending', 'running', 'passed', 'failed')}
            write(run / 'status.json', state)
            write(archive / 'VALIDATION_SUMMARY.json', state)
            write(archive / 'reports/Soft_Chain.json', dict(source=meta, results=state))
            lines = ['# 软件 CHAIN 尝试', '', f"更新时间：{now()}；完成：{state['complete']}；通过：{state['passed']}。", '',
                     'K1U1，单 Hash 通道；仅综合，不布线。面积使用相同配置 common，不含程序 ROM 或签名缓存。',
                     '100MHz仅为 ATP 的假定频率，低频综合时序不代表布线闭合。',
                     '44项默认测试＋12项q边界/空消息Sign。h16/h15/h20仅Verify，完整Keygen/Sign本轮未运行。',
                     '外部输入、期望输出及计数保持C1认证字节身份；仅替换program/template/descriptor。',
                     '逐字节核对输出及签名缓存，比较64位Hash/块数及完整原像/结果count、SUM256、XOR256指纹（概率性多重集检查）。', '',
                     f"整核状态：`{state['counts']}`。", '',
                     '| 后端 | C1 LUT / FF | 新 LUT / FF | 新等效Slice | 状态 |', '|---|---:|---:|---:|---|']
            for backend in LOW:
                old, new = area_baseline[backend], state['synthesis'].get(backend, {})
                lines.append(f"| {backend} | {old['lut']} / {old['ff']} | {new.get('lut', '—')} / {new.get('ff', '—')} | {new.get('equivalent_slice', '—')} | {new.get('status', 'pending')} |")
            for name in ('slh_128f', 'xmss_h10', 'lms_h10'):
                lines += ['', f'## {name} Sign', '', '| 后端 | C1周期 | 新周期 | C1 ATP | 新ATP | 变化 |', '|---|---:|---:|---:|---:|---:|']
                for backend in LOW:
                    key = f'{backend}/{name}/sign'
                    old, new = baseline['tests'][key], state['tests'].get(key, {})
                    old_atp = area_baseline[backend]['equivalent_slice'] * old['cycles'] / 100000
                    new_area = state['synthesis'].get(backend, {}).get('equivalent_slice')
                    new_atp = new_area * new['cycles'] / 100000 if new_area is not None and new.get('status') == 'passed' else None
                    lines.append(f"| {backend} | {old['cycles']} | {new.get('cycles', '—')} | {old_atp:.6f} | {f'{new_atp:.6f}' if new_atp is not None else '—'} | {f'{(new_atp/old_atp-1)*100:+.3f}%' if new_atp is not None else '—'} |")
            lines += ['', '## 镜像容量与有效条数', '', '| 后端/参数 | program | template | descriptor |', '|---|---|---|---|']
            for key, row in state['images'].items():
                usage = row.get('usage', {})
                lines.append(f"| {key} | {str(usage.get('program_used', '—')) + '/' + str(usage.get('program_allocated', '—'))} | {str(usage.get('template_used', '—')) + '/' + str(usage.get('template_allocated', '—'))} | {str(usage.get('descriptor_used', '—')) + '/' + str(usage.get('descriptor_allocated', '—'))} |")
            lines += ['', '## 整核测试', '', '| 测试 | 周期 | Hash | 块数 | 动态指令 | 状态 |', '|---|---:|---:|---:|---:|---|']
            for key, row in state['tests'].items():
                lines.append(f"| {key} | {row.get('cycles', '—')} | {row.get('hashes', '—')} | {row.get('permutations', '—')} | {row.get('macro_metrics', {}).get('dynamic_instructions', '—')} | {row['status']} |")
            lines += ['', '附加检查：`' + str({key: row['status'] for key, row in state['checks'].items()}) + '`。', '',
                      f'详细仿真日志保留于 `{run}`；归档只保留摘要、冻结源码及综合证据。']
            target = archive / 'reports/Soft_Chain.md'
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text('\n'.join(lines) + '\n')

    def update(group, key, **value):
        with lock:
            state[group].setdefault(key, {}).update(value)
            publish()

    # Generate only small immutable images. This never evaluates a full tree.
    for backend in LOW:
        for name in profile_names(backend):
            image = compile_image(name, hash_backend=backend)
            folder = run / 'images' / backend / name
            image.write(folder)
            usage = image.usage() if callable(image.usage) else image.usage
            update('images', f'{backend}/{name}', status='passed', usage=usage, sha256=hashes(folder))
    write(archive / 'IMAGE_SUMMARY.json', state['images'])

    def add_case(key, backend, name, operation, old, old_vector):
        full_identity = hashes(old_vector)
        certified = old.get('vectors_sha256', old.get('final_vector_sha256'))
        if full_identity != certified:
            raise AssertionError(f'C1 fixture changed: {old_vector}')
        folder = run / 'vectors' / key.replace('/', '_') / name / operation
        folder.mkdir(parents=True, exist_ok=True)
        for filename in full_identity:
            shutil.copy2(old_vector / filename, folder / filename)
        for filename in ROMS:
            shutil.copy2(run / 'images' / backend / name / filename, folder / filename)
        new_identity = hashes(folder)
        if {k: v for k, v in new_identity.items() if k not in ROMS} != {k: v for k, v in full_identity.items() if k not in ROMS}:
            raise AssertionError('External fixture identity changed while replacing ROMs')
        cases.append((key, backend, name, operation, old, folder))
        update('tests', key, status='pending', baseline_cycles=old['cycles'], baseline_vector=str(old_vector),
               baseline_vectors_sha256=full_identity, vectors_sha256=new_identity,
               external_vector_identity_equal=True, operation=operation, backend=backend, profile=name)

    baseline_source = Path(baseline_meta['source'])
    for key, old in baseline['tests'].items():
        backend, name, operation = key.split('/')
        folder = (baseline_source.parent / 'high_vectors' / backend if name in HIGH else baseline_source / 'tb/vectors' / ('sha2' if backend == 'sha2' else '')) / name / operation
        add_case(key, backend, name, operation, old, folder)
    for filename in ('SIGN_INDEX_VALIDATION.json', 'EMPTY_MESSAGE_VALIDATION.json'):
        group = json.loads((archive / ('C1_' + filename)).read_text())
        if not group['complete'] or group['passed'] != (8 if filename.startswith('SIGN_INDEX') else 4):
            raise AssertionError('C1 supplement not certified')
        for key, old in group['results'].items():
            backend, name = key.split('/')[:2]
            suffix = 'empty' if filename.startswith('EMPTY') else key.split('/')[-1]
            add_case(f'{backend}/{name}/sign_{suffix}', backend, name, 'sign', old, Path(old['vector']))
    if len(cases) != 56 or len(state['images']) != 20:
        raise AssertionError('Required regression/image count differs')

    def command(cmd, log, env=None):
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open('w') as stream:
            result = subprocess.run(cmd, cwd=src, env=dict(os.environ, **(env or {})),
                                    stdin=subprocess.DEVNULL, stdout=stream, stderr=subprocess.STDOUT)
        if result.returncode:
            raise RuntimeError(f'Exit {result.returncode}: {log}')
        return log.read_text()

    def simulate(case):
        key, backend, name, operation, old, folder = case
        update('tests', key, status='running')
        started = time.monotonic()
        try:
            log = run / 'sim' / (key.replace('/', '_') + '.log')
            text = command(['bash', 'scripts/simulate_fast.sh', name, operation, '1', '1'], log,
                           dict(HASH_BACKEND=backend, VECTORS_DIR=str(folder.parent.parent),
                                SIM_FAST_OPT_SLOW='-O1', SIM_HASH_TRACE='1'))
            match = re.search(r'STATEFUL_PASS P1U1 op=(\d+) cycles=(\d+) total=(\d+) hashes=(\d+) permutations=(\d+)', text)
            trace_match = re.search(r'HASH_TRACE_METRICS (\{[^\n]+)', text)
            macro_match = re.search(r'MACRO_METRICS (\{[^\n]+)', text)
            if not match or not trace_match or not macro_match:
                raise AssertionError('Missing byte/cache/count/authorization PASS')
            op, cycles, total, hash_count, blocks = map(int, match.groups())
            trace, macro = json.loads(trace_match[1]), json.loads(macro_match[1])
            expected_trace = old['primitive_trace']
            if {k: trace.get(k) for k in expected_trace} != expected_trace or hash_count != old['hashes'] or blocks != old['permutations']:
                raise AssertionError('C1 cryptographic primitive workload/result fingerprint mismatch')
            if macro['CHAIN'] or macro['TREE'] or macro['TREE_child_CHAIN']:
                raise AssertionError('Forbidden autonomous macro executed')
            update('tests', key, status='passed', cycles=cycles, total_cycles=total, hashes=hash_count,
                   permutations=blocks, primitive_trace=trace, primitive_trace_matches_C1=True,
                   byte_exact_output=True, byte_exact_signature_cache=op == 1,
                   macro_metrics=macro, log=str(log), log_sha256=digest(log), seconds=time.monotonic()-started)
        except Exception as error:
            update('tests', key, status='failed', error=str(error), seconds=time.monotonic()-started)

    def check(key, cmd, env=None):
        update('checks', key, status='running')
        started = time.monotonic()
        try:
            log = run / 'checks' / (key + '.log')
            text = command(cmd, log, env)
            update('checks', key, status='passed', log=str(log), log_sha256=digest(log),
                   seconds=time.monotonic()-started, summary=text[-1800:])
        except Exception as error:
            update('checks', key, status='failed', error=str(error), seconds=time.monotonic()-started)

    def synthesize(backend):
        update('synthesis', backend, status='running', started_at=now())
        started = time.monotonic()
        folder = run / 'synthesis' / backend
        folder.mkdir(parents=True)
        log = folder / 'vivado.log'
        try:
            with log.open('w') as stream:
                task = subprocess.Popen([os.environ.get('VIVADO', 'vivado'), '-mode', 'batch', '-nolog', '-nojournal',
                                         '-source', str(src / 'scripts/diagnose_timing.tcl'), '-tclargs', str(src), '1', '1', str(folder), '10.0'],
                                        cwd=src, env=dict(os.environ, HASH_BACKEND=backend), stdin=subprocess.DEVNULL,
                                        stdout=stream, stderr=subprocess.STDOUT)
                while task.poll() is None:
                    time.sleep(5)
                    if time.monotonic()-started > 600 and state['synthesis'][backend]['status'] == 'running':
                        update('synthesis', backend, status='analysis_deferred', pid=task.pid,
                               reason='Synthesis continues in background; analysis proceeds with other results')
                if task.returncode:
                    raise RuntimeError(f'Vivado exit {task.returncode}: {log}')
            report = (folder / 'utilization.rpt').read_text()
            def resource(pattern):
                match = re.search(pattern, report)
                if not match:
                    raise AssertionError('Utilization resource field missing: ' + pattern)
                return int(match[1].replace(',', ''))
            lut = resource(r'\|\s*Slice LUTs\*?\s*\|\s*([\d,]+)')
            ff = resource(r'\|\s*Slice Registers\s*\|\s*([\d,]+)')
            bram = resource(r'\|\s*Block RAM Tile\s*\|\s*([\d,]+)')
            dsp = resource(r'\|\s*DSPs\s*\|\s*([\d,]+)')
            audit = json.loads((folder / 'debug_audit.json').read_text())
            if not audit['passed']:
                raise AssertionError('Debug registers survived synthesis')
            evidence = archive / 'synthesis' / backend
            evidence.mkdir(parents=True)
            for name in ('utilization.rpt', 'hierarchical.rpt', 'timing.rpt', 'critical_paths.rpt', 'settings.txt', 'debug_audit.json', 'vivado.log'):
                shutil.copy2(folder / name, evidence / name)
            update('synthesis', backend, status='passed', lut=lut, ff=ff, bram=bram, dsp=dsp,
                   equivalent_slice=lut/4+ff/8, debug_audit=audit, seconds=time.monotonic()-started,
                   settings=(folder / 'settings.txt').read_text(), report_sha256={p.name: digest(p) for p in evidence.iterdir()})
        except Exception as error:
            update('synthesis', backend, status='failed', error=str(error), seconds=time.monotonic()-started)

    checks = [
        ('control_faults', [sys.executable, 'scripts/check_chain_controls.py'], None),
        ('model_verify_bounds', [sys.executable, 'scripts/check_chain_model.py', '--full', '--verify-only', '--output', str(archive / 'MODEL_VALIDATION.json')], None),
        ('ordered_hash_trace', [sys.executable, 'scripts/check_soft_chain_ordered.py',
                                '--source', str(src), '--baseline-source', str(baseline_source),
                                '--run', str(run / 'ordered'), '--summary', str(archive / 'ORDERED_TRACE_VALIDATION.json')], None),
    ]
    for backend in LOW:
        for synthesis in (False, True):
            checks.append((backend + '_recipes' + ('_synthesis' if synthesis else ''),
                           [sys.executable, 'scripts/check_recipes.py', '--hash', backend, '--pipeline', '1', '--unroll', '1'] + (['--synthesis'] if synthesis else []), None))
        checks.append((backend + '_signature_views', [sys.executable, 'scripts/check_top_signature.py', '--hash', backend], None))
        for name in ('slh_128f', 'xmss_h10', 'lms_h10'):
            env = dict(HASH_BACKEND=backend)
            checks.append((backend + '_' + name + '_stall_reset', ['bash', 'scripts/simulate.sh', name, 'verify', '1', '1', '+STALL=1', '+REPLAYS=2', '+INTERRUPT=1'], env))
            checks.append((backend + '_' + name + '_truncate', ['bash', 'scripts/simulate.sh', name, 'verify', '1', '1', '+CUT=2'], env))
            for tamper in range(1, 6):
                checks.append((backend + '_' + name + '_tamper' + str(tamper), ['bash', 'scripts/simulate.sh', name, 'verify', '1', '1', '+TAMPER=' + str(tamper)], env))
        for name in ('xmss_h10', 'lms_h10'):
            checks.append((backend + '_' + name + '_q_overflow', ['bash', 'scripts/simulate.sh', name, 'verify', '1', '1', '+Q=1024', '+INVALID=1'], dict(HASH_BACKEND=backend)))
    # Full Sign fixtures remain q0/q1/q1023 only, at h10.
    cases.sort(key=lambda row: (0 if row[3] == 'verify' else 1 if row[3] == 'sign' and row[2] in ('slh_128f', 'xmss_h10', 'lms_h10') else 2, row[0]))
    publish()
    with cf.ThreadPoolExecutor(max_workers=4) as simulations, cf.ThreadPoolExecutor(max_workers=2) as auxiliaries, cf.ThreadPoolExecutor(max_workers=2) as synthesis:
        futures = [simulations.submit(simulate, case) for case in cases]
        futures += [auxiliaries.submit(check, *row) for row in checks]
        if meta['synthesize']:
            futures += [synthesis.submit(synthesize, backend) for backend in LOW]
        for future in cf.as_completed(futures):
            future.result()
    state['complete'] = True
    state['finished_at'] = now()
    state['source_unchanged'] = all(digest(src / name) == value for name, value in meta['sha256'].items())
    state['passed'] = state['source_unchanged'] and all(row['status'] == 'passed' for group in ('images', 'tests', 'checks', 'synthesis') for row in state[group].values())
    publish()
    write(archive / 'ARTIFACTS.json', dict(complete=True, passed=state['passed'], sha256={str(p.relative_to(archive)): digest(p) for p in archive.rglob('*') if p.is_file() and p.name != 'ARTIFACTS.json'}))
    raise SystemExit(0 if state['passed'] else 1)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--launch', action='store_true')
    parser.add_argument('--synthesize', action='store_true')
    parser.add_argument('--run', type=Path)
    args = parser.parse_args()
    if args.launch:
        launch(args)
    elif args.run:
        execute(args)
    else:
        parser.error('Use --launch [--synthesize] or --run PATH')


if __name__ == '__main__':
    main()
