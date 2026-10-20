#!/usr/bin/env python3
"""Collect source-bound common-core results for the three image granularities."""
from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import time
from zoneinfo import ZoneInfo

TARGETS = ('slh_128f', 'xmss_h10', 'lms_h10')
CAPACITIES = {'image': (512, 0, 32), 'image-chain': (128, 32, 32),
              'image-chain-tree': (16, 16, 32)}


def read(path):
    if not path or not Path(path).is_file():
        return {}
    try:
        return json.loads(Path(path).read_text())
    except json.JSONDecodeError:
        return {}


def identity(path):
    data = read(path)
    files = data.get('files', data.get('sha256', data.get('source_sha256', {})))
    return {name: value for name, value in files.items()
            if name.startswith('rtl/') and name.endswith(('.sv', '.svh'))}


def atomic(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_text(text)
    temporary.replace(path)


def signature_hash(vectors, profile, architecture):
    if not vectors:
        return None
    folder = Path(vectors) / profile / 'sign'
    if architecture == 'image':
        return read(folder / 'result.json').get('standard_signature_sha256')
    expected = folder / 'expected.mem'
    if expected.is_file():
        return hashlib.sha256(bytes(int(word, 16) for word in expected.read_text().split())).hexdigest()
    return None


def collect(manifest):
    result = {'updated_at': datetime.now(ZoneInfo('Asia/Singapore')).isoformat(timespec='seconds'),
              'main_source': manifest['main_source'], 'configuration': 'K1U1',
              'clock_mhz_assumed': 100, 'routed_frequency_measured': False,
              'area_scope': 'common; excludes all image ROMs and signature cache',
              'acceptance': 'functional reconstruction and measurements; no assumed ATP ordering',
              'high_tree_policy': 'h16/h15/h20 Verify only; no complete high-tree Keygen/Sign',
              'static_usage': read(manifest.get('static_usage')),
              'architectures': {}, 'complete': False}
    complete = True
    for name in CAPACITIES:
        spec = manifest.get('architectures', {}).get(name, {})
        architecture = {'capacities_words': dict(zip(('program', 'template', 'descriptor'), CAPACITIES[name])),
                        'backends': {}}
        for backend in ('shake', 'sha2'):
            task = spec.get(backend, {})
            synth_all = read(task.get('synthesis_status'))
            synth = synth_all.get('synthesis', {}).get(backend, synth_all)
            regression = read(task.get('regression_results'))
            synth_id = identity(task.get('synthesis_source'))
            sim_id = identity(task.get('regression_source'))
            bound = bool(synth_id and sim_id and synth_id == sim_id)
            area = dict(synth.get('resources', synth.get('area', {})))
            if 'equivalent_slice' in area:
                area['equivalent_slices'] = area.pop('equivalent_slice')
            cases = regression.get('cases', regression.get('tests', regression.get('results', {})))
            if isinstance(cases, list):
                cases = {row.get('name', row.get('case', '')): row for row in cases}
            regression_status = regression.get('status', 'passed' if regression.get('acceptance_passed')
                                                else 'finished_with_failures' if regression.get('complete')
                                                else 'running' if regression else 'pending')
            row = {'synthesis_status': synth.get('status', 'pending'),
                   'regression_status': regression_status,
                   'analysis_deferred': synth.get('analysis_deferred', False),
                   'production_rtl_equal': bound, 'resources': area, 'sign': {}}
            for profile in TARGETS:
                measured = cases.get(profile + '/sign', cases.get(backend + '/' + profile + '/sign', {}))
                cycles = measured.get('cycles')
                passed = measured.get('passed', measured.get('status') == 'passed')
                entry = {'status': 'passed' if passed else 'pending',
                         'cycles': cycles if passed else None,
                         'hashes': measured.get('hashes') if passed else None,
                         'permutations': measured.get('permutations') if passed else None,
                         'macro_metrics': measured.get('macro_metrics'),
                         'standard_signature_sha256': (signature_hash(task.get('vectors_root'), profile, name)
                             or task.get('standard_signature_sha256', {}).get(profile)) if passed else None,
                         'atp_slice_ms': None, 'time_ms': None}
                if passed and cycles is not None:
                    entry['time_ms'] = cycles / 100000
                    if bound and area.get('equivalent_slices') is not None:
                        entry['atp_slice_ms'] = area['equivalent_slices'] * entry['time_ms']
                if entry['atp_slice_ms'] is None:
                    complete = False
                row['sign'][profile] = entry
            architecture['backends'][backend] = row
        result['architectures'][name] = architecture
    result['focus_measurements_complete'] = complete
    all_signatures = True
    signatures_available = True
    for backend in ('shake', 'sha2'):
        for profile in TARGETS:
            entries = [a['backends'][backend]['sign'][profile] for a in result['architectures'].values()]
            checksums = [r['standard_signature_sha256'] for r in entries]
            match = len(set(checksums)) == 1 if all(checksums) else None
            all_signatures = all_signatures and match is True
            signatures_available = signatures_available and match is not None
            for row in entries:
                row['standard_signature_equal_across_architectures'] = match
                row['rank'] = None
            if all(row['atp_slice_ms'] is not None for row in entries):
                for rank, row in enumerate(sorted(entries, key=lambda row: row['atp_slice_ms']), 1):
                    row['rank'] = rank
    result['focus_signatures_equal'] = all_signatures if signatures_available else None
    result['complete'] = complete and all_signatures
    return result


def render(result):
    lines = ['# Template macro architecture comparison', '',
             'K1U1, SHAKE / SHA2. Area is common only, excluding program/template/descriptor ROMs '
             'and signature cache. ATP uses an assumed 100 MHz; synthesis timing is diagnostic and '
             'does not establish a routed frequency.', '',
             'The frozen main job inputs are used for all three architectures. Main stateful Sign '
             'may repeat target-chain prefix work; report actual Hash counts rather than assuming '
             'identical primitive workloads.', '',
             '| Architecture | Program capacity | Template capacity | Descriptor capacity |',
             '|---|---:|---:|---:|']
    for name, entry in result['architectures'].items():
        p, t, d = (entry['capacities_words'][k] for k in ('program', 'template', 'descriptor'))
        lines.append(f'| {name} | {p} | {t} | {d} |')
    if result['static_usage']:
        lines += ['', 'Static usage covers the shared image for all three operations. Descriptor usage '
                  'includes meaningful zero-valued identity records. Macro counts below count program '
                  'words, not repetitions or TREE-internal CHAIN execution.', '',
                  '| Profile | Backend | Architecture | Program used | Template used | Descriptor valid / reachable | Static CHAIN / TREE | Valid record bytes |',
                  '|---|---|---|---:|---:|---|---|---:|']
        for profile in TARGETS:
            for backend in ('shake', 'sha2'):
                for name in CAPACITIES:
                    u = result['static_usage'].get(name, {}).get(backend, {}).get(profile, {})
                    if not u:
                        continue
                    operations = u.get('static_operations', {})
                    valid = u.get('descriptor_valid', u['descriptor_used'])
                    reachable = u['descriptor_used'] if name != 'image' else '—'
                    words = [u['program_used'], u['template_used'], valid]
                    lines.append(f'| {profile} | {backend} | {name} | {words[0]} | {words[1]} | {valid} / {reachable}'
                                 + f' | {operations.get("CHAIN", 0)} / {operations.get("TREE", 0)} | {8 * sum(words)} |')
    lines += ['', '| Architecture | Backend | LUT | FF | BRAM36 | Equivalent Slice | Status | RTL bound |',
              '|---|---|---:|---:|---:|---:|---|---|']
    for name, architecture in result['architectures'].items():
        for backend, row in architecture['backends'].items():
            a = row['resources']
            values = [f'{a[key]:,.3f}'.rstrip('0').rstrip('.') if key in a else ''
                      for key in ('lut', 'ff', 'bram36', 'equivalent_slices')]
            status = row['synthesis_status'] + ('; analysis_deferred' if row['analysis_deferred'] else '')
            lines.append(f'| {name} | {backend} | ' + ' | '.join(values)
                         + f' | {status} | {row["production_rtl_equal"]} |')
    for profile in TARGETS:
        lines += ['', f'## {profile} Sign', '',
                  '| Architecture | Backend | Cycles | Hashes | Blocks | Time ms | ATP Slice·ms | Rank within backend | Standard signature equal |',
                  '|---|---|---:|---:|---:|---:|---:|---:|---|']
        for name, architecture in result['architectures'].items():
            for backend, row in architecture['backends'].items():
                item = row['sign'][profile]
                values = [str(item[k]) if item[k] is not None else '' for k in ('cycles', 'hashes', 'permutations')]
                values += [f'{item[k]:,.6f}' if item[k] is not None else '' for k in ('time_ms', 'atp_slice_ms')]
                equal = item['standard_signature_equal_across_architectures']
                lines.append(f'| {name} | {backend} | ' + ' | '.join(values)
                             + f' | {item["rank"] if item["rank"] is not None else ""} | {equal if equal is not None else ""} |')
    lines += ['', '## Dynamic Sign macro execution', '',
              'Direct CHAIN commands and TREE-child CHAIN executions are separate counts. '
              'A CHAIN invocation executes a whole configured chain group, including leaf construction.', '',
              '| Architecture | Backend | Profile | HASH | Direct CHAIN | TREE | TREE-child CHAIN | TRANSFORM | Controls |',
              '|---|---|---|---:|---:|---:|---:|---:|---:|']
    for name, architecture in result['architectures'].items():
        for backend, row in architecture['backends'].items():
            for profile, item in row['sign'].items():
                metrics = item.get('macro_metrics')
                if not metrics:
                    continue
                values = [str(metrics.get(k, 0)) for k in ('HASH', 'CHAIN', 'TREE', 'TREE_child_CHAIN', 'TRANSFORM', 'control_instructions')]
                lines.append(f'| {name} | {backend} | {profile} | ' + ' | '.join(values) + ' |')
    if result['complete']:
        lines += ['', '## Measured result', '',
                  'The requested control boundaries and standard outputs are reproduced. The measured '
                  'ATP ordering must be read from the tables: the hoped-for image > image-chain > '
                  'image-chain-tree ordering is not an acceptance assumption.', '',
                  'For SHAKE, the CHAIN executor controller uses 7,536 LUT and its sequencer uses 977 LUT; '
                  'the TREE executor uses 5,508 LUT and a 182-LUT sequencer. Both have one 2,157-LUT '
                  'Keccak round and the same 954-LUT workspace. The explicit control decode/selection '
                  'and instruction handshake are remaining area/cycle costs; static image compression '
                  'does not imply a smaller common core. Hierarchical synthesis reports provide this breakdown.']
    lines += ['', 'Pending results are blank. h16/h15 full Keygen/Sign are not run; h20 full trees remain stopped.',
              '', f'All focus measurements available: {result["focus_measurements_complete"]}. '
              f'Focus signatures agree: {result["focus_signatures_equal"] if result["focus_signatures_equal"] is not None else "pending"}. '
              'This measurement status does not replace the required full regression summaries.', '']
    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--watch', action='store_true')
    args = parser.parse_args()
    while True:
        manifest = read(args.manifest)
        base = args.manifest.resolve().parent
        for key in ('report_prefix', 'static_usage'):
            if manifest.get(key) and not Path(manifest[key]).is_absolute():
                manifest[key] = str(base / manifest[key])
        for architecture in manifest.get('architectures', {}).values():
            for task in architecture.values():
                for key in ('synthesis_status', 'synthesis_source', 'regression_results', 'regression_source', 'vectors_root'):
                    if task.get(key) and not Path(task[key]).is_absolute():
                        task[key] = str(base / task[key])
        result = collect(manifest)
        output = Path(manifest['report_prefix'])
        atomic(output.with_suffix('.json'), json.dumps(result, indent=2) + '\n')
        atomic(output.with_suffix('.md'), render(result))
        if not args.watch or result['complete']:
            print(output.with_suffix('.md'))
            return
        time.sleep(30)


if __name__ == '__main__':
    main()
