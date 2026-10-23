#!/usr/bin/env python3
"""Freeze a generic frequency-repair candidate and measure explicit points.

Only --launch starts hardware. All work uses the same immutable snapshot and
ends naturally; report polling is globally limited to once every 60 seconds.
"""
import argparse
import math
from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
from datetime import datetime
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

import run_dual_pu_route_matrix as dual

ROOT = Path(os.environ.get('MHBS_M_WORKSPACE', dual.ROOT)).resolve()
dual.ROOT = dual.archive.ROOT = ROOT
dual.archive.ARCHIVES = ROOT / 'docs/manifests/experiments'
# Explicit repair points and already-closed guards.
# Do not turn this into a Cartesian backend/configuration product.
FAILED_POINTS = (
    ('shake', 12, 1), ('sha2', 6, 1),
)
GUARD_POINTS = (
    ('shake', 1, 1), ('shake', 4, 1), ('shake', 8, 1),
    ('sha2', 1, 1), ('sha2', 4, 1), ('sha2', 8, 1),
    ('sha2', 12, 1), ('sha2', 4, 2),
)
POINTS = FAILED_POINTS + GUARD_POINTS
# Exercise the changed scheduled RAM paths in both simulation views at the
# already-closed P4/P8 guards too. Complete Sign separately checks real Jobs.
SUPPLEMENTAL_POINTS = FAILED_POINTS + (
    ('shake', 4, 1), ('shake', 8, 1), ('sha2', 8, 1),
)
dual.REPORT_REFRESH_SECONDS = 60
CONFIGS = tuple(dual.route_key(*point) for point in POINTS)
BASE_RECIPE_POINTS = (('shake', 1, 1), ('shake', 1, 2),
    ('sha2', 1, 1), ('sha2', 1, 2), ('sha2', 4, 1), ('sha2', 4, 2), ('sha2', 12, 1))
BASE_BATCH_POINTS = (('sha2', 4, 1), ('sha2', 4, 2))
BASE_VERIFY_POINTS = (('shake', 1, 1), ('shake', 1, 2),
    ('sha2', 1, 1), ('sha2', 1, 2), ('sha2', 4, 1))
BASE_SYNTH_VERIFY_CASES = (('shake', 1, 1, 'xmss_h10'), ('sha2', 1, 1, 'slh_128f'),
                           ('sha2', 4, 2, 'lms_h10'))
# Match the independently frozen validator's named cases, not just its self-reported count.
BASE_FUNCTIONAL_NAMES = tuple(
    [f'recipes_{b}_P{p}U{u}_syn{s}' for b, p, u in BASE_RECIPE_POINTS for s in (0, 1)] +
    [f'batch_{b}_P{p}U{u}_syn{s}' for b, p, u in BASE_BATCH_POINTS for s in (0, 1)] +
    [f'verify_{b}_P{p}U{u}_{profile}_replay_reset'
     for b, p, u in BASE_VERIFY_POINTS for profile in dual.PROFILES] +
    [f'verify_{b}_P{p}U{u}_{profile}_synthesis' for b, p, u, profile in BASE_SYNTH_VERIFY_CASES])
SUPPLEMENTAL_CASES = tuple((backend, p, u, synthesis, script, marker)
    for backend, p, u in SUPPLEMENTAL_POINTS for synthesis in (False, True)
    for script, marker in (('check_recipes.py', 'RECIPE_PASS'),
        ('check_pipeline.py', 'PIPELINE_PASS') if p >= 4 else ('simulate.sh', 'STATEFUL_PASS')))
FUNCTIONAL_GROUPS = len(BASE_FUNCTIONAL_NAMES) + len(SUPPLEMENTAL_CASES)
CONTROLS = ('run_timing_m.py', *dual.CONTROLS,
            'diagnose_timing.tcl', 'validate_p1sha_candidate.py')
BASELINES = (
    ('build/dual_pu_route_matrix/20261022_164951',
     '2caa69ccd872dbfe7ae7115624d7fef40317315d6e9c16eb40c0477c04283817'),
)
read, write, sha, now = dual.read, dual.write, dual.sha, dual.now


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def reference_evidence():
    """Bind only completed native logs/checkpoints; leave pending routes alone."""
    evidence = dict(tests={}, routes={}, sources=[])
    for name, expected in BASELINES:
        native = ROOT / name
        require(sha(native / 'SOURCE.json') == expected, 'Baseline SOURCE changed: ' + name)
        meta, state = read(native / 'SOURCE.json'), read(native / 'status.json')
        require(all(sha(Path(meta['source_root']) / n) == h for n, h in meta['sha256'].items()),
                'Baseline frozen files changed: ' + name)
        evidence['sources'].append(dict(run=str(native), source_manifest_sha256=expected,
            status_snapshot_updated_at=state.get('updated_at'),
            pending_route_keys=[key for key, job in state.get('routes', {}).items()
                if job.get('status') not in ('passed', 'target_not_met', 'error', 'failed',
                                             'stopped_by_user', 'validation_failed')],
            pending_jobs_not_waited_or_stopped=True))
        for config in CONFIGS:
            route = deepcopy(state.get('routes', {}).get(config, {}))
            if route.get('status') in ('passed', 'target_not_met'):
                folder = native / 'jobs' / config
                require(route.get('source_unchanged'), 'Unbound baseline route: ' + config)
                require('COMMON_TARGET_PASS' in (folder / 'vivado.log').read_text(errors='replace'),
                        'Missing native route completion marker: ' + config)
                for stage, field in (('synth/synthesized.dcp', 'synthesized_checkpoint_sha256'),
                                     ('route/routed.dcp', 'routed_checkpoint_sha256')):
                    require(sha(folder / stage) == route[field], 'Baseline checkpoint changed: ' + config)
                result = read(folder / 'result.json')
                require(all(route['result'].get(k) == v for k, v in result.items()),
                        'Baseline native result differs: ' + config)
                route.update(native_run=str(native), native_source_manifest_sha256=expected,
                    native_evidence_sha256={str(f.relative_to(native)): sha(f) for f in folder.rglob('*')
                        if f.is_file() and f.suffix in ('.log', '.rpt', '.json', '.xdc')})
                evidence['routes'][config] = route
            for profile in dual.PROFILES:
                key = config + '/' + profile
                test = deepcopy(state.get('tests', {}).get(key, {}))
                require(test.get('status') == 'passed' and test.get('source_unchanged')
                    and test.get('source_manifest_sha256') == expected
                    and test.get('output_and_signature_cache_checked_bytewise'),
                    'Completed native baseline Sign required: ' + key)
                for field in ('log', 'raw_log'):
                    require(sha(test[field]) == test[field + '_sha256'], 'Baseline log changed: ' + key)
                require(all(meta['sha256'][n] == h == sha(Path(meta['source_root']) / n)
                            for n, h in test['vectors_sha256'].items()), 'Baseline vector changed: ' + key)
                test.update(native_run=str(native), native_source_manifest_sha256=expected)
                evidence['tests'][key] = test
    return evidence


def timing(path):
    text = path.read_text(errors='replace')
    result = {}
    for key, pattern, cast in (
        ('data_path_ns', r'Data Path Delay:\s+([\d.]+)ns', float),
        ('logic_levels', r'Logic Levels:\s+(\d+)', int),
        ('source', r'^  Source:\s+(.+)$', str),
        ('destination', r'^  Destination:\s+(.+)$', str),
    ):
        match = re.search(pattern, text, re.M)
        if match:
            result[key] = cast(match[1])
    return result


def closed(route, u):
    result = route.get('result', {})
    return bool(route.get('status') == 'passed' and route.get('source_unchanged')
                and result.get('setup_hold_met') and result.get('drc_errors') == 0
                and route.get('route_status', {}).get('passed')
                and result.get('actual_period_ns', float('inf')) <= 1000 / (150 if u == 1 else 100))


def paired_cost(candidate, reference, tests, old_tests, frequency, limit):
    """A planning gate using equal-clock synthesis proxies, never closure proof."""
    require(math.isfinite(limit) and limit >= 0, 'Cost growth limit must be finite and nonnegative')
    require(candidate.get('status') == reference.get('status') == 'passed',
            'Both 100MHz common diagnostics must pass before cost comparison')
    area = candidate['area']['equivalent_slice']
    old_area = reference['area']['equivalent_slice']
    require(all(math.isfinite(a) and a > 0 for a in (area, old_area)), 'Invalid paired diagnostic area')
    profiles = {}
    for profile in dual.PROFILES:
        test, old = tests[profile], old_tests[profile]
        require(test.get('status') == old.get('status') == 'passed', 'Complete Sign required for cost gate')
        require(test.get('baseline_workload_equal') is True, 'Cost gate requires identical baseline workload')
        cycles, old_cycles = test['cycles'], old['cycles']
        require(cycles > 0 and old_cycles > 0, 'Invalid measured Sign cycles')
        ratio = (area * cycles) / (old_area * old_cycles)
        profiles[profile] = dict(candidate_cycles=cycles, baseline_cycles=old_cycles,
            candidate_target_proxy_slice_ms=area * cycles / (frequency * 1000),
            baseline_target_proxy_slice_ms=old_area * old_cycles / (frequency * 1000),
            cost_ratio=ratio, change_pct=100 * (ratio - 1))
    worst = max(p['cost_ratio'] for p in profiles.values())
    allowed = worst <= 1 + limit
    return dict(status='passed' if allowed else 'atp_cost_deferred', allowed=allowed,
        max_cost_ratio=worst, growth_limit_fraction=limit, candidate_diagnostic_slice=area,
        baseline_diagnostic_slice=old_area, target_frequency_mhz=frequency, profiles=profiles,
        diagnostic_period_ns=10.0, proxy_only=True, proves_frequency_closure=False,
        policy_is_user_hard_constraint=False,
        reason=('Paired diagnostic area × measured cycles passes the planning threshold' if allowed else
                'Paired diagnostic area × measured cycles exceeds the planning threshold; route not started'))


class Runner(dual.Runner):
    def __init__(self, run):
        super().__init__(run)
        if (self.run / 'CONTROL_SOURCE.json').exists():
            for name, wanted in read(self.run / 'CONTROL_SOURCE.json').items():
                require(sha(self.run / 'control' / name) == wanted ==
                        self.meta['sha256']['scripts/' + name], 'Frozen control changed: ' + name)
        self.reference = read(self.run / 'REFERENCE_EVIDENCE.json')
        self.reference_meta = read(self.run / 'REFERENCE_SOURCE.json')
        self.reference_source = Path(self.reference_meta['source_root'])
        self.reference_manifest_sha = sha(self.run / 'REFERENCE_SOURCE.json')
        require(self.reference_manifest_sha == BASELINES[0][1], 'Reference SOURCE identity differs')
        self.cost_growth_limit = self.meta.get('cost_growth_limit_fraction', .01)
        self.state.update(schema='mhbs.timing_m.results.v1',
                          synthesis={c: dict(status='pending') for c in CONFIGS},
                          reference_synthesis={c: dict(status='pending') for c in CONFIGS},
                          cost_gate={c: dict(status='pending') for c in CONFIGS},
                          reference_source_manifest_sha256=self.reference_manifest_sha,
                          functional=dict(status='pending'))
        # The parent initializes a Cartesian matrix; discard all unrequested entries.
        self.state['routes'] = {c: self.state['routes'][c] for c in CONFIGS}
        self.state['tests'] = {c + '/' + p: self.state['tests'][c + '/' + p]
                               for c in CONFIGS for p in dual.PROFILES}
        self.changed = threading.Condition(self.lock)

    def update(self, group, key, **values):
        # Apply workload equality before exposing a passed test to route gates.
        old = self.reference['tests'].get(key) if group == 'tests' else None
        if old and values.get('status') == 'passed':
            equal = all(values.get(n) == old[n] for n in ('hashes', 'permutations', 'vectors_sha256', 'verified_output_bytes'))
            values['baseline_workload_equal'] = equal
            if not equal:
                values.update(status='failed', error='Native baseline Hash/compression/vector/byte workload differs')
        with self.changed:
            super().update(group, key, **values)
            self.changed.notify_all()

    def reference_unchanged(self):
        return (sha(self.run / 'REFERENCE_SOURCE.json') == self.reference_manifest_sha and
                all(sha(self.reference_source / name) == wanted
                    for name, wanted in self.reference_meta['sha256'].items()))

    def synthesize(self, backend, p, u, reference=False):
        config = dual.route_key(backend, p, u)
        group = 'reference_synthesis' if reference else 'synthesis'
        output = self.run / ('reference_synth' if reference else 'synth') / config
        source = self.reference_source if reference else self.source
        unchanged = self.reference_unchanged if reference else self.unchanged
        identity = self.reference_manifest_sha if reference else self.state['source_manifest_sha256']
        started = time.monotonic()
        reserved = False
        try:
            output.mkdir(parents=True, exist_ok=True)
            self.update(group, config, status='waiting_for_capacity')
            self.capacity_token.worker_marker = str(output)
            self.reserve()
            reserved = True
            require(unchanged(), 'Frozen diagnostic source changed before synthesis')
            command = [self.meta['vivado'], '-mode', 'batch', '-nolog', '-nojournal', '-notrace',
                       '-source', str(self.run / 'control/diagnose_timing.tcl'), '-tclargs',
                       str(source), str(p), str(u), str(output), '10.0']
            with (output / 'vivado.log').open('w') as stream:
                process = subprocess.Popen(command, cwd=output, stdin=subprocess.DEVNULL,
                    stdout=stream, stderr=subprocess.STDOUT, start_new_session=True,
                    env=dict(os.environ, HASH_BACKEND=backend))
                self.update(group, config, status='running', pid=process.pid,
                            started_at=now(), command=command, log=str(output / 'vivado.log'))
                while process.poll() is None:
                    try:
                        process.wait(timeout=60)
                    except subprocess.TimeoutExpired:
                        elapsed = time.monotonic() - started
                        self.update(group, config, elapsed_seconds=elapsed, analysis_deferred=elapsed >= 600)
            require(process.returncode == 0 and f'MHBS_TIMING_DIAGNOSTIC_PASS P{p}U{u}' in
                    (output / 'vivado.log').read_text(errors='replace'), 'Diagnostic synthesis failed')
            require(unchanged(), 'Frozen diagnostic source changed')
            self.update(group, config, status='passed', source_unchanged=True,
                source_manifest_sha256=identity, source_root=str(source),
                diagnostic_controller_sha256=sha(self.run / 'control/diagnose_timing.tcl'),
                area=dual.resources(output / 'utilization.rpt'), timing=timing(output / 'critical_paths.rpt'),
                reports_sha256={f.name: sha(f) for f in output.iterdir()
                               if f.is_file() and f.suffix in ('.rpt', '.log', '.txt', '.xdc')},
                checkpoint_sha256=sha(output / 'synthesized.dcp'), analysis_deferred=False,
                elapsed_seconds=time.monotonic()-started, finished_at=now())
        except Exception as error:
            self.update(group, config, status='failed', error=str(error), finished_at=now())
        finally:
            if reserved:
                self.release_capacity()
                with self.capacity_lock:
                    self.reserved -= 1

    def validate(self):
        log = self.run / 'functional_validator.log'
        self.state['functional'] = dict(status='running', started_at=now(), log=str(log))
        try:
            command = [sys.executable, str(self.source / 'scripts/validate_p1sha_candidate.py'),
                       '--run-root', str(self.run)]
            with log.open('w') as stream:
                process = subprocess.Popen(command, cwd=ROOT, stdin=subprocess.DEVNULL,
                    stdout=stream, stderr=subprocess.STDOUT, start_new_session=True)
                with self.lock:
                    self.state['functional'].update(pid=process.pid, command=command)
                process.wait()
            proof = read(self.run / 'functional_validation/VALIDATION.json')
            require(process.returncode == 0 and proof.get('complete')
                    and proof.get('total_planned') == len(BASE_FUNCTIONAL_NAMES)
                    and proof.get('passed') == len(BASE_FUNCTIONAL_NAMES)
                    and proof.get('failed') == 0 and proof.get('source_unchanged')
                    and sorted(test['name'] for test in proof.get('tests', [])) == sorted(BASE_FUNCTIONAL_NAMES),
                    f'Functional {len(BASE_FUNCTIONAL_NAMES)}-group validation failed')
            require(proof['source_manifest_sha256'] == self.state['source_manifest_sha256'],
                    'Functional source identity differs')
            require(sha(self.run / 'functional_validation/validator.py') == proof['validator_sha256'],
                    'Validator identity differs')
            for test in proof['tests']:
                require(test['passed'] and sha(test['log']) == test['log_sha256'], 'Functional log changed')
            extra = self.validate_supplemental()
            require(extra['complete'] and extra['passed'] == extra['total_planned'] == len(SUPPLEMENTAL_CASES)
                    and extra['source_unchanged'], 'Supplemental validation failed')
            with self.changed:
                self.state['functional'].update(status='passed', summary=proof,
                    supplemental=extra, total_planned=FUNCTIONAL_GROUPS, passed=FUNCTIONAL_GROUPS, finished_at=now(),
                    summary_sha256=sha(self.run / 'functional_validation/VALIDATION.json'),
                    supplemental_summary_sha256=sha(self.run / 'supplemental_validation/SUMMARY.json'))
                self.changed.notify_all()
        except Exception as error:
            with self.changed:
                self.state['functional'].update(status='failed', error=str(error), finished_at=now())
                self.changed.notify_all()
        self.publish()

    def validate_supplemental(self):
        """Four-tag batch checks for P>=4; full-core Verify exercises P<4."""
        folder = self.run / 'supplemental_validation'
        folder.mkdir(parents=True, exist_ok=False)
        cases = SUPPLEMENTAL_CASES
        def execute(case):
            backend, p, u, synthesis, script, marker = case
            name = f'{Path(script).stem}_{backend}_P{p}U{u}_syn{int(synthesis)}'
            log = folder / (name + '.log')
            if script == 'simulate.sh':
                command = ['bash', 'scripts/simulate.sh', 'slh_128f', 'verify', str(p), str(u),
                           '+STALL=1', '+REPLAYS=2', '+INTERRUPT=1']
            else:
                command = [sys.executable, 'scripts/' + script, '--hash', backend,
                           '--pipeline', str(p), '--unroll', str(u)]
                if synthesis:
                    command.append('--synthesis')
            env = dict(os.environ, HASH_BACKEND=backend, SIM_SYNTHESIS=str(int(synthesis)),
                       VERILATOR=self.meta['verilator'], KECCAK_LUT6='0', SIM_VCD='0')
            for key in ('PROFILE_ENABLE', 'VECTORS_DIR'):
                env.pop(key, None)
            started = time.monotonic()
            with log.open('w') as stream:
                process = subprocess.run(command, cwd=self.source, env=env,
                    stdin=subprocess.DEVNULL, stdout=stream, stderr=subprocess.STDOUT,
                    start_new_session=True)
            return dict(name=name, command=command, hash_backend=backend, pipeline=p, unroll=u,
                synthesis=synthesis, returncode=process.returncode,
                passed=process.returncode == 0 and marker in log.read_text(errors='replace'),
                elapsed_seconds=time.monotonic()-started, log=str(log), log_sha256=sha(log))
        with ThreadPoolExecutor(max_workers=2) as pool:
            tests = list(pool.map(execute, cases))
        result = dict(complete=True, total_planned=len(cases),
            passed=sum(t['passed'] for t in tests), source_unchanged=self.unchanged(),
            source_manifest_sha256=self.state['source_manifest_sha256'], tests=tests,
            scope='Recipe bytes/counts in both views; P>=4 uses unchanged four-live-tag batch tests '
                  '(P>4 does not claim full occupancy). P<4 uses full-core SLH Verify stalls, '
                  'replay and in-flight reset in both views instead of the four-tag test; '
                  'complete Sign on three algorithms separately covers its actual scheduling.')
        write(folder / 'SUMMARY.json', result)
        return result

    def route(self, backend, p, u):
        config = dual.route_key(backend, p, u)
        require((backend, p, u) in POINTS, 'Unrequested route')
        require(self.meta.get('explicit_user_authorization'), 'Fixed-clock route authorization missing')
        with self.changed:
            while True:
                jobs = [self.state['synthesis'][config], self.state['reference_synthesis'][config],
                        self.state['functional']]
                jobs += [self.state['tests'][config + '/' + profile] for profile in dual.PROFILES]
                if any(t['status'] in ('failed', 'error') for t in jobs):
                    self.update('routes', config, status='validation_failed')
                    return
                if all(t['status'] == 'passed' for t in jobs):
                    break
                # A repeated waiting update would notify every other waiter,
                # creating a loop where route threads continuously wake peers.
                if self.state['routes'][config]['status'] != 'waiting_for_validation':
                    self.update('routes', config, status='waiting_for_validation')
                self.changed.wait(timeout=60)
        try:
            require(self.unchanged(), 'Frozen candidate changed before route')
            require(self.reference_unchanged(), 'Frozen reference changed before route')
            proof = self.state['functional']
            for path, field in (('functional_validation/VALIDATION.json', 'summary_sha256'),
                                ('supplemental_validation/SUMMARY.json', 'supplemental_summary_sha256')):
                require(sha(self.run / path) == proof[field], 'Functional summary changed before route')
            for test in [*proof['summary']['tests'], *proof['supplemental']['tests']]:
                require(test['passed'] and sha(test['log']) == test['log_sha256'],
                        'Functional log changed before route')
            for group, folder, identity in (
                ('synthesis', 'synth', self.state['source_manifest_sha256']),
                ('reference_synthesis', 'reference_synth', self.reference_manifest_sha)):
                diagnostic = self.state[group][config]
                require(diagnostic.get('source_unchanged') and diagnostic['source_manifest_sha256'] == identity,
                        'Paired diagnostic source identity differs')
                require(diagnostic['diagnostic_controller_sha256'] ==
                        sha(self.run / 'control/diagnose_timing.tcl'), 'Paired diagnostic settings differ')
                for name, wanted in diagnostic['reports_sha256'].items():
                    require(sha(self.run / folder / config / name) == wanted, 'Diagnostic report changed')
                require(sha(self.run / folder / config / 'synthesized.dcp') == diagnostic['checkpoint_sha256'],
                        'Diagnostic checkpoint changed')
            for profile in dual.PROFILES:
                test = self.state['tests'][config + '/' + profile]
                for name in ('log', 'raw_log'):
                    require(sha(test[name]) == test[name + '_sha256'], 'Sign log changed')
            cost = paired_cost(self.state['synthesis'][config], self.state['reference_synthesis'][config],
                {p: self.state['tests'][config + '/' + p] for p in dual.PROFILES},
                {p: self.reference['tests'][config + '/' + p] for p in dual.PROFILES},
                150 if u == 1 else 100, self.cost_growth_limit)
            self.update('cost_gate', config, **cost)
            if not cost['allowed']:
                self.update('routes', config, status='atp_cost_deferred', reason=cost['reason'],
                            max_cost_ratio=cost['max_cost_ratio'], route_started=False, finished_at=now())
                return
            super().route(backend, p, u)
            item = self.state['routes'][config]
            if 'result' in item:
                strict = closed(item, u)
                self.update('routes', config, status='passed' if strict else 'target_not_met', meets_target=strict)
        except Exception as error:
            self.update('routes', config, status='validation_failed', error=str(error))

    def rows(self):
        rows = []
        for backend, p, u in POINTS:
            config = dual.route_key(backend, p, u)
            physical = self.state['routes'][config]
            diagnostic = self.state['synthesis'][config]
            reference_diagnostic = self.state['reference_synthesis'][config]
            reference_route = self.reference['routes'].get(config, {})
            for profile in dual.PROFILES:
                test = self.state['tests'][config + '/' + profile]
                old = self.reference['tests'].get(config + '/' + profile, {})
                row = dict(hash_backend=backend, configuration=f'P{p}U{u}', profile=profile,
                    role='repair' if (backend, p, u) in FAILED_POINTS else 'guard',
                    cycles=test.get('cycles'), hashes=test.get('hashes'), permutations=test.get('permutations'),
                    simulation_status=test['status'], physical_status=physical['status'],
                    target_frequency_mhz=150 if u == 1 else 100, actual_closed_frequency_mhz=None,
                    target_time_ms=None, routed_time_ms=None, routed_atp_slice_ms=None,
                    diagnostic_assumed_atp=None, baseline_cycles=old.get('cycles'),
                    baseline_diagnostic_target_proxy_atp=None, diagnostic_cost_ratio=None,
                    diagnostic_cost_change_pct=None, diagnostic_proxy_is_closure=False,
                    cost_gate_status=self.state['cost_gate'][config]['status'],
                    cycles_change_pct=None, baseline_workload_equal=None,
                    baseline_routed_atp=None, routed_atp_change_pct=None)
                if test['status'] == 'passed':
                    row['target_time_ms'] = test['cycles'] / (row['target_frequency_mhz'] * 1000)
                    if diagnostic['status'] == 'passed':
                        row['diagnostic_assumed_atp'] = diagnostic['area']['equivalent_slice'] * row['target_time_ms']
                    if reference_diagnostic['status'] == 'passed' and old:
                        row['baseline_diagnostic_target_proxy_atp'] = (
                            reference_diagnostic['area']['equivalent_slice'] * old['cycles'] /
                            (row['target_frequency_mhz'] * 1000))
                        if row['diagnostic_assumed_atp'] is not None:
                            row['diagnostic_cost_ratio'] = (row['diagnostic_assumed_atp'] /
                                row['baseline_diagnostic_target_proxy_atp'])
                            row['diagnostic_cost_change_pct'] = 100 * (row['diagnostic_cost_ratio'] - 1)
                    if closed(physical, u):
                        row['actual_closed_frequency_mhz'] = 1000 / physical['result']['actual_period_ns']
                        row['routed_time_ms'] = test['cycles'] * physical['result']['actual_period_ns'] / 1e6
                        row['routed_atp_slice_ms'] = physical['routed_area']['equivalent_slice'] * row['routed_time_ms']
                    if old:
                        row['cycles_change_pct'] = 100 * (test['cycles'] / old['cycles'] - 1)
                        row['baseline_workload_equal'] = all(test.get(n) == old.get(n) for n in
                            ('hashes', 'permutations', 'vectors_sha256', 'verified_output_bytes'))
                        if closed(reference_route, u):
                            row['baseline_routed_atp'] = (reference_route['routed_area']['equivalent_slice']
                                * old['cycles'] * reference_route['result']['actual_period_ns'] / 1e6)
                            if row['routed_atp_slice_ms'] is not None:
                                row['routed_atp_change_pct'] = 100 * (row['routed_atp_slice_ms'] / row['baseline_routed_atp'] - 1)
                rows.append(row)
        dual.rank_rows(rows)
        return rows

    def _publish(self):
        self.state['updated_at'] = now()
        self.state['counts'] = {group: {status: sum(t['status'] == status for t in self.state[group].values())
            for status in sorted({t['status'] for t in self.state[group].values()})}
            for group in ('routes', 'tests', 'synthesis', 'reference_synthesis', 'cost_gate')}
        self.state['results'] = self.rows()
        for base in (self.run, self.out):
            write(base / 'status.json', self.state)
        write(self.out / 'VALIDATION_SUMMARY.json', dict(complete=self.state['complete'],
            source_manifest_sha256=self.state['source_manifest_sha256'],
            sign_counts=self.state['counts']['tests'], functional=self.state['functional'],
            tests={k: {n: v for n, v in t.items() if n != 'command'} for k, t in self.state['tests'].items()},
            h20_full_keygen_sign_run=False))
        target = self.out / 'reports' / ('Timing_M_' + self.meta['run_id'])
        write(target.with_suffix('.json'), dict(source=self.meta, results=self.state,
            reference=self.reference, diagnostic_is_not_fmax=True))
        fmt = lambda value: '—' if value is None else f'{value:,.3f}'
        pending = [(source['run'], key) for source in self.reference.get('sources', [])
                   for key in source.get('pending_route_keys', [])]
        repaired = '；'.join(backend.upper() + '待修复' + '、'.join(
            f'P{p}U{u}' for b, p, u in FAILED_POINTS if b == backend)
            for backend in dual.BACKENDS if any(b == backend for b, _, _ in FAILED_POINTS))
        lines = ['# M：未闭合参数频率修复与ATP对照', '',
            f'更新时间：{self.state["updated_at"]}；状态：' + ('任务全部结束。' if self.state['complete'] else '后台运行。'), '',
            f'任务计数：`{self.state["counts"]}`。', '',
            f'同一冻结源码，{len(POINTS)}个明确配置：{len(FAILED_POINTS)}个待修复点及'
            f'{len(GUARD_POINTS)}个已闭合守护点；候选及基线各{len(POINTS)}次100MHz common配对诊断、'
            f'{len(POINTS) * len(dual.PROFILES)}项完整Sign、{len(BASE_FUNCTIONAL_NAMES)}组功能验证及'
            f'{len(SUPPLEMENTAL_CASES)}组补充验证。每点候选及基线诊断与三个Sign、'
            f'全局{FUNCTIONAL_GROUPS}组功能验证全部通过后，再检查面积×周期筛选条件，'
            '通过才独立启动明确授权的指定频率布线。', '',
            f'布线前筛选：同设置100MHz综合面积×各算法实测周期的最大增长不超过'
            f'{100*self.cost_growth_limit:g}%。这是节省实验资源的筛选阈值，非用户硬性验收约束。'
            '超出标记`atp_cost_deferred`，记录比值和原因，不启动该点布线；不终止其他在途任务。', '',
            repaired + '。其余为守护配置。'
            f'基线证据快照时尚有{len(pending)}个未完成布线，不等待、不停止，也不借用其他点结果。'
            '快照中的未完成配置：' + ('、'.join(key for _, key in pending) or '无') + '。', '',
            '补充验证覆盖两个修复点，以及SHAKE P4/P8、SHA2 P8守护点的正常与SYNTHESIS配方和'
            '四标签batch；完整Sign另行检查各点实际整核调度。SHA2 P6U2的两轮算术和其余未闭合点'
            '本轮不改动，也不将本轮子集结果当作它们的频率验收。', '',
            'U1=150MHz，U2=100MHz；器件xc7a200tffg1156-3、common OOC、默认时序驱动、'
            '全局最多12个Vivado、每个2线程。100MHz仅作诊断；最终严格核对实际周期、setup/hold、'
            '完整路由、DRC和同源证明，不降频，不新增时序例外。', '',
            '等效Slice=LUT/4+FF/8+232.4×BRAM36+102.4×DSP。common不含外部ROM与可选签名缓存。'
            '面积、实测Sign周期和ATP均取同后端同配置；未闭合基线实际ATP留空。', '',
            '候选及基线“目标频率代理ATP”均用100MHz配对综合面积与实测周期，按目标150/100MHz换算。'
            '该代理值用于筛选和成本归因，对未闭合基线也显示，不能证明频率闭合；'
            '实际布线ATP仍只在同源setup/hold、完整路由和DRC全部通过时填写。', '',
            '后台报告/归档每60秒最多一次，初始及最终立即发布，全部结束后退出刷新。'
            '单点综合600秒后仅标记analysis_deferred，不终止进程。', '',
            '## common面积与布线STA', '']
        for backend in dual.BACKENDS:
            lines += [f'### {backend.upper()}', '',
                '| P/U | 作用 | MHz | 基线100MHz Slice | 候选100MHz Slice | 最大成本比 | 综合LUT | 综合FF | 综合BRAM36 | 综合Slice | 布线LUT | 布线FF | 布线BRAM36 | 布线Slice | WNS ns | WHS ns | 状态 |',
                '|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|']
            for b, p, u in POINTS:
                if b != backend:
                    continue
                config = dual.route_key(b, p, u)
                task, diag = self.state['routes'][config], self.state['synthesis'][config]
                a, area, result = task.get('synth_area', {}), task.get('routed_area', {}), task.get('result', {})
                label = task['status'] + ('；analysis_deferred' if task.get('analysis_deferred') else '')
                lines.append('| ' + ' | '.join([f'P{p}U{u}', '修复' if (b, p, u) in FAILED_POINTS else '守护',
                    str(150 if u == 1 else 100),
                    fmt(self.state['reference_synthesis'][config].get('area', {}).get('equivalent_slice')),
                    fmt(diag.get('area', {}).get('equivalent_slice')),
                    fmt(self.state['cost_gate'][config].get('max_cost_ratio')),
                    *[fmt(a.get(n)) for n in ('lut', 'ff', 'bram36', 'equivalent_slice')],
                    *[fmt(area.get(n)) for n in ('lut', 'ff', 'bram36', 'equivalent_slice')],
                    fmt(result.get('wns_ns')), fmt(result.get('whs_ns')), label]) + ' |')
            lines.append('')
        titles = dict(slh_128f='SLH-DSA 128f Sign', xmss_h10='XMSS h10 Sign', lms_h10='LMS h10 Sign')
        for profile in dual.PROFILES:
            lines += [f'## {titles[profile]}', '',
                '| 后端 | ATP排名 | P/U | Sign周期 | Hash | 置换/压缩 | 目标时间ms | 基线代理ATP | 候选代理ATP | 代理成本变化% | 闭合MHz | 布线时间ms | 布线ATP Slice·ms | 基线周期 | 周期变化% | 同工作量 | 基线实际ATP | ATP变化% | 仿真/物理 |',
                '|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---:|---:|---|']
            for row in sorted((r for r in self.state['results'] if r['profile'] == profile),
                key=lambda r: (dual.BACKENDS.index(r['hash_backend']), r['rank'] is None, r['rank'] or 100)):
                lines.append('| ' + ' | '.join([row['hash_backend'], fmt(row['rank']), row['configuration'],
                    *[fmt(row[n]) for n in ('cycles', 'hashes', 'permutations', 'target_time_ms',
                        'baseline_diagnostic_target_proxy_atp', 'diagnostic_assumed_atp',
                        'diagnostic_cost_change_pct',
                        'actual_closed_frequency_mhz', 'routed_time_ms', 'routed_atp_slice_ms',
                        'baseline_cycles', 'cycles_change_pct')], str(row['baseline_workload_equal']),
                    fmt(row['baseline_routed_atp']), fmt(row['routed_atp_change_pct']),
                    row['simulation_status'] + '/' + row['physical_status']]) + ' |')
            lines.append('')
        lines += ['## 100MHz关键路径诊断', '',
            '| 配置 | 数据路径ns | 逻辑级数 | 起点 | 终点 | 状态 |',
            '|---|---:|---:|---|---|---|']
        for group, label in (('reference_synthesis', '基线'), ('synthesis', '候选')):
            for config, job in self.state[group].items():
                path = job.get('timing', {})
                lines.append('| ' + ' | '.join([label + '/' + config,
                    fmt(path.get('data_path_ns')), fmt(path.get('logic_levels')),
                    str(path.get('source', '—')), str(path.get('destination', '—')),
                    job['status'] + ('；analysis_deferred' if job.get('analysis_deferred') else '')]) + ' |')
        functional = self.state['functional']
        lines += ['', f'全局功能门禁：{functional["status"]}；'
            f'{functional.get("summary", {}).get("passed", 0)}/{len(BASE_FUNCTIONAL_NAMES)} + '
            f'{functional.get("supplemental", {}).get("passed", 0)}/{len(SUPPLEMENTAL_CASES)}。', '']
        for group in ('synthesis', 'reference_synthesis', 'tests', 'routes', 'cost_gate'):
            for key, item in self.state[group].items():
                if item.get('error'):
                    lines += [f'错误 `{group}/{key}`：{item["error"]}', '']
                if item.get('status') == 'atp_cost_deferred' and group == 'cost_gate':
                    lines += [f'延后布线 `{key}`：最大成本比{item["max_cost_ratio"]:.9f}，'
                              f'允许上界{1+self.cost_growth_limit:.9f}；{item["reason"]}。', '']
        if functional.get('error'):
            lines += [f'功能验证错误：{functional["error"]}', '']
        lines += [f'运行目录：`{self.run}`；冻结SOURCE：`{self.state["source_manifest_sha256"]}`。', '',
            f'基线SOURCE：`{self.reference_manifest_sha}`；基线冻结源码只读；'
            '本次基线配对诊断输出在`reference_synth/`，不写入旧实验。', '',
            '冻结RTL与support压缩包、SOURCE及control校验、分层/时序和完整Vivado日志随实验归档。'
            '仿真/validation明细仅留运行目录，摘要归档；DCP留运行目录。'
            '缺项在ARTIFACTS.json明确列出，历史源码不替换。共同核结果不代表板级或顶层I/O时序。', '']
        dual.archive.atomic(target.with_suffix('.md'), '\n'.join(lines))
        for folder in ('jobs', 'synth', 'reference_synth'):
            for path in (self.run / folder).rglob('*') if (self.run / folder).exists() else []:
                if path.is_file() and path.suffix in ('.rpt', '.log', '.json', '.txt', '.xdc'):
                    identity = (path.stat().st_mtime_ns, path.stat().st_size)
                    if self.copied.get(path) != identity:
                        dual.archive.copy_changed(path, self.out / path.relative_to(self.run))
                        self.copied[path] = identity
        for source, destination in (
            (self.run / 'runner.log', self.out / 'runner.log'),
            (self.run / 'functional_validation/VALIDATION.json', self.out / 'supplementary_evidence/functional/SUMMARY.json'),
            (self.run / 'supplemental_validation/SUMMARY.json', self.out / 'supplementary_evidence/supplemental/SUMMARY.json')):
            if source.is_file():
                dual.archive.copy_changed(source, destination)
        required = ('synth/hierarchical.rpt', 'synth/timing.rpt', 'route/hierarchical.rpt',
            'route/timing.rpt', 'route/route_status.rpt', 'route/drc.rpt', 'result.json')
        inventory = dict(complete=self.state['complete'], omitted_details=['sim', 'validation'],
            missing={c: [n for n in required if not (self.out / 'jobs' / c / n).is_file()] for c in CONFIGS},
            missing_diagnostic_reports={c: [n for n in ('hierarchical.rpt', 'timing.rpt')
                if not (self.out / 'synth' / c / n).is_file()] for c in CONFIGS},
            missing_reference_diagnostic_reports={c: [n for n in ('hierarchical.rpt', 'timing.rpt')
                if not (self.out / 'reference_synth' / c / n).is_file()] for c in CONFIGS})
        for path in self.out.rglob('*'):
            if path.is_file() and path.name != 'ARTIFACTS.json' and not path.name.endswith('.tmp'):
                identity = (path.stat().st_mtime_ns, path.stat().st_size)
                if self.checksums.get(path, (None,))[0] != identity:
                    self.checksums[path] = (identity, sha(path))
        inventory['sha256'] = {str(p.relative_to(self.out)): v[1] for p, v in self.checksums.items()}
        write(self.out / 'ARTIFACTS.json', inventory)

    def execute(self):
        self.publish(force=True)
        dual.archive.index()
        write(self.run / 'INITIAL_PUBLICATION.json', dict(pid=os.getpid(), at=now()))
        finished = threading.Event()

        def refresh():
            while not finished.wait(60):
                self.publish()

        monitor = threading.Thread(target=refresh, name='report-60s', daemon=True)
        monitor.start()
        try:
            with ThreadPoolExecutor(max_workers=8) as diagnostics, ThreadPoolExecutor(max_workers=4) as simulations, \
                    ThreadPoolExecutor(max_workers=8) as routes, ThreadPoolExecutor(max_workers=1) as validation:
                jobs = [validation.submit(self.validate)]
                for backend, p, u in POINTS:
                    jobs += [diagnostics.submit(self.synthesize, backend, p, u),
                             diagnostics.submit(self.synthesize, backend, p, u, True),
                             simulations.submit(self.simulate, backend, p, u),
                             routes.submit(self.route, backend, p, u)]
                for future in as_completed(jobs):
                    future.result()
            with self.lock:
                self.state.update(complete=True, finished_at=now(), source_unchanged=self.unchanged(),
                                  reference_source_unchanged=self.reference_unchanged())
                self.publish(force=True)
            dual.archive.index()
            return int(not self.state['source_unchanged'] or not self.state['reference_source_unchanged']
                or self.state['functional']['status'] != 'passed'
                or any(t['status'] != 'passed' for group in ('synthesis', 'reference_synthesis', 'tests', 'routes')
                       for t in self.state[group].values()))
        finally:
            finished.set()
            monitor.join(timeout=5)


def launch(label, cost_growth_limit=.01):
    require(math.isfinite(cost_growth_limit) and cost_growth_limit >= 0,
            'Cost growth limit must be finite and nonnegative')
    tools = {n: shutil.which(os.environ.get(n.upper(), n)) for n in ('vivado', 'verilator')}
    require(all(tools.values()), 'Vivado and Verilator are required')
    reference = reference_evidence()
    stamp = datetime.now(ZoneInfo('Asia/Singapore')).strftime('%Y%m%d_%H%M%S')
    run = ROOT / 'build/timing_m' / stamp
    out = dual.archive.ARCHIVES / ('timing_m_' + stamp)
    require(not run.exists() and not out.exists(), 'Run already exists')
    checks = dual.frozen_snapshot(ROOT, run / 'source')
    meta = dict(schema='mhbs.p1sha_atp.source.v1', experiment_family='timing_m',
        kind='candidate', label=label, run_id=stamp, started_at=now(), source_root=str(run / 'source'),
        archive_directory=str(out), sha256=checks, **tools,
        rtl_files=[n for n in (ROOT / 'sources.txt').read_text().splitlines() if n.strip()],
        tool_versions={n: subprocess.check_output([p, '-version' if n == 'vivado' else '--version'],
                       text=True, timeout=30).strip() for n, p in tools.items()},
        base_commit=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
        configs=CONFIGS, points=POINTS, failed_points=FAILED_POINTS, guard_points=GUARD_POINTS,
        supplemental_points=SUPPLEMENTAL_POINTS,
        backends=dual.BACKENDS, profiles=dual.PROFILES, top='common', operation='sign',
        diagnostic_common=len(POINTS), complete_sign=len(POINTS) * len(dual.PROFILES),
        reference_diagnostic_common=len(POINTS), total_diagnostic_common=2*len(POINTS),
        cost_growth_limit_fraction=cost_growth_limit, cost_limit_is_user_hard_constraint=False,
        baseline_diagnostic_source_manifest_sha256=BASELINES[0][1],
        base_functional_groups=len(BASE_FUNCTIONAL_NAMES), supplemental_groups=len(SUPPLEMENTAL_CASES),
        functional_groups=FUNCTIONAL_GROUPS, fixed_target_routes=len(POINTS),
        part='xc7a200tffg1156-3', vivado_workers=12, threads_per_vivado=2, simulation_workers=4,
        synthesis_period_ns=10.0, targets_mhz={'1': 150, '2': 100}, report_refresh_seconds=60,
        analysis_defer_seconds=600, explicit_user_authorization=True,
        frequency_search=False, automatic_frequency_fallback=False,
        new_timing_exceptions=False, h20_full_keygen_sign_run=False)
    for base in (run, out):
        write(base / 'SOURCE.json', meta)
        write(base / 'REFERENCE_EVIDENCE.json', reference)
        dual.archive.copy_changed(ROOT / BASELINES[0][0] / 'SOURCE.json', base / 'REFERENCE_SOURCE.json')
        for name in CONTROLS:
            dual.archive.copy_changed(run / 'source/scripts' / name, base / 'control' / name)
        write(base / 'CONTROL_SOURCE.json', {name: sha(base / 'control' / name) for name in CONTROLS})
    dual.archive.pack_rtl(run / 'source', out / 'rtl.tar.gz', checks)
    reference_meta = read(run / 'REFERENCE_SOURCE.json')
    require(sha(run / 'REFERENCE_SOURCE.json') == BASELINES[0][1], 'Copied reference SOURCE differs')
    dual.archive.pack_rtl(Path(reference_meta['source_root']), out / 'reference_rtl.tar.gz',
                          reference_meta['sha256'])
    support = {n: h for n, h in checks.items() if not n.startswith('rtl/') and n != 'sources.txt'}
    with tarfile.open(out / 'support.tar.gz', 'w:gz') as tar:
        for name, wanted in support.items():
            require(sha(run / 'source' / name) == wanted, 'Frozen support changed')
            tar.add(run / 'source' / name, arcname=name, recursive=False)
    write(out / 'SUPPORT_SOURCE.json', support)
    with (run / 'runner.log').open('w') as stream:
        process = subprocess.Popen([sys.executable, str(run / 'control/run_timing_m.py'),
            '--run-root', str(run)], cwd=ROOT,
            env=dict(os.environ, MHBS_M_WORKSPACE=str(ROOT), MHBS_DUAL_MATRIX_WORKSPACE=str(ROOT)),
            stdin=subprocess.DEVNULL, stdout=stream, stderr=subprocess.STDOUT, start_new_session=True)
    deadline = time.monotonic() + 30
    while not (run / 'INITIAL_PUBLICATION.json').exists():
        require(process.poll() is None and time.monotonic() < deadline, 'Initial publication failed: ' + str(run / 'runner.log'))
        time.sleep(.1)
    result = dict(pid=process.pid, run_root=str(run), source_manifest_sha256=sha(run / 'SOURCE.json'),
        report=str(out / 'reports' / ('Timing_M_' + stamp + '.md')),
        diagnostic_common=len(POINTS), complete_sign=len(POINTS) * len(dual.PROFILES),
        reference_diagnostic_common=len(POINTS), total_diagnostic_common=2*len(POINTS),
        cost_growth_limit_fraction=cost_growth_limit,
        functional_groups=FUNCTIONAL_GROUPS, fixed_target_routes=len(POINTS),
        report_refresh_seconds=60, max_total_vivado=12, threads_per_vivado=2)
    write(run / 'LAUNCH.json', result)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--launch', action='store_true')
    mode.add_argument('--run-root', type=Path)
    parser.add_argument('--label', default='M1')
    parser.add_argument('--cost-growth-limit', type=float, default=.01,
                        help='Allowed diagnostic area×cycles growth fraction before routing (default 0.01; planning policy)')
    args = parser.parse_args()
    if args.launch:
        import json
        print(json.dumps(launch(args.label, args.cost_growth_limit), ensure_ascii=False, indent=2))
    else:
        raise SystemExit(Runner(args.run_root).execute())
