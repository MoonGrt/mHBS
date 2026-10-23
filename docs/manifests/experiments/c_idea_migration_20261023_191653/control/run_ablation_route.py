#!/usr/bin/env python3
"""Freeze i/c/t and launch their SHAKE/SHA2 P1U1 fixed-clock routes."""
import argparse
from concurrent.futures import ThreadPoolExecutor, wait
from datetime import datetime
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
from zoneinfo import ZoneInfo

DESIGNS = ('i', 'c', 't')
BACKENDS = ('shake', 'sha2')
REFRESH_SECONDS = 60


def now():
    return datetime.now(ZoneInfo('Asia/Singapore')).isoformat(timespec='seconds')


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def atomic(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_text(value)
    temporary.replace(path)


def write(path, value):
    atomic(path, json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def read(path):
    return json.loads(Path(path).read_text())


def copy_changed(source, target):
    source, target = Path(source), Path(target)
    if not target.is_file() or sha(source) != sha(target):
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(target.name + '.tmp')
        shutil.copyfile(source, temporary)
        temporary.replace(target)


def resources(path):
    if not path.is_file():
        return None
    text = path.read_text()

    def count(label):
        match = re.search(r'^\|\s*' + re.escape(label) + r'\*?\s*\|\s*([\d,.]+)', text, re.M)
        return float(match.group(1).replace(',', '')) if match else None

    lut, ff, bram, dsp = [count(label) for label in ('Slice LUTs', 'Slice Registers', 'Block RAM Tile', 'DSPs')]
    if any(value is None for value in (lut, ff, bram, dsp)):
        return None
    return dict(lut=int(lut), ff=int(ff), bram=bram, dsp=dsp,
                equivalent_slice=lut / 4 + ff / 8 + 232.4 * bram + 102.4 * dsp)


def launch(root, frequency, workers, vivado):
    root = Path(root).resolve()
    stamp = datetime.now(ZoneInfo('Asia/Singapore')).strftime('%Y%m%d_%H%M%S')
    experiment = f'ablation_route_{stamp}'
    run = root / 'build/ablation_route' / stamp
    archive = root / 'docs/manifests/experiments' / experiment
    run.mkdir(parents=True, exist_ok=False)
    (archive / 'reports').mkdir(parents=True, exist_ok=False)
    checks = {}
    for design in DESIGNS:
        frozen = run / 'source' / design
        listed = (root / f'rtl/{design}/sources.txt').read_text().splitlines()
        names = {name.strip() for name in listed if name.strip() and not name.startswith('#')}
        names.update(str(p.relative_to(root)) for p in (root / f'rtl/{design}').rglob('*.svh'))
        names.add(f'rtl/{design}/sources.txt')
        names.add('scripts/audit_debug.tcl')
        local = {}
        for name in sorted(names):
            local[name] = sha(root / name)
            copy_changed(root / name, frozen / name)
            if sha(root / name) != local[name] or sha(frozen / name) != local[name]:
                raise RuntimeError(f'Source changed during freeze: {name}')
        atomic(frozen / 'sources.txt', '\n'.join(name for name in listed if name.strip()) + '\n')
        local['sources.txt'] = sha(frozen / 'sources.txt')
        checks[design] = local
        write(frozen / 'SOURCE.json', dict(design=design, sha256=local))
    for name in ('run_ablation_route.py', 'route_ablation_common.tcl'):
        copy_changed(root / 'scripts' / name, run / 'control' / name)
        copy_changed(root / 'scripts' / name, archive / 'control' / name)
    metadata = dict(schema='mhbs.ablation.fixed_clock_route.source.v1', started_at=now(),
                    workspace=str(root), run=str(run), archive=str(archive),
                    branch=subprocess.check_output(['git', 'branch', '--show-current'], cwd=root, text=True).strip(),
                    commit=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip(),
                    designs=DESIGNS, backends=BACKENDS, configuration='P1U1', top='common',
                    part='xc7a200tffg1156-3', frequency_mhz=frequency, period_ns=1000 / frequency,
                    threads=2, workers=workers, vivado=str(vivado), refresh_seconds=REFRESH_SECONDS,
                    statistics='SYNTHESIS', keccak='generic', mode='out_of_context',
                    sha256=checks,
                    controls={p.name: sha(p) for p in (run / 'control').iterdir()},
                    scope='common internal constrained setup/hold; excludes external ROM/signature cache',
                    timing_exceptions='none added', frequency_search=False)
    for path in (run / 'SOURCE.json', archive / 'SOURCE.json'):
        write(path, metadata)
    with tarfile.open(archive / 'frozen_rtl.tar.gz', 'w:gz') as bundle:
        for path in sorted((run / 'source').rglob('*')):
            if path.is_file():
                bundle.add(path, arcname=path.relative_to(run / 'source'))
    index = archive.parent / 'INDEX.md'
    report_name = f'Ablation_Route_{stamp}'
    entry = f'| {stamp} | i/c/t SHAKE/SHA2 P1U1 {frequency:g}MHz布线 | [报告]({experiment}/reports/{report_name}.md) | [证据]({experiment}/ARTIFACTS.json) |\n'
    with index.open('a') as stream:
        stream.write(entry)
    runner = Runner(run)
    runner.publish()
    command = [sys.executable, str(run / 'control/run_ablation_route.py'), '--run', str(run)]
    with (run / 'controller.log').open('w') as stream:
        process = subprocess.Popen(command, cwd=root, stdin=subprocess.DEVNULL,
                                   stdout=stream, stderr=subprocess.STDOUT, start_new_session=True)
    write(run / 'LAUNCH.json', dict(pid=process.pid, command=command, report=str(archive / 'reports' / f'{report_name}.md')))
    atomic(run / 'controller.pid', str(process.pid) + '\n')
    print(json.dumps(dict(pid=process.pid, run=str(run), archive=str(archive),
                          report=str(archive / 'reports' / f'{report_name}.md')), indent=2))


class Runner:
    def __init__(self, run):
        self.run = Path(run).resolve()
        self.meta = read(self.run / 'SOURCE.json')
        self.archive = Path(self.meta['archive'])
        self.lock = threading.RLock()
        self.complete = False
        self.jobs = {f'{backend}/{design}': dict(status='pending', design=design, backend=backend)
                     for backend in BACKENDS for design in DESIGNS}

    def verify(self, design):
        root = self.run / 'source' / design
        return all(sha(root / name) == value for name, value in self.meta['sha256'][design].items())

    def worker(self, backend, design):
        key = f'{backend}/{design}'
        out = self.run / 'jobs' / key
        out.mkdir(parents=True, exist_ok=True)
        started = time.time()
        try:
            if not self.verify(design):
                raise RuntimeError('Frozen source checksum mismatch')
            command = [self.meta['vivado'], '-mode', 'batch', '-nolog', '-nojournal', '-notrace',
                       '-source', str(self.run / 'control/route_ablation_common.tcl'), '-tclargs',
                       str(self.run / 'source' / design), design, backend, str(out),
                       str(self.meta['frequency_mhz']), str(self.meta['threads'])]
            write(out / 'command.json', command)
            with (out / 'vivado.log').open('w') as stream:
                process = subprocess.Popen(command, cwd=out, stdin=subprocess.DEVNULL,
                                           stdout=stream, stderr=subprocess.STDOUT, start_new_session=True)
                with self.lock:
                    self.jobs[key].update(status='synthesis', pid=process.pid, started_epoch=started,
                                          started_at=now(), log=str(out / 'vivado.log'))
                returncode = process.wait()
            final = read(out / 'result.json') if (out / 'result.json').is_file() else None
            intact = self.verify(design)
            accepted = bool(returncode == 0 and intact and final and
                            final['setup_hold_met'] and final['accepted_frequency'] and
                            final['wns_ns'] >= 0 and final['whs_ns'] >= 0 and
                            final['actual_period_ns'] <= 1000 / self.meta['frequency_mhz'] and
                            final['fully_routed'] and not final['route_has_errors'] and
                            final['drc_errors'] == 0 and not (out / 'failure.json').exists())
            with self.lock:
                self.jobs[key].update(status='passed' if accepted else 'target_not_met' if final and returncode == 0 else 'error',
                                      returncode=returncode, source_intact=intact, result=final,
                                      accepted_frequency=accepted, finished_at=now(), elapsed_seconds=time.time() - started)
        except Exception as error:
            with self.lock:
                self.jobs[key].update(status='error', error=str(error), accepted_frequency=False,
                                      finished_at=now(), elapsed_seconds=time.time() - started)
        print(now(), key, self.jobs[key]['status'], flush=True)

    def publish(self):
        with self.lock:
            rows = []
            for key, job in self.jobs.items():
                out = self.run / 'jobs' / key
                if job['status'] not in ('pending', 'passed', 'target_not_met', 'error') and (out / 'stage.json').exists():
                    job['status'] = read(out / 'stage.json')['stage']
                if job['status'] == 'synthesis' and time.time() - job.get('started_epoch', time.time()) >= 600:
                    job['analysis_deferred'] = True
                row = dict(job)
                row['synth_area'] = resources(out / 'synth/utilization.rpt')
                row['route_area'] = resources(out / 'route/utilization.rpt')
                rows.append(row)
                if out.exists():
                    for path in out.rglob('*'):
                        if path.is_file() and (path.suffix in ('.rpt', '.json', '.txt', '.log', '.xdc')):
                            copy_changed(path, self.archive / 'jobs' / key / path.relative_to(out))
            summary = dict(schema='mhbs.ablation.fixed_clock_route.results.v1', updated_at=now(),
                           complete=self.complete, controller_pid=os.getpid(), refresh_seconds=REFRESH_SECONDS,
                           frequency_mhz=self.meta['frequency_mhz'], configuration='P1U1',
                           top='common', rows=rows, source_manifest='SOURCE.json')
            write(self.run / 'STATE.json', summary)
            stamp = self.run.name
            reports = self.archive / 'reports'
            write(reports / f'Ablation_Route_{stamp}.json', summary)
            lines = [f'# i / c / t P1U1：SHAKE / SHA2 {self.meta["frequency_mhz"]:g}MHz 布线', '',
                     f'更新：{summary["updated_at"]}；状态：{"全部结束" if self.complete else "后台运行"}。', '',
                     '同器件 xc7a200tffg1156-3、common OOC、SYNTHESIS 统计关闭、通用 Keccak、每任务2线程。',
                     '固定目标周期10.000ns，不搜索频率、不增加时序例外；60秒刷新，全部结束后退出。', '',
                     '| Backend | Design | 状态 | 综合 LUT / FF | 综合等效Slice | 布线 LUT / FF | 布线BRAM | 布线等效Slice | WNS(ns) | WHS(ns) | 完整路由 | DRC错误 | 100MHz达标 |',
                     '|---|---|---|---:|---:|---:|---:|---:|---:|---:|---|---:|---|']
            def area(a):
                return f'{a["lut"]:,} / {a["ff"]:,}' if a else '—'
            def equivalent(a):
                return f'{a["equivalent_slice"]:,.3f}' if a else '—'
            for row in rows:
                synth, routed, result = row['synth_area'], row['route_area'], row.get('result')
                end = row['status'] in ('passed', 'target_not_met', 'error')
                lines.append('| ' + ' | '.join([
                    row['backend'], row['design'], row['status'] + (' (analysis_deferred)' if row.get('analysis_deferred') else ''),
                    area(synth), equivalent(synth), area(routed),
                    str(routed['bram']) if routed else '—', equivalent(routed),
                    f'{result["wns_ns"]:.3f}' if result else '—',
                    f'{result["whs_ns"]:.3f}' if result else '—',
                    ('是' if result['fully_routed'] and not result['route_has_errors'] else '否') if result else '—',
                    str(result['drc_errors']) if result else '—',
                    ('是' if row.get('accepted_frequency') else '否') if end else '待完成']) + ' |')
            lines += ['', '达标同时要求受约束 setup/hold ≥0、实际周期≤10ns、完整路由、无路由错误、DRC Error/Critical Warning为0、Vivado正常退出及冻结源码一致。',
                      '等效Slice=LUT/4+FF/8+232.4×BRAM36+102.4×DSP，沿用既有矩阵口径。common不含外部ROM和signature缓存；结论仅针对OOC内部受约束路径，非板级接口验收。',
                      '综合超过10分钟只标记analysis_deferred，进程继续；尚未完成的数值留空。', '',
                      '[冻结源码身份](../SOURCE.json) · [冻结RTL](../frozen_rtl.tar.gz) · [完整证据索引](../ARTIFACTS.json)', '']
            atomic(reports / f'Ablation_Route_{stamp}.md', '\n'.join(lines))
            artifacts = {str(p.relative_to(self.archive)): sha(p) for p in self.archive.rglob('*')
                         if p.is_file() and p.name != 'ARTIFACTS.json' and not p.name.endswith('.tmp')}
            write(self.archive / 'ARTIFACTS.json', dict(sha256=artifacts, complete=self.complete))

    def run_all(self):
        print(now(), 'Starting six common routes', flush=True)
        with ThreadPoolExecutor(max_workers=self.meta['workers']) as pool:
            futures = [pool.submit(self.worker, backend, design) for backend in BACKENDS for design in DESIGNS]
            while True:
                _, pending = wait(futures, timeout=REFRESH_SECONDS)
                self.complete = not pending
                self.publish()
                if self.complete:
                    for future in futures:
                        future.result()
                    break
        print(now(), 'All jobs ended; report refresher exiting', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path)
    parser.add_argument('--frequency', type=float, default=100)
    parser.add_argument('--workers', type=int, default=6, choices=range(1, 7))
    args = parser.parse_args()
    if args.run:
        Runner(args.run).run_all()
    else:
        if args.frequency != 100:
            parser.error('This authorized run is fixed at 100 MHz')
        vivado = shutil.which(os.environ.get('VIVADO', 'vivado'))
        if not vivado:
            parser.error('Vivado not found')
        launch(Path(__file__).resolve().parents[1], args.frequency, args.workers, vivado)


if __name__ == '__main__':
    main()
