#!/usr/bin/env python3
"""Detached, resumable 128f Sign timing search. No model or conversation needed."""
import argparse
import concurrent.futures
import csv
import fcntl
import hashlib
import json
import math
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

from v42_external_flow import ROOT, BASE, BUILD, capture, identity, sha, tool_version
from v42_external_route import resources, audit_rom, audit_timing

RUN = ROOT / 'build/v4.2/sign_timing_u1234_v1'
FLOW = ROOT / 'build/sign_route_positive.tcl'
SHELL = 'slh_128f_sign'
POINTS = [(k, u) for u in (1, 2, 3, 4) for k in (1, 2, 4)]
TERMINAL = {'passed', 'timing_failed', 'congestion', 'tool_error', 'timeout'}


def atomic(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    pending = path.with_name(path.name + '.pending')
    with pending.open('w') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(pending, path)


def load(path):
    return json.loads(path.read_text())


def pid_start(pid):
    try:
        fields = Path(f'/proc/{pid}/stat').read_text().split(') ', 1)[1].split()
        return fields[19] if fields[0] != 'Z' else None
    except (FileNotFoundError, ProcessLookupError):
        return None


def alive(process):
    return bool(process and pid_start(process['pid']) == process.get('start_ticks'))


def terminate(process):
    if not alive(process):
        return
    try:
        os.killpg(process['pid'], signal.SIGTERM)
        os.killpg(process['pid'], signal.SIGCONT)
    except ProcessLookupError:
        return
    deadline = time.monotonic() + 5
    while alive(process) and time.monotonic() < deadline:
        time.sleep(.1)
    if alive(process):
        try:
            os.killpg(process['pid'], signal.SIGKILL)
        except ProcessLookupError:
            pass


def ticks(value):
    return int(math.ceil(value * 10 - 1e-8))


def coarse(u):
    return [ticks(value * u / 2) for value in (20, 15, 12.5, 10, 8, 6.4)]


def new_search():
    return dict(phase='coarse', coarse_index=0, loosen_count=0,
                pass_ticks=None, fail_ticks=None, refinements=0, reason=None)


def request(search, u):
    phase = search['phase']
    if phase == 'done':
        return None
    if phase == 'coarse':
        return coarse(u)[search['coarse_index']], 'coarse'
    if phase == 'loosen':
        return int(math.ceil(search['fail_ticks'] * 1.5)), 'loosen'
    if phase == 'repeat':
        return search['fail_ticks'], 'repeat'
    if phase == 'probe':
        return max(1, int(math.ceil(search['pass_ticks'] * .8))), 'probe'
    if phase == 'refine':
        return (search['pass_ticks'] + search['fail_ticks'] + 1) // 2, 'refine'
    raise ValueError(phase)


def advance(search, u, target, kind, passed):
    """Pure search transition; persist together with the completed attempt."""
    if passed:
        old = search['pass_ticks']
        search['pass_ticks'] = target if old is None else min(old, target)
    if kind == 'coarse':
        if passed:
            search['coarse_index'] += 1
            if search['coarse_index'] == len(coarse(u)):
                search.update(phase='done', reason='all_scheduled_coarse_targets_passed')
        else:
            search['fail_ticks'] = target
            search['phase'] = 'loosen' if search['pass_ticks'] is None else 'repeat'
    elif kind == 'loosen':
        search['loosen_count'] += 1
        if passed:
            search['phase'] = 'repeat'
        else:
            search['fail_ticks'] = target
            if search['loosen_count'] == 2:
                search.update(phase='done', reason='no_pass_after_two_relaxations')
    elif kind == 'repeat':
        if passed:
            # An observed failure is not assumed to be a monotonic boundary.
            search['fail_ticks'] = None
            search['phase'] = 'probe'
        else:
            search['phase'] = 'refine'
    elif kind == 'probe':
        if not passed:
            search.update(fail_ticks=target, phase='repeat')
    elif kind == 'refine':
        search['refinements'] += 1
        if not passed:
            search['fail_ticks'] = target
    if search['phase'] == 'refine' and (search['refinements'] >= 3 or
                                      search['pass_ticks'] - search['fail_ticks'] <= 2):
        search.update(phase='done', reason='refinement_limit_or_0.2ns_interval')


def checkpoint(folder, target):
    manifest = folder / 'stage.json'
    if manifest.exists():
        try:
            record = load(manifest)
            path = folder / (record['stage'] + '.dcp')
            if record['stage'] in ('post_place', 'post_route') and path.exists() and \
                    math.isclose(record['period_ns'], target) and sha(path) == record['checkpoint_sha256']:
                return record['stage']
        except (OSError, ValueError, KeyError):
            pass
    return 'fresh'


def classify(log):
    if 'SIGN_SCAN_TIMING_FAILED' in log:
        return 'timing_failed'
    if re.search(r'Design is not legally routed|failed to route due to routing congestion', log):
        return 'congestion'
    return 'tool_error'


class Interrupted(Exception):
    pass


class Driver:
    def __init__(self, run):
        self.run = run
        self.lock = threading.RLock()
        self.stop = threading.Event()
        self.state = load(run / 'state.json')
        self.baseline = load(BASE / 'candidates/program16_20260927_v1/simulation.json')['cases'][SHELL]

    def save(self):
        with self.lock:
            self.state['updated_at'] = datetime.now().astimezone().isoformat(timespec='seconds')
            atomic(self.run / 'state.json', self.state)
            self.status_text()

    def status_text(self):
        points = self.state['points']
        finished = sum(p['status'] in ('completed', 'preparation_failed') for p in points.values())
        attempts = [a for p in points.values() for a in p['attempts']]
        active = [label + ': ' + p.get('activity', '') for label, p in points.items()
                  if p['status'] == 'running']
        text = '\n'.join(['# 128f Sign 后台扫描状态', '',
                          '状态：' + self.state['status'],
                          f'完成组合：{finished}/12；已结束档位：{sum(a["status"] in TERMINAL for a in attempts)}；'
                          f'通过档位：{sum(a["status"] == "passed" for a in attempts)}。',
                          '当前任务：' + ('；'.join(active) or self.state.get('activity') or '-'),
                          '更新：' + self.state['updated_at'],
                          '结果：' + str(self.run / 'report.md'), ''])
        pending = self.run / 'STATUS.md.pending'
        pending.write_text(text)
        os.replace(pending, self.run / 'STATUS.md')

    def command(self, command, folder, name, record, timeout=None):
        """Persist active time and process identity; recover by killing any orphan."""
        folder.mkdir(parents=True, exist_ok=True)
        process = record.get('process')
        if alive(process):
            # Count time since the last heartbeat while an orphan was still alive.
            record['elapsed_seconds'] = record.get('elapsed_seconds', 0) + max(
                0, time.time() - record.get('heartbeat_epoch', time.time()))
            terminate(process)
        else:
            terminate(process)
        record.pop('process', None)
        elapsed = record.get('elapsed_seconds', 0)
        if timeout is not None and elapsed >= timeout:
            return None, True
        if self.stop.is_set():
            raise Interrupted()
        segment_start = time.monotonic()
        log_path = folder / name
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open('a') as log:
            log.write('\nSESSION ' + datetime.now().astimezone().isoformat() + '\n')
            log.flush()
            child = subprocess.Popen(command, cwd=folder, stdout=log, stderr=subprocess.STDOUT,
                                     start_new_session=True)
            with self.lock:
                record.update(command=command, process=dict(pid=child.pid, start_ticks=pid_start(child.pid)),
                              heartbeat_epoch=time.time())
                self.save()
            timed_out = False
            try:
                while child.poll() is None:
                    with self.lock:
                        record['elapsed_seconds'] = elapsed + time.monotonic() - segment_start
                        record['heartbeat_epoch'] = time.time()
                        self.save()
                    if self.stop.is_set():
                        terminate(record['process'])
                        raise Interrupted()
                    if timeout is not None and record['elapsed_seconds'] >= timeout:
                        timed_out = True
                        terminate(record['process'])
                        break
                    wait = 2 if timeout is None else min(2, max(0, timeout-record['elapsed_seconds']))
                    self.stop.wait(wait)
                child.wait()
            finally:
                if child.poll() is None:
                    terminate(record.get('process'))
                child.wait()
                with self.lock:
                    record['elapsed_seconds'] = elapsed + time.monotonic() - segment_start
                    record.pop('process', None)
                    record.pop('heartbeat_epoch', None)
                    self.save()
        return child.returncode, timed_out

    def units(self):
        for u in (1, 2, 3, 4):
            record = self.state['units'].setdefault(str(u), {})
            if record.get('passed'):
                continue
            self.state['activity'] = f'Keccak U{u} 编译及等价检查'
            self.save()
            out = self.run / 'units' / f'U{u}'
            obj = out / 'obj'
            binary = obj / 'Vtb_mhbs_sign_scan_keccak'
            if not binary.exists():
                command = ['verilator', '--binary', '--timing', '-j', '8', '-Wno-fatal',
                           '--top-module', 'tb_mhbs_sign_scan_keccak', f'-GUNROLL={u}',
                           '--Mdir', str(obj), str(ROOT / 'rtl/hash_lane/mhbs_keccak.sv'),
                           str(ROOT / 'rtl/hash_lane/mhbs_compact_shake_context_lane.sv'),
                           str(ROOT / 'tb/unit/tb_mhbs_sign_scan_keccak.sv')]
                code, _ = self.command(command, out, 'compile.log', record)
                if code:
                    raise RuntimeError(f'U{u} Keccak compilation failed')
            code, _ = self.command([str(binary)], out, 'run.log', record)
            if code or 'COMPACT_SHAKE_CONTEXT_LANE_PASS' not in (out / 'run.log').read_text():
                raise RuntimeError(f'U{u} Keccak equivalence failed')
            record.update(passed=True, run_sha256=sha(out / 'run.log'))
            self.save()
        self.state['activity'] = 'Keccak 门禁全部通过'
        self.save()

    def prepare(self, label):
        point = self.state['points'][label]
        folder = BUILD / point['tag']
        inputs = load(folder / 'inputs.json')
        assert inputs['snapshot_sha256'] == point['snapshot_sha256'] == sha(folder / 'source_snapshot.tar.gz')
        assert (inputs['lanes'], inputs['unroll']) == (point['k'], point['u'])
        with self.lock:
            point.update(status='running', activity='仿真及综合准备')
            preparation = point.setdefault('preparation', {})
            self.save()
        simulation_path = folder / 'simulation.json'
        if not simulation_path.exists():
            command = [sys.executable, str(ROOT / 'scripts/v42_external_flow.py'), 'sim',
                       '--tag', point['tag'], '--profile', 'slh_128f', '--operation', 'sign',
                       '--lanes', str(point['k']), '--unroll', str(point['u'])]
            code, _ = self.command(command, ROOT, str(self.run / label / 'simulation_driver.log'), preparation)
            if code:
                raise RuntimeError(f'{label} simulation failed')
        simulation = load(simulation_path)
        assert simulation['passed'] and set(simulation['cases']) == {SHELL}
        assert simulation['rtl_sha256'] == self.state['config']['rtl_sha256']
        sim = simulation['cases'][SHELL]
        assert sim['passed'] and sim['output_sha256'] == self.baseline['output_sha256']
        assert (sim['hashes'], sim['permutations']) == (self.baseline['hashes'], self.baseline['permutations'])
        if label == 'K2U2':
            assert sim['sign_cycles'] == self.baseline['sign_cycles'], 'Program16 baseline cycle mismatch'
        with self.lock:
            point['simulation'] = sim
        dcp = folder / 'synthesis' / SHELL / 'post_synth.dcp'
        if not dcp.exists():
            for name in ('synth_source', 'synthesis'):
                path = folder / name
                if path.exists():
                    path.rename(folder / (name + '_interrupted_' + str(time.time_ns())))
            command = [sys.executable, str(ROOT / 'scripts/v42_external_synth.py'), point['tag'], '--only', SHELL]
            code, _ = self.command(command, ROOT, str(self.run / label / 'synthesis_driver.log'), preparation)
            if code:
                raise RuntimeError(f'{label} synthesis failed')
        digest = sha(dcp)
        assert not point.get('source_dcp_sha256') or point['source_dcp_sha256'] == digest, 'Source DCP changed'
        with self.lock:
            point.update(source_dcp_sha256=digest, common_area=resources(folder / 'synthesis/core_utilization.rpt'),
                         synth_shell_area=resources(dcp.parent / 'utilization.rpt'))
            self.save()
        return dcp

    def attempt(self, label, source, attempt):
        point = self.state['points'][label]
        out = self.run / label / f"attempt_{attempt['index']:02d}_{attempt['ticks']}ticks"
        out.mkdir(parents=True, exist_ok=True)
        target = attempt['ticks'] / 10
        fingerprint = dict(source_dcp_sha256=point['source_dcp_sha256'],
                           source_snapshot_sha256=point['snapshot_sha256'],
                           flow_sha256=self.state['config']['flow_sha256'], period_ns=target)
        invocation = out / 'invocation.json'
        if invocation.exists():
            assert load(invocation)['fingerprint'] == fingerprint
        else:
            atomic(invocation, dict(fingerprint=fingerprint, point=label, kind=attempt['kind']))
        if (out / 'result.json').exists():
            cached = load(out / 'result.json')
            assert cached['ticks'] == attempt['ticks'] and cached['fingerprint'] == fingerprint
            return cached
        stage = checkpoint(out, target)
        with self.lock:
            point['activity'] = f"{target:g} ns ({stage})"
            attempt['status'] = 'running'
            self.save()
        command = ['vivado', '-mode', 'batch', '-nolog', '-nojournal', '-source', str(FLOW),
                   '-tclargs', str(source), str(out), str(target), stage]
        code, timed_out = self.command(command, out, 'route.log', attempt,
                                       timeout=self.state['config']['timeout_seconds'])
        result = dict(index=attempt['index'], ticks=attempt['ticks'], period_ns=target,
                      kind=attempt['kind'], elapsed_seconds=attempt.get('elapsed_seconds', 0),
                      folder=str(out.relative_to(ROOT)), fingerprint=fingerprint)
        log = (out / 'route.log').read_text(errors='replace') if (out / 'route.log').exists() else ''
        current_log = log.rsplit('\nSESSION ', 1)[-1]
        if timed_out:
            result.update(status='timeout', failure='单档累计运行达到 7200 秒')
        elif code:
            errors = [line for line in current_log.splitlines() if line.startswith('ERROR:')]
            result.update(status=classify(current_log), failure='; '.join(errors[:2]) or f'Vivado exit {code}')
        else:
            try:
                clock = load(out / 'clock.json')
                assert math.isclose(clock['period_ns'], target)
                assert clock['wns_ns'] > 0 and clock['whs_ns'] >= 0
                audit_timing(out)
                rom = audit_rom(out / 'initialized_rom.tsv', BASE / 'images/slh_128f')
                area = resources(out / 'utilization.rpt')
                cycles = point['simulation']['sign_cycles']
                result.update(status='passed', **area, **clock, frequency_mhz=1000/target,
                              compute_cycles=cycles, latency_ms=cycles*target/1e6,
                              area_time_product=area['equivalent_slice']*cycles*target/1e6,
                              rom_audit=rom)
            except Exception as error:
                result.update(status='tool_error', failure=f'Audit failed: {error!r}')
        for path in (out / 'clock.json', out / 'utilization.rpt'):
            if path.exists() and result['status'] != 'passed':
                if path.name == 'clock.json':
                    result['timing_observation'] = load(path)
                    result.update({key: result['timing_observation'][key] for key in ('wns_ns', 'whs_ns')})
                else:
                    result['area_observation'] = resources(path)
                    result.update(result['area_observation'])
        result['evidence_sha256'] = {path.name: sha(path) for path in out.iterdir()
                                     if path.is_file() and path.suffix in ('.json', '.rpt', '.log', '.xdc', '.tsv', '.dcp')}
        atomic(out / 'result.json', result)
        print('SIGN_SCAN_ATTEMPT', label, target, result['status'], flush=True)
        return result

    def point(self, label):
        point = self.state['points'][label]
        if point['status'] in ('completed', 'preparation_failed'):
            if label == 'K2U2' and point['status'] == 'preparation_failed':
                raise RuntimeError('K2U2 preparation/baseline gate previously failed: ' + point['failure'])
            return
        try:
            source = self.prepare(label)
            while point['search']['phase'] != 'done':
                if self.stop.is_set():
                    raise Interrupted()
                pending = next((a for a in point['attempts'] if a['status'] not in TERMINAL), None)
                if pending is None:
                    if len(point['attempts']) >= self.state['config']['max_attempts']:
                        with self.lock:
                            point['search'].update(phase='done', reason='ten_attempt_limit')
                        break
                    target, kind = request(point['search'], point['u'])
                    pending = dict(index=len(point['attempts'])+1, ticks=target, kind=kind,
                                   status='pending', elapsed_seconds=0)
                    with self.lock:
                        point['attempts'].append(pending)
                        self.save()
                result = self.attempt(label, source, pending)
                with self.lock:
                    pending.update(result)
                    advance(point['search'], point['u'], result['ticks'], result['kind'], result['status'] == 'passed')
                    self.save()
                self.report()
            with self.lock:
                point.update(status='completed', activity='结束')
                self.save()
            self.report()
        except Interrupted:
            with self.lock:
                point.update(status='interrupted', activity='已停止，可恢复')
                self.save()
            raise
        except Exception as error:
            with self.lock:
                point.update(status='preparation_failed', failure=repr(error), activity='准备或调度失败')
                self.save()
            print('SIGN_SCAN_POINT_ERROR', label, repr(error), flush=True)
            if label == 'K2U2':
                raise

    def report(self):
        with self.lock:
            state = json.loads(json.dumps(self.state))
        rows = []
        summaries = []
        for label, point in state['points'].items():
            passed = [a for a in point['attempts'] if a['status'] == 'passed']
            fastest = max(passed, key=lambda a: (a['frequency_mhz'], -a['area_time_product'])) if passed else {}
            best_atp = min(passed, key=lambda a: a['area_time_product']) if passed else {}
            summaries.append(dict(point=label, status=point['status'], fastest=fastest,
                                  best_atp=best_atp, simulation=point.get('simulation'),
                                  search=point['search'], failure=point.get('failure')))
            for a in point['attempts']:
                rows.append(dict(profile_operation='128f SG', point=label, attempt=a['index'],
                                 kind=a['kind'], status=a['status'], period_ns=a['ticks']/10,
                                 compute_cycles=point.get('simulation', {}).get('sign_cycles'),
                                 **{key: a.get(key) for key in ('lut', 'ff', 'lutram', 'equivalent_slice',
                                    'frequency_mhz', 'latency_ms', 'area_time_product', 'wns_ns', 'whs_ns',
                                    'elapsed_seconds', 'failure')}))
        def value(x):
            return '-' if x is None else f'{x:.3f}' if isinstance(x, float) else str(x)
        def attempt_table(selected):
            lines = ['| 参数集/操作 | K/U | 档位 | 类型 | 目标 ns | LUT | FF | LUTRAM | 等效 Slice | 周期 | 核内 MHz | 签名 ms | ATP Slice·ms | Setup ns | Hold ns | 用时 s | 状态 |',
                     '|---|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|']
            for row in selected:
                fields = ('profile_operation', 'point', 'attempt', 'kind', 'period_ns', 'lut', 'ff',
                          'lutram', 'equivalent_slice', 'compute_cycles', 'frequency_mhz', 'latency_ms',
                          'area_time_product', 'wns_ns', 'whs_ns', 'elapsed_seconds', 'status')
                lines.append('| ' + ' | '.join(value(row.get(key)) for key in fields) + ' |')
            return lines
        lines = ['# 128f Sign：U1/U2/U3/U4 时序扫描', '',
                 '目的：按相同搜索规则、不同 U 的约束范围比较最高通过频率、实际签名时间和 ATP。', '',
                 f"状态：{state['status']}；更新：{state['updated_at']}。", '',
                 '器件 xc7a200tffg1156-3，Vivado 2025.2。核内路径签核；外部接口未签核。'
                 '每档重新布局布线，按原目标周期检查 Setup > 0 ns、Hold ≥ 0。',
                 '等效 Slice=LUT/4+FF/8+BRAM36×232.4+DSP×102.4；签名 ms=周期×目标 ns/10⁶；ATP=布线等效 Slice×签名 ms。',
                 '记录的是有次数与时间预算的搜索结果，不是全局最高频率；超时不证明该频率不可实现。', '',
                 '## 十二点汇总', '',
                 '| 参数集/操作 | K/U | LUT | FF | LUTRAM | 等效 Slice | 签名周期 | 最高通过 MHz | 对应签名 ms | 对应 ATP | 最低 ATP | 最低 ATP 档 ns | 状态 |',
                 '|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|']
        for summary in summaries:
            a = summary['fastest']; b = summary['best_atp']; sim = summary['simulation'] or {}
            cells = ['128f SG', summary['point'], *[a.get(key) for key in ('lut', 'ff', 'lutram', 'equivalent_slice')],
                     sim.get('sign_cycles'), *[a.get(key) for key in ('frequency_mhz', 'latency_ms', 'area_time_product')],
                     b.get('area_time_product'), b.get('period_ns'), summary['status']]
            lines.append('| ' + ' | '.join(value(cell) for cell in cells) + ' |')
        lines += ['', '## K2U2 首轮扫描', ''] + attempt_table([r for r in rows if r['point'] == 'K2U2'])
        lines += ['', '## 全部档位', ''] + attempt_table(rows)
        lines += ['', '## 历史流程对照', '',
                  '以下使用不同布线口径，只作历史对照，不参与本轮排名。', '',
                  '| 参数集/操作 | K/U | 历史初始约束 | 核内 MHz | 签名 ms | ATP |',
                  '|---|---|---|---:|---:|---:|']
        for k, u in [(k, u) for k in (1, 2, 4) for u in (1, 2, 4)]:
            for name in ('route', 'route_internal20_v1'):
                path = BUILD / f'ku_k{k}u{u}_v2' / name / SHELL / 'result.json'
                if path.exists():
                    old = load(path)
                    if old.get('passed'):
                        lines.append('| 128f SG | K%dU%d | %s | %s | %s | %s |' % (
                            k, u, '10 ns' if name == 'route' else '20 ns', value(old['frequency_mhz']),
                            value(old['latency_ms']), value(old['area_time_product'])))
        lines += ['', '## 失败及未完成档', '']
        lines += [f"- {r['point']} 档 {r['attempt']}：{r['status']}；{r.get('failure') or '-'}"
                  for r in rows if r['status'] != 'passed']
        lines += [f"- {s['point']} 准备失败：{s['failure']}" for s in summaries if s.get('failure')]
        lines += ['', '## 恢复与证据', '',
                  '完整状态及搜索边界：`state.json`；各档日志、DCP、资源、时序及哈希：各组合的 `attempt_*` 目录。',
                  '恢复会跳过已完成档位；未完成档优先使用可靠布线后／布局后检查点。没有检查点时重启该档；内存中的路由进度不能恢复。',
                  '生产 RTL 未替换，Git 历史未改写，未推送。', '']
        # Concurrent point workers serialize publication of all report files.
        with self.lock:
            atomic(self.run / 'results.json', dict(status=state['status'], updated_at=state['updated_at'],
                                                 summaries=summaries, attempts=rows, config=state['config']))
            if rows:
                pending = self.run / 'attempts.csv.pending'
                with pending.open('w', newline='', encoding='utf-8-sig') as stream:
                    writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
                    writer.writeheader()
                    writer.writerows({key: '-' if v is None else v for key, v in row.items()} for row in rows)
                os.replace(pending, self.run / 'attempts.csv')
            pending = self.run / 'report.md.pending'
            pending.write_text('\n'.join(lines))
            os.replace(pending, self.run / 'report.md')

    def execute(self):
        self.state.update(status='running', driver=dict(pid=os.getpid(), start_ticks=pid_start(os.getpid())))
        self.save()
        try:
            assert self.state['config']['rtl_sha256'] == identity(), 'RTL changed since capture'
            for path, digest in self.state['config']['runtime_sha256'].items():
                assert sha(ROOT / path) == digest, f'Runtime source changed: {path}'
            for path, digest in self.state['config']['source_sha256'].items():
                assert sha(ROOT / path) == digest, f'Captured source changed: {path}'
            for record in list(self.state.get('units', {}).values()) + [record
                           for point in self.state['points'].values()
                           for record in [point.get('preparation', {}), *point['attempts']]]:
                process = record.get('process')
                if alive(process):
                    record['elapsed_seconds'] = record.get('elapsed_seconds', 0) + max(
                        0, time.time() - record.get('heartbeat_epoch', time.time()))
                    terminate(process)
                record.pop('process', None)
                record.pop('heartbeat_epoch', None)
            self.save()
            self.report()
            self.units()
            self.point('K2U2')
            for u in (1, 2, 3, 4):
                labels = [f'K{k}U{u}' for k in (1, 2, 4) if f'K{k}U{u}' != 'K2U2']
                with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
                    futures = [pool.submit(self.point, label) for label in labels]
                    for future in futures:
                        future.result()
            all_valid = all(p['status'] == 'completed' and any(a['status'] == 'passed' for a in p['attempts'])
                            for p in self.state['points'].values())
            has_errors = not all_valid or any(p['status'] != 'completed' or any(a['status'] != 'passed' for a in p['attempts'])
                             for p in self.state['points'].values())
            self.state['status'] = 'finished_with_failed_attempts' if has_errors else 'finished_all_attempts_passed'
            self.state['all_points_have_valid_results'] = all_valid
            self.save()
            self.report()
            atomic(self.run / 'FINISHED.json', dict(status=self.state['status'], finished_at=self.state['updated_at'],
                                                   all_points_have_valid_results=all_valid,
                                                   report=str(self.run / 'report.md')))
            print('SIGN_SCAN_FINISHED', self.state['status'], flush=True)
        except Interrupted:
            self.state['status'] = 'stopped'
            self.save()
            self.report()
            print('SIGN_SCAN_STOPPED_RESUMABLE', flush=True)
        except Exception as error:
            self.state.update(status='blocked', failure=repr(error))
            self.save()
            self.report()
            atomic(self.run / 'FINISHED.json', dict(status='blocked', failure=repr(error)))
            print('SIGN_SCAN_BLOCKED', repr(error), flush=True)
        finally:
            self.state.pop('driver', None)
            self.save()


def initialize(run):
    run.mkdir(parents=True, exist_ok=True)
    if (run / 'state.json').exists():
        return
    runtime = ['scripts/sign_timing_scan.py', 'scripts/v42_external_flow.py', 'scripts/v42_external_synth.py',
               'scripts/v42_external_route.py', 'scripts/v42_common_partition.py',
               'experiments/v4.2/sign_timing/route.tcl', 'experiments/v4.2/external_job_message/synth.tcl',
               'experiments/v4.2/external_job_message/rom_mapping.tcl', 'scripts/v42_external_rom.py',
               'tb/unit/tb_mhbs_sign_scan_keccak.sv']
    points = {}
    common_source = None
    for k, u in POINTS:
        tag = f'signscan_k{k}u{u}_v1'
        folder = capture(tag, lanes=k, unroll=u)
        inputs = load(folder / 'inputs.json')
        if common_source is None:
            common_source = inputs['source_sha256']
        assert common_source == inputs['source_sha256']
        points[f'K{k}U{u}'] = dict(k=k, u=u, tag=tag, snapshot_sha256=inputs['snapshot_sha256'],
                                   status='pending', activity='', attempts=[], search=new_search())
    config = dict(device='xc7a200tffg1156-3', tool_version=tool_version('vivado', '-version'),
                  profile='slh_128f', operation='sign', timeout_seconds=7200, max_attempts=10,
                  worker_threads=8, parallel_points=3, io_timing_qualified=False,
                  flow_sha256=sha(FLOW), runtime_sha256={path: sha(ROOT / path) for path in runtime},
                  rtl_sha256=identity(), source_sha256=common_source)
    atomic(run / 'config.json', config)
    atomic(run / 'state.json', dict(schema='mhbs.sign_timing_scan.v1', status='ready',
                                   config=config, points=points, units={}, updated_at=datetime.now().astimezone().isoformat()))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('start', 'resume', 'run', 'status', 'stop'))
    parser.add_argument('--run-dir', type=Path, default=RUN)
    parser.add_argument('--lock-fd', type=int, help=argparse.SUPPRESS)
    args = parser.parse_args()
    run = args.run_dir.resolve()
    if args.action == 'status':
        state = load(run / 'state.json')
        print((run / 'STATUS.md').read_text() if (run / 'STATUS.md').exists() else state['status'])
        return
    if args.action == 'stop':
        state = load(run / 'state.json')
        driver = state.get('driver')
        if state['status'].startswith('finished_') and not alive(driver):
            print('ALREADY_FINISHED', run / 'report.md')
            return
        if alive(driver):
            os.kill(driver['pid'], signal.SIGTERM)
            deadline = time.monotonic() + 15
            while alive(driver) and time.monotonic() < deadline:
                time.sleep(.2)
        state = load(run / 'state.json')
        for record in list(state.get('units', {}).values()) + [r for p in state['points'].values()
                         for r in [p.get('preparation', {}), *p['attempts']]]:
            if alive(record.get('process')):
                record['elapsed_seconds'] = record.get('elapsed_seconds', 0) + max(
                    0, time.time() - record.get('heartbeat_epoch', time.time()))
            terminate(record.get('process'))
        if alive(driver):
            terminate(driver)
        final_state = load(run / 'state.json')
        # Preserve time recovered above when the coordinator was already gone.
        if driver and not alive(driver):
            for label, point in state['points'].items():
                final_point = final_state['points'][label]
                for old, current in zip(point['attempts'], final_point['attempts']):
                    current['elapsed_seconds'] = max(old.get('elapsed_seconds', 0), current.get('elapsed_seconds', 0))
        state = final_state
        state.pop('driver', None)
        state['status'] = 'stopped'
        for point in state['points'].values():
            if point['status'] == 'running':
                point.update(status='interrupted', activity='已停止，可恢复')
        for record in list(state.get('units', {}).values()) + [record for point in state['points'].values()
                       for record in [point.get('preparation', {}), *point['attempts']]]:
            record.pop('process', None)
            record.pop('heartbeat_epoch', None)
        atomic(run / 'state.json', state)
        stopped = Driver(run)
        stopped.save()
        stopped.report()
        print('STOP_REQUESTED', run)
        return
    run.mkdir(parents=True, exist_ok=True)
    lock_stream = os.fdopen(args.lock_fd, 'a+') if args.lock_fd is not None else (run / 'driver.lock').open('a+')
    with lock_stream as guard:
        try:
            fcntl.flock(guard, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print('ALREADY_RUNNING', run)
            return
        if args.action in ('start', 'resume'):
            initialize(run)
            state = load(run / 'state.json')
            if state['status'].startswith('finished_'):
                print('ALREADY_FINISHED', run / 'report.md')
                return
            if alive(state.get('driver')):
                print('ALREADY_RUNNING', state['driver']['pid'])
                return
            with (run / 'driver.log').open('a') as log:
                child = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), 'run', '--run-dir', str(run),
                                          '--lock-fd', str(guard.fileno())],
                                         cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, start_new_session=True,
                                         pass_fds=(guard.fileno(),))
            atomic(run / 'launched.json', dict(pid=child.pid, start_ticks=pid_start(child.pid),
                                              launched_at=datetime.now().astimezone().isoformat()))
            print(json.dumps(dict(pid=child.pid, status=str(run / 'STATUS.md'),
                                  state=str(run / 'state.json'), log=str(run / 'driver.log'),
                                  finished=str(run / 'FINISHED.json'), report=str(run / 'report.md')), ensure_ascii=False))
            return
        driver = Driver(run)
        signal.signal(signal.SIGTERM, lambda *_: driver.stop.set())
        signal.signal(signal.SIGINT, lambda *_: driver.stop.set())
        if (run / 'FINISHED.json').exists():
            (run / 'FINISHED.json').unlink()
        driver.execute()


if __name__ == '__main__':
    main()
