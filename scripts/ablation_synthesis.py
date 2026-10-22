#!/usr/bin/env python3
"""Freeze and archive a selected common-core synthesis."""
import argparse
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import tarfile
from zoneinfo import ZoneInfo
from ablation_paths import ROOT, DESIGN, freeze


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('begin', 'finish'))
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    output = args.output.resolve()
    if args.action == 'begin':
        stamp = datetime.now(ZoneInfo('Asia/Singapore')).strftime('%Y%m%d_%H%M%S')
        backend = os.environ.get('HASH_BACKEND', 'shake')
        archive = ROOT / 'docs/manifests/experiments' / f'ablation_synthesis_{DESIGN}_{backend}_{stamp}'
        source = output / f'source_{stamp}'
        freeze(source)
        archive.mkdir(parents=True, exist_ok=False)
        identity = json.loads((source / 'SOURCE.json').read_text())
        identity.update(source_root=str(source), hash_backend=backend, started_at=stamp, common_core=True,
                        period_ns=10.0, placement_routing=False, statistics='SYNTHESIS', threads=2)
        (archive / 'SOURCE.json').write_text(json.dumps(identity, indent=2)+'\n')
        with tarfile.open(archive / 'frozen_rtl.tar.gz', 'w:gz') as bundle:
            for path in sorted(source.rglob('*')):
                if path.is_file(): bundle.add(path, arcname=path.relative_to(source))
        (output / 'archive_path.txt').write_text(str(archive)+'\n')
        print(source)
        return
    archive = Path((output / 'archive_path.txt').read_text().strip())
    for name in ('core_utilization.rpt','core_hierarchical.rpt','core_timing.rpt','debug_audit.json','vivado.log','settings.txt'):
        path = output / name
        if path.exists(): shutil.copyfile(path, archive / name)
    reports = archive / 'reports'; reports.mkdir(exist_ok=True)
    summary = dict(design=DESIGN, hash_backend=os.environ.get('HASH_BACKEND','shake'),
                   synthesis_completed=True, placement_routing=False, period_ns=10.0,
                   atp_frequency='assumed; no routed frequency claim', source='SOURCE.json')
    (reports / 'Synthesis.json').write_text(json.dumps(summary, indent=2)+'\n')
    (reports / 'Synthesis.md').write_text(f'# Common 综合：{DESIGN} / {summary["hash_backend"]}\n\n'
        '100 MHz、OOC、统计关闭、每任务 2 线程。未布局布线；频率仅为综合约束。\n\n'
        '[分层面积](../core_hierarchical.rpt) · [时序](../core_timing.rpt) · [源码](../SOURCE.json)\n')
    artifacts = {str(path.relative_to(archive)): hashlib.sha256(path.read_bytes()).hexdigest()
                 for path in sorted(archive.rglob('*')) if path.is_file()}
    (archive / 'ARTIFACTS.json').write_text(json.dumps(dict(sha256=artifacts), indent=2)+'\n')
    index = archive.parent / 'INDEX.md'
    if index.exists():
        text = index.read_text()
        if archive.name not in text:
            timestamp = '_'.join(archive.name.rsplit('_', 2)[-2:])
            index.write_text(text.rstrip()+'\n'+f'| {timestamp} | {archive.name} | [报告]({archive.name}/reports/Synthesis.md) | [证据]({archive.name}/ARTIFACTS.json) |\n')
    print(archive)


if __name__ == '__main__': main()
