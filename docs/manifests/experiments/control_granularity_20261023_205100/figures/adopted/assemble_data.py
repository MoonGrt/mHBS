#!/usr/bin/env python3
"""Assemble exact measured clocks for the adopted implementations."""
from datetime import datetime
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PREVIOUS = ROOT / 'tmp/sloth_ict_cycle_comparison'
EXPERIMENT = ROOT / 'docs/manifests/experiments/ic_timing_remaining_20261023_195418'
RUN = ROOT / 'build/ic_timing_remaining/20261023_195418'
MEASURES = ('total', 'hash', 'transfer', 'remaining', 'rounds', 'feedforward',
            'hash_count', 'physical_blocks', 'logical_blocks', 'signature_sha256',
            'signature_cache_sha256', 'signature_cache_and_kat_match', 'signature_bytes')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    return json.loads(path.read_text())


def main():
    previous = read(PREVIOUS / 'cycle_breakdown_data.json')
    decision = read(EXPERIMENT / 'DECISION.json')
    assert decision['selected'] == {'i': 'i_software', 'c': 'c_control_pipeline'}
    assert decision['status'] == 'adopted'
    assert all(sha(ROOT / p) == row['after_sha256'] for p, row in decision['changed_files'].items())
    sources = HERE / 'sources'
    sources.mkdir(exist_ok=True)
    source_report = PREVIOUS / 'sources/SLOTH_CYCLE_REPORT.md'
    shutil.copyfile(source_report, sources / source_report.name)
    source_map = {}
    rows = []
    for backend in ('shake', 'sha2'):
        report_row = next(r for r in previous['rows'] if r['backend'] == backend and r['design'] == 'SLotH')
        assert sha(source_report) == report_row['source_sha256']
        rows.append(dict(report_row, source='sources/SLOTH_CYCLE_REPORT.md', status='original_report'))
        for design in ('i', 'c', 't'):
            if design == 'i':
                path = RUN / 'profiles/i_software' / backend / 'result.json'
            elif design == 'c':
                path = HERE / 'profile/c' / backend / 'result.json'
            else:
                path = PREVIOUS / 'profile/t' / backend / 'result.json'
            result = read(path)
            assert result.get('status') == 'passed' or result.get('signature_cache_and_kat_match')
            assert result['message_bytes'] == 33
            assert result['configuration'] == 'P1U1'
            assert result['signature_cache_and_kat_match']
            assert result['signature_sha256'] == result['signature_cache_sha256']
            assert result['total'] == result['hash'] + result['transfer'] + result['remaining']
            assert result['hash'] == result['rounds'] + result['feedforward']
            assert result['transfer'] == 0
            if result.get('source_unchanged') is not None:
                assert result['source_unchanged']
            for field in ('hash_count', 'physical_blocks', 'logical_blocks', 'signature_sha256'):
                old = next(r for r in previous['rows'] if r['backend'] == backend and r['design'] == design)
                assert result[field] == old[field], (backend, design, field)
            dest = sources / f'{design}_{backend}_result.json'
            shutil.copyfile(path, dest)
            row = {k: result[k] for k in MEASURES if k in result}
            row.update(backend=backend, design=design, status='passed', message_bytes=33,
                       configuration='P1U1', source=str(dest.relative_to(HERE)), source_sha256=sha(dest))
            rows.append(row)
            source_map[f'{design}/{backend}'] = dict(original=str(path.relative_to(ROOT)), sha256=sha(path))
    assert len(rows) == 8
    for backend in ('shake', 'sha2'):
        group = [r for r in rows if r['backend'] == backend]
        assert [r['design'] for r in group] == ['SLotH', 'i', 'c', 't']
        assert all(group[1][key] == row[key] for row in group[2:]
                   for key in ('hash', 'hash_count', 'physical_blocks', 'signature_sha256'))
        assert group[1]['remaining'] < group[0]['remaining']
    audit = read(HERE / 'DATA_AUDIT.json')
    assert audit['passed'], 'Independent data audit must pass before figure assembly'
    data = dict(schema='mhbs.latest_sloth_ict.cycle_composition.v1', created_at=datetime.now().astimezone().isoformat(),
                profile='slh_128f', operation='sign', configuration='P1U1', message_bytes=33,
                ablation_head=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
                adopted=decision['selected'], rows=rows, sources=source_map,
                priority=previous['priority'], definitions=previous['definitions'], caveats=previous['caveats'],
                independent_data_audit='DATA_AUDIT.json',
                measured_not_estimated=True, previous_data_preserved=True)
    (HERE / 'cycle_breakdown_data.json').write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n')
    table = ['# Latest SLH-DSA-128f Sign clocks', '',
             'P1U1; one matched 33-byte KAT per backend. All counts are measured integer clocks.', '',
             '| Backend | Design | Hash | Transfer | Remaining | Total |', '|---|---|---:|---:|---:|---:|']
    table += ['| ' + ' | '.join([r['backend'].upper(), r['design'], *[f'{r[k]:,}' for k in ('hash', 'transfer', 'remaining', 'total')]]) + ' |' for r in rows]
    table += ['', 'i uses adopted i_software; c uses adopted c_control_pipeline; t is unchanged and source checked.', '',
              'Transfer counts non-overlapped hash-MMIO clocks (zero for i/c/t). Internal movement outside Hash remains in Remaining.',
              'SLotH reported Hash includes some engine setup/chain control; project Hash counts primitive rounds and SHA2 feed-forward.',
              'The SHA2 Hash difference is accounting, with matching primitive work; no control clocks were relabelled as Hash.', '']
    (HERE / 'cycle_breakdown_table.md').write_text('\n'.join(table))
    print('\n'.join(table[:15]))


if __name__ == '__main__':
    main()
