#!/usr/bin/env python3
"""Keep reports, frozen RTL and synthesis evidence together per experiment."""
import argparse
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tarfile
import time
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
ARCHIVES = ROOT / 'docs/manifests/experiments'
LEGACY = ROOT / 'docs/report'
FAMILIES = {
    'ATP_Optimization_20261013': 'atp_optimization_20261013',
    'P4U1_Redundancy_Performance_ATP_20261013': 'p4_joint_20261013',
    'Stateful_SHAKE256_Standard_Migration_20261013': 'stateful_standard_20261013',
    'Stateful_XMSS_LMS': 'stateful_pipeline_20261012',
    'PU_Generic_Sharing_20261013': 'pu_generic_sharing_20261013',
    'RTL_Debug_Sharing_Cleanup_20261013': 'rtl_debug_sharing_20261013',
    'ATP_Focus_P12_P4_P1_20261014': 'atp_focus_20261014',
    'Recipe_Redundancy_ATP_20261014': 'recipe_redundancy_20261014',
    'Recipe_Integration_Matrix_20261014': 'recipe_integration_20261014',
    'P1_Scalar_20261014': 'p1_scalar_20261014',
    'SLH_DSA_128f_sign_ATP_150_110': 'single_lane_13_20261009_v4',
}


def now():
    return datetime.now(ZoneInfo('Asia/Singapore')).isoformat(timespec='seconds')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def atomic(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f'.{os.getpid()}.tmp')
    temporary.write_text(text)
    temporary.replace(path)


def family(name):
    stem = Path(name).stem
    match = re.match(r'PU_Sign_Matrix_(\d{8}_\d{6})', stem)
    if match:
        return 'pu_sign_matrix_' + match[1]
    for label, folder in FAMILIES.items():
        if stem == label or stem.startswith(label + '_'):
            return folder
    return re.sub(r'[^a-z0-9_]+', '_', stem.lower())


def report_prefix(name):
    path = Path(name)
    return ARCHIVES / family(path.name) / 'reports' / path.name


def canonical_report(path):
    path = Path(path)
    absolute = path if path.is_absolute() else ROOT / path
    if absolute.parent == LEGACY:
        return report_prefix(path.name)
    return path


def copy_changed(source, target):
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and source.stat().st_size == target.stat().st_size and sha(source) == sha(target):
        return
    temporary = target.with_name(target.name + f'.{os.getpid()}.tmp')
    shutil.copyfile(source, temporary)
    temporary.replace(target)


def pack_rtl(source, destination, expected=None):
    """Package actual frozen RTL; never substitute current working-tree RTL."""
    source = Path(source)
    destination = Path(destination)
    if not source.is_dir() or not (source / 'rtl').is_dir():
        return dict(status='missing', reason='Frozen RTL directory is unavailable', source=str(source))
    names = [str(p.relative_to(source)) for p in sorted((source / 'rtl').rglob('*'))
             if p.is_file() and p.suffix in ('.sv', '.svh', '.v', '.vh', '.mem', '.hex')]
    names += [name for name in ('sources.txt', 'scripts/clock.xdc') if (source / name).exists()]
    hashes = {name: sha(source / name) for name in names}
    if expected is None and (source / 'source.sha256').exists():
        expected = dict((name.strip(), checksum) for checksum, name in
                        (line.split('  ', 1) for line in (source / 'source.sha256').read_text().splitlines()))
    mismatches = [name for name in names if expected and name in expected and hashes[name] != expected[name]]
    if mismatches:
        raise ValueError(f'Frozen RTL checksum mismatch: {source}: {mismatches}')
    manifest = destination.parent / 'RTL_SOURCE.json'
    data = dict(source_root=str(source), files=hashes, frozen_manifest_verified=bool(expected))
    if not destination.exists() or not manifest.exists() or json.loads(manifest.read_text()) != data:
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(destination.name + f'.{os.getpid()}.tmp')
        with tarfile.open(temporary, 'w:gz') as tar:
            for name in names:
                tar.add(source / name, arcname=name, recursive=False)
        temporary.replace(destination)
        atomic(manifest, json.dumps(data, indent=2) + '\n')
    return dict(status='saved', path=str(destination), sha256=sha(destination), files=len(hashes))


def archive_run(run):
    run = Path(run)
    manifest = run / 'SOURCE.json'
    if not manifest.exists():
        return None
    metadata = json.loads(manifest.read_text())
    archive_root = Path(metadata.get('archive_root', ARCHIVES))
    output = archive_root / ('pu_sign_matrix_' + run.name)
    copy_changed(manifest, output / 'SOURCE.json')
    source = Path(metadata['source_root'])
    rtl = pack_rtl(source, output / 'rtl.tar.gz', metadata.get('sha256'))
    for name in ('status.json', 'source.sha256', 'working_tree.patch', 'working_tree_status.txt', 'runner.log'):
        if (run / name).exists():
            copy_changed(run / name, output / name)
    for part in ('synth',):
        for path in sorted((run / part).rglob('*')):
            if path.is_file() and 'obj' not in path.parts and path.suffix in ('.rpt', '.log', '.json', '.txt'):
                copy_changed(path, output / path.relative_to(run))
    for path in (source / 'validation/FINAL_VALIDATION.json',
                 source / 'validation/p1_scalar/VALIDATION.json'):
        if path.exists():
            data = json.loads(path.read_text())
            summary = {key: value for key, value in data.items()
                       if key in ('schema', 'expected_records', 'complete', 'passed',
                                  'elapsed_seconds', 'source_unchanged', 'h20_full_keygen_sign_run')}
            summary['completed_records'] = len(data.get('results', []))
            summary['failed_cases'] = [r['name'] for r in data.get('results', []) if not r['passed']]
            atomic(output / 'VALIDATION_SUMMARY.json', json.dumps(summary, indent=2) + '\n')
    for name in ('sim', 'validation'):
        if (output / name).exists():
            shutil.rmtree(output / name)
    for path in sorted((run / 'synth').rglob('*.rpt')):
        if path.name in ('core_hierarchical.rpt', 'core_timing.rpt', 'top_hierarchical.rpt', 'top_timing.rpt'):
            name = 'hierarchical.rpt' if 'hierarchical' in path.name else 'timing.rpt'
            copy_changed(path, output / path.parent.relative_to(run) / name)
    state = json.loads((run / 'status.json').read_text()) if (run / 'status.json').exists() else {}
    tests = []
    for key, task in state.get('tasks', {}).items():
        if not key.startswith('synth/'):
            continue
        directory = output / key
        tests.append(dict(test=key, status=task['status'], analysis_deferred=task.get('analysis_deferred', False),
                          hierarchical=(directory / 'hierarchical.rpt').exists(),
                          timing=(directory / 'timing.rpt').exists(), rtl_archive=rtl['status']))
    artifacts = {str(p.relative_to(output)): sha(p) for p in sorted(output.rglob('*'))
                 if p.is_file() and p.name not in ('ARTIFACTS.json',) and 'reports' not in p.parts}
    atomic(output / 'ARTIFACTS.json', json.dumps(dict(updated_at=now(), run_id=run.name,
           source=str(manifest), rtl=rtl, tests=tests,
           omitted_details=['sim', 'validation'], sha256=artifacts), indent=2) + '\n')
    return output


def archive_test(source, results, output):
    """Archive a non-matrix test with its own source and raw reports."""
    source, results, output = Path(source), Path(results), Path(output)
    rtl = pack_rtl(source, output / 'rtl.tar.gz')
    copied = []
    for path in sorted(results.rglob('*')):
        if not path.is_file() or path.suffix not in ('.rpt', '.log', '.json', '.txt', '.tcl', '.xdc'):
            continue
        if any(part in ('obj', '.Xil', 'source', 'rtl', 'model', 'tb', 'sim', 'validation') for part in path.relative_to(results).parts):
            continue
        target = output / 'results' / path.relative_to(results)
        copy_changed(path, target)
        copied.append(target)
        if path.name in ('core_hierarchical.rpt', 'top_hierarchical.rpt', 'core_timing.rpt', 'top_timing.rpt'):
            alias = 'hierarchical.rpt' if 'hierarchical' in path.name else 'timing.rpt'
            normalized = target.with_name(alias)
            copy_changed(path, normalized)
            copied.append(normalized)
    atomic(output / 'ARTIFACTS.json', json.dumps(dict(updated_at=now(), source=str(source), results=str(results),
           rtl=rtl, hierarchical=[str(p.relative_to(output)) for p in copied if p.name == 'hierarchical.rpt'],
           timing=[str(p.relative_to(output)) for p in copied if p.name == 'timing.rpt'],
           sha256={str(p.relative_to(output)): sha(p) for p in copied}), indent=2) + '\n')


def begin_synthesis(results):
    results = Path(results).resolve()
    stamp = datetime.now(ZoneInfo('Asia/Singapore')).strftime('%Y%m%d_%H%M%S_%f')
    output = ARCHIVES / ('synth_' + results.name + '_' + stamp)
    source = output / 'source'
    names = (ROOT / 'sources.txt').read_text().splitlines()
    names += ['sources.txt', 'scripts/clock.xdc', 'scripts/audit_debug.tcl']
    hashes = {}
    for name in names:
        before = sha(ROOT / name)
        copy_changed(ROOT / name, source / name)
        if sha(source / name) != before or sha(ROOT / name) != before:
            raise ValueError('RTL changed while freezing: ' + name)
        hashes[name] = before
    atomic(output / 'SOURCE.json', json.dumps(dict(source_root=str(source), results=str(results),
           started_at=now(), sha256=hashes), indent=2) + '\n')
    pack_rtl(source, output / 'rtl.tar.gz', hashes)
    print(output)


def backfill_historical():
    # Preserve every individually frozen legacy candidate, including rejected tests.
    for name in ('atp_optimization_20261013', 'p4_joint_20261013'):
        folder = ARCHIVES / name
        for listfile in sorted(folder.rglob('sources.txt')):
            source = listfile.parent
            if (source / 'rtl').is_dir():
                pack_rtl(source, source / 'rtl.tar.gz')
                for path in sorted(source.rglob('core_*.rpt')):
                    if path.name in ('core_hierarchical.rpt', 'core_timing.rpt'):
                        copy_changed(path, path.with_name(path.name.removeprefix('core_')))
    standard = ROOT / 'build/standard_migration/source'
    if standard.exists():
        archive_test(standard, ROOT / 'build/synth/P4U1_generic', ARCHIVES / 'stateful_standard_20261013/tests/common')
        for results in sorted((ROOT / 'build/synth/top_P4U1_generic').iterdir()):
            if results.is_dir():
                archive_test(standard, results, ARCHIVES / 'stateful_standard_20261013/tests' / results.name)
    for source in sorted((ROOT / 'build/rtl_cleanup_20261013/variants').glob('*/sources.txt')):
        archive_test(source.parent, source.parent / 'synth', ARCHIVES / 'rtl_debug_sharing_20261013/tests' / source.parent.name)
    for source in sorted((ROOT / 'build/pu_generic/20261013_201408').glob('*/sources.txt')):
        archive_test(source.parent, source.parent / 'synth', ARCHIVES / 'pu_generic_sharing_20261013/tests' / source.parent.name)
    legacy = ROOT.parents[1] / 'manifests/experiments'
    for name in ('single_lane_13_20261009_v4', 'stateful_pipeline_20261012'):
        original = legacy / name
        if not original.exists():
            continue
        destination = ARCHIVES / name
        if name.startswith('single_lane'):
            archive_test(original / 'source', original, destination / 'tests')
            for path in sorted(original.glob('P*U*/mhbs_common.sv')):
                copy_changed(path, destination / 'tests/results' / path.relative_to(original))
        else:
            for listfile in sorted(original.rglob('sources.txt')):
                source = listfile.parent
                if (source / 'rtl').is_dir():
                    archive_test(source, source, destination / 'tests' / source.relative_to(original))
            for bundle in sorted(original.glob('*/source_snapshot.tar.gz')):
                extracted = ROOT / 'build/report_archive_20261014/legacy_sources' / name / bundle.parent.name
                with tarfile.open(bundle) as tar:
                    for member in tar.getmembers():
                        path = Path(member.name)
                        if not member.isfile() or path.is_absolute() or '..' in path.parts:
                            continue
                        if (path.parts[0] == 'rtl' and path.suffix == '.sv') or member.name == 'manifests/v42_sources.txt':
                            target = extracted / path
                            target.parent.mkdir(parents=True, exist_ok=True)
                            target.write_bytes(tar.extractfile(member).read())
                if (extracted / 'rtl').exists():
                    target = destination / 'tests' / bundle.parent.name
                    archive_test(extracted, bundle.parent, target)
                    atomic(target / 'ORIGIN.json', json.dumps(dict(source_archive=str(bundle), sha256=sha(bundle)), indent=2) + '\n')


def rewrite_links(text, old_path, new_path, mapping):
    def replacement(match):
        target = match[1]
        if re.match(r'\w+://|#|mailto:', target):
            return match[0]
        raw = target.strip('<>')
        suffix = ''
        if '#' in raw:
            raw, anchor = raw.split('#', 1); suffix = '#' + anchor
        p = Path(raw)
        absolute = p if p.is_absolute() else old_path.parent / p
        absolute = Path(os.path.abspath(absolute))
        resolved = mapping.get(str(absolute), absolute)
        if not resolved.exists() and resolved == absolute:
            return match[0]
        result = str(resolved) if p.is_absolute() else os.path.relpath(resolved, new_path.parent)
        return '](' + result + suffix + ')'
    return re.sub(r'\]\(([^)]+)\)', replacement, text)


def migrate_reports():
    LEGACY.mkdir(parents=True, exist_ok=True)
    paths = [p for p in LEGACY.iterdir() if p.is_file() and p.name != 'README.md' and p.suffix in ('.md', '.csv', '.json')]
    mapping_path = ARCHIVES / 'REPORT_PATHS.json'
    mapping = json.loads(mapping_path.read_text()) if mapping_path.exists() else {}
    new = {str(p): str(report_prefix(p.name)) for p in paths}
    mapping.update(new)
    destinations = {old: Path(target) for old, target in mapping.items()}
    for p in paths:
        target = destinations[str(p)]
        target.parent.mkdir(parents=True, exist_ok=True)
        if p.suffix == '.md':
            atomic(target, rewrite_links(p.read_text(), p, target, destinations))
        else:
            copy_changed(p, target)
        p.unlink()
    atomic(mapping_path, json.dumps(mapping, indent=2) + '\n')
    return destinations


def index():
    folders = [p for p in sorted(ARCHIVES.iterdir()) if p.is_dir()]
    lines = ['# 实验与测试归档', '',
             '每次测试保存报告、冻结 RTL 压缩包及对应综合的 hierarchical.rpt / timing.rpt。'
             'RTL_SOURCE.json 和 ARTIFACTS.json 记录文件校验、后台状态和实际缺项。', '',
             '最新结果：[P1 标量路径](p1_scalar_20261014/reports/P1_Scalar_20261014.md)、'
             '[Recipe 合并](recipe_integration_20261014/reports/Recipe_Integration_Matrix_20261014.md)。', '',
             '| 实验 | 报告 | RTL / 综合证据 |', '|---|---|---|']
    for folder in folders:
        reports = sorted((folder / 'reports').glob('*.md'))
        reports = [p for p in reports if not p.stem.endswith('_Notes')]
        if not reports and not (folder / 'ARTIFACTS.json').exists():
            continue
        links = '，'.join(f'[{p.stem}]({p.relative_to(ARCHIVES)})' for p in reports)
        evidence = f'[证据]({folder.name}/ARTIFACTS.json)' if (folder / 'ARTIFACTS.json').exists() else f'[目录]({folder.name}/)'
        lines.append(f'| {folder.name} | {links or "尚无报告"} | {evidence} |')
    lines += ['', '后台补齐：`python3 scripts/experiment_archive.py --sync --watch`。'
              '只整理已产生的结果，不停止综合，不从其他源码借用数据。', '']
    atomic(ARCHIVES / 'INDEX.md', '\n'.join(lines))


def sync():
    migrate_reports()
    for manifest in sorted((ROOT / 'build/pu_sign_matrix').glob('*/SOURCE.json')):
        archive_run(manifest.parent)
    index()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path)
    parser.add_argument('--sync', action='store_true')
    parser.add_argument('--watch', action='store_true')
    parser.add_argument('--backfill-historical', action='store_true')
    parser.add_argument('--begin-synthesis', type=Path)
    parser.add_argument('--finish-synthesis', type=Path)
    parser.add_argument('--results', type=Path)
    args = parser.parse_args()
    if args.begin_synthesis:
        begin_synthesis(args.begin_synthesis)
        return
    if args.finish_synthesis:
        if not args.results:
            parser.error('--finish-synthesis requires --results')
        reports = {p.name for p in args.results.rglob('*.rpt')}
        if not reports.intersection({'hierarchical.rpt', 'core_hierarchical.rpt', 'top_hierarchical.rpt'}) or not reports.intersection({'timing.rpt', 'core_timing.rpt', 'top_timing.rpt'}):
            raise ValueError('Completed synthesis is missing hierarchy or timing evidence')
        archive_test(args.finish_synthesis / 'source', args.results, args.finish_synthesis)
        index()
        return
    if args.backfill_historical:
        backfill_historical()
    while True:
        if args.run:
            archive_run(args.run)
        else:
            sync()
        if not args.watch:
            break
        time.sleep(30)


if __name__ == '__main__':
    main()
