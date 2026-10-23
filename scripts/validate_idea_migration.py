#!/usr/bin/env python3
"""Run byte/count/cycle validation against one frozen ablation source tree."""
import argparse
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from zoneinfo import ZoneInfo


PROFILES = {
    'shake': ('slh_128f', 'slh_128s', 'slh_192f', 'slh_192s',
              'slh_256f', 'slh_256s', 'xmss_h10', 'xmss_h16', 'xmss_h20',
              'lms_h10', 'lms_h15', 'lms_h20'),
    'sha2': ('slh_128f', 'slh_128s', 'xmss_h10', 'xmss_h16', 'xmss_h20',
             'lms_h10', 'lms_h15', 'lms_h20'),
}
FOCUS = ('slh_128f', 'xmss_h10', 'lms_h10', 'slh_128s')
OPERATIONS = {'keygen': 0, 'sign': 1, 'verify': 2}


def now():
    return datetime.now(ZoneInfo('Asia/Singapore')).isoformat(timespec='seconds')


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f'.{os.getpid()}.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    temporary.replace(path)


def selected_bench(source, design, name):
    path = source / 'tb' / design / name
    return path if path.is_file() else source / 'tb' / name


def source_identity(source, design):
    manifest = source / 'rtl' / design / 'sources.txt'
    paths = {manifest}
    for line in manifest.read_text().splitlines():
        name = line.strip()
        if name and not name.startswith('#'):
            paths.add(source / name)
    paths.update((source / 'rtl' / design).rglob('*.svh'))
    paths.update(selected_bench(source, design, name)
                 for name in ('tb_fast.sv', 'fast_main.cpp', 'tb_recipe.sv'))
    paths.update(source / 'scripts' / name for name in
                 ('simulate_fast.sh', 'ablation_paths.py', 'check_recipes.py'))
    paths.update((source / 'model').rglob('*.py'))
    for tree in (source / 'image' / design, source / 'tb' / 'vectors' / design):
        paths.update(tree.rglob('*.mem'))
    return {str(path.relative_to(source)): digest(path) for path in sorted(paths)}


def cache_checks(source, design):
    path = selected_bench(source, design, 'fast_main.cpp')
    text = path.read_text()
    marker = text.find('STATEFUL_PASS')
    messages = ('Output byte mismatch', 'Signature metadata mismatch',
                'Signature cache byte mismatch', 'Signature cache length mismatch')
    checks = {message: 0 <= text.find(message) < marker for message in messages}
    if not all(checks.values()):
        raise ValueError(f'Fast driver does not establish byte/cache checks before PASS: {path}')
    return dict(path=str(path), sha256=digest(path), checks=checks,
                scope='STATEFUL_PASS is emitted after output checking and, for Sign, complete signature-cache checking.')


def parse_fast(text, operation):
    matches = re.findall(r'^STATEFUL_PASS P(\d+)U(\d+)\s+([^\n]+)', text, re.M)
    if len(matches) != 1:
        raise ValueError('Expected exactly one complete STATEFUL_PASS marker')
    p, u, tail = matches[0]
    fields = dict(re.findall(r'(\w+)=([^\s]+)', tail))
    required = ('op', 'cycles', 'total', 'hashes', 'permutations', 'tamper')
    numbers = {name: int(fields[name]) for name in required}
    if (p, u) != ('1', '1') or numbers['op'] != OPERATIONS[operation] or numbers['tamper'] != 0:
        raise ValueError(f'Unexpected configuration, operation or tamper result: {matches[0]}')
    if any(numbers[name] < 0 for name in ('cycles', 'total', 'hashes', 'permutations')):
        raise ValueError('Negative cycle/work counter')
    result = dict(cycles=numbers['cycles'], total_cycles=numbers['total'],
                  hashes=numbers['hashes'], permutations=numbers['permutations'],
                  physical_blocks=numbers['permutations'], pass_marker='STATEFUL_PASS',
                  output_bytes_checked=True,
                  signature_cache_checked=operation == 'sign',
                  signature_cache_and_output_validated=operation == 'sign',
                  verify_pass_and_node_consumption_checked=operation == 'verify')
    if 'logical_permutations' in fields:
        result['logical_permutations'] = int(fields['logical_permutations'])
    macro = re.search(r'^MACRO_METRICS (\{[^\n]+\})', text, re.M)
    if macro:
        result['macro_metrics'] = json.loads(macro.group(1))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--design', choices=('i', 'c', 't'), required=True)
    parser.add_argument('--backend', choices=('shake', 'sha2'), required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    source, output = args.source.resolve(), args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(ZoneInfo('Asia/Singapore')).strftime('%Y%m%d_%H%M%S_%f')
    logs = source / 'build' / 'idea_migration_validation' / args.design / args.backend / stamp
    logs.mkdir(parents=True, exist_ok=False)
    cases = [(profile, 'verify') for profile in PROFILES[args.backend]]
    cases += [(profile, op) for profile in FOCUS for op in ('keygen', 'sign')]
    tests = ['recipes_full']
    if args.backend == 'shake':
        tests += ['recipes_mask_0100', 'recipes_mask_101e']
    tests += ['synthesis_slh_128f_sign']
    env = os.environ.copy()
    for name in ('ALLOW_FULL_STATEFUL_TREE', 'PROFILE_ENABLE', 'VECTORS_DIR', 'SIM_COMPILE_ONLY'):
        env.pop(name, None)
    env.update(MHBS_DESIGN=args.design, HASH_BACKEND=args.backend, SIM_SYNTHESIS='0')
    env.setdefault('SIM_FAST_OPT_SLOW', '-O1')
    env.setdefault('SIM_HASH_TRACE', '0')
    relevant_env = ('MHBS_DESIGN', 'HASH_BACKEND', 'SIM_SYNTHESIS',
                    'SIM_FAST_OPT_SLOW', 'SIM_HASH_TRACE')
    summary = dict(schema='mhbs.idea_migration.validation.v1', source=str(source),
                   design=args.design, backend=args.backend, configuration='P1U1',
                   started_at=now(), updated_at=now(), complete=False, passed=False,
                   expected_cases=len(cases), expected_tests=len(tests),
                   cases={f'{profile}/{op}': dict(status='pending') for profile, op in cases},
                   tests={name: dict(status='pending') for name in tests},
                   runtime_log_directory=str(logs), validator_sha256=digest(__file__),
                   environment={key: env[key] for key in relevant_env},
                   high_tree_keygen_sign_requested=False,
                   hardware_synthesis_or_route_started=False,
                   scope='Real complete operations and recipe tests; no extrapolated cycles. SYNTHESIS view is Verilator simulation.')

    def save():
        summary['updated_at'] = now()
        summary['case_counts'] = {status: sum(row['status'] == status for row in summary['cases'].values())
                                  for status in ('pending', 'running', 'passed', 'failed')}
        summary['test_counts'] = {status: sum(row['status'] == status for row in summary['tests'].values())
                                  for status in ('pending', 'running', 'passed', 'failed')}
        write_json(output / 'SUMMARY.json', summary)

    def execute(group, name, command, parse, overrides=None):
        current_env = dict(env, **(overrides or {}))
        log = logs / (name.replace('/', '_') + '.log')
        row = dict(status='running', started_at=now(), command=command,
                   cwd=str(source), log=str(log), source_id=summary['source_id'],
                   environment={key: current_env[key] for key in relevant_env})
        summary[group][name] = row
        save()
        started = time.monotonic()
        try:
            with log.open('w') as stream:
                result = subprocess.run(command, cwd=source, env=current_env,
                                        stdin=subprocess.DEVNULL, stdout=stream,
                                        stderr=subprocess.STDOUT)
            row['returncode'] = result.returncode
            row['log_sha256'] = digest(log)
            if result.returncode:
                raise RuntimeError(f'Command exited {result.returncode}; see {log}')
            row.update(parse(log.read_text()))
            row['status'] = 'passed'
        except Exception as error:
            row.update(status='failed', error=str(error))
        finally:
            row.update(finished_at=now(), seconds=time.monotonic() - started)
            save()
        print(f'{args.design}/{args.backend} {name}: {row["status"]}', flush=True)

    save()
    try:
        identity = source_identity(source, args.design)
        summary['source_sha256'] = identity
        summary['source_id'] = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
        summary['fast_driver_validation_contract'] = cache_checks(source, args.design)
        save()
        for profile, operation in cases:
            # Only Verify is listed for h15/h16/h20; never opt into full high trees.
            command = ['bash', str(source / 'scripts/simulate_fast.sh'), profile, operation, '1', '1']
            execute('cases', f'{profile}/{operation}', command,
                    lambda text, op=operation: parse_fast(text, op))

        masks = [('recipes_full', 0xffff)]
        if args.backend == 'shake':
            masks += [('recipes_mask_0100', 0x0100), ('recipes_mask_101e', 0x101e)]
        for name, mask in masks:
            command = [sys.executable, str(source / 'scripts/check_recipes.py'),
                       '--hash', args.backend, '--pipeline', '1', '--unroll', '1',
                       '--recipe-mask', hex(mask)]

            def parse_recipe(text, expected_mask=mask):
                marker = re.search(r'RECIPE_PASS cases=(\d+) mask=([0-9a-fA-F]+)', text)
                if not marker or int(marker[1]) <= 0 or int(marker[2], 16) != expected_mask:
                    raise ValueError('Missing or mismatched RECIPE_PASS marker')
                suffix = '' if expected_mask == 0xffff else f'_mask{expected_mask:04x}'
                if args.backend == 'sha2':
                    suffix += '_sha2'
                coverage = source / 'build' / 'ablation' / args.design / 'recipe_check' / ('P1U1' + suffix) / 'coverage.json'
                record = dict(pass_marker='RECIPE_PASS', cases=int(marker[1]),
                              recipe_mask=f'0x{expected_mask:04x}')
                if coverage.is_file():
                    value = json.loads(coverage.read_text())
                    if not value.get('passed') or value.get('cases') != int(marker[1]):
                        raise ValueError('Recipe coverage summary disagrees with PASS')
                    record.update(coverage=str(coverage), coverage_sha256=digest(coverage),
                                  coverage_summary=value)
                return record

            execute('tests', name, command, parse_recipe)
        execute('tests', 'synthesis_slh_128f_sign',
                ['bash', str(source / 'scripts/simulate_fast.sh'), 'slh_128f', 'sign', '1', '1'],
                lambda text: parse_fast(text, 'sign'), {'SIM_SYNTHESIS': '1'})
        summary['source_unchanged'] = all((source / name).is_file() and digest(source / name) == value
                                          for name, value in identity.items())
        summary['passed'] = (summary['source_unchanged'] and
                             all(row['status'] == 'passed' for row in summary['cases'].values()) and
                             all(row['status'] == 'passed' for row in summary['tests'].values()))
    except KeyboardInterrupt:
        summary.update(error='Interrupted', interrupted=True)
    except Exception as error:
        summary['error'] = str(error)
    finally:
        summary.update(complete=True, finished_at=now())
        save()
    return 0 if summary['passed'] else 130 if summary.get('interrupted') else 1


if __name__ == '__main__':
    raise SystemExit(main())
