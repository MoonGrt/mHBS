#!/usr/bin/env python3
"""Prove generated images retire message data before shared digest writes.

The RTL additionally rejects a later message recipe with atomic error 0x300b.
Use --rtl to replay a deliberately reordered, otherwise byte-identical image.
"""
from dataclasses import replace
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from model.executor import compile_image, validate
from model.mHBS import compile_image as compile_external

NAMES = ('slh_128f', 'slh_192f', 'slh_256f', 'slh_128s', 'slh_192s', 'slh_256s',
         'xmss_h10', 'xmss_h16', 'xmss_h20', 'lms_h10', 'lms_h15', 'lms_h20')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rtl', action='store_true')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    result = {'message_bytes': 87, 'fors_region_bits': [0, 319],
              'digits_region_bits': [320, 575], 'generated_images': [], 'negative_model': [], 'negative_rtl': []}
    for backend in ('shake', 'sha2'):
        names = NAMES if backend == 'shake' else tuple(n for n in NAMES if n not in ('slh_192f', 'slh_192s', 'slh_256f', 'slh_256s'))
        for name in names:
            logical = compile_image(name, hash_backend=backend)
            validate(logical)
            image = compile_external(name, hash_backend=backend)
            # The lifetime check is a constraint on use, not a ROM rewrite.
            image.decode()
            vector = ROOT / 'tb/vectors' / (Path('sha2') if backend == 'sha2' else Path()) / name / 'verify'
            if not vector.exists():
                vector = vector.parent / 'sign'
            for label, words in (('program', image.program), ('template', image.templates), ('descriptor', image.descriptors)):
                archived = vector / (label + '.mem')
                if archived.exists():
                    expected = ''.join(f'{word:016x}\n' for word in words).encode()
                    if archived.read_bytes() != expected:
                        raise AssertionError(f'ROM changed: {backend}/{name}/{label}')
            result['generated_images'].append({'backend': backend, 'profile': name, 'status': 'passed'})
        logical = compile_image('slh_128f', hash_backend=backend)
        # Replay H_msg after the tree's final digest has reused message RAM.
        repeated_hmsg = logical.tokens[logical.entry(True) + 1]
        invalid = replace(logical, tokens=logical.tokens[:-1] + (repeated_hmsg, logical.tokens[-1]))
        try:
            validate(invalid)
        except ValueError as error:
            if str(error) != 'message recipe after digest storage reuse':
                raise
            result['negative_model'].append({'backend': backend, 'status': 'passed', 'reason': str(error)})
        else:
            raise AssertionError('message-after-digest image was accepted')
        if args.rtl:
            work = ROOT / 'build/message_workspace' / backend
            vector_root = work / 'vectors'
            target = vector_root / 'slh_128f/sign'
            source = ROOT / 'tb/vectors' / ('sha2' if backend == 'sha2' else '') / 'slh_128f/sign'
            target.mkdir(parents=True, exist_ok=True)
            for path in source.glob('*.mem'):
                shutil.copyfile(path, target / path.name)
            image = compile_external('slh_128f', hash_backend=backend)
            program = list(image.program)
            sign_entry = (image.descriptors[0] >> 41) & 31
            halt = next(i for i in range(sign_entry, 16) if program[i] == 3 << 62)
            assert halt + 1 < 16
            program[halt], program[halt + 1] = program[sign_entry + 1], 3 << 62
            (target / 'program.mem').write_text(''.join(f'{word:016x}\n' for word in program))
            environment = dict(os.environ, HASH_BACKEND=backend, VECTORS_DIR=str(vector_root))
            process = subprocess.run(['bash', 'scripts/simulate_fast.sh', 'slh_128f', 'sign', '1', '1'],
                                     cwd=ROOT, env=environment, capture_output=True, text=True)
            actual = ROOT / ('build/sim/P1U1_fast_o3_synthesis0' + ('_sha2' if backend == 'sha2' else '')) / 'slh_128f_sign.log'
            data = actual.read_text()
            log = work / 'message_after_digest.log'
            shutil.copyfile(actual, log)
            if process.returncode == 0 or 'RTL error 12299' not in data:
                raise AssertionError(f'RTL failed to reject atomically: {backend}: {data}')
            result['negative_rtl'].append({'backend': backend, 'status': 'passed', 'error_code': '0x300b',
                                          'log': str(log), 'log_sha256': sha(log)})
    result['passed'] = True
    text = json.dumps(result, indent=2) + '\n'
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text)
    print(f"MESSAGE_WORKSPACE_PASS generated={len(result['generated_images'])} negative_model={len(result['negative_model'])} negative_rtl={len(result['negative_rtl'])}")


if __name__ == '__main__':
    main()
