#!/usr/bin/env python3
"""Resolve one ablation design inside the shared project tree."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]
DESIGN = os.environ.get('MHBS_DESIGN', 'i')
if DESIGN not in ('i', 'c', 't'):
    raise SystemExit('MHBS_DESIGN must be i, c or t')


def source_files():
    manifest = ROOT / 'rtl' / DESIGN / 'sources.txt'
    result = []
    for line in manifest.read_text().splitlines():
        name = line.strip()
        if not name or name.startswith('#'):
            continue
        path = Path(name)
        if name.startswith('rtl/') and not name.startswith(f'rtl/{DESIGN}/'):
            path = Path('rtl') / DESIGN / Path(name).relative_to('rtl')
        elif not name.startswith('rtl/'):
            path = Path('rtl') / DESIGN / path
        if not (ROOT / path).is_file():
            raise FileNotFoundError(ROOT / path)
        result.append(str(path))
    return result


def bench(name):
    selected = ROOT / 'tb' / DESIGN / name
    if not selected.is_file():
        selected = ROOT / 'tb' / name
    if not selected.is_file():
        raise FileNotFoundError(selected)
    return str(selected.relative_to(ROOT))


def headers():
    return [str(path.relative_to(ROOT)) for path in sorted((ROOT / 'rtl' / DESIGN).rglob('*.svh'))]


def build_dir(name):
    return ROOT / 'build' / 'ablation' / DESIGN / name


def rtl(name):
    return f'rtl/{DESIGN}/{name}'


def prepare_vector(profile, operation, backend='shake', vectors_root=None):
    """Attach the chosen ROMs to immutable input/expected fixtures in build/."""
    if backend not in ('shake', 'sha2'):
        raise ValueError('Hash backend must be shake or sha2')
    if vectors_root:
        fixtures = Path(vectors_root).resolve() / profile / operation
    else:
        fixtures = ROOT / 'tb' / 'vectors' / DESIGN
        if backend == 'sha2':
            fixtures /= 'sha2'
        fixtures = fixtures / profile / operation
    if not fixtures.is_dir():
        raise FileNotFoundError(f'Unknown vector: {fixtures}')
    names = ('program.mem', 'template.mem', 'descriptor.mem')
    # Deliberately supplied complete bundles may contain fault-test ROMs.
    if vectors_root and all((fixtures / name).is_file() for name in names):
        return fixtures
    rom = ROOT / 'image' / DESIGN / backend / profile
    for name in names:
        if not (rom / name).is_file():
            raise FileNotFoundError(rom / name)
    if vectors_root:
        identity = hashlib.sha256(str(fixtures).encode()).hexdigest()[:12]
        output = build_dir(f'vectors/custom_{identity}/{backend}/{profile}/{operation}')
    else:
        output = build_dir(f'vectors/{backend}/{profile}/{operation}')
    output.mkdir(parents=True, exist_ok=True)
    files = {path.name: path for path in fixtures.iterdir() if path.is_file() and path.name not in names}
    files.update({name: rom / name for name in names})
    for name, source in files.items():
        target = output / name
        if not target.exists() or source.read_bytes() != target.read_bytes():
            temporary = target.with_name(target.name + f'.{os.getpid()}.tmp')
            shutil.copyfile(source, temporary)
            temporary.replace(target)
    return output


def freeze(output):
    """Freeze the selected compilation inputs without copying other designs."""
    output = Path(output).resolve()
    names = source_files() + headers() + ['scripts/audit_debug.tcl', 'scripts/clock.xdc']
    hashes = {}
    for name in names:
        source = ROOT / name
        destination = output / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
        hashes[name] = hashlib.sha256(source.read_bytes()).hexdigest()
    (output / 'sources.txt').write_text('\n'.join(source_files()) + '\n')
    (output / 'SOURCE.json').write_text(json.dumps(dict(design=DESIGN, sha256=hashes), indent=2)+'\n')
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('sources')
    sub.add_parser('headers')
    sub.add_parser('design')
    selected = sub.add_parser('bench'); selected.add_argument('name')
    vector = sub.add_parser('vector')
    vector.add_argument('profile'); vector.add_argument('operation')
    vector.add_argument('--hash', choices=('shake','sha2'), default='shake')
    vector.add_argument('--vectors-root')
    frozen = sub.add_parser('freeze'); frozen.add_argument('output')
    args = parser.parse_args()
    if args.command == 'sources': print('\n'.join(source_files()))
    elif args.command == 'headers': print('\n'.join(headers()))
    elif args.command == 'design': print(DESIGN)
    elif args.command == 'bench': print(bench(args.name))
    elif args.command == 'vector': print(prepare_vector(args.profile, args.operation, args.hash, args.vectors_root))
    else: print(freeze(args.output))


if __name__ == '__main__':
    main()
