#!/usr/bin/env python3
"""Compare ordinary project vectors/optional RTL dump to independent slhdsa-c.

Only reads job.mem/message.mem to obtain primitive inputs. The C executable is
built exclusively from ../../source/slhdsa-c and a file-I/O-only adapter.
No project Python algorithm, ROM executor or formatter is imported.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]
ADAPTER = Path(__file__).with_name('reference_slhdsa.c')


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build(reference, work):
    import tarfile
    sources = sorted(reference.glob('*.c'))
    if not sources or not (reference/'slh_dsa.h').exists():
        raise ValueError(f'No slhdsa-c reference found at {reference}')
    work.mkdir(parents=True, exist_ok=True)
    identity = {str(path.relative_to(reference)): sha256(path)
                for path in sorted(reference.glob('*')) if path.suffix in ('.h', '.c')}
    identity['test/my_dbg.h'] = sha256(reference / 'test/my_dbg.h')
    identity['README.md'] = sha256(reference / 'README.md')
    manifest = dict(reference_directory=str(reference), files=identity,
                    source_aggregate_sha256=hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest(),
                    reference_git_checkout=False,
                    origin_note='Local slhdsa-c README declares derivation from SLotH driver; no independent .git directory present.',
                    adapter_sha256=sha256(ADAPTER),
                    instrumentation='SLH_EXPERIMENTAL enables existing compression counters and expands scratch limits; uninstrumented build independently compared byte-for-byte')
    (work/'REFERENCE_SOURCE.json').write_text(json.dumps(manifest, indent=2)+'\n')
    with tarfile.open(work/'reference_source.tar.gz', 'w:gz') as archive:
        for name in (*identity, 'LICENSE'):
            archive.add(reference/name, arcname='slhdsa-c/'+name, recursive=False)
        archive.add(ADAPTER, arcname='adapter/reference_slhdsa.c', recursive=False)
        archive.add(Path(__file__), arcname='adapter/check_slhdsa_c.py', recursive=False)
    for instrumentation in (False, True):
        executable = work/('reference_cli_instrumented' if instrumentation else 'reference_cli')
        command = ['gcc', '-O3', '-std=c99', '-Wall', '-Wextra',
                   *(['-DSLH_EXPERIMENTAL'] if instrumentation else []),
                   '-I', str(reference), str(ADAPTER), *(str(p) for p in sources),
                   '-o', str(executable)]
        result = subprocess.run(command, text=True, capture_output=True)
        executable.with_suffix('.compile.log').write_text(result.stdout + result.stderr)
        result.check_returncode()
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--vector', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--verify-signature', type=Path)
    parser.add_argument('--reference-root', type=Path, default=ROOT/'../../source/slhdsa-c')
    parser.add_argument('--work', type=Path, default=ROOT/'build/sha2_p1_audit/c_reference')
    args = parser.parse_args()
    work = args.work.resolve()
    manifest = build(args.reference_root.resolve(), work)
    vector, out = args.vector.resolve(), args.output.resolve()
    out.mkdir(parents=True, exist_ok=True)
    job = [int(v, 16) for v in (vector/'job.mem').read_text().split()]
    if job[7] != 1:
        raise ValueError('Expected a Sign vector')
    message = bytes(int(v, 16) for v in (vector/'message.mem').read_text().split())[:job[8]]
    payload = b''.join(v.to_bytes(32, 'little')[:16] for v in job[:4]) + message
    (out/'input.bin').write_bytes(payload)
    command = [str(work/'reference_cli'), str(out/'input.bin'), str(out)]
    if args.verify_signature:
        command.append(str(args.verify_signature.resolve()))
    start = time.monotonic()
    result = subprocess.run(command, text=True, capture_output=True)
    (out/'reference.log').write_text(result.stdout + result.stderr)
    result.check_returncode()
    summary = json.loads(result.stdout)
    plain_artifacts = {name:(out/name).read_bytes() for name in ('sk.bin', 'pk.bin', 'signature.bin')}
    command[0] = str(work/'reference_cli_instrumented')
    instrumented = subprocess.run(command, text=True, capture_output=True)
    (out/'reference_instrumented.log').write_text(instrumented.stdout + instrumented.stderr)
    instrumented.check_returncode()
    instrumentation_matches = all((out/name).read_bytes()==value for name,value in plain_artifacts.items())
    if not instrumentation_matches:
        raise ValueError('Instrumented and plain C reference outputs differ')
    counted = json.loads(instrumented.stdout)
    for name,value in counted.items():
        if name.endswith('_blocks'):
            summary[name] = value
    summary['plain_and_instrumented_match'] = instrumentation_matches
    expected = bytes(int(v, 16) for v in (vector/'expected.mem').read_text().split())
    signature = (out/'signature.bin').read_bytes()
    pk = (out/'pk.bin').read_bytes()
    vector_pk = job[2].to_bytes(32, 'little')[:16] + job[4].to_bytes(32, 'little')[:16]
    summary.update(vector_directory=str(vector), seconds=time.monotonic()-start,
                   signature_matches_vector=signature==expected, public_key_matches_vector=pk==vector_pk,
                   signature_sha256=hashlib.sha256(signature).hexdigest(),
                   vector_signature_sha256=hashlib.sha256(expected).hexdigest(),
                   public_key_hex=pk.hex(), message_hex=message.hex(),
                   input_sha256=sha256(out/'input.bin'), reference_source=manifest,
                   vector_files_sha256={p.name:sha256(p) for p in sorted(vector.glob('*.mem'))})
    summary['passed'] = summary['signature_matches_vector'] and summary['public_key_matches_vector']
    (out/'SUMMARY.json').write_text(json.dumps(summary, indent=2)+'\n')
    print(json.dumps({k:v for k,v in summary.items() if k not in ('reference_source', 'vector_files_sha256')}, indent=2))
    if not summary['passed']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
