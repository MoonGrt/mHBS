#!/usr/bin/env python3
"""Check 64-bit statistics carry and real fixed-hash completion through recipe."""
import argparse
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--hash', dest='hash_backend', choices=('shake', 'sha2'), default='shake')
    parser.add_argument('--synthesis', action='store_true',
                        help='Verify functional completion with diagnostic ports removed')
    parser.add_argument('--pipeline', type=int, default=1)
    parser.add_argument('--unroll', type=int, default=1)
    args = parser.parse_args()
    if args.pipeline < 1 or args.unroll < 1 or 24 % (args.pipeline * args.unroll):
        parser.error('P*U must be a positive divisor of 24')
    work = ROOT / ('build/statistics_check_synthesis' if args.synthesis else 'build/statistics_check') / f'P{args.pipeline}U{args.unroll}'
    if args.hash_backend == 'sha2': work = work.parent / (work.name + '_sha2')
    work.mkdir(parents=True, exist_ok=True)
    command = [os.environ.get('VERILATOR', 'verilator'), '--binary', '--timing', '-O3',
               '-j', '2', '-Wno-fatal', '--top-module', 'tb_statistics', '--Mdir', str(work/'obj'),
               f'-GPIPELINE={args.pipeline}', f'-GUNROLL={args.unroll}',
               'rtl/hash/keccak.sv', 'rtl/hash/shake-recipe.sv', 'rtl/hash/sha256.sv', 'rtl/hash/sha2-recipe.sv', 'tb/tb_statistics.sv']
    if args.hash_backend == 'sha2': command.append('-DMHBS_SHA2')
    if args.synthesis:
        command.append('-DSYNTHESIS')
    with (work/'compile.log').open('w') as log:
        subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True)
    result = subprocess.run([str(work/'obj/Vtb_statistics')], cwd=ROOT, text=True,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    (work/'run.log').write_text(result.stdout)
    print(result.stdout, end='')
    result.check_returncode()
    if 'STATISTICS_PASS' not in result.stdout:
        raise RuntimeError('Statistics check did not report success')


if __name__ == '__main__':
    main()
