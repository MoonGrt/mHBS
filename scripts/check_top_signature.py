#!/usr/bin/env python3
"""Run complete SLH-128f Sign through top in four signature/debug macro views."""
import argparse
import os
from pathlib import Path
import subprocess

from ablation_paths import ROOT, DESIGN, source_files, headers, bench, build_dir, rtl, prepare_vector


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--hash', dest='hash_backend', choices=('shake', 'sha2'), default='shake')
    parser.add_argument('--synthesis', choices=('0', '1', 'both'), default='both')
    parser.add_argument('--signature', choices=('0', '1', 'both'), default='both')
    args = parser.parse_args()
    sources = source_files()
    values = lambda value: (0, 1) if value == 'both' else (int(value),)
    for synthesis in values(args.synthesis):
        for signature in values(args.signature):
            work = build_dir(f'top_signature_check/synthesis{synthesis}_signature{signature}')
            if args.hash_backend == 'sha2': work = work.parent / (work.name + '_sha2')
            work.mkdir(parents=True, exist_ok=True)
            defines = (['-DSYNTHESIS'] if synthesis else []) + (['-DMHBS_SIGNATURE_STORE'] if signature else [])
            if args.hash_backend == 'sha2': defines.append('-DMHBS_SHA2')
            command = [os.environ.get('VERILATOR', 'verilator'), '--binary', '--timing', '-O3',
                       '-j', '2', '-Wno-fatal', '--top-module', 'tb_top_signature',
                       '--Mdir', str(work / 'obj'), *defines, *sources, bench('tb_top_signature.sv')]
            with (work / 'compile.log').open('w') as log:
                subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True)
            result = subprocess.run([str(work / 'obj/Vtb_top_signature'), f'+VECTOR={prepare_vector("slh_128f", "sign", args.hash_backend)}'], cwd=ROOT, text=True,
                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            (work / 'run.log').write_text(result.stdout)
            print(f'SYNTHESIS={synthesis} MHBS_SIGNATURE_STORE={signature} {result.stdout}', end='')
            result.check_returncode()


if __name__ == '__main__':
    main()
