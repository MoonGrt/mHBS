#!/usr/bin/env python3
"""Elaborate frozen V2 source with archived executor variants; no simulation."""
import argparse
import hashlib
import json
import subprocess
from pathlib import Path


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, required=True)
    parser.add_argument('--log-dir', type=Path, required=True,
                        help='Use build/ outside experiment archive for detailed logs')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    source = args.source_root.resolve()
    here = Path(__file__).resolve().parent
    names = ['rtl/hash/keccak.sv', 'rtl/hash/shake-recipe.sv', 'rtl/hash/sha256.sv',
             'rtl/hash/sha2-recipe.sv', 'rtl/memory/value.sv', 'rtl/memory/signature.sv',
             'rtl/executor/sequencer.sv', 'rtl/executor/executor.sv',
             'rtl/top/top.sv', 'rtl/top/common.sv']
    before = {name: sha(source / name) for name in names}
    version = subprocess.check_output(['verilator', '--version'], text=True).strip()
    args.log_dir.mkdir(parents=True, exist_ok=True)
    cases = [('combined', p, backend, synthesis) for p in (1, 4, 12)
             for backend in ('shake', 'sha2') for synthesis in (False, True)]
    cases += [(variant, 12, 'shake', False) for variant in ('parent_path', 'allocator')]
    results = []
    for variant, p, backend, synthesis in cases:
        executor = here / 'variants' / f'{variant}_executor.sv'
        files = [str(executor if name == 'rtl/executor/executor.sv' else source / name) for name in names]
        command = ['verilator', '--lint-only', '--timing', '-Wno-fatal', '--top-module', 'common',
                   f'-GPIPELINE={p}', '-GUNROLL=1']
        if backend == 'sha2':
            command.append('-DMHBS_SHA2')
        if synthesis:
            command.append('-DSYNTHESIS')
        command += files
        proc = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        name = f'{variant}_{backend}_P{p}U1' + ('_synthesis' if synthesis else '')
        log = args.log_dir / f'{name}.log'
        log.write_text(proc.stdout)
        item = dict(name=name, command=command, executor_sha256=sha(executor), exit_code=proc.returncode,
                    errors=proc.stdout.count('%Error'),
                    combinational_loop_warnings=proc.stdout.count('%Warning-UNOPTFLAT'),
                    latch_warnings=proc.stdout.count('%Warning-LATCH'),
                    multiple_driver_warnings=proc.stdout.count('%Warning-MULTIDRIVEN'),
                    raw_log=str(log.resolve()), raw_log_sha256=sha(log))
        item['pass'] = all(item[k] == 0 for k in ('exit_code', 'errors', 'combinational_loop_warnings',
                                                'latch_warnings', 'multiple_driver_warnings'))
        results.append(item)
    after = {name: sha(source / name) for name in names}
    summary = dict(scope='Verilator lint/elaboration only; no cycles or algorithm outputs measured',
                   source_root=str(source), source_sha256=before, source_unchanged=before == after,
                   tool_version=version, results=results)
    summary['pass'] = before == after and all(item['pass'] for item in results)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(summary, indent=2) + '\n')
    print(json.dumps(dict(result='PASS' if summary['pass'] else 'FAIL', cases=len(results))))
    if not summary['pass']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
