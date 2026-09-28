#!/usr/bin/env python3
"""Verify the frozen KU archive and latest report evidence without build outputs."""
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = ROOT / 'manifests/experiments/ku_sign_latest'


def verify(manifest, base):
    count = 0
    for line in manifest.read_text().splitlines():
        digest, name = line.split('  ', 1)
        path = (base / name).resolve()
        if not path.is_relative_to(base.resolve()):
            raise ValueError(f'Path outside evidence root: {name}')
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != digest:
            raise ValueError(f'Hash mismatch: {path}')
        count += 1
    return count


if __name__ == '__main__':
    raw = verify(ARCHIVE / 'SHA256SUMS', ARCHIVE)
    report = verify(ROOT / 'docs/v4.2/KU_Sign_ATP_151_112_67_48.sha256', ROOT)
    print(f'KU_ARCHIVE_PASS: {raw} archived files; {report} report/input hashes')
