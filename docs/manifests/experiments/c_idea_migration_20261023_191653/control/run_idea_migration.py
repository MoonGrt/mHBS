#!/usr/bin/env python3
"""Measure isolated migration candidates, retain wins, and retire archived worktree."""
import argparse
from concurrent.futures import ThreadPoolExecutor, wait
from datetime import datetime
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import threading
import time
from zoneinfo import ZoneInfo

REFRESH = 60
FOCUS = ('slh_128f', 'xmss_h10', 'lms_h10')
SPEC = {
    'c_control': ('c', ('shake', 'sha2')),
    'c_shared': ('c', ('shake', 'sha2')),
    'i_shared': ('i', ('shake',)),
    't_shared': ('t', ('shake',)),
}


def now():
    return datetime.now(ZoneInfo('Asia/Singapore')).isoformat(timespec='seconds')


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text())


def atomic(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_text(value)
    temporary.replace(path)


def write(path, value):
    atomic(path, json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def copy(source, target):
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists() or sha(source) != sha(target):
        temporary = target.with_name(target.name + '.tmp')
        shutil.copyfile(source, temporary)
        temporary.replace(target)


def prepare(run):
    meta = read(run / 'SOURCE.json')
    root = Path(meta['workspace'])
    archive = Path(meta['archive'])
    staging = root / 'build/c_idea_migration_staging'
    candidate_meta = {}
    for label, (design, backends) in SPEC.items():
        folder = run / 'candidates' / label / 'source'
        shutil.copytree(run / 'baseline_source', folder)
        changes = {}
        if design == 'c':
            changes['rtl/c/executor/executor.sv'] = staging / 'control/executor.sv'
        if label.endswith('_shared'):
            changes[f'rtl/{design}/hash/shake-recipe.sv'] = staging / f'formatter_stream/rtl/{design}/hash/shake-recipe.sv'
        for name, source in changes.items():
            shutil.copyfile(source, folder / name)
        shutil.copyfile(root / 'scripts/validate_idea_migration.py', folder / 'scripts/validate_idea_migration.py')
        (folder / 'sources.txt').write_text((folder / f'rtl/{design}/sources.txt').read_text())
        names = (folder / 'sources.txt').read_text().splitlines()
        names += [str(p.relative_to(folder)) for p in (folder / f'rtl/{design}').rglob('*.svh')]
        names += ['sources.txt', 'scripts/audit_debug.tcl']
        checks = {name: sha(folder / name) for name in sorted(set(names))}
        record = dict(label=label, design=design, backends=backends, source=str(folder),
                      changed={name: sha(folder / name) for name in changes}, sha256=checks)
        candidate_meta[label] = record
        write(archive / 'candidates' / label / 'SOURCE.json', record)
        with tarfile.open(archive / 'candidates' / label / 'frozen_rtl.tar.gz', 'w:gz') as bundle:
            for name in checks:
                bundle.add(folder / name, arcname=name)
    shutil.copyfile(root / 'scripts/validate_idea_migration.py', run / 'baseline_source/scripts/validate_idea_migration.py')
    for name in ('run_idea_migration.py', 'validate_idea_migration.py', 'route_ablation_common.tcl', 'run_ablation_route.py'):
        copy(root / 'scripts' / name, run / 'control' / name)
        copy(root / 'scripts' / name, archive / 'control' / name)
    for part in ('control', 'formatter', 'stream', 'formatter_stream'):
        if (staging / part).exists():
            shutil.copytree(staging / part, archive / 'idea_audits' / part,
                            ignore=shutil.ignore_patterns('obj', '__pycache__'))
    plan = dict(candidates=candidate_meta, configuration='P1U1', frequency_mhz=100,
                refresh_seconds=REFRESH, vivado=shutil.which('vivado'),
                acceptance='Full validation; legal complete route with hold/DRC passing; preserve a closed100MHz baseline or improve setup for an unclosed baseline; no three-focus routed-area x measured-cycle regression in either affected backend; at least one strict gain. Unclosed100MHz ATP remains explicitly hypothetical.',
                decision='pending', complete=False, started_at=now())
    write(run / 'PLAN.json', plan)
    write(archive / 'PLAN.json', plan)
    controller = Controller(run)
    controller.publish()
    command = [sys.executable, str(run / 'control/run_idea_migration.py'), '--run', str(run)]
    with (run / 'controller.log').open('w') as stream:
        process = subprocess.Popen(command, cwd=root, stdin=subprocess.DEVNULL,
                                   stdout=stream, stderr=subprocess.STDOUT, start_new_session=True)
    write(run / 'LAUNCH.json', dict(pid=process.pid, command=command))
    print(json.dumps(dict(pid=process.pid, run=str(run), report=str(controller.report)), indent=2))


class Controller:
    def __init__(self, run):
        self.run = Path(run).resolve()
        self.meta = read(self.run / 'SOURCE.json')
        self.plan = read(self.run / 'PLAN.json')
        self.root = Path(self.meta['workspace'])
        self.archive = Path(self.meta['archive'])
        self.report = self.archive / 'reports' / f'Idea_Migration_{self.meta["stamp"]}.md'
        self.lock = threading.RLock()
        self.state = dict(started_at=now(), complete=False, routes={}, validation={}, decisions={}, cleanup=None)
        spec = importlib.util.spec_from_file_location('route_helpers', self.run / 'control/run_ablation_route.py')
        helper = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(helper)
        self.resources = helper.resources

    def intact(self, label):
        record = self.plan['candidates'][label]
        return all(sha(Path(record['source']) / name) == value for name, value in record['sha256'].items())

    def route(self, label, backend):
        record = self.plan['candidates'][label]
        out = self.run / 'routes' / label / backend
        out.mkdir(parents=True, exist_ok=True)
        key = label + '/' + backend
        entry = dict(status='starting', design=record['design'], backend=backend, started_at=now(), started_epoch=time.time())
        with self.lock:
            self.state['routes'][key] = entry
        try:
            if not self.intact(label):
                raise RuntimeError('Candidate frozen RTL changed')
            command = [self.plan['vivado'], '-mode', 'batch', '-nolog', '-nojournal', '-notrace',
                       '-source', str(self.run / 'control/route_ablation_common.tcl'), '-tclargs',
                       record['source'], record['design'], backend, str(out), '100', '2']
            write(out / 'command.json', command)
            with (out / 'vivado.log').open('w') as stream:
                process = subprocess.Popen(command, cwd=out, stdin=subprocess.DEVNULL,
                                           stdout=stream, stderr=subprocess.STDOUT, start_new_session=True)
                entry.update(pid=process.pid, status='synthesis')
                code = process.wait()
            result = read(out / 'result.json') if (out / 'result.json').exists() else None
            accepted = bool(code == 0 and result and result['accepted_frequency'] and result['setup_hold_met'] and
                            result['wns_ns'] >= 0 and result['whs_ns'] >= 0 and result['actual_period_ns'] <= 10 and
                            result['fully_routed'] and not result['route_has_errors'] and result['drc_errors'] == 0 and
                            self.intact(label) and not (out / 'failure.json').exists())
            entry.update(status='passed' if accepted else 'target_not_met' if result else 'error',
                         returncode=code, result=result, accepted_frequency=accepted)
        except Exception as error:
            entry.update(status='error', error=str(error), accepted_frequency=False)
        entry['finished_at'] = now()
        print(now(), 'route', key, entry['status'], flush=True)

    def validate(self, label, design, backend, source):
        key = label + '/' + backend
        out = self.run / 'validation' / label / backend
        out.mkdir(parents=True, exist_ok=True)
        entry = dict(status='running', design=design, backend=backend, started_at=now())
        with self.lock:
            self.state['validation'][key] = entry
        command = [sys.executable, str(self.run / 'control/validate_idea_migration.py'),
                   '--source', str(source), '--design', design, '--backend', backend, '--output', str(out)]
        write(out / 'command.json', command)
        with (out / 'validator.log').open('w') as stream:
            result = subprocess.run(command, cwd=source, stdin=subprocess.DEVNULL, stdout=stream, stderr=subprocess.STDOUT)
        summary = read(out / 'SUMMARY.json') if (out / 'SUMMARY.json').exists() else None
        entry.update(status='passed' if result.returncode == 0 and summary and summary['passed'] else 'failed',
                     returncode=result.returncode, summary=str(out / 'SUMMARY.json'), finished_at=now())
        print(now(), 'validation', key, entry['status'], flush=True)

    def sample(self, label, backend):
        return read(self.run / 'validation' / label / backend / 'SUMMARY.json')

    def route_area(self, label, backend):
        return self.resources(self.run / 'routes' / label / backend / 'synth/utilization.rpt')

    def choose(self):
        for design in ('c', 'i', 't'):
            options = []
            for label, record in self.plan['candidates'].items():
                if record['design'] != design:
                    continue
                reasons, ratios = [], {}
                for backend in record['backends']:
                    route = self.state['routes'][label + '/' + backend]
                    old_out = Path(self.meta['baseline_route']) / 'jobs' / backend / design
                    old_route = read(old_out / 'result.json') if (old_out / 'result.json').exists() else None
                    result = route.get('result')
                    legal = bool(result and route.get('returncode') == 0 and result['fully_routed'] and
                                 not result['route_has_errors'] and result['drc_errors'] == 0 and result['whs_ns'] >= 0)
                    if not legal or not old_route:
                        reasons.append(backend + ': complete legal routed comparison unavailable')
                    elif old_route['accepted_frequency'] and not route.get('accepted_frequency'):
                        reasons.append(backend + ': previously closed100MHz lost closure')
                    elif not old_route['accepted_frequency'] and result['wns_ns'] < old_route['wns_ns']:
                        reasons.append(backend + ': setup worsened versus unclosed100MHz baseline')
                    new_key = label + '/' + backend
                    old_label = 'baseline_' + design
                    old_key = old_label + '/' + backend
                    if self.state['validation'][new_key]['status'] != 'passed' or self.state['validation'][old_key]['status'] != 'passed':
                        reasons.append(backend + ': validation incomplete or failed')
                        continue
                    old_area = self.resources(old_out / 'route/utilization.rpt')
                    new_area = self.resources(self.run / 'routes' / label / backend / 'route/utilization.rpt')
                    if not old_area or not new_area:
                        reasons.append(backend + ': measured routed area unavailable')
                        continue
                    old, new = self.sample(old_label, backend), self.sample(label, backend)
                    for case, old_case in old['cases'].items():
                        new_case = new['cases'][case]
                        if any(old_case[field] != new_case[field] for field in ('hashes', 'physical_blocks')):
                            reasons.append(backend + '/' + case + ': Hash workload changed')
                    for profile in FOCUS:
                        old_cycles = old['cases'][profile + '/sign']['cycles']
                        new_cycles = new['cases'][profile + '/sign']['cycles']
                        ratio = new_area['equivalent_slice'] * new_cycles / (old_area['equivalent_slice'] * old_cycles)
                        ratios[backend + '/' + profile] = dict(ratio=ratio, baseline_cycles=old_cycles,
                                                              candidate_cycles=new_cycles,
                                                              baseline_routed_area=old_area['equivalent_slice'],
                                                              candidate_routed_area=new_area['equivalent_slice'],
                                                              baseline_wns_ns=old_route['wns_ns'], candidate_wns_ns=result['wns_ns'],
                                                              baseline100MHz=old_route['accepted_frequency'],
                                                              candidate100MHz=route.get('accepted_frequency', False),
                                                              baseline_atp100=old_area['equivalent_slice'] * old_cycles / 100000,
                                                              candidate_atp100=new_area['equivalent_slice'] * new_cycles / 100000,
                                                              atp_frequency_scope='measured cycles at assumed100MHz; physical closure separately reported')
                        if ratio > 1:
                            reasons.append(backend + '/' + profile + ': same-frequency area-cycle product regressed')
                if not ratios or not any(value['ratio'] < 1 for value in ratios.values()):
                    reasons.append('No strictly improved focus ATP')
                score = math.prod(value['ratio'] for value in ratios.values()) ** (1 / len(ratios)) if ratios else None
                options.append(dict(label=label, eligible=not reasons, reasons=reasons, score=score, focus=ratios))
            eligible = [option for option in options if option['eligible']]
            best = min(eligible, key=lambda option: option['score']) if eligible else None
            self.state['decisions'][design] = dict(selected=best['label'] if best else 'baseline', alternatives=options)
        changes = {}
        for decision in self.state['decisions'].values():
            if decision['selected'] != 'baseline':
                record = self.plan['candidates'][decision['selected']]
                for name in record['changed']:
                    changes[name] = Path(record['source']) / name
        affected_designs = {name.split('/')[1] for name in changes}
        guarded = [name for name in self.meta['sha256'] if any(name.startswith('rtl/' + design + '/') for design in affected_designs)]
        for name in guarded:
            if sha(self.root / name) != self.meta['sha256'][name]:
                self.state['deployment'] = dict(status='blocked_external_change', file=name,
                                                selected_changes=list(changes), production_modified=False)
                return
        for name, source in changes.items():
            copy(source, self.root / name)
        if changes:
            designs = read(self.root / 'DESIGNS.json')
            for design in affected_designs:
                entry = designs['designs'][design]
                for name in changes:
                    if name.startswith('rtl/' + design + '/'):
                        entry['sha256'][name] = sha(self.root / name)
                entry['idea_migration'] = dict(experiment=str(self.archive.relative_to(self.root)),
                                               selected=self.state['decisions'][design]['selected'],
                                               validation='passed', frequency_mhz=100,
                                               frequency_acceptance='see measured per-backend route result')
            write(self.root / 'DESIGNS.json', designs)
        self.state['deployment'] = dict(status='applied' if changes else 'kept_baseline', applied_at=now(),
                                       files={name: sha(self.root / name) for name in changes},
                                       previous_sha256={name: self.meta['sha256'][name] for name in changes})
        write(self.archive / 'SELECTION.json', self.state['decisions'])
        write(self.archive / 'DEPLOYMENT.json', self.state['deployment'])
        with tarfile.open(self.archive / 'selected_rtl.tar.gz', 'w:gz') as bundle:
            selected = {}
            for design in ('i', 'c', 't'):
                for path in sorted((self.root / 'rtl' / design).rglob('*')):
                    if path.is_file():
                        name = str(path.relative_to(self.root))
                        selected[name] = sha(path)
                        bundle.add(path, arcname=name)
            write(self.archive / 'SELECTED_SOURCE.json', dict(sha256=selected, decisions=self.state['decisions']))

    def cleanup(self):
        evidence = self.archive / 'legacy_worktree/PRESERVATION_SUMMARY.json'
        if not evidence.exists() or self.state.get('deployment', {}).get('status') == 'blocked_external_change':
            self.state['cleanup'] = dict(status='retained', reason='Preservation or deployment unresolved')
            return
        # The preserved source inventory is immutable and independently checked.
        preserved = read(evidence)
        if preserved.get('status') != 'preserved_verified' or sha(self.archive / 'legacy_worktree/worktree_sources_and_history.tar.gz') != preserved['tar_sha256']:
            self.state['cleanup'] = dict(status='retained', reason='Legacy preservation checksum not verified')
            return
        temporary = Path(self.meta['temporary_worktree'])
        if not temporary.exists():
            self.state['cleanup'] = dict(status='already_absent')
            return
        status = subprocess.check_output(['git', '-C', str(temporary), 'status', '--porcelain=v1', '--untracked-files=all'], text=True)
        recorded = read(self.archive / 'legacy_worktree/GIT_STATE.json')
        head = subprocess.check_output(['git', '-C', str(temporary), 'rev-parse', 'HEAD'], text=True).strip()
        if status != recorded['status_porcelain_v1'] or head != recorded['head']:
            self.state['cleanup'] = dict(status='retained', reason='Temporary worktree status changed or status evidence unavailable')
            return
        for filename in ('TRACKED_WORKING_FILES.json', 'UNTRACKED_FILES.json'):
            for name, item in read(self.archive / 'legacy_worktree' / filename).items():
                if not (temporary / name).is_file() or sha(temporary / name) != item['sha256']:
                    self.state['cleanup'] = dict(status='retained', reason='Temporary source changed after archival', file=name)
                    return
        for process in Path('/proc').iterdir():
            if process.name.isdigit():
                try:
                    cwd = str((process / 'cwd').resolve())
                    arguments = (process / 'cmdline').read_bytes().split(b'\0')
                    if cwd.startswith(str(temporary) + '/') or cwd == str(temporary) or any(str(temporary).encode() in argument for argument in arguments):
                        self.state['cleanup'] = dict(status='retained', reason='Process still depends on temporary worktree', pid=int(process.name))
                        return
                except (OSError, RuntimeError):
                    pass
        result = subprocess.run(['git', 'worktree', 'remove', '--force', str(temporary)], cwd=self.root,
                                text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        self.state['cleanup'] = dict(status='removed' if result.returncode == 0 else 'retained',
                                     at=now(), returncode=result.returncode, output=result.stdout,
                                     preserved_evidence=str(evidence), preserved_summary=preserved)
        write(self.archive / 'CLEANUP.json', self.state['cleanup'])

    def publish(self):
        with self.lock:
            for key, entry in self.state['routes'].items():
                out = self.run / 'routes' / key
                stage = out / 'stage.json'
                if entry['status'] not in ('passed', 'target_not_met', 'error') and stage.exists():
                    entry['status'] = read(stage)['stage']
                if entry['status'] == 'synthesis' and time.time() - entry['started_epoch'] >= 600:
                    entry['analysis_deferred'] = True
                entry['synth_area'] = self.resources(out / 'synth/utilization.rpt')
                entry['route_area'] = self.resources(out / 'route/utilization.rpt')
                for path in out.rglob('*'):
                    if path.is_file() and path.suffix in ('.rpt', '.json', '.log', '.txt', '.xdc'):
                        copy(path, self.archive / 'routes' / key / path.relative_to(out))
            for key, entry in self.state['validation'].items():
                summary = self.run / 'validation' / key / 'SUMMARY.json'
                if summary.exists():
                    copy(summary, self.archive / 'validation_summary' / (key.replace('/', '_') + '.json'))
            self.state['updated_at'] = now()
            self.state['refresh_seconds'] = REFRESH
            write(self.run / 'STATE.json', self.state)
            write(self.report.with_suffix('.json'), self.state)
            lines = ['# 临时面积优化思路迁移与实测', '', f'更新：{now()}；状态：{"已完成" if self.state["complete"] else "后台测量"}。', '',
                     '固定P1U1／common／100MHz／xc7a200tffg1156-3／SYNTHESIS／每Vivado2线程。',
                     '保留原SHA2行为修正；不迁移旧参数简化、游标或握手候选。c_control只复用生命周期互斥字段；c_shared叠加通用SHAKE格式化和就地吸收，i/t分别检验适用的通用部分。', '',
                     '| 候选 | Backend | 状态 | 综合等效Slice | 布线等效Slice | WNS/ns | WHS/ns | 100MHz严格达标 |',
                     '|---|---|---|---:|---:|---:|---:|---|']
            for key, entry in sorted(self.state['routes'].items()):
                result, area, routed = entry.get('result'), entry.get('synth_area'), entry.get('route_area')
                lines.append('| ' + ' | '.join([key.split('/')[0], entry['backend'], entry['status'],
                    f'{area["equivalent_slice"]:.3f}' if area else '—', f'{routed["equivalent_slice"]:.3f}' if routed else '—',
                    f'{result["wns_ns"]:.3f}' if result else '—', f'{result["whs_ns"]:.3f}' if result else '—',
                    ('是' if entry.get('accepted_frequency') else '否') if result else '待完成']) + ' |')
            lines += ['', '取舍：输出、签名缓存、Hash/实际压缩计数及边界配方验证通过；完整路由、hold和DRC通过；已闭合100MHz的基线不能失去闭合，未闭合基线的setup不得恶化；三个目标Sign的布线面积×实测周期均不回退且至少一个改善。100MHz未闭合时ATP仅是同频假定值，不能当作硬件运行时间或频率达标证据。',
                      '基线来自 ablation_route_20261023_190751 的同源100MHz综合/布线，周期在本次冻结源重测。未完成数据不借用，不杀异常耗时任务。', '',
                      '## 验证', '', '| 组 | 状态 |', '|---|---|']
            lines += [f'| {key} | {entry["status"]} |' for key, entry in sorted(self.state['validation'].items())]
            if self.state['decisions']:
                lines += ['', '## 取舍', '', '```json', json.dumps(self.state['decisions'], ensure_ascii=False, indent=2), '```', '',
                          '部署：' + json.dumps(self.state.get('deployment'), ensure_ascii=False), '',
                          '临时工作区清理：' + json.dumps(self.state.get('cleanup', {}).get('status'), ensure_ascii=False)]
            lines += ['', '原始验证明细留在build；归档保留验证摘要、冻结RTL、综合/布线报告及日志。60秒刷新，任务结束后退出。', '']
            atomic(self.report, '\n'.join(lines))
            artifacts = {str(path.relative_to(self.archive)): sha(path) for path in self.archive.rglob('*')
                         if path.is_file() and path.name != 'ARTIFACTS.json' and not path.name.endswith('.tmp')}
            write(self.archive / 'ARTIFACTS.json', dict(sha256=artifacts, complete=self.state['complete']))

    def run_all(self):
        print(now(), 'Migration measurement starting', flush=True)
        futures = []
        with ThreadPoolExecutor(max_workers=6) as physical, ThreadPoolExecutor(max_workers=6) as functional:
            for label, record in self.plan['candidates'].items():
                for backend in record['backends']:
                    futures.append(physical.submit(self.route, label, backend))
                    futures.append(functional.submit(self.validate, label, record['design'], backend, Path(record['source'])))
            for design, backend in (('c', 'shake'), ('c', 'sha2'), ('i', 'shake'), ('t', 'shake')):
                futures.append(functional.submit(self.validate, 'baseline_' + design, design, backend, self.run / 'baseline_source'))
            while True:
                _, pending = wait(futures, timeout=REFRESH)
                self.publish()
                if not pending:
                    for future in futures:
                        future.result()
                    break
        self.choose()
        self.cleanup()
        self.state['complete'] = True
        self.publish()
        print(now(), 'Migration complete; refresher exits', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--launch', action='store_true')
    args = parser.parse_args()
    if args.launch:
        prepare(args.run.resolve())
    else:
        Controller(args.run).run_all()


if __name__ == '__main__':
    main()
